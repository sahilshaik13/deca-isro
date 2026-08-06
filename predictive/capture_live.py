#!/usr/bin/env python3
"""Poll Prometheus during a capture window and write series.csv (1 Hz).

If Prom/lab feed is empty (typical when Pis lose power), waits without writing
blank rows and without consuming the sample budget — so protocol wall-clock
pauses until telemetry is healthy again.

Fabric:
  --fabric pi|gns3 (or DECA_FABRIC). GNS3 retargets PromQL via with_fabric_label
  and defaults Prom to :9091.

CAPTURE_CONTRACT (docs/CAPTURE_CONTRACT.md):
  - Always derive path_asymmetry from gre/eth0 latency (never controller 5s hold).
  - Log / optionally fill timestamp gaps; one Prom retry when ts would skip.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

from .prom_export import (
    Q1_QUERIES,
    Q2_QUERIES,
    prom_url_for_fabric,
    sample_bundle,
    with_fabric_label,
)

# Optional external pause latch written by watch_protocol_capture.sh
PAUSE_ENV = "DECA_CAPTURE_PAUSE_FILE"


def _pause_file_active(path: str) -> bool:
    if not path:
        return False
    p = Path(path)
    return p.is_file()


def _row_healthy(row: dict, require_key: str = "latency_gre_ms") -> bool:
    v = row.get(require_key)
    if v is None:
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _resolve_fabric(raw: str | None) -> str:
    fab = (raw or os.environ.get("DECA_FABRIC", "pi") or "pi").strip().lower()
    return fab if fab in ("pi", "gns3") else "pi"


def _derive_asymmetry(row: dict) -> None:
    """CAPTURE_CONTRACT: overwrite path_asymmetry from same-sample gre/eth0."""
    g, e = row.get("latency_gre_ms"), row.get("latency_eth0_ms")
    if g is None or e is None:
        return
    try:
        row["path_asymmetry"] = abs(float(g) - float(e))
    except (TypeError, ValueError):
        return


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fabric",
        default=None,
        choices=("pi", "gns3"),
        help="pi (default) or gns3 — selects PromQL labels + default Prom URL",
    )
    ap.add_argument(
        "--prom",
        default=None,
        help="Prometheus base URL (default: fabric-specific :9090 / :9091)",
    )
    ap.add_argument("--out", required=True, help="output series.csv")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--q1-only", action="store_true")
    ap.add_argument(
        "--pause-on-empty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="wait (do not write / burn samples) when Prom Q1 empty (default: on)",
    )
    ap.add_argument(
        "--health-key",
        default="latency_gre_ms",
        help="series key that must be present for a sample to count",
    )
    ap.add_argument(
        "--max-pause-seconds",
        type=int,
        default=int(os.environ.get("DECA_CAPTURE_MAX_PAUSE_S", "180")),
        help="abort if Prom health key stays empty this long (default 180; "
        "0=wait forever). Prevents fabric-label / Prom outages from burning wall clock.",
    )
    ap.add_argument(
        "--gap-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="one extra Prom sample if ts_unix would skip a second (CAPTURE_CONTRACT C)",
    )
    args = ap.parse_args()

    fabric = _resolve_fabric(args.fabric)
    # CLI --fabric always wins over ambient NOC / sibling-pack env.
    os.environ["DECA_FABRIC"] = fabric
    prom = (args.prom or prom_url_for_fabric(fabric)).rstrip("/")

    base = dict(Q1_QUERIES) if args.q1_only else {**Q1_QUERIES, **Q2_QUERIES}
    queries = {name: with_fabric_label(q, fabric) for name, q in base.items()}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pause_file = os.environ.get(PAUSE_ENV, "")
    gap_log_path = out.with_suffix(".gaps.jsonl")

    fieldnames = ["ts_unix", *queries.keys()]
    n = max(1, int(args.seconds / args.interval))
    print(
        f"capturing {n} samples → {out} fabric={fabric} prom={prom} "
        f"pause_on_empty={args.pause_on_empty} max_pause_s={args.max_pause_seconds} "
        f"gap_retry={args.gap_retry}",
        flush=True,
    )

    written = 0
    paused_s = 0
    gap_events = 0
    last_ts: int | None = None
    with out.open("w", newline="") as f, gap_log_path.open("w") as gap_f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        while written < n:
            # External latch (watchdog) — freeze without writing
            while _pause_file_active(pause_file):
                if paused_s % 30 == 0:
                    print(
                        f"  paused by {pause_file} (written={written}/{n} paused_s={paused_s})",
                        flush=True,
                    )
                time.sleep(1.0)
                paused_s += 1

            row = sample_bundle(prom, queries)
            _derive_asymmetry(row)
            if args.pause_on_empty and not _row_healthy(row, args.health_key):
                if paused_s % 30 == 0:
                    print(
                        f"  waiting for Prom {args.health_key} "
                        f"(written={written}/{n} paused_s={paused_s} "
                        f"fabric={fabric} prom={prom})",
                        flush=True,
                    )
                if (
                    args.max_pause_seconds > 0
                    and written == 0
                    and paused_s >= args.max_pause_seconds
                ):
                    raise SystemExit(
                        f"capture abort: {args.health_key} empty for "
                        f"{paused_s}s on fabric={fabric} prom={prom} "
                        f"(likely DECA_FABRIC/Prom mismatch or telemetry down)"
                    )
                time.sleep(args.interval)
                paused_s += max(1, int(args.interval))
                continue

            row["ts_unix"] = int(row["ts_unix"])
            # CAPTURE_CONTRACT C: detect skipped unix seconds
            if last_ts is not None and row["ts_unix"] > last_ts + 1:
                skipped = int(row["ts_unix"] - last_ts - 1)
                gap_events += skipped
                gap_f.write(
                    json.dumps(
                        {
                            "prev_ts": last_ts,
                            "next_ts": row["ts_unix"],
                            "skipped_seconds": skipped,
                            "written": written,
                        }
                    )
                    + "\n"
                )
                gap_f.flush()
                if args.gap_retry:
                    time.sleep(0.05)
                    retry = sample_bundle(prom, queries)
                    _derive_asymmetry(retry)
                    if _row_healthy(retry, args.health_key):
                        retry["ts_unix"] = int(retry["ts_unix"])
                        # Prefer denser ts if retry landed on a missing second
                        if last_ts < retry["ts_unix"] < row["ts_unix"]:
                            row = retry

            w.writerow(row)
            f.flush()
            last_ts = int(row["ts_unix"])
            written += 1
            if written % 10 == 0:
                lat = row.get("latency_gre_ms")
                asym = row.get("path_asymmetry")
                util = row.get("util_gre_mbps")
                print(
                    f"  t+{written}s latency_gre_ms={lat} path_asymmetry={asym} "
                    f"util_gre_mbps={util}",
                    flush=True,
                )
            if written < n:
                time.sleep(args.interval)

    print(
        f"done: {out} written={written} paused_s≈{paused_s} gap_seconds≈{gap_events} "
        f"gaps_log={gap_log_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
