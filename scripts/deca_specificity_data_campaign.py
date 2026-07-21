#!/usr/bin/env python3
"""DECA specificity data campaign — targeted near-miss + confusion-triangle labels.

After specificity exam v1, the lake still under-teaches:
  - aborted onsets that must stay **healthy** (near-miss / precursor_aborted)
  - PE2 calm-path flicker (exam failed ``vrf`` / ``tunnel`` on station2)
  - balanced real tunnel / congestion / VRF (and BGP) so retrain doesn't forget detection

This campaign is **quota-driven and mostly deterministic** (fixed near-miss holds,
round-robin fault types). It reuses ``deca_fault_campaign`` injectors and logs
compatible with ``rebuild_unified.py``.

Usage
-----
    # Default: 12 near-misses (8 PE1 + 4 PE2) + 3 real events × 4 fault types
    python scripts/deca_specificity_data_campaign.py --run-id spec_data_$(date +%Y%m%d)

    python scripts/deca_specificity_data_campaign.py --near-misses-pe1 8 --near-misses-pe2 4 --per-type 3

After the campaign finishes:
    python scripts/rebuild_unified.py
    python scripts/deca_school_exam_train.py   # or your promote path
    # then re-run: scripts/deca_blind_test.sh … --playlist scripts/playlists/specificity_exam_v1.json

See docs/DECA_SPECIFICITY_EXAM.md § Next loop.
"""
from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timezone

import deca_fault_campaign as dfc

# Fixed hold ladder (seconds) — matches exam playlist / stretches past soft enter
PE1_HOLD_LADDER = [25, 30, 35, 40, 45, 50, 30, 40]
PE2_HOLD_LADDER = [30, 35, 40, 45]

# Focus types first in the round-robin (confusion triangle), BGP last for balance
FAULT_ORDER = [
    "tunnel_degradation",
    "congestion_breach",
    "vrf_leakage",
    "bgp_route_flap",
]

REST_BETWEEN_MIN = (4.0, 7.0)  # minutes of clean ops between events
SETTLE_AFTER_REAL_MIN = (3.0, 5.0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rest(minutes_lo: float, minutes_hi: float, label: str) -> None:
    m = random.uniform(minutes_lo, minutes_hi)
    dfc.log(f"{label} {m:.1f} min...")
    time.sleep(m * 60)


def run_campaign(
    *,
    near_misses_pe1: int,
    near_misses_pe2: int,
    per_type: int,
    rest_min: float,
    rest_max: float,
) -> None:
    dfc.clear_all_faults()
    dfc.generate_dynamic_traffic()

    nm_pe1_done = 0
    nm_pe2_done = 0
    real_done: dict[str, int] = {t: 0 for t in FAULT_ORDER}
    real_index = 0

    # Interleave: near-miss blocks, then one real fault of each type, repeat.
    # Guarantees near-miss quota even if we stop early on shutdown.
    while (
        nm_pe1_done < near_misses_pe1
        or nm_pe2_done < near_misses_pe2
        or any(real_done[t] < per_type for t in FAULT_ORDER)
    ):
        if dfc._shutdown_requested:
            dfc.log("Shutdown requested — stopping specificity data campaign.")
            break

        # Prefer unfinished near-misses first (the trust gap).
        if nm_pe1_done < near_misses_pe1:
            _rest(rest_min, rest_max, "Normal ops before PE1 near-miss")
            if dfc._shutdown_requested:
                break
            hold = PE1_HOLD_LADDER[nm_pe1_done % len(PE1_HOLD_LADDER)]
            nm_pe1_done += 1
            nm_id = f"nm_pe1_{nm_pe1_done:03d}"
            dfc.log(f"=== PE1 near-miss {nm_id} hold_s={hold} (label=precursor_aborted) ===")
            fs, bt = dfc.inject_near_miss_aborted(nm_id, hold_s=hold)
            dfc.append_log_row("precursor_aborted", f"real_{nm_id}", fs, bt)
            dfc.clear_all_faults()
            continue

        if nm_pe2_done < near_misses_pe2:
            _rest(rest_min, rest_max, "Normal ops before PE2 near-miss")
            if dfc._shutdown_requested:
                break
            hold = PE2_HOLD_LADDER[nm_pe2_done % len(PE2_HOLD_LADDER)]
            nm_pe2_done += 1
            nm_id = f"nm_pe2_{nm_pe2_done:03d}"
            dfc.log(f"=== PE2 near-miss {nm_id} hold_s={hold} (label=precursor_aborted) ===")
            fs, bt = dfc.inject_near_miss_pe2_aborted(nm_id, hold_s=hold)
            dfc.append_log_row("precursor_aborted", f"real_{nm_id}", fs, bt)
            dfc.clear_all_faults()
            continue

        # Real faults — round-robin by FAULT_ORDER until each hits per_type.
        candidates = [t for t in FAULT_ORDER if real_done[t] < per_type]
        if not candidates:
            break
        fault_type = candidates[real_index % len(candidates)]
        real_index += 1
        _rest(rest_min, rest_max, f"Normal ops before real {fault_type}")
        if dfc._shutdown_requested:
            break
        real_done[fault_type] += 1
        n = real_done[fault_type]
        run_id = f"spec_{fault_type}_{n:03d}"
        dfc.log(f"=== REAL {fault_type} {n}/{per_type} run_id={run_id} ===")
        try:
            fs, bt = dfc.INJECTORS[fault_type](run_id)
            dfc.append_log_row(fault_type, f"real_{run_id}", fs, bt)
            dfc.log(f"Logged {fault_type} {fs.isoformat()} -> {bt.isoformat()}")
        except Exception as exc:  # noqa: BLE001
            dfc.log(f"ERROR during {fault_type}: {exc}")
            real_done[fault_type] = max(0, real_done[fault_type] - 1)
        finally:
            dfc.clear_all_faults()
        settle = random.uniform(*SETTLE_AFTER_REAL_MIN)
        dfc.log(f"  recovery settle {settle:.1f} min...")
        time.sleep(settle * 60)
        dfc.generate_dynamic_traffic()

    dfc.log("=" * 60)
    dfc.log(
        f"SPECIFICITY DATA CAMPAIGN DONE — "
        f"nm_pe1={nm_pe1_done}/{near_misses_pe1} "
        f"nm_pe2={nm_pe2_done}/{near_misses_pe2} "
        f"real={real_done}"
    )
    dfc.log("=" * 60)
    dfc.clear_all_faults()
    dfc.run_ssh(dfc.PE1_SSH, "pkill iperf3", quiet=True)
    # Export Prom window for rebuild_unified (required network_telemetry.csv).
    dfc.export_prometheus_csv()
    # Soft validate — near-miss-heavy campaigns won't hit classic per-type mins.
    try:
        dfc.validate_campaign_log(min_per=max(1, min(per_type, 1)))
    except Exception as exc:  # noqa: BLE001
        dfc.log(f"validate warn: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DECA specificity data campaign — near-miss + confusion-triangle quotas"
    )
    parser.add_argument("--run-id", default=None, help="Run dir under data/rpi-net/runs/")
    parser.add_argument("--near-misses-pe1", type=int, default=8, help="PE1 aborted onsets")
    parser.add_argument("--near-misses-pe2", type=int, default=4, help="PE2 aborted onsets")
    parser.add_argument(
        "--per-type",
        type=int,
        default=3,
        help="Real fault events per type (tunnel/congestion/vrf/bgp)",
    )
    parser.add_argument("--rest-min", type=float, default=4.0, help="Min rest minutes between events")
    parser.add_argument("--rest-max", type=float, default=7.0, help="Max rest minutes between events")
    args = parser.parse_args()
    if args.near_misses_pe1 < 0 or args.near_misses_pe2 < 0 or args.per_type < 0:
        parser.error("quotas must be >= 0")
    if args.rest_max < args.rest_min:
        parser.error("--rest-max must be >= --rest-min")

    dfc.init_run_paths(args.run_id)
    dfc.ensure_log_header()
    dfc._campaign_start = _now()
    dfc.log(f"Run directory: {dfc.LOG_FILE.parent}")
    dfc.log("=" * 60)
    dfc.log(
        f"DECA SPECIFICITY DATA CAMPAIGN — "
        f"nm_pe1={args.near_misses_pe1} nm_pe2={args.near_misses_pe2} "
        f"per_type={args.per_type} (×{len(FAULT_ORDER)} types)"
    )
    dfc.log("=" * 60)

    run_campaign(
        near_misses_pe1=args.near_misses_pe1,
        near_misses_pe2=args.near_misses_pe2,
        per_type=args.per_type,
        rest_min=args.rest_min,
        rest_max=args.rest_max,
    )


if __name__ == "__main__":
    main()
