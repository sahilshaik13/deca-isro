#!/usr/bin/env python3
"""Poll Prometheus during a capture window and write series.csv (1 Hz).

If Prom/lab feed is empty (typical when Pis lose power), waits without writing
blank rows and without consuming the sample budget — so protocol wall-clock
pauses until telemetry is healthy again.

Fabric:
  --fabric pi|gns3 (or DECA_FABRIC). GNS3 retargets PromQL via with_fabric_label
  and defaults Prom to :9091.
"""
from __future__ import annotations

import argparse
import csv
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
    args = ap.parse_args()

    fabric = _resolve_fabric(args.fabric)
    os.environ["DECA_FABRIC"] = fabric
    prom = (args.prom or prom_url_for_fabric(fabric)).rstrip("/")

    base = dict(Q1_QUERIES) if args.q1_only else {**Q1_QUERIES, **Q2_QUERIES}
    queries = {name: with_fabric_label(q, fabric) for name, q in base.items()}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pause_file = os.environ.get(PAUSE_ENV, "")

    fieldnames = ["ts_unix", *queries.keys()]
    n = max(1, int(args.seconds / args.interval))
    print(
        f"capturing {n} samples → {out} fabric={fabric} prom={prom} "
        f"pause_on_empty={args.pause_on_empty}",
        flush=True,
    )

    written = 0
    paused_s = 0
    with out.open("w", newline="") as f:
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
            # Derive path asymmetry when gauge missing (common on GNS3 twin exporter).
            if row.get("path_asymmetry") is None:
                g, e = row.get("latency_gre_ms"), row.get("latency_eth0_ms")
                if g is not None and e is not None:
                    row["path_asymmetry"] = abs(float(g) - float(e))
            if args.pause_on_empty and not _row_healthy(row, args.health_key):
                if paused_s % 30 == 0:
                    print(
                        f"  waiting for Prom {args.health_key} "
                        f"(written={written}/{n} paused_s={paused_s})",
                        flush=True,
                    )
                time.sleep(args.interval)
                paused_s += max(1, int(args.interval))
                continue

            row["ts_unix"] = int(row["ts_unix"])
            w.writerow(row)
            f.flush()
            written += 1
            if written % 10 == 0:
                lat = row.get("latency_gre_ms")
                print(f"  t+{written}s latency_gre_ms={lat}", flush=True)
            if written < n:
                time.sleep(args.interval)

    print(f"done: {out} written={written} paused_s≈{paused_s}", flush=True)


if __name__ == "__main__":
    main()
