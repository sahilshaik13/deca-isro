#!/usr/bin/env python3
"""Lean PE2 VRF recall campaign — restore detection without flooding near-miss.

After specificity PASS, the blind night missed a genuine PE2 ``vrf_leakage``.
This campaign adds **completed** VRF (and light tunnel) reals so rebuild can
pull the VRF decision boundary back toward recall — without another large
``precursor_aborted`` dump that would re-teach over-conservatism.

Usage
-----
    python scripts/deca_vrf_recall_campaign.py --run-id vrf_recall_$(date +%Y%m%d_%H%M) \\
        --vrf 5 --tunnel 2

Then:
    python scripts/rebuild_unified.py --all-rpi-runs
    python scripts/deca_school_exam_train.py --auto-promote --baseline-macro-f1 0.7157
    python scripts/deca_score_temporal.py --soft-streak
    # Re-check: specificity_exam_v1 + v2 + short control — must not reopen cry-wolf.
"""
from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timezone

import deca_fault_campaign as dfc

REST_BETWEEN_MIN = (4.0, 6.5)
SETTLE_AFTER_REAL_MIN = (3.0, 4.5)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rest(lo: float, hi: float, label: str) -> None:
    m = random.uniform(lo, hi)
    dfc.log(f"{label} {m:.1f} min...")
    time.sleep(m * 60)


def run_campaign(*, n_vrf: int, n_tunnel: int, rest_min: float, rest_max: float) -> None:
    dfc.clear_all_faults()
    dfc.generate_dynamic_traffic()

    # Interleave VRF-heavy schedule with a few tunnels so the lake doesn't
    # skew to a single class, but VRF is the quota that must complete.
    schedule: list[str] = []
    for i in range(max(n_vrf, n_tunnel)):
        if i < n_vrf:
            schedule.append("vrf_leakage")
        if i < n_tunnel:
            schedule.append("tunnel_degradation")

    done = {"vrf_leakage": 0, "tunnel_degradation": 0}
    for fault_type in schedule:
        if dfc._shutdown_requested:
            dfc.log("Shutdown requested — stopping VRF recall campaign.")
            break
        _rest(rest_min, rest_max, f"Normal ops before real {fault_type}")
        if dfc._shutdown_requested:
            break
        done[fault_type] += 1
        n = done[fault_type]
        run_id = f"recall_{fault_type}_{n:03d}"
        dfc.log(f"=== REAL {fault_type} {n} run_id={run_id} ===")
        try:
            fs, bt = dfc.INJECTORS[fault_type](run_id)
            dfc.append_log_row(fault_type, f"real_{run_id}", fs, bt)
            dfc.log(f"Logged {fault_type} {fs.isoformat()} -> {bt.isoformat()}")
        except Exception as exc:  # noqa: BLE001
            dfc.log(f"ERROR during {fault_type}: {exc}")
            done[fault_type] = max(0, done[fault_type] - 1)
        finally:
            dfc.clear_all_faults()
        settle = random.uniform(*SETTLE_AFTER_REAL_MIN)
        dfc.log(f"  recovery settle {settle:.1f} min...")
        time.sleep(settle * 60)
        dfc.generate_dynamic_traffic()

    dfc.log("=" * 60)
    dfc.log(f"VRF RECALL CAMPAIGN DONE — {done}")
    dfc.log("=" * 60)
    dfc.clear_all_faults()
    dfc.run_ssh(dfc.PE1_SSH, "pkill iperf3", quiet=True)
    dfc.export_prometheus_csv()
    try:
        dfc.validate_campaign_log(min_per=1)
    except Exception as exc:  # noqa: BLE001
        dfc.log(f"validate warn: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lean PE2 VRF recall data campaign")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--vrf", type=int, default=5, help="Completed vrf_leakage events")
    parser.add_argument("--tunnel", type=int, default=2, help="Completed tunnel events (balance)")
    parser.add_argument("--rest-min", type=float, default=4.0)
    parser.add_argument("--rest-max", type=float, default=6.5)
    args = parser.parse_args()
    if args.vrf < 1:
        parser.error("--vrf must be >= 1")
    if args.rest_max < args.rest_min:
        parser.error("--rest-max must be >= --rest-min")

    dfc.init_run_paths(args.run_id)
    dfc.ensure_log_header()
    dfc._campaign_start = _now()
    dfc.log(f"Run directory: {dfc.LOG_FILE.parent}")
    dfc.log("=" * 60)
    dfc.log(f"DECA VRF RECALL CAMPAIGN — vrf={args.vrf} tunnel={args.tunnel}")
    dfc.log("=" * 60)
    run_campaign(
        n_vrf=args.vrf,
        n_tunnel=args.tunnel,
        rest_min=args.rest_min,
        rest_max=args.rest_max,
    )


if __name__ == "__main__":
    main()
