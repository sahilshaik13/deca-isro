#!/usr/bin/env python3
"""Aggregate multiple DECA blind-test runs into a trustworthy range.

A single 60-minute blind run is statistical noise — the same problem the School
Exam solved with ``--report-seeds 5``. Few real events in a short random window
swing hard on which circumstances happen to land. This tool ingests N graded
``scorecard.json`` files and reports mean +/- spread (and min/max) per metric, so
you can quote a range instead of one night's lucky/unlucky number.

It also pools the raw per-event records across runs to recompute the rate
metrics on the *combined* sample (detection rate, class accuracy, severity r),
which is a stronger estimate than averaging per-run rates when runs have
different event counts.

Usage
-----
    # explicit scorecards
    python scripts/deca_blind_aggregate.py run_a/scorecard.json run_b/scorecard.json

    # or every archived run
    python scripts/deca_blind_aggregate.py --glob 'data/rpi-net/blind-tests/*/scorecard.json'

    # or by run-id under data/rpi-net/{live,blind-tests}/
    python scripts/deca_blind_aggregate.py --run-id blind_a blind_b blind_c
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import math
from pathlib import Path

from _paths import RPI_NET_DIR


def _mean_sd(xs: list[float]) -> tuple[float | None, float | None]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return round(m, 3), 0.0
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return round(m, 3), round(math.sqrt(var), 3)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / math.sqrt(sxx * syy), 3)


def resolve_run_id(run_id: str) -> Path | None:
    for sub in ("blind-tests", "live"):
        p = RPI_NET_DIR / sub / run_id / "scorecard.json"
        if p.exists():
            return p
    return None


def collect_paths(args) -> list[Path]:
    paths: list[Path] = []
    for p in args.scorecards:
        paths.append(Path(p))
    if args.glob:
        paths.extend(Path(p) for p in sorted(globmod.glob(args.glob)))
    for rid in args.run_id or []:
        p = resolve_run_id(rid)
        if p is None:
            print(f"  WARN: no scorecard for run-id '{rid}'")
        else:
            paths.append(p)
    # de-dupe, keep order
    seen, out = set(), []
    for p in paths:
        rp = p.resolve()
        if rp not in seen and p.exists():
            seen.add(rp)
            out.append(p)
    return out


# Metrics summarised as mean +/- sd across runs.
PER_RUN_METRICS = [
    ("detection_rate", "Detection rate", ""),
    ("class_accuracy", "Class accuracy (first decl)", ""),
    ("class_accuracy_eventually", "Class accuracy (eventual)", ""),
    ("mean_confirmed_lead_min", "Confirmed lead", " min"),
    ("mean_advisory_lead_min", "Advisory lead", " min"),
    ("eta_mae_min", "ETA MAE", " min"),
    ("severity_agreement", "Severity bucket agreement", ""),
    ("severity_pearson_r", "Severity Pearson r", ""),
    ("spurious_false_alarms", "Spurious false alarms", ""),
]


def aggregate(reports: list[dict]) -> dict:
    summaries = [r["summary"] for r in reports]

    per_metric = {}
    for key, _label, _suf in PER_RUN_METRICS:
        m, sd = _mean_sd([s.get(key) for s in summaries])
        vals = [s.get(key) for s in summaries if s.get(key) is not None]
        per_metric[key] = {
            "mean": m,
            "sd": sd,
            "min": round(min(vals), 3) if vals else None,
            "max": round(max(vals), 3) if vals else None,
            "n_runs": len(vals),
        }

    # Pooled estimates over the combined event sample.
    all_events = [e for r in reports for e in r["events"]]
    total_created = sum(s["circumstances_created"] for s in summaries)
    total_detected = sum(s["detected"] for s in summaries)
    total_correct = sum(s.get("class_correct", 0) for s in summaries)
    total_correct_ev = sum(s.get("class_correct_eventually", 0) for s in summaries)
    total_nm = sum(s.get("near_misses", 0) for s in summaries)
    total_nm_fa = sum(s.get("near_miss_false_alarms", 0) for s in summaries)
    total_spurious = sum(s.get("spurious_false_alarms", 0) for s in summaries)

    sev_pairs = [
        (e["model_severity_score"], e["actual_severity_score"])
        for e in all_events
        if e.get("model_severity_score") is not None and e.get("actual_severity_score") is not None
    ]
    pooled = {
        "runs": len(reports),
        "total_circumstances": total_created,
        "total_detected": total_detected,
        "pooled_detection_rate": round(total_detected / total_created, 3) if total_created else None,
        "pooled_class_accuracy": round(total_correct / total_created, 3) if total_created else None,
        "pooled_class_accuracy_eventually": round(total_correct_ev / total_created, 3) if total_created else None,
        "total_near_misses": total_nm,
        "total_near_miss_false_alarms": total_nm_fa,
        "total_spurious_false_alarms": total_spurious,
        "pooled_severity_pearson_r": _pearson([p for p, _ in sev_pairs], [a for _, a in sev_pairs]),
        "severity_pairs": len(sev_pairs),
    }
    return {"pooled": pooled, "per_run_metric": per_metric,
            "run_ids": [s["run_id"] for s in summaries]}


def print_report(agg: dict) -> None:
    pooled = agg["pooled"]
    line = "=" * 72
    print(line)
    print(f"  DECA BLIND TEST — AGGREGATE OVER {pooled['runs']} RUN(S)")
    print(f"  runs: {', '.join(agg['run_ids'])}")
    print(line)
    print("  Per-run metric            mean +/- sd        [min .. max]   n")
    print("  " + "-" * 68)
    for key, label, suf in PER_RUN_METRICS:
        m = agg["per_run_metric"][key]
        if m["mean"] is None:
            print(f"  {label:<26} n/a")
            continue
        print(f"  {label:<26} {m['mean']}{suf} +/- {m['sd']}"
              f"    [{m['min']} .. {m['max']}]   {m['n_runs']}")
    print(line)
    print("  Pooled over the combined event sample:")
    print(f"    Circumstances                 : {pooled['total_circumstances']}")
    print(f"    Detection rate                : {pooled['pooled_detection_rate']} "
          f"({pooled['total_detected']}/{pooled['total_circumstances']})")
    print(f"    Class accuracy (first decl)   : {pooled['pooled_class_accuracy']}")
    print(f"    Class accuracy (eventual)     : {pooled['pooled_class_accuracy_eventually']}")
    print(f"    Severity Pearson r            : {pooled['pooled_severity_pearson_r']} "
          f"({pooled['severity_pairs']} pairs)")
    print(f"    Near-miss false alarms        : {pooled['total_near_miss_false_alarms']} "
          f"/ {pooled['total_near_misses']}")
    print(f"    Spurious false alarms (total) : {pooled['total_spurious_false_alarms']}")
    print(line)
    if pooled["runs"] < 3:
        print("  NOTE: <3 runs — treat these as indicative only. Run more nights "
              "with different seeds before quoting a range.")
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate DECA blind-test scorecards")
    parser.add_argument("scorecards", nargs="*", help="Paths to scorecard.json files")
    parser.add_argument("--glob", help="Glob of scorecard.json files")
    parser.add_argument("--run-id", nargs="*", help="Run ids under data/rpi-net/{blind-tests,live}/")
    parser.add_argument("--out", help="Write aggregate JSON here")
    args = parser.parse_args()

    paths = collect_paths(args)
    if not paths:
        raise SystemExit("No scorecards found. Pass paths, --glob, or --run-id.")

    reports = []
    for p in paths:
        try:
            reports.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: skipping {p}: {exc}")
    if not reports:
        raise SystemExit("No readable scorecards.")

    agg = aggregate(reports)
    print_report(agg)

    if args.out:
        Path(args.out).write_text(json.dumps(agg, indent=2), encoding="utf-8")
        print(f"  aggregate -> {args.out}")


if __name__ == "__main__":
    main()
