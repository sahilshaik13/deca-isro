"""RIPE Atlas latency / loss — memory-safe full historical or latest snapshot."""

import argparse
import csv
import gc
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

from _paths import PUBLIC_DIR

CHECKPOINT = PUBLIC_DIR / "ripe_atlas_full_checkpoint.json"
ATLAS_API = "https://atlas.ripe.net/api/v2"
DEFAULT_MSM_ID = 1001
DEFAULT_START = datetime(2026, 7, 8, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_END = datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc)
MIN_CHUNK_MINUTES = 5
MAX_RETRIES = 5

CSV_FIELDS = [
    "timestamp",
    "probe_id",
    "rtt_ms",
    "rtt_min_ms",
    "rtt_max_ms",
    "packet_loss_pct",
    "dst_addr",
    "metric",
    "source",
]


def _row_from_result(result: dict) -> dict | None:
    probe_id = result.get("prb_id")
    ts = result.get("timestamp")
    if probe_id is None or ts is None:
        return None
    loss = None
    if result.get("sent"):
        loss = (1 - result.get("rcvd", 0) / result["sent"]) * 100
    return {
        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        "probe_id": probe_id,
        "rtt_ms": result.get("avg"),
        "rtt_min_ms": result.get("min"),
        "rtt_max_ms": result.get("max"),
        "packet_loss_pct": loss,
        "dst_addr": result.get("dst_addr"),
        "metric": "ping",
        "source": "ripe_atlas",
    }


def _append_payload_csv(payload: list, writer: csv.DictWriter) -> int:
    n = 0
    for result in payload:
        row = _row_from_result(result)
        if row:
            writer.writerow(row)
            n += 1
    return n


def fetch_latest_ping(msm_id: int) -> pd.DataFrame:
    url = f"{ATLAS_API}/measurements/{msm_id}/latest/"
    print(f"⏳ RIPE Atlas latest msm_id={msm_id}")
    resp = requests.get(url, params={"format": "json"}, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return pd.DataFrame()
    rows = [_row_from_result(r) for r in payload]
    rows = [r for r in rows if r]
    df = pd.DataFrame(rows)
    print(f"  ✅ {len(df)} probe snapshots (latest only)")
    return df


def _load_checkpoint() -> set[str]:
    if not CHECKPOINT.exists():
        return set()
    return set(json.loads(CHECKPOINT.read_text()).get("done_chunks", []))


def _save_checkpoint(done: set[str]) -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps({"done_chunks": sorted(done)}))


def _chunk_key(start: datetime, end: datetime) -> str:
    return f"{int(start.timestamp())}-{int(end.timestamp())}"


def _parse_key(key: str) -> tuple[int, int]:
    a, b = key.split("-")
    return int(a), int(b)


def _is_covered(start: datetime, end: datetime, done_chunks: set[str]) -> bool:
    """True if [start, end) is fully inside any already-done chunk (any size)."""
    a, b = int(start.timestamp()), int(end.timestamp())
    for key in done_chunks:
        x, y = _parse_key(key)
        if x <= a and b <= y:
            return True
    return False


def _download_chunk(
    url: str,
    start: datetime,
    end: datetime,
    headers: dict,
) -> list:
    """Download one time window; retries on truncated JSON / network errors."""
    params = {
        "start": int(start.timestamp()),
        "stop": int(end.timestamp()),
        "format": "json",
    }
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=600)
            resp.raise_for_status()
            expected = resp.headers.get("Content-Length")
            content = resp.content
            if expected and len(content) < int(expected):
                raise ValueError(
                    f"truncated response ({len(content)} / {expected} bytes)"
                )
            payload = json.loads(content)
            if not isinstance(payload, list):
                raise ValueError(f"unexpected payload type: {type(payload)}")
            return payload
        except (json.JSONDecodeError, ValueError, requests.RequestException) as exc:
            last_exc = exc
            wait = min(60, 2 ** attempt)
            print(
                f"    retry {attempt + 1}/{MAX_RETRIES} "
                f"{start.strftime('%H:%M')}→{end.strftime('%H:%M')}: {exc} — wait {wait}s",
                flush=True,
            )
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _fetch_range(
    msm_id: int,
    start: datetime,
    end: datetime,
    *,
    writer: csv.DictWriter,
    fh,
    done_chunks: set[str],
    headers: dict,
    session_total: list[int],
    chunk_minutes: int,
) -> None:
    """Fetch a time range; bisect on failure if window > MIN_CHUNK_MINUTES."""
    key = _chunk_key(start, end)
    if key in done_chunks or _is_covered(start, end, done_chunks):
        return

    window_min = (end - start).total_seconds() / 60
    url = f"{ATLAS_API}/measurements/{msm_id}/results/"

    try:
        payload = _download_chunk(url, start, end, headers)
        n = _append_payload_csv(payload, writer)
        fh.flush()
        done_chunks.add(key)
        # Also mark exact parental hour if this finishes a known gap fragment
        _save_checkpoint(done_chunks)
        session_total[0] += n
        print(
            f"  ✓ {start.isoformat()} → {end.isoformat()}: +{n:,} rows "
            f"(session {session_total[0]:,})",
            flush=True,
        )
        del payload
        gc.collect()
    except Exception as exc:
        if window_min <= MIN_CHUNK_MINUTES:
            print(
                f"  ✗ {start.isoformat()} → {end.isoformat()} failed after retries: {exc}",
                flush=True,
            )
            return
        mid = start + (end - start) / 2
        print(
            f"  ↯ splitting {start.strftime('%H:%M')}→{end.strftime('%H:%M')} "
            f"after error: {exc}",
            flush=True,
        )
        _fetch_range(
            msm_id, start, mid,
            writer=writer, fh=fh, done_chunks=done_chunks, headers=headers,
            session_total=session_total, chunk_minutes=chunk_minutes,
        )
        _fetch_range(
            msm_id, mid, end,
            writer=writer, fh=fh, done_chunks=done_chunks, headers=headers,
            session_total=session_total, chunk_minutes=chunk_minutes,
        )


def fetch_historical_ping(
    msm_id: int,
    start: datetime,
    end: datetime,
    *,
    chunk_minutes: int = 15,
    api_key: str | None = None,
    out_path: Path | None = None,
    resume: bool = False,
) -> int:
    """Stream historical results to CSV in small time chunks (low RAM)."""
    headers = {"Authorization": f"Key {api_key}"} if api_key else {}
    done_chunks = _load_checkpoint() if resume else set()
    session_total = [0]
    step = timedelta(minutes=chunk_minutes)

    out_path = out_path or PUBLIC_DIR / "ripe_atlas_ping_full.csv"
    write_header = not (out_path.exists() and out_path.stat().st_size > 0)

    print(
        f"⏳ RIPE Atlas historical msm_id={msm_id} "
        f"{start.date()} → {end.date()} ({chunk_minutes}min chunks, retry+bisect)",
        flush=True,
    )
    if resume and done_chunks:
        # Count how many top-level steps are already covered (skip without network)
        covered = 0
        cursor0 = start
        while cursor0 < end:
            ce = min(cursor0 + step, end)
            if _is_covered(cursor0, ce, done_chunks):
                covered += 1
            cursor0 = ce
        print(f"  resume: {covered} already-covered {chunk_minutes}min windows will be skipped", flush=True)

    with out_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()

        cursor = start
        while cursor < end:
            chunk_end = min(cursor + step, end)
            _fetch_range(
                msm_id, cursor, chunk_end,
                writer=writer, fh=fh, done_chunks=done_chunks, headers=headers,
                session_total=session_total, chunk_minutes=chunk_minutes,
            )
            cursor = chunk_end

    print(f"  ✅ {session_total[0]:,} rows written this run → {out_path}")
    return session_total[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="RIPE Atlas ping downloader (low memory)")
    parser.add_argument("--msm-id", type=int, default=DEFAULT_MSM_ID)
    parser.add_argument("--full", action="store_true", help="Full historical window")
    parser.add_argument("--start", default="2026-07-08")
    parser.add_argument("--end", default="2026-07-13")
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=15,
        help="Time window per request (default 15; splits smaller on failure)",
    )
    parser.add_argument("--chunk-hours", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--resume", action="store_true", help="Skip completed time chunks")
    parser.add_argument("--reset", action="store_true", help="Clear checkpoint and output")
    args = parser.parse_args()

    chunk_minutes = args.chunk_minutes
    if args.chunk_hours:
        chunk_minutes = args.chunk_hours * 60

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("RIPE_ATLAS_API_KEY")

    if args.full:
        if args.reset:
            CHECKPOINT.unlink(missing_ok=True)
            out = PUBLIC_DIR / "ripe_atlas_ping_full.csv"
            if out.exists():
                out.unlink()
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        out = PUBLIC_DIR / "ripe_atlas_ping_full.csv"
        fetch_historical_ping(
            args.msm_id,
            start,
            end,
            chunk_minutes=chunk_minutes,
            api_key=api_key,
            out_path=out,
            resume=args.resume or not args.reset,
        )
        row_count = sum(1 for _ in open(out, encoding="utf-8")) - 1 if out.exists() else 0
        print(f"✨ Saved {out} ({row_count:,} rows total)")
        return

    df = fetch_latest_ping(args.msm_id)
    out = PUBLIC_DIR / "ripe_atlas_ping_baseline.csv"
    df.to_csv(out, index=False)
    print(f"✨ Saved {out} ({len(df)} rows)")


if __name__ == "__main__":
    main()
