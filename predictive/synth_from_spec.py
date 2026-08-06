"""Physics-faithful synthetic series.csv generator (Pi contract).

Fills L0 / L3 / L5 gaps in seconds using trajectories from
docs/SYNTHETIC_DATASET_NETWORK_SPEC.md — not LLM freestyle floats.

Does NOT replace sealed Pi chaos_final. Train/augment only; always oneshot
on real chaos before promote.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SERIES_COLS = [
    "ts_unix",
    "latency_gre_ms",
    "latency_eth0_ms",
    "jitter_gre_ms",
    "loss_gre_pct",
    "util_gre_mbps",
    "net_bytes_recv_eth0",
    "net_bytes_sent_eth0",
    "cpu_usage_system",
    "cpu_usage_user",
    "mem_used_percent",
    "bgp_flap_count",
    "netflow_bulk_bytes",
    "netflow_voice_bytes",
    "ipsec_rekey_events_1h",
    "ipsec_rekey_anomaly",
    "htb_payload_ceil_mbps",
    "path_asymmetry",
]


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _idle_row(rng: np.random.Generator, ts: int, *, bgp0: float, bytes_rx: float, bytes_tx: float) -> dict:
    gre = float(np.clip(rng.normal(0.29, 0.04), 0.15, 0.8))
    eth = float(np.clip(rng.normal(0.29, 0.03), 0.15, 0.7))
    util = float(np.clip(rng.normal(0.18, 0.07), 0.02, 0.6))
    cpu_u = float(np.clip(rng.normal(12.0, 4.0), 2.0, 28.0))
    cpu_s = float(np.clip(rng.normal(14.0, 4.0), 3.0, 30.0))
    # ~1–3 Mbps ambient byte rates
    bytes_rx += float(rng.uniform(8e4, 2.5e5))
    bytes_tx += float(rng.uniform(5e4, 2.0e5))
    return {
        "ts_unix": int(ts),
        "latency_gre_ms": gre,
        "latency_eth0_ms": eth,
        "jitter_gre_ms": float(np.clip(abs(rng.normal(0.04, 0.02)), 0.0, 0.4)),
        "loss_gre_pct": 0.0,
        "util_gre_mbps": util,
        "net_bytes_recv_eth0": bytes_rx,
        "net_bytes_sent_eth0": bytes_tx,
        "cpu_usage_system": cpu_s,
        "cpu_usage_user": cpu_u,
        "mem_used_percent": float(np.clip(rng.normal(8.8, 0.15), 7.5, 12.0)),
        "bgp_flap_count": float(bgp0),
        "netflow_bulk_bytes": 0.0,
        "netflow_voice_bytes": 0.0,
        "ipsec_rekey_events_1h": float(rng.integers(40, 55)),
        "ipsec_rekey_anomaly": 1.0,
        "htb_payload_ceil_mbps": 34.0,
        "path_asymmetry": abs(gre - eth),
    }


def synthesize_l0(
    *,
    seconds: int = 600,
    seed: int = 0,
    t0: int | None = None,
) -> pd.DataFrame:
    rng = _rng(seed)
    t0 = int(t0 if t0 is not None else 1_700_000_000 + seed * 10_000)
    bgp0 = float(rng.integers(5000, 8000))
    rx = float(rng.uniform(1e9, 2e9))
    tx = float(rng.uniform(5e8, 1e9))
    rows = []
    for i in range(seconds):
        rows.append(_idle_row(rng, t0 + i, bgp0=bgp0, bytes_rx=rx, bytes_tx=tx))
        rx = rows[-1]["net_bytes_recv_eth0"]
        tx = rows[-1]["net_bytes_sent_eth0"]
    return pd.DataFrame(rows)[SERIES_COLS]


def synthesize_l3(
    *,
    baseline_sec: int = 60,
    inject_sec: int = 180,
    post_sec: int = 40,
    period_sec: float = 5.0,
    mild: bool = True,
    seed: int = 0,
    t0: int | None = None,
) -> pd.DataFrame:
    """BGP flap: cumulative counter steps. Mild ~0.3–0.8/s, severe ≥1.0/s over 10s roll."""
    rng = _rng(seed)
    t0 = int(t0 if t0 is not None else 1_700_100_000 + seed * 10_000)
    bgp = float(rng.integers(5000, 8000))
    rx = float(rng.uniform(1e9, 2e9))
    tx = float(rng.uniform(5e8, 1e9))
    rows: list[dict] = []
    # flaps per period: mild ~2–4, severe ~6–10 (period 5 → rate 0.4–0.8 vs 1.2–2.0)
    if mild:
        flaps_per_cycle = int(rng.integers(2, 5))
    else:
        flaps_per_cycle = int(rng.integers(6, 11))
    total = baseline_sec + inject_sec + post_sec
    next_flap_t = baseline_sec
    for i in range(total):
        row = _idle_row(rng, t0 + i, bgp0=bgp, bytes_rx=rx, bytes_tx=tx)
        rx, tx = row["net_bytes_recv_eth0"], row["net_bytes_sent_eth0"]
        if baseline_sec <= i < baseline_sec + inject_sec:
            if i >= next_flap_t:
                bgp += float(flaps_per_cycle)
                next_flap_t += max(1.0, float(period_sec) + float(rng.normal(0, 0.3)))
            # tiny secondary jitter only — do not invent rain/loss as BGP signature
            row["jitter_gre_ms"] = float(np.clip(row["jitter_gre_ms"] + abs(rng.normal(0, 0.05)), 0, 1.0))
        row["bgp_flap_count"] = bgp
        row["path_asymmetry"] = abs(row["latency_gre_ms"] - row["latency_eth0_ms"])
        rows.append(row)
    return pd.DataFrame(rows)[SERIES_COLS]


def synthesize_l5(
    *,
    baseline_sec: int = 40,
    ramp_sec: int = 200,
    plateau_sec: int = 80,
    post_sec: int = 40,
    start_mbit: float = 5.0,
    end_mbit: float = 24.0,
    seed: int = 0,
    t0: int | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Util congestion with BE-lift physics: util ≈ 1.07 × scheduled ceil."""
    rng = _rng(seed)
    t0 = int(t0 if t0 is not None else 1_700_200_000 + seed * 10_000)
    bgp = float(rng.integers(5000, 8000))
    rx = float(rng.uniform(1e9, 2e9))
    tx = float(rng.uniform(5e8, 1e9))
    rows: list[dict] = []
    sched: list[dict] = []
    inject = ramp_sec + plateau_sec
    total = baseline_sec + inject + post_sec
    for i in range(total):
        row = _idle_row(rng, t0 + i, bgp0=bgp, bytes_rx=rx, bytes_tx=tx)
        rx, tx = row["net_bytes_recv_eth0"], row["net_bytes_sent_eth0"]
        phase = "baseline"
        ceil = 34.0
        be_lifted = False
        if baseline_sec <= i < baseline_sec + inject:
            be_lifted = True
            t_inj = i - baseline_sec
            if t_inj < ramp_sec:
                phase = "ramp"
                frac = t_inj / max(1, ramp_sec - 1)
                ceil = float(start_mbit + frac * (end_mbit - start_mbit))
            else:
                phase = "plateau"
                ceil = float(end_mbit)
            # track ceil with encap overhead ~1.07 + small noise
            util = float(np.clip(ceil * 1.07 + rng.normal(0, 0.35), 0.5, 42.0))
            row["util_gre_mbps"] = util
            row["htb_payload_ceil_mbps"] = ceil
            # bytes scale with util (~Mbps → bytes/s)
            add = util * 1e6 / 8.0
            row["net_bytes_sent_eth0"] = tx + add
            tx = row["net_bytes_sent_eth0"]
            sched.append(
                {
                    "ts_unix": int(t0 + i),
                    "htb_payload_ceil_mbps": ceil,
                    "end_mbit": float(end_mbit),
                    "offer_mbit": float(2.0 * end_mbit),
                    "shape": "ce_veth",
                    "be_lifted": True,
                    "phase": phase,
                }
            )
        else:
            row["htb_payload_ceil_mbps"] = 34.0
            if i >= baseline_sec + inject:
                phase = "post"
        row["path_asymmetry"] = abs(row["latency_gre_ms"] - row["latency_eth0_ms"])
        rows.append(row)
    return pd.DataFrame(rows)[SERIES_COLS], sched


def _write_iter(
    out: Path,
    *,
    root: int,
    name: str,
    series: pd.DataFrame,
    recipe: dict,
    schedule: list[dict] | None = None,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    series.to_csv(out / "series.csv", index=False)
    label = {
        "train": True,
        "name": name,
        "root_label": int(root),
        "fabric": "pi",
        "synthetic": True,
        "schema_version": 2,
        "recipe": recipe,
    }
    (out / "label.json").write_text(json.dumps(label, indent=2) + "\n")
    (out / "recipe.json").write_text(json.dumps(recipe, indent=2) + "\n")
    if schedule is not None:
        with (out / "util_ceil_schedule.jsonl").open("w") as f:
            for row in schedule:
                f.write(json.dumps(row) + "\n")


def generate_gap_stamp(
    out_root: Path,
    *,
    n_l3_mild: int = 24,
    n_l3_severe: int = 12,
    n_l5: int = 24,
    n_l0: int = 2,
    seed: int = 42,
) -> dict:
    """Emit a protocol-like stamp focused on util + BGP gap classes."""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    meta = {
        "stamp": out_root.name,
        "synthetic": True,
        "physics": "SYNTHETIC_DATASET_NETWORK_SPEC.md",
        "counts": {},
    }
    # L0
    for i in range(n_l0):
        s = synthesize_l0(seconds=600, seed=seed + i)
        _write_iter(
            out_root / "L0_normal" / f"iter_{i+1:02d}",
            root=0,
            name="normal",
            series=s,
            recipe={"kind": "L0", "seconds": 600, "seed": seed + i},
        )
    meta["counts"]["L0"] = n_l0

    # L3 mild / severe
    periods_mild = [4, 5, 6, 7, 8, 10, 12]
    periods_sev = [3, 4, 5]
    for i in range(n_l3_mild):
        per = periods_mild[i % len(periods_mild)]
        s = synthesize_l3(
            inject_sec=150 + 10 * (i % 4),
            period_sec=float(per),
            mild=True,
            seed=seed + 100 + i,
        )
        _write_iter(
            out_root / "L3_bgp_flap" / f"iter_{i+1:02d}",
            root=3,
            name="bgp_flap",
            series=s,
            recipe={"kind": "L3", "mild": True, "period_sec": per, "seed": seed + 100 + i},
        )
    for i in range(n_l3_severe):
        per = periods_sev[i % len(periods_sev)]
        idx = n_l3_mild + i + 1
        s = synthesize_l3(
            inject_sec=150 + 10 * (i % 3),
            period_sec=float(per),
            mild=False,
            seed=seed + 200 + i,
        )
        _write_iter(
            out_root / "L3_bgp_flap" / f"iter_{idx:02d}",
            root=3,
            name="bgp_flap",
            series=s,
            recipe={"kind": "L3", "mild": False, "period_sec": per, "seed": seed + 200 + i},
        )
    meta["counts"]["L3_mild"] = n_l3_mild
    meta["counts"]["L3_severe"] = n_l3_severe

    # L5 grid (chaos uses 24; densify uses 12…34)
    ends = [12, 16, 20, 24, 28, 30, 32, 34]
    for i in range(n_l5):
        end = float(ends[i % len(ends)])
        s, sch = synthesize_l5(
            ramp_sec=160 + 15 * (i % 3),
            plateau_sec=60 + 10 * (i % 4),
            end_mbit=end,
            seed=seed + 300 + i,
        )
        _write_iter(
            out_root / "L5_util_congestion" / f"iter_{i+1:02d}",
            root=5,
            name="util_congestion",
            series=s,
            recipe={"kind": "L5", "end_mbit": end, "seed": seed + 300 + i},
            schedule=sch,
        )
    meta["counts"]["L5"] = n_l5
    (out_root / "SYNTH_META.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out_root / "ACTIVE_DONE").write_text(
        json.dumps({"status": "SYNTH_DONE", "meta": meta}, indent=2) + "\n"
    )
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        default="",
        help="output stamp dir (default: data/deca/predictive/protocol/synth_gap_<utc>)",
    )
    ap.add_argument("--n-l3-mild", type=int, default=24)
    ap.add_argument("--n-l3-severe", type=int, default=12)
    ap.add_argument("--n-l5", type=int, default=24)
    ap.add_argument("--n-l0", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.out:
        out = Path(args.out)
    else:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("synth_gap_%Y%m%dT%H%M%SZ")
        out = Path("data/deca/predictive/protocol") / stamp
    meta = generate_gap_stamp(
        out,
        n_l3_mild=args.n_l3_mild,
        n_l3_severe=args.n_l3_severe,
        n_l5=args.n_l5,
        n_l0=args.n_l0,
        seed=args.seed,
    )
    print(json.dumps({"out": str(out), **meta}, indent=2))


if __name__ == "__main__":
    main()
