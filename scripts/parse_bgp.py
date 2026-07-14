"""Parse BGP MRT archives into minute-level rates — memory-safe (no full timestamp lists)."""

import argparse
import bz2
import gc
import gzip
import json
from collections import Counter
from pathlib import Path

import pandas as pd
from mrtparse import Reader

from _paths import PROCESSED_DIR, PUBLIC_DIR

CHECKPOINT = PROCESSED_DIR / "bgp_parse_checkpoint.json"


def _entry_timestamp(entry) -> int | None:
    if getattr(entry, "err", None):
        return None
    ts_map = getattr(entry, "data", {}).get("timestamp")
    if not ts_map:
        return None
    return next(iter(ts_map))


def _is_bgp_update(entry) -> bool:
    if getattr(entry, "err", None):
        return False
    bgp_msg = getattr(entry, "data", {}).get("bgp_message") or {}
    msg_type = bgp_msg.get("type") or {}
    return "UPDATE" in msg_type.values()


def _open_mrt(path: Path):
    name = path.name.lower()
    if name.endswith(".gz"):
        return gzip.open(path, "rb")
    if name.endswith(".bz2"):
        return bz2.open(path, "rb")
    return open(path, "rb")


def parse_mrt_buckets(file_path: Path) -> Counter | None:
    """Return per-minute update counts; O(minutes) memory, not O(updates)."""
    print(f"  parsing {file_path.name}...", flush=True)
    buckets: Counter = Counter()
    updates = 0
    try:
        with _open_mrt(file_path) as handle:
            reader = Reader(handle)
            for entry in reader:
                if not _is_bgp_update(entry):
                    continue
                ts = _entry_timestamp(entry)
                if ts is not None:
                    buckets[ts // 60] += 1
                    updates += 1
    except (EOFError, OSError) as exc:
        print(f"    ⚠️ skipped corrupt archive: {exc}")
        return None

    print(f"    {updates:,} updates → {len(buckets)} minute buckets", flush=True)
    return buckets


def find_mrt_files(public_dir: Path) -> list[Path]:
    files: list[Path] = []
    for pat in ("*updates*.gz", "*updates*.bz2"):
        files.extend(public_dir.glob(pat))
    return sorted(set(files))


def load_checkpoint() -> tuple[set[str], Counter]:
    if not CHECKPOINT.exists():
        return set(), Counter()
    payload = json.loads(CHECKPOINT.read_text())
    done = set(payload.get("done", []))
    counts = Counter({int(k): int(v) for k, v in payload.get("minute_counts", {}).items()})
    return done, counts


def save_checkpoint(done: set[str], counts: Counter) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(
        json.dumps(
            {
                "done": sorted(done),
                "minute_counts": {str(k): v for k, v in sorted(counts.items())},
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse BGP MRT files (low memory)")
    parser.add_argument("--limit", type=int, default=0, help="Max files (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip files in checkpoint")
    parser.add_argument("--reset", action="store_true", help="Clear checkpoint and re-parse")
    args = parser.parse_args()

    files = find_mrt_files(PUBLIC_DIR)
    if args.limit:
        files = files[: args.limit]
    if not files:
        print("❌ No MRT files — run routeviews.py and riperis.py")
        return

    if args.reset and CHECKPOINT.exists():
        CHECKPOINT.unlink()

    done, global_counter = load_checkpoint() if args.resume else (set(), Counter())
    todo = [f for f in files if f.name not in done]

    print(f"⏳ Parsing {len(todo)} BGP MRT archives ({len(done)} cached)...", flush=True)

    skipped = 0
    for f in todo:
        buckets = parse_mrt_buckets(f)
        if buckets is None:
            skipped += 1
            continue
        global_counter.update(buckets)
        done.add(f.name)
        save_checkpoint(done, global_counter)
        del buckets
        gc.collect()

    if skipped:
        print(f"  ⚠️ skipped {skipped} corrupt file(s) — re-fetch with routeviews.py / riperis.py")

    if not global_counter:
        print("❌ No parseable data")
        return

    minutes = sorted(global_counter)
    global_rate = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(minutes, unit="m", utc=True),
            "bgp_update_rate": [global_counter[m] for m in minutes],
        }
    )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    global_out = PROCESSED_DIR / "bgp_update_rates_full.parquet"
    csv_out = PUBLIC_DIR / "bgp_update_rates_full.csv"
    global_rate.to_parquet(global_out, index=False)
    global_rate.to_csv(csv_out, index=False)

    print(f"✨ Saved {global_out} ({len(global_rate)} minute buckets)")
    print(f"✨ Saved {csv_out}")


if __name__ == "__main__":
    main()
