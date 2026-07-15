#!/usr/bin/env python3
"""DECA MLOps orchestrator — teach → test → examine → score → improve → repeat.

Loop continues with a **fresh random exam paper every cycle** until the promotion
gate PASSes (or ``--max-cycles`` is hit). No human judge: the machine decides.

Default Mode A uses the current lake (no running Tier-6 campaign ingest).

See docs/DECA_MLOps_Continuous_Learning_Pipeline.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from _paths import MODELS_DIR, PROCESSED_DIR, REPO_ROOT, RPI_NET_DIR, SCRIPTS_DIR

PYTHON = sys.executable


def _required_campaign_files(run_dir: Path) -> list[Path]:
    return [
        run_dir / "network_telemetry.csv",
        run_dir / "network_campaign_export.csv",
        run_dir / "fault_injection_log.csv",
    ]


def ingest_mode_b(rpi_run: Path) -> None:
    missing = [p.name for p in _required_campaign_files(rpi_run) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Campaign run incomplete — missing {missing} under {rpi_run}. "
            "Wait for the campaign to finish before Mode B ingest."
        )
    print(f"\n{'=' * 60}\n▶ Ingest Mode B — rebuild unified lake from {rpi_run.name}\n{'=' * 60}")
    subprocess.run(
        [PYTHON, str(SCRIPTS_DIR / "rebuild_unified.py"), "--rpi-run", str(rpi_run)],
        cwd=REPO_ROOT,
        check=True,
    )


def write_orchestrator_log(payload: dict) -> Path:
    out_dir = MODELS_DIR / "school_exam"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "orchestrator_latest.json"
    path.write_text(json.dumps(payload, indent=2))
    hist = out_dir / "orchestrator_history.jsonl"
    with hist.open("a") as f:
        f.write(json.dumps(payload) + "\n")
    return path


def improve_boosts(prev_boosts: list[float], best_beta: float, cycle: int) -> list[float]:
    """Widen / densify the β grid around the best weight from the last fail cycle."""
    spread = 0.25 * cycle
    grid = {
        round(max(0.5, best_beta + d), 3)
        for d in (
            -2 * spread,
            -spread,
            -spread / 2,
            0.0,
            spread / 2,
            spread,
            2 * spread,
            3 * spread,
        )
    }
    grid.update(round(b, 3) for b in prev_boosts)
    # Escalate rare emphasis gradually — never invent data, only reweight.
    grid.add(round(min(8.0, best_beta + 0.5 * cycle), 3))
    return sorted(grid)


def fresh_exam_seed(cycle: int, fixed: int | None) -> int | None:
    """New random questions each cycle. Fixed seed only for single-cycle audit."""
    if fixed is not None:
        return fixed
    # Mix UTC seconds + cycle so back-to-back cycles never share a paper.
    return int(time.time()) + cycle * 17_863


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DECA MLOps orchestrator — teach/test/examine/score/improve until PASS"
    )
    parser.add_argument(
        "--mode",
        choices=("A", "B"),
        default="A",
        help="A = same lake (default); B = ingest completed campaign then exam loop",
    )
    parser.add_argument(
        "--rpi-run",
        type=Path,
        default=None,
        help="Mode B only: campaign run dir or id under data/rpi-net/runs/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Full loop scoring only — never promote",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=10,
        help="Stop after N cycles if still failing (default 10)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Single cycle only (no improve loop)",
    )
    parser.add_argument("--holdout-frac", type=float, default=0.20)
    parser.add_argument(
        "--holdout-policy",
        choices=("random", "time_tail"),
        default="random",
        help="random = new questions each cycle (required for anti-memorization)",
    )
    parser.add_argument(
        "--exam-seed",
        type=int,
        default=None,
        help="Fix paper (forces --once). Omit for fresh random questions every cycle",
    )
    parser.add_argument("--rare-boosts", type=str, default="1,1.5,2,3")
    parser.add_argument(
        "--families",
        type=str,
        default="plain,wm,moe",
        help="Head families each cycle: plain=champion, wm=cluster booster, moe=cluster + per-fault experts",
    )
    parser.add_argument("--baseline-macro-f1", type=float, default=None)
    parser.add_argument("--min-rare-recall-drop", type=float, default=0.03)
    args = parser.parse_args()

    if args.exam_seed is not None:
        args.once = True
        print("NOTE: --exam-seed set → single-cycle audit (no random loop)")

    max_cycles = 1 if args.once else max(1, args.max_cycles)
    if args.holdout_policy != "random" and not args.once:
        print(
            "WARN: holdout-policy=time_tail in a multi-cycle loop reuses the same "
            "chronological quiz — prefer --holdout-policy random"
        )

    started = datetime.now(timezone.utc).isoformat()
    print(f"\n{'=' * 60}")
    print(f"▶ DECA MLOps orchestrator  mode={args.mode}  max_cycles={max_cycles}")
    print("  cycle = TEACH → TEST → EXAMINE → SCORE → IMPROVE (until PASS)")
    print(f"{'=' * 60}")

    lake = PROCESSED_DIR / "deca_unified_dataset.parquet"
    if args.mode == "B":
        if args.rpi_run is None:
            parser.error("Mode B requires --rpi-run (completed campaign export)")
        run_dir = args.rpi_run
        if not run_dir.is_absolute():
            run_dir = RPI_NET_DIR / "runs" / run_dir.name
        ingest_mode_b(run_dir)
    elif not lake.exists():
        print(f"ERROR: missing {lake} — run scripts/rebuild_unified.py first")
        return 1

    from deca_school_exam_train import run_school_exam

    boosts = [float(x) for x in args.rare_boosts.split(",") if x.strip()]
    fams = [x.strip() for x in args.families.split(",") if x.strip()]
    cycle_logs: list[dict] = []
    final_result: dict | None = None
    final_action = "exhausted"

    for cycle in range(1, max_cycles + 1):
        seed = fresh_exam_seed(cycle, args.exam_seed)
        print(f"\n{'#' * 60}")
        print(f"# CYCLE {cycle}/{max_cycles}  exam_seed={seed}  β={boosts}")
        print(f"{'#' * 60}")

        # TEACH + TEST + EXAMINE + SCORE (engine)
        result = run_school_exam(
            holdout_frac=args.holdout_frac,
            holdout_policy=args.holdout_policy,
            exam_seed=seed,
            rare_boosts=boosts,
            families=fams,
            auto_promote=False,  # orchestrator owns promote after SCORE
            baseline_macro_f1=args.baseline_macro_f1,
            min_rare_recall_drop=args.min_rare_recall_drop,
            mode_label=f"school_exam_{args.mode}_c{cycle}",
            unit_test_active=True,
        )
        final_result = result

        entry = {
            "cycle": cycle,
            "exam_seed": result["exam_seed"],
            "rare_boosts": boosts,
            "unit_test_active": result.get("unit_test_active"),
            "best": result["best"],
            "gate": result["gate"],
            "gate_ok": result["gate_ok"],
        }
        cycle_logs.append(entry)

        print(f"\n--- CYCLE {cycle} SCORE ---")
        print(f"  gate={'PASS' if result['gate_ok'] else 'FAIL'}")
        print(
            f"  candidate Macro-F1={result['gate']['candidate_macro_f1']:.4f}  "
            f"baseline={result['baseline_macro_f1']:.4f}"
        )

        if result["gate_ok"]:
            if args.dry_run:
                print("  DRY-RUN: would PROMOTE — stopping loop (pass)")
                final_action = "dry_run_would_promote"
            else:
                from deca_school_exam_train import promote_candidate

                best = result["best_payload"]
                promote_candidate(
                    best,
                    baseline=result["baseline_macro_f1"],
                    class_to_idx=result["class_to_idx"],
                    cand=result["gate"]["candidate_macro_f1"],
                    rare=result["gate"]["candidate_mean_rare_recall"],
                )
                final_action = "promoted"
                print(f"  CYCLE {cycle}: PASS → PROMOTED — loop complete")
            break

        # IMPROVE for next cycle (never mutate the exam set — only weights)
        if cycle < max_cycles:
            best_beta = float(result["best"]["rare_boost"])
            new_boosts = improve_boosts(boosts, best_beta, cycle)
            print(f"\n--- CYCLE {cycle} IMPROVE ---")
            print(f"  previous β={boosts}")
            print(f"  next β={new_boosts}  (centered on best={best_beta})")
            print("  next cycle draws a NEW random exam paper")
            boosts = new_boosts
        else:
            print(f"\n  Max cycles ({max_cycles}) reached without PASS — keeping active models")
            final_action = "exhausted_kept_active"

    assert final_result is not None
    log = {
        "orchestrator_date": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "dry_run": args.dry_run,
        "max_cycles": max_cycles,
        "cycles_run": len(cycle_logs),
        "holdout_policy": args.holdout_policy,
        "action": final_action,
        "promoted": final_action == "promoted",
        "gate_ok": final_result["gate_ok"],
        "final_gate": final_result["gate"],
        "final_best": final_result["best"],
        "cycles": cycle_logs,
        "loop": "teach → test → examine → score → improve → (new random paper)",
    }
    if args.mode == "B" and args.rpi_run is not None:
        log["rpi_run"] = str(args.rpi_run)

    log_path = write_orchestrator_log(log)
    print(f"\nWrote {log_path}")
    print(f"\n{'=' * 60}")
    print(f"ORCHESTRATOR DONE  action={final_action}  cycles={len(cycle_logs)}")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
