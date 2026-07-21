#!/usr/bin/env python3
"""Lean standalone bgp_route_flap seed campaign — first real telemetry for
the new live bgp_flap_count feature (docs/DECA_ROI_TIERS.md Tier 5b).

Every historical bgp_route_flap window in the lake predates the
bgp_flap_count exporter (deployed 2026-07-21) — rebuild_unified.py only
reads each run's already-exported network_telemetry.csv, so those rows will
carry bgp_flap_count=NaN forever; there is no live re-query that backfills a
metric Telegraf wasn't scraping at the time. This campaign's only job is to
give the classifier a first batch of real, non-NaN bgp_flap_count values
attached to real bgp_route_flap labels, before deca_bgp_diagnose.py's
gate-separability numbers (baseline: p(anomaly)=0.516, 46.6% flagged) can be
re-checked meaningfully.

Standalone (no VRF compound) and no near-miss baiting — same lean-recall
shape as deca_vrf_recall_campaign.py, just for the other rare class.

Usage
-----
    python scripts/deca_bgp_flap_recall_campaign.py --run-id bgp_flap_recall_$(date +%Y%m%d_%H%M) \\
        --bgp 6

Then:
    python scripts/rebuild_unified.py --all-rpi-runs
    python scripts/deca_school_exam_train.py --auto-promote --baseline-macro-f1 0.717
    python scripts/deca_bgp_diagnose.py --exam-seed 42 --family plain --beta 1.5
"""
from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timezone

import deca_fault_campaign as dfc

REST_BETWEEN_MIN = (3.5, 5.5)
SETTLE_AFTER_REAL_MIN = (2.5, 4.0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rest(lo: float, hi: float, label: str) -> None:
    m = random.uniform(lo, hi)
    dfc.log(f"{label} {m:.1f} min...")
    time.sleep(m * 60)


def run_campaign(*, n_bgp: int, rest_min: float, rest_max: float) -> dict:
    dfc.clear_all_faults()
    dfc.generate_dynamic_traffic()

    done = {"bgp_route_flap": 0}
    for i in range(n_bgp):
        if dfc._shutdown_requested:
            dfc.log("Shutdown requested — stopping bgp_flap recall campaign.")
            break
        _rest(rest_min, rest_max, "Normal ops before real bgp_route_flap")
        if dfc._shutdown_requested:
            break
        done["bgp_route_flap"] += 1
        n = done["bgp_route_flap"]
        run_id = f"bgp_flap_recall_{n:03d}"
        dfc.log(f"=== REAL bgp_route_flap {n}/{n_bgp} run_id={run_id} ===")
        try:
            fs, bt = dfc.INJECTORS["bgp_route_flap"](run_id)
            dfc.append_log_row("bgp_route_flap", f"real_{run_id}", fs, bt)
            dfc.log(f"Logged bgp_route_flap {fs.isoformat()} -> {bt.isoformat()}")
        except Exception as exc:  # noqa: BLE001
            dfc.log(f"ERROR during bgp_route_flap: {exc}")
            done["bgp_route_flap"] = max(0, done["bgp_route_flap"] - 1)
        finally:
            dfc.clear_all_faults()
        settle = random.uniform(*SETTLE_AFTER_REAL_MIN)
        dfc.log(f"  recovery settle {settle:.1f} min...")
        time.sleep(settle * 60)
        dfc.generate_dynamic_traffic()

    dfc.log("=" * 60)
    dfc.log(f"BGP FLAP RECALL CAMPAIGN DONE — {done}")
    dfc.log("=" * 60)
    dfc.clear_all_faults()
    dfc.run_ssh(dfc.PE1_SSH, "pkill iperf3", quiet=True)
    dfc.export_prometheus_csv()
    try:
        dfc.validate_campaign_log(min_per=1)
    except Exception as exc:  # noqa: BLE001
        dfc.log(f"validate warn: {exc}")
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="Lean standalone bgp_route_flap seed campaign")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--bgp", type=int, default=6, help="Completed bgp_route_flap events")
    parser.add_argument("--rest-min", type=float, default=REST_BETWEEN_MIN[0])
    parser.add_argument("--rest-max", type=float, default=REST_BETWEEN_MIN[1])
    args = parser.parse_args()
    if args.bgp < 1:
        parser.error("--bgp must be >= 1")
    if args.rest_max < args.rest_min:
        parser.error("--rest-max must be >= --rest-min")

    dfc.init_run_paths(args.run_id)
    dfc.ensure_log_header()
    dfc._campaign_start = _now()
    dfc.log(f"Run directory: {dfc.LOG_FILE.parent}")
    dfc.log("=" * 60)
    dfc.log(f"DECA BGP FLAP RECALL CAMPAIGN — bgp_route_flap x{args.bgp} (Tier 5b seed)")
    dfc.log("=" * 60)
    run_campaign(n_bgp=args.bgp, rest_min=args.rest_min, rest_max=args.rest_max)


if __name__ == "__main__":
    main()
