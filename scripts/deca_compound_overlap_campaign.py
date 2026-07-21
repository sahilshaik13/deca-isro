#!/usr/bin/env python3
"""Compound overlap data campaign — teach simultaneous PE1 + PE2 VRF windows.

After compound blinds showed VRF leg misses and PE1 class swaps under overlap,
isolated faults and operator gates are not enough. This adds **labelled**
overlapping injections (same threading model as blind chaos) to the training lake.

Usage
-----
    python scripts/deca_compound_overlap_campaign.py --run-id compound_overlap_$(date +%Y%m%d_%H%M)

    python scripts/deca_compound_overlap_campaign.py --per-pe1 2 --retry 2

    # Weighted schedule — e.g. consolidate a VRF gain without diluting BGP:
    python scripts/deca_compound_overlap_campaign.py \
        --counts tunnel_degradation=4,congestion_breach=4,bgp_route_flap=0

Resuming after a crash / power outage
--------------------------------------
Re-run with the SAME --run-id and the SAME --counts/--per-pe1 (they are treated
as totals, not additions): already-completed compound pairs are detected from
fault_injection_log.csv and skipped, numbering continues from where it left
off, and the true campaign start (for the final Prometheus export window) is
restored from data/rpi-net/runs/<run-id>/compound_overlap_state.json rather
than reset to the resume time.

Then:
    python scripts/rebuild_unified.py --all-rpi-runs
    python scripts/deca_school_exam_train.py --auto-promote --baseline-macro-f1 0.717
    python scripts/deca_score_temporal.py --soft-streak
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import deca_fault_campaign as dfc

PE1_FAULTS = ["congestion_breach", "tunnel_degradation", "bgp_route_flap"]
PE2_FAULT = "vrf_leakage"
REST_BETWEEN_MIN = (3.5, 5.5)
SETTLE_AFTER_COMPOUND_MIN = (2.5, 4.0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_file() -> Path:
    return dfc.LOG_FILE.parent / "compound_overlap_state.json"


def _load_or_init_campaign_start() -> datetime:
    """Restore the true campaign start across resumes so the end-of-run
    Prometheus export window covers compounds completed in earlier, crashed
    invocations instead of starting from the resume moment."""
    sf = _state_file()
    if sf.exists():
        try:
            state = json.loads(sf.read_text(encoding="utf-8"))
            return datetime.fromisoformat(state["started_at"])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    started = _now()
    sf.write_text(json.dumps({"started_at": started.isoformat()}, indent=2), encoding="utf-8")
    return started


def completed_compound_counts() -> dict[str, int]:
    """Scan fault_injection_log.csv for fully-logged compound_<pe1>_<NN> pairs
    (both the PE1 leg and the vrf_leakage leg present) per PE1 fault type, so
    a resumed run doesn't repeat — or renumber over — already-done compounds."""
    counts = {f: 0 for f in PE1_FAULTS}
    if not dfc.LOG_FILE.exists():
        return counts

    group_re = re.compile(r"^compound_(" + "|".join(PE1_FAULTS) + r")_(\d+)_(.+)$")
    groups: dict[tuple[str, str], set[str]] = {}
    with open(dfc.LOG_FILE, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            m = group_re.match(row.get("run_id", ""))
            if not m:
                continue
            pe1, num, leg = m.group(1), m.group(2), m.group(3)
            groups.setdefault((pe1, num), set()).add(leg)

    for (pe1, _num), legs in groups.items():
        if pe1 in legs and PE2_FAULT in legs:
            counts[pe1] += 1
    return counts


def _rest(lo: float, hi: float, label: str) -> None:
    m = random.uniform(lo, hi)
    dfc.log(f"{label} {m:.1f} min...")
    time.sleep(m * 60)


def run_compound(pe1_fault: str, group_id: str) -> tuple[bool, bool]:
    """Inject PE1 fault and PE2 VRF concurrently; log both legs for rebuild."""
    dfc.log(f"=== COMPOUND {group_id}: {pe1_fault} (station1) + {PE2_FAULT} (station2) ===")
    results: dict[str, tuple] = {}
    errors: dict[str, Exception] = {}

    def worker(fault_type: str) -> None:
        try:
            results[fault_type] = dfc.INJECTORS[fault_type](f"{group_id}_{fault_type}")
        except Exception as exc:  # noqa: BLE001
            errors[fault_type] = exc

    legs = [pe1_fault, PE2_FAULT]
    threads = [threading.Thread(target=worker, args=(ft,), name=ft) for ft in legs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_pe1 = ok_pe2 = False
    for ft in legs:
        if ft in errors:
            dfc.log(f"COMPOUND leg {ft} ERROR: {errors[ft]}")
            continue
        fs, bt = results[ft]
        log_id = f"compound_{group_id}_{ft}"
        dfc.append_log_row(ft, log_id, fs, bt)
        dfc.log(f"Logged {ft} {fs.isoformat()} -> {bt.isoformat()}")
        if ft == pe1_fault:
            ok_pe1 = True
        else:
            ok_pe2 = True
    dfc.clear_all_faults()
    return ok_pe1, ok_pe2


def run_campaign(
    *,
    per_pe1: int,
    retry: int,
    rest_min: float,
    rest_max: float,
    counts: dict[str, int] | None = None,
    already_done: dict[str, int] | None = None,
) -> dict:
    dfc.clear_all_faults()
    dfc.generate_dynamic_traffic()

    already_done = already_done or {f: 0 for f in PE1_FAULTS}
    targets = counts if counts is not None else {f: per_pe1 for f in PE1_FAULTS}
    weights = {f: max(targets.get(f, 0) - already_done.get(f, 0), 0) for f in PE1_FAULTS}
    schedule: list[str] = []
    for pe1, n in weights.items():
        schedule.extend([pe1] * n)
    random.shuffle(schedule)

    if any(already_done.values()):
        dfc.log(
            f"Resuming: already-completed compounds {already_done} — "
            f"remaining schedule {weights} (targets {targets})"
        )

    done: dict[str, int] = dict(already_done)
    attempts = 0

    for pe1 in schedule:
        if dfc._shutdown_requested:
            dfc.log("Shutdown requested — stopping compound overlap campaign.")
            break
        _rest(rest_min, rest_max, f"Normal ops before compound {pe1}+{PE2_FAULT}")
        if dfc._shutdown_requested:
            break

        done[pe1] += 1
        n = done[pe1]
        group_id = f"{pe1}_{n:02d}"
        success = False
        for attempt in range(1, retry + 2):
            attempts += 1
            dfc.log(f"Compound slot {pe1} #{n} attempt {attempt}/{retry + 1}")
            ok_pe1, ok_pe2 = run_compound(pe1, group_id)
            if ok_pe1 and ok_pe2:
                success = True
                break
            dfc.log(f"Compound incomplete (pe1={ok_pe1} vrf={ok_pe2}) — retrying after settle")
            settle = random.uniform(1.5, 2.5)
            time.sleep(settle * 60)
            dfc.clear_all_faults()
            dfc.generate_dynamic_traffic()

        if not success:
            dfc.log(f"WARN: compound {pe1} #{n} failed after {retry + 1} attempts")
            done[pe1] -= 1

        settle = random.uniform(*SETTLE_AFTER_COMPOUND_MIN)
        dfc.log(f"  recovery settle {settle:.1f} min...")
        time.sleep(settle * 60)
        dfc.generate_dynamic_traffic()

    dfc.log("=" * 60)
    dfc.log(f"COMPOUND OVERLAP CAMPAIGN DONE — pe1 counts {done} attempts={attempts}")
    dfc.log("=" * 60)
    dfc.clear_all_faults()
    dfc.run_ssh(dfc.PE1_SSH, "pkill iperf3", quiet=True)
    dfc.run_ssh(dfc.PE2_SSH, "pkill iperf3", quiet=True)
    dfc.export_prometheus_csv()
    try:
        dfc.validate_campaign_log(min_per=1)
    except Exception as exc:  # noqa: BLE001
        dfc.log(f"validate warn: {exc}")
    return done


def _parse_counts(spec: str) -> dict[str, int]:
    """Parse "fault=count,fault=count" into a schedule dict; unknown types rejected."""
    out: dict[str, int] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"--counts entries must be fault_type=N, got {part!r}")
        name, n = part.split("=", 1)
        name = name.strip()
        if name not in PE1_FAULTS:
            raise ValueError(f"--counts unknown PE1 fault {name!r}, expected one of {PE1_FAULTS}")
        out[name] = int(n.strip())
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Compound PE1+VRF overlap training campaign")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--per-pe1", type=int, default=2, help="Overlapping compounds per PE1 fault type")
    parser.add_argument(
        "--counts",
        default=None,
        help=(
            "Weighted schedule override, e.g. "
            "'tunnel_degradation=4,congestion_breach=4,bgp_route_flap=0'. "
            "Takes precedence over --per-pe1; omitted types default to 0."
        ),
    )
    parser.add_argument("--retry", type=int, default=2, help="Extra attempts per slot if a leg fails")
    parser.add_argument("--rest-min", type=float, default=REST_BETWEEN_MIN[0])
    parser.add_argument("--rest-max", type=float, default=REST_BETWEEN_MIN[1])
    args = parser.parse_args()
    if args.per_pe1 < 1:
        parser.error("--per-pe1 must be >= 1")
    if args.rest_max < args.rest_min:
        parser.error("--rest-max must be >= --rest-min")

    counts = None
    if args.counts:
        try:
            counts = _parse_counts(args.counts)
        except ValueError as exc:
            parser.error(str(exc))
        for pe1 in PE1_FAULTS:
            counts.setdefault(pe1, 0)
        if sum(counts.values()) < 1:
            parser.error("--counts must schedule at least one compound")

    dfc.init_run_paths(args.run_id)
    dfc.ensure_log_header()
    dfc._campaign_start = _load_or_init_campaign_start()
    already_done = completed_compound_counts()
    dfc.log(f"Run directory: {dfc.LOG_FILE.parent}")
    dfc.log("=" * 60)
    if counts:
        dfc.log(f"DECA COMPOUND OVERLAP CAMPAIGN — weighted counts {counts} (retry={args.retry})")
    else:
        dfc.log(
            f"DECA COMPOUND OVERLAP CAMPAIGN — {args.per_pe1}× each PE1 + {PE2_FAULT} "
            f"(retry={args.retry})"
        )
    dfc.log("=" * 60)
    run_campaign(
        per_pe1=args.per_pe1,
        retry=args.retry,
        rest_min=args.rest_min,
        rest_max=args.rest_max,
        counts=counts,
        already_done=already_done,
    )


if __name__ == "__main__":
    main()
