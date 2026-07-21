#!/usr/bin/env python3
"""Phase-aware specificity exam report — pass bar for playlist runs.

Reads ``exam_phases.jsonl`` (stamped by ``deca_blind_chaos --playlist``), sealed
near-misses, and operator ``declarations.jsonl``. Grades each phase:

- ``calm`` with ``score_spurious``: any ``confirmed_raise`` in the phase window fails
- ``near_miss`` with ``score_near_miss``: any confirmed non-healthy in the sealed
  near-miss window (+ grace) fails

Pass bar (exit 0 only if all hold):
- near-miss FA count == 0
- scored-calm spurious confirms == 0
- BGP confirmed raises in the whole run == 0 (no-pulse invention must stay dead)

Usage
-----
    python scripts/deca_blind_exam_report.py --run-id specificity_exam_v1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deca_live_common import declarations_path, ground_truth_path, live_run_dir, read_jsonl, run_meta_path

NEAR_MISS_GRACE_MIN = 3.0
HEALTHY = "healthy"


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_phase_windows(stamps: list[dict]) -> list[dict]:
    """Pair start/end stamps into closed windows."""
    open_phases: dict[str, dict] = {}
    windows: list[dict] = []
    for rec in stamps:
        pid = rec["phase_id"]
        if rec.get("status") == "start":
            open_phases[pid] = rec
        elif rec.get("status") == "end" and pid in open_phases:
            start = open_phases.pop(pid)
            windows.append(
                {
                    "phase_id": pid,
                    "kind": start.get("kind") or rec.get("kind"),
                    "t0": parse_ts(start["ts"]),
                    "t1": parse_ts(rec["ts"]),
                    "score_spurious": bool(start.get("score_spurious", True)),
                    "score_near_miss": bool(start.get("score_near_miss", True)),
                    "event_id": start.get("event_id") or rec.get("event_id"),
                    "note": start.get("note"),
                }
            )
    return windows


def confirmed_raises_in(decls: list[dict], t0: datetime, t1: datetime) -> list[dict]:
    out = []
    for d in decls:
        if d.get("event") != "confirmed_raise":
            continue
        ts = parse_ts(d["ts"])
        if t0 <= ts <= t1:
            out.append(d)
    return out


def grade(run_id: str) -> dict:
    run_dir = live_run_dir(run_id)
    phases_path = run_dir / "exam_phases.jsonl"
    if not phases_path.exists():
        raise SystemExit(f"No exam_phases.jsonl for {run_id} — not a playlist exam?")

    stamps = read_jsonl(phases_path)
    windows = build_phase_windows(stamps)
    decls = read_jsonl(declarations_path(run_id))
    sealed = read_jsonl(ground_truth_path(run_id))
    sealed_by_id = {e["event_id"]: e for e in sealed}

    phase_rows = []
    calm_spurious_total = 0
    near_miss_fa_total = 0
    near_miss_scored = 0

    for w in windows:
        row: dict = {
            "phase_id": w["phase_id"],
            "kind": w["kind"],
            "t0": w["t0"].isoformat(),
            "t1": w["t1"].isoformat(),
            "note": w.get("note"),
            "pass": True,
            "detail": None,
        }
        if w["kind"] == "calm":
            if not w["score_spurious"]:
                row["detail"] = "warm-up — not scored"
                phase_rows.append(row)
                continue
            raises = confirmed_raises_in(decls, w["t0"], w["t1"])
            # Exclude raises that fall inside a near-miss sealed window (those are NM FAs).
            nm_windows = []
            for ev in sealed:
                if not ev.get("is_near_miss"):
                    continue
                a = parse_ts(ev["fault_start"])
                b = parse_ts(ev["breach_time"]) + timedelta(minutes=NEAR_MISS_GRACE_MIN)
                nm_windows.append((ev["host"], a, b))
            spurious = []
            for d in raises:
                ts = parse_ts(d["ts"])
                host = d.get("host")
                inside_nm = any(h == host and a <= ts <= b for (h, a, b) in nm_windows)
                if not inside_nm:
                    spurious.append({"host": host, "ts": d["ts"], "class": d.get("confirmed")})
            calm_spurious_total += len(spurious)
            row["spurious"] = spurious
            row["pass"] = len(spurious) == 0
            row["detail"] = f"spurious={len(spurious)}"
        elif w["kind"] == "near_miss":
            if not w["score_near_miss"]:
                row["detail"] = "not scored"
                phase_rows.append(row)
                continue
            near_miss_scored += 1
            ev_id = w.get("event_id")
            ev = sealed_by_id.get(ev_id) if ev_id else None
            if ev is None:
                # Fallback: match by phase id suffix in event_id
                for e in sealed:
                    if e.get("is_near_miss") and w["phase_id"] in str(e.get("event_id")):
                        ev = e
                        break
            if ev is None:
                row["pass"] = False
                row["detail"] = "missing sealed near-miss"
                near_miss_fa_total += 1
            else:
                host = ev["host"]
                a = parse_ts(ev["fault_start"])
                b = parse_ts(ev["breach_time"]) + timedelta(minutes=NEAR_MISS_GRACE_MIN)
                host_decls = [d for d in decls if d.get("host") == host]
                # Carry-over sticky confirm + in-window confirms (same idea as scorecard).
                hit_class = None
                prev = None
                for d in host_decls:
                    if parse_ts(d["ts"]) < a:
                        prev = d
                if prev is not None and prev.get("confirmed", HEALTHY) != HEALTHY:
                    hit_class = prev.get("confirmed")
                if hit_class is None:
                    for d in host_decls:
                        ts = parse_ts(d["ts"])
                        if a <= ts <= b and d.get("confirmed", HEALTHY) != HEALTHY:
                            hit_class = d.get("confirmed")
                            break
                fa = hit_class is not None
                if fa:
                    near_miss_fa_total += 1
                row["false_alarm"] = fa
                row["class"] = hit_class
                row["pass"] = not fa
                row["detail"] = f"FA={fa} class={row['class']}"
        else:
            row["detail"] = f"unknown kind {w['kind']}"
        phase_rows.append(row)

    bgp_confirms = [
        d
        for d in decls
        if d.get("event") == "confirmed_raise" and d.get("confirmed") == "bgp_route_flap"
    ]

    passed = (
        near_miss_fa_total == 0
        and calm_spurious_total == 0
        and len(bgp_confirms) == 0
    )
    report = {
        "run_id": run_id,
        "passed": passed,
        "pass_bar": {
            "near_miss_fa": near_miss_fa_total,
            "near_miss_scored": near_miss_scored,
            "calm_spurious": calm_spurious_total,
            "bgp_confirms": len(bgp_confirms),
            "require": {
                "near_miss_fa": 0,
                "calm_spurious": 0,
                "bgp_confirms": 0,
            },
        },
        "phases": phase_rows,
        "bgp_confirms": [
            {"host": d.get("host"), "ts": d.get("ts")} for d in bgp_confirms
        ],
    }
    out_path = run_dir / "exam_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def print_report(report: dict) -> None:
    bar = report["pass_bar"]
    print("=" * 60)
    print(f"  DECA specificity exam — {report['run_id']}")
    print("=" * 60)
    for p in report["phases"]:
        mark = "PASS" if p["pass"] else "FAIL"
        print(f"  [{mark}] {p['phase_id']:<10} {p['kind']:<10} {p.get('detail')}")
    print("-" * 60)
    print(
        f"  Near-miss FA : {bar['near_miss_fa']} / {bar['near_miss_scored']}  "
        f"(require 0)"
    )
    print(f"  Calm spurious: {bar['calm_spurious']}  (require 0)")
    print(f"  BGP confirms : {bar['bgp_confirms']}  (require 0)")
    print("-" * 60)
    if report["passed"]:
        print("  RESULT: PASS — specificity exam trust bar met")
    else:
        print("  RESULT: FAIL — specificity exam trust bar NOT met")
    print("=" * 60)
    print(f"  Wrote {live_run_dir(report['run_id']) / 'exam_report.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="DECA specificity exam phase report")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    # Touch meta so missing runs fail loudly
    if not run_meta_path(args.run_id).exists() and not (
        live_run_dir(args.run_id) / "exam_phases.jsonl"
    ).exists():
        raise SystemExit(f"Run not found: {args.run_id}")
    report = grade(args.run_id)
    print_report(report)
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
