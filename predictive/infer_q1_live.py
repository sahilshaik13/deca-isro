"""Live Q1 TTI inference + Critical Prediction Alert gate.

Polls Prometheus :9090 at 1 Hz, maintains a 30-sample window, predicts
eta_seconds with a trained LSTM, and posts Decide-rail preemption via
POST /api/v1/simulation/seed-preemption when ETA ≤ --red-sec (default 120).

States (plan §3):
  healthy — ETA unknown or ≫ yellow
  yellow  — drift / ETA > red (advisory log only)
  red     — ETA ≤ red window → seed HITL alert (cooldown)

Usage:
  .venv-predictive/bin/python -m predictive.infer_q1_live \\
    --model data/deca/predictive/pooled/lstm_q1/q1_tti_lstm.keras \\
    --scaler data/deca/predictive/pooled/lstm_q1/q1_scaler.npz \\
    --seconds 180 --dry-run
"""
from __future__ import annotations

import argparse
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

from .prom_export import Q1_QUERIES, DEFAULT_PROM, prom_url_for_fabric, sample_bundle

FEATURE_ORDER_DEFAULT = [
    "latency_gre_ms",
    "latency_eth0_ms",
    "jitter_gre_ms",
    "loss_gre_pct",
    "net_bytes_recv_eth0",
    "net_bytes_sent_eth0",
]


def load_scaler(path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    data = np.load(path, allow_pickle=True)
    mean = data["mean"].astype(np.float32)
    std = data["std"].astype(np.float32)
    cols = [str(c) for c in data["feature_cols"].tolist()]
    return mean, std, cols


def seed_preemption(
    orch: str,
    *,
    eta_seconds: float,
    confidence: float,
    host: str,
    path: str,
    title: str,
    dry_run: bool,
) -> dict[str, Any]:
    body = {
        "title": title,
        "host": host,
        "path": path,
        "confidence": confidence,
        "eta_minutes": max(0.1, eta_seconds / 60.0),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "body": body}
    url = f"{orch.rstrip('/')}/api/v1/simulation/seed-preemption"
    resp = requests.post(url, json=body, timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def classify(
    eta: float | None,
    red_sec: float,
    yellow_sec: float,
    *,
    latency_ms: float | None,
    latency_floor_ms: float,
    rising: bool,
) -> str:
    """Gate ETA with a latency precursor so a low-biased model cannot spam red."""
    if eta is None:
        return "warmup"
    hot = latency_ms is not None and (
        latency_ms >= latency_floor_ms or rising
    )
    if eta <= red_sec and hot:
        return "red"
    if eta <= yellow_sec and hot:
        return "yellow"
    if eta <= red_sec and not hot:
        # Model says imminent but path still healthy — treat as yellow advisory
        return "yellow"
    return "healthy"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--scaler", required=True)
    ap.add_argument("--prom", default=None, help="Prometheus base URL (default: fabric Prom)")
    ap.add_argument("--orch", default="http://127.0.0.1:8000")
    ap.add_argument("--seconds", type=int, default=0, help="0 = run forever")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--win", type=int, default=30)
    ap.add_argument("--red-sec", type=float, default=120.0)
    ap.add_argument("--yellow-sec", type=float, default=300.0)
    ap.add_argument("--cooldown-sec", type=float, default=60.0)
    ap.add_argument(
        "--latency-floor-ms",
        type=float,
        default=8.0,
        help="require GRE latency ≥ this (or rising slope) before red",
    )
    ap.add_argument("--host", default="station1")
    ap.add_argument("--steer-path", default="eth0", choices=("gre", "eth0"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default="", help="optional JSONL event log")
    args = ap.parse_args()
    if not args.prom:
        args.prom = prom_url_for_fabric()

    try:
        from tensorflow import keras
    except ImportError as exc:
        raise SystemExit("TensorFlow required in .venv-predictive") from exc

    model = keras.models.load_model(args.model)
    mean, std, feat_cols = load_scaler(Path(args.scaler))
    if not feat_cols:
        feat_cols = FEATURE_ORDER_DEFAULT

    buf: deque[list[float]] = deque(maxlen=args.win)
    lat_hist: deque[float] = deque(maxlen=args.win)
    last_alert_ts = 0.0
    state = "warmup"
    log_path = Path(args.log) if args.log else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"Q1 live infer: win={args.win} red≤{args.red_sec}s yellow≤{args.yellow_sec}s "
        f"lat_floor≥{args.latency_floor_ms}ms dry_run={args.dry_run}",
        flush=True,
    )

    t0 = time.time()
    n = 0
    while True:
        if args.seconds > 0 and (time.time() - t0) >= args.seconds:
            break
        sample = sample_bundle(args.prom, Q1_QUERIES)
        row = [float(sample.get(c) or 0.0) for c in feat_cols]
        buf.append(row)
        lat = sample.get("latency_gre_ms")
        if lat is not None:
            lat_hist.append(float(lat))
        n += 1

        eta: float | None = None
        if len(buf) >= args.win:
            X = np.asarray([list(buf)], dtype=np.float32)
            X = (X - mean) / std
            eta = float(model.predict(X, verbose=0)[0][0])
            eta = max(0.0, eta)

        rising = False
        if len(lat_hist) >= 10:
            ys = np.asarray(lat_hist, dtype=float)
            t = np.arange(len(ys), dtype=float)
            rising = float(np.polyfit(t, ys, 1)[0]) > 0.05  # ms/sample

        prev = state
        state = classify(
            eta,
            args.red_sec,
            args.yellow_sec,
            latency_ms=float(lat) if lat is not None else None,
            latency_floor_ms=args.latency_floor_ms,
            rising=rising,
        )
        ts = datetime.now(timezone.utc).isoformat()
        event: dict[str, Any] = {
            "ts": ts,
            "n": n,
            "state": state,
            "prev_state": prev,
            "eta_seconds": eta,
            "latency_gre_ms": lat,
            "rising": rising,
        }

        if state == "red":
            now = time.time()
            if now - last_alert_ts >= args.cooldown_sec:
                title = (
                    f"Q1 TTI preemption: GRE SLA in ~{int(eta or 0)}s"
                    if eta is not None
                    else "Q1 TTI preemption"
                )
                # Confidence heuristic: closer ETA + higher latency → higher conf
                conf = 0.75
                if eta is not None:
                    conf = float(np.clip(0.55 + (args.red_sec - eta) / args.red_sec * 0.35, 0.55, 0.95))
                try:
                    resp = seed_preemption(
                        args.orch,
                        eta_seconds=eta or args.red_sec,
                        confidence=conf,
                        host=args.host,
                        path=args.steer_path,
                        title=title,
                        dry_run=args.dry_run,
                    )
                    event["alert"] = resp
                    last_alert_ts = now
                    print(f"[{state}] eta={eta:.1f}s lat={lat} ALERT {resp}", flush=True)
                except requests.RequestException as exc:
                    event["alert_error"] = str(exc)
                    print(f"[{state}] eta={eta} alert failed: {exc}", flush=True)
            else:
                rem = int(args.cooldown_sec - (now - last_alert_ts))
                print(f"[{state}] eta={eta:.1f}s lat={lat} cooldown {rem}s", flush=True)
        elif state == "yellow":
            print(f"[{state}] eta={eta:.1f}s lat={lat} (advisory)", flush=True)
        elif n % 10 == 0 or state != prev:
            eta_s = f"{eta:.1f}" if eta is not None else "—"
            print(f"[{state}] eta={eta_s}s lat={lat}", flush=True)

        if log_path:
            with log_path.open("a") as f:
                f.write(json.dumps(event) + "\n")

        time.sleep(args.interval)

    print(f"done after {n} samples", flush=True)


if __name__ == "__main__":
    main()
