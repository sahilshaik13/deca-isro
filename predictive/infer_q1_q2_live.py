"""Live Q1 TTI + Q2 root-cause inference → Decide-rail alert gate.

Combines LSTM ETA with XGBoost/RF fault class. On red (ETA ≤ 120 s and
latency hot), seeds HITL with both time-to-impact and root-cause label.

Usage:
  .venv-predictive/bin/python -m predictive.infer_q1_q2_live \\
    --q1-model data/deca/predictive/pooled/lstm_q1/q1_tti_lstm.keras \\
    --q1-scaler data/deca/predictive/pooled/lstm_q1/q1_scaler.npz \\
    --q2-model data/deca/predictive/q2_pooled/xgb_q2/q2_root_cause.joblib \\
    --seconds 120
"""
from __future__ import annotations

import argparse
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import requests

from .prom_export import (
    Q1_QUERIES,
    Q2_QUERIES,
    DEFAULT_PROM,
    active_queries,
    prom_url_for_fabric,
    sample_bundle,
)
from .q2_windows import FEATURE_COLS, CUMULATIVE_COLS, slope
from .alert_fusion import fuse_alert_fields
from .severity_label import (
    ID_TO_SEVERITY,
    RED_SEVERITIES,
    SEVERITY_NAMES,
    SEVERITY_TO_ROOT,
)

Q1_FEATURE_DEFAULT = [
    "latency_gre_ms",
    "latency_eth0_ms",
    "jitter_gre_ms",
    "loss_gre_pct",
    "net_bytes_recv_eth0",
    "net_bytes_sent_eth0",
]

Q2_TO_ALERT_CLASS = {
    0: "congestion_breach",
    1: "tunnel_degradation",
    2: "congestion_breach",
    3: "bgp_route_flap",
    4: "tunnel_degradation",
    5: "congestion_breach",
}

Q2_LABEL_NAMES = {
    0: "normal",
    1: "physical_degradation",
    2: "crypto_cpu_exhaustion",
    3: "route_flap",
    4: "loss_progression",
    5: "util_congestion",
}


def load_q1_scaler(path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    data = np.load(path, allow_pickle=True)
    return (
        data["mean"].astype(np.float32),
        data["std"].astype(np.float32),
        [str(c) for c in data["feature_cols"].tolist()],
    )


def window_features(buf: list[dict[str, float]], feat_cols: list[str]) -> dict[str, float]:
    """Match predictive.q2_windows aggregation for one live window."""
    out: dict[str, float] = {}
    bases: set[str] = set()
    for c in feat_cols:
        for agg in (
            "_mean",
            "_max",
            "_std",
            "_last",
            "_slope",
            "_delta",
            "_rate_mean",
            "_rate_std",
            "_rate_max",
        ):
            if c.endswith(agg):
                bases.add(c[: -len(agg)])
                break
    if not bases:
        bases = set(FEATURE_COLS)

    for base in sorted(bases):
        vals = np.asarray([float(r.get(base) or 0.0) for r in buf], dtype=float)
        if base in CUMULATIVE_COLS:
            d = np.diff(vals, prepend=vals[0])
            out[f"{base}_delta"] = float(vals[-1] - vals[0])
            out[f"{base}_slope"] = slope(vals)
            out[f"{base}_rate_mean"] = float(np.mean(d))
            out[f"{base}_rate_std"] = float(np.std(d))
            out[f"{base}_rate_max"] = float(np.max(d))
        else:
            out[f"{base}_mean"] = float(np.mean(vals))
            out[f"{base}_max"] = float(np.max(vals))
            out[f"{base}_std"] = float(np.std(vals))
            out[f"{base}_last"] = float(vals[-1])
            out[f"{base}_slope"] = slope(vals)
            out[f"{base}_delta"] = float(vals[-1] - vals[0])
    return out


def classify_gate(
    eta: float | None,
    red_sec: float,
    yellow_sec: float,
    *,
    latency_ms: float | None,
    latency_floor_ms: float,
    rising: bool,
    severity: str | None = None,
    require_red_severity: bool = True,
) -> str:
    if eta is None:
        return "warmup"
    hot = latency_ms is not None and (latency_ms >= latency_floor_ms or rising)
    sev_ok = (severity in RED_SEVERITIES) if (require_red_severity and severity) else True
    if eta <= red_sec and hot and sev_ok:
        return "red"
    if eta <= red_sec and hot and not sev_ok:
        return "yellow"  # early severity — advisory only
    if eta <= yellow_sec and hot:
        return "yellow"
    if eta <= red_sec and not hot:
        return "yellow"
    return "healthy"


def seed_preemption(orch: str, body: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "body": body}
    url = f"{orch.rstrip('/')}/api/v1/simulation/seed-preemption"
    resp = requests.post(url, json=body, timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--q1-model", required=True)
    ap.add_argument("--q1-scaler", required=True)
    ap.add_argument("--q2-model", required=True)
    ap.add_argument("--q1-loss-model", default="", help="optional loss-TTI LSTM")
    ap.add_argument("--q1-loss-scaler", default="")
    ap.add_argument("--q1-jitter-model", default="", help="optional jitter-TTI LSTM")
    ap.add_argument("--q1-jitter-scaler", default="")
    ap.add_argument("--q1-util-model", default="", help="optional util/congestion-TTI LSTM")
    ap.add_argument("--q1-util-scaler", default="")
    ap.add_argument("--loss-sla-pct", type=float, default=2.0)
    ap.add_argument("--loss-floor-pct", type=float, default=0.05)
    ap.add_argument("--jitter-floor-ms", type=float, default=2.0)
    ap.add_argument("--util-floor-mbps", type=float, default=20.0)
    ap.add_argument("--prom", default=None, help="Prometheus base URL (default: fabric Prom)")
    ap.add_argument(
        "--fabric",
        default="",
        choices=("", "pi", "gns3"),
        help="retarget PromQL (sets DECA_FABRIC); required for GNS3 twin live infer",
    )
    ap.add_argument("--orch", default="http://127.0.0.1:8000")
    ap.add_argument("--seconds", type=int, default=0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--win", type=int, default=30)
    ap.add_argument("--red-sec", type=float, default=120.0)
    ap.add_argument("--yellow-sec", type=float, default=300.0)
    ap.add_argument("--cooldown-sec", type=float, default=60.0)
    ap.add_argument("--latency-floor-ms", type=float, default=8.0)
    ap.add_argument(
        "--allow-early-red",
        action="store_true",
        help="allow red without worst-case severity (1B/1C/2B/3B)",
    )
    ap.add_argument("--host", default="station1")
    ap.add_argument("--steer-path", default="eth0", choices=("gre", "eth0"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default="")
    args = ap.parse_args()
    if args.fabric:
        import os

        os.environ["DECA_FABRIC"] = args.fabric
    if not args.prom:
        args.prom = prom_url_for_fabric()

    try:
        from tensorflow import keras
    except ImportError as exc:
        raise SystemExit("TensorFlow required in .venv-predictive") from exc

    q1 = keras.models.load_model(args.q1_model)
    mean, std, q1_cols = load_q1_scaler(Path(args.q1_scaler))
    if not q1_cols:
        q1_cols = Q1_FEATURE_DEFAULT

    q1_loss = None
    loss_mean = loss_std = None
    q1_loss_cols: list[str] = []
    if args.q1_loss_model and args.q1_loss_scaler:
        q1_loss = keras.models.load_model(args.q1_loss_model)
        loss_mean, loss_std, q1_loss_cols = load_q1_scaler(Path(args.q1_loss_scaler))
        if not q1_loss_cols:
            q1_loss_cols = q1_cols

    q1_jitter = None
    jit_mean = jit_std = None
    q1_jitter_cols: list[str] = []
    if args.q1_jitter_model and args.q1_jitter_scaler:
        q1_jitter = keras.models.load_model(args.q1_jitter_model)
        jit_mean, jit_std, q1_jitter_cols = load_q1_scaler(Path(args.q1_jitter_scaler))
        if not q1_jitter_cols:
            q1_jitter_cols = q1_cols

    q1_util = None
    util_mean = util_std = None
    q1_util_cols: list[str] = []
    if args.q1_util_model and args.q1_util_scaler:
        q1_util = keras.models.load_model(args.q1_util_model)
        util_mean, util_std, q1_util_cols = load_q1_scaler(Path(args.q1_util_scaler))
        if not q1_util_cols:
            q1_util_cols = q1_cols

    bundle = joblib.load(args.q2_model)
    q2 = bundle["model"]
    q2_feat_cols: list[str] = list(bundle["feature_cols"])
    label_names = bundle.get("label_names") or Q2_LABEL_NAMES
    q2_mode = bundle.get("mode", "root")
    id_to_sev = bundle.get("id_to_severity") or ID_TO_SEVERITY
    sev_to_root = bundle.get("severity_to_root") or SEVERITY_TO_ROOT

    # Always fabric-retarget (GNS3: job/host rewrite). Raw Q1_QUERIES miss twin → lat=None forever.
    queries = active_queries()
    buf: deque[dict[str, float]] = deque(maxlen=args.win)
    lat_hist: deque[float] = deque(maxlen=args.win)
    last_alert_ts = 0.0
    state = "warmup"
    log_path = Path(args.log) if args.log else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"Q1+Q2 live: mode={q2_mode} win={args.win} red≤{args.red_sec}s "
        f"lat_floor≥{args.latency_floor_ms}ms dry_run={args.dry_run}",
        flush=True,
    )

    t0 = time.time()
    n = 0
    while True:
        if args.seconds > 0 and (time.time() - t0) >= args.seconds:
            break
        sample = sample_bundle(args.prom, queries)
        row = {c: float(sample.get(c) or 0.0) for c in set(q1_cols) | set(FEATURE_COLS)}
        buf.append(row)
        lat = sample.get("latency_gre_ms")
        lat_eth = sample.get("latency_eth0_ms")
        if lat is not None:
            lat_hist.append(float(lat))
        # PS13-O2.2: named GRE vs eth0 differential (dual 1Hz probes)
        asym_ms = None
        asym_abs = None
        asym_hit = False
        if lat is not None and lat_eth is not None:
            asym_ms = float(lat) - float(lat_eth)
            asym_abs = abs(asym_ms)
            baseline = max(min(float(lat), float(lat_eth)), 0.1)
            asym_hit = asym_abs >= 5.0 or (asym_abs / baseline) >= 0.5
        n += 1

        eta: float | None = None
        eta_loss: float | None = None
        eta_jitter: float | None = None
        eta_util: float | None = None
        q2_label: int | None = None
        q2_name: str | None = None
        q2_conf: float | None = None
        severity: str | None = None
        root_label: int | None = None

        if len(buf) >= args.win:
            X1 = np.asarray([[float(r.get(c) or 0.0) for c in q1_cols] for r in buf], dtype=np.float32)
            X1 = ((X1 - mean) / std)[None, ...]
            eta = max(0.0, float(q1.predict(X1, verbose=0)[0][0]))
            if q1_loss is not None and loss_mean is not None and loss_std is not None:
                Xl = np.asarray(
                    [[float(r.get(c) or 0.0) for c in q1_loss_cols] for r in buf],
                    dtype=np.float32,
                )
                Xl = ((Xl - loss_mean) / loss_std)[None, ...]
                eta_loss = max(0.0, float(q1_loss.predict(Xl, verbose=0)[0][0]))
            if q1_jitter is not None and jit_mean is not None and jit_std is not None:
                Xj = np.asarray(
                    [[float(r.get(c) or 0.0) for c in q1_jitter_cols] for r in buf],
                    dtype=np.float32,
                )
                Xj = ((Xj - jit_mean) / jit_std)[None, ...]
                eta_jitter = max(0.0, float(q1_jitter.predict(Xj, verbose=0)[0][0]))
            if q1_util is not None and util_mean is not None and util_std is not None:
                Xu = np.asarray(
                    [[float(r.get(c) or 0.0) for c in q1_util_cols] for r in buf],
                    dtype=np.float32,
                )
                Xu = ((Xu - util_mean) / util_std)[None, ...]
                eta_util = max(0.0, float(q1_util.predict(Xu, verbose=0)[0][0]))

            feats = window_features(list(buf), q2_feat_cols)
            X2 = np.asarray([[feats.get(c, 0.0) for c in q2_feat_cols]], dtype=np.float32)
            if hasattr(q2, "predict_proba"):
                proba = q2.predict_proba(X2)[0]
                q2_label = int(np.argmax(proba))
                q2_conf = float(proba[q2_label])
            else:
                q2_label = int(q2.predict(X2)[0])
                q2_conf = 0.8
            if q2_mode == "severity":
                severity = id_to_sev.get(q2_label, "0")
                q2_name = SEVERITY_NAMES.get(severity, label_names.get(q2_label, str(q2_label)))
                root_label = int(sev_to_root.get(severity, 0))
            else:
                root_label = q2_label
                q2_name = label_names.get(q2_label, str(q2_label))
                severity = None

        rising = False
        if len(lat_hist) >= 10:
            ys = np.asarray(lat_hist, dtype=float)
            t = np.arange(len(ys), dtype=float)
            rising = float(np.polyfit(t, ys, 1)[0]) > 0.05

        prev = state
        state = classify_gate(
            eta,
            args.red_sec,
            args.yellow_sec,
            latency_ms=float(lat) if lat is not None else None,
            latency_floor_ms=args.latency_floor_ms,
            rising=rising,
            severity=severity,
            require_red_severity=(q2_mode == "severity" and not args.allow_early_red),
        )
        # Parallel TTI reds (loss / jitter / util) — do not overwrite latency ETA
        loss_pct = sample.get("loss_gre_pct")
        loss_hot = loss_pct is not None and float(loss_pct) >= args.loss_floor_pct
        jit_ms = sample.get("jitter_gre_ms")
        jit_hot = jit_ms is not None and float(jit_ms) >= args.jitter_floor_ms
        util_mbps = sample.get("util_gre_mbps")
        util_hot = util_mbps is not None and float(util_mbps) >= args.util_floor_mbps

        def _sev_ok() -> bool:
            return (
                (severity in RED_SEVERITIES)
                if (q2_mode == "severity" and not args.allow_early_red and severity)
                else True
            )

        if state != "red" and eta_loss is not None and eta_loss <= args.red_sec and loss_hot and _sev_ok():
            state = "red"
        if state != "red" and eta_jitter is not None and eta_jitter <= args.red_sec and jit_hot and _sev_ok():
            state = "red"
        if state != "red" and eta_util is not None and eta_util <= args.red_sec and util_hot and _sev_ok():
            state = "red"

        lat_hot = lat is not None and (float(lat) >= args.latency_floor_ms or rising)
        fusion = fuse_alert_fields(
            red_sec=args.red_sec,
            eta_lat=eta,
            lat_hot=lat_hot,
            eta_loss=eta_loss,
            loss_hot=loss_hot,
            eta_jitter=eta_jitter,
            jitter_hot=jit_hot,
            eta_util=eta_util,
            util_hot=util_hot,
            q2_name=q2_name,
            severity=severity,
            q2_confidence=q2_conf,
        )
        arb = fusion["arbitration"]
        urgency_eta = arb.get("urgency_eta_seconds")

        event: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "n": n,
            "state": state,
            "prev_state": prev,
            "eta_seconds": eta,
            "urgency_eta_seconds": urgency_eta,
            "q2_label": q2_label,
            "q2_name": q2_name,
            "q2_confidence": q2_conf,
            "severity": severity,
            "root_label": root_label,
            "latency_gre_ms": lat,
            "latency_eth0_ms": lat_eth,
            "path_asymmetry_ms": asym_ms,
            "path_asymmetry_abs_ms": asym_abs,
            "path_asymmetry_detected": asym_hit,
            "eta_loss_seconds": eta_loss,
            "eta_jitter_seconds": eta_jitter,
            "eta_util_seconds": eta_util,
            "rising": rising,
            **fusion,
        }

        if state == "red":
            now = time.time()
            if now - last_alert_ts >= args.cooldown_sec:
                rc_label = root_label if root_label is not None else 1
                rc_name = q2_name or Q2_LABEL_NAMES.get(rc_label, "unknown")
                alert_class = Q2_TO_ALERT_CLASS.get(rc_label, "congestion_breach")
                conf = float(q2_conf or 0.75)
                clock_eta = urgency_eta if urgency_eta is not None else eta
                if clock_eta is not None:
                    conf = float(
                        np.clip(
                            0.5 * conf
                            + 0.5
                            * (0.55 + (args.red_sec - clock_eta) / args.red_sec * 0.35),
                            0.55,
                            0.97,
                        )
                    )
                heads = ",".join(h["head"] for h in arb.get("firing_tti_heads") or []) or "latency"
                # Display language: util-led clock = approaching ceiling; else hard SLA breach.
                clock_kind = str(arb.get("urgency_clock_kind") or "hard_sla")
                title_suf = str(arb.get("phrase_title_suffix") or "SLA breach in")
                phrase_eta = str(arb.get("phrase_eta") or "SLA breach in")
                eta_i = int(clock_eta or 0)
                title = f"Q1+Q2: {rc_name} — {title_suf} ~{eta_i}s"
                summary = (
                    f"Urgency: {phrase_eta} {eta_i}s "
                    f"(min firing TTI; heads={heads}; clock={clock_kind}); "
                    f"primary issue=Q2 {rc_name} severity={severity or 'n/a'} "
                    f"(p={q2_conf:.2f}). Approve to steer to {args.steer_path}."
                )
                if arb.get("compound_suspected"):
                    summary += (
                        " Compound: multiple TTI heads red — Q2 owns primary class; "
                        "see firing_tti_heads / chaos_compound runbook."
                    )
                if asym_hit and asym_ms is not None:
                    summary += (
                        f" Path asymmetry GRE−eth0={asym_ms:+.2f} ms "
                        f"(|Δ|={asym_abs:.2f} ms) — preferred underlay diverged."
                    )
                body = {
                    "title": title,
                    "host": args.host,
                    "path": args.steer_path,
                    "confidence": conf,
                    "eta_minutes": max(0.1, (clock_eta or args.red_sec) / 60.0),
                    "alert_class": alert_class,
                    "root_cause": rc_name,
                    "root_cause_label": rc_label,
                    "severity": severity or "",
                    "summary": summary,
                    "urgency_clock_kind": clock_kind,
                    "urgency_lead_head": arb.get("urgency_lead_head") or "latency",
                    "path_asymmetry_ms": asym_ms,
                    "path_asymmetry_abs_ms": asym_abs,
                    "path_asymmetry_detected": asym_hit,
                    "eta_loss_minutes": (
                        max(0.1, eta_loss / 60.0) if eta_loss is not None else None
                    ),
                    "eta_jitter_minutes": (
                        max(0.1, eta_jitter / 60.0) if eta_jitter is not None else None
                    ),
                    "eta_util_minutes": (
                        max(0.1, eta_util / 60.0) if eta_util is not None else None
                    ),
                    "arbitration": arb,
                    "contributing_signals": {
                        k: float(v)
                        for k, v in {
                            "latency_gre_ms": lat,
                            "latency_eth0_ms": lat_eth,
                            "path_asymmetry_ms": asym_ms,
                            "path_asymmetry_abs_ms": asym_abs,
                            "eta_seconds": eta,
                            "urgency_eta_seconds": urgency_eta,
                            "eta_loss_seconds": eta_loss,
                            "eta_jitter_seconds": eta_jitter,
                            "eta_util_seconds": eta_util,
                            "loss_gre_pct": loss_pct,
                            "jitter_gre_ms": jit_ms,
                            "util_gre_mbps": util_mbps,
                        }.items()
                        if v is not None
                    },
                }
                # drop None eta_*_minutes keys for clean JSON
                for _k in ("eta_loss_minutes", "eta_jitter_minutes", "eta_util_minutes"):
                    if body.get(_k) is None:
                        body.pop(_k, None)
                try:
                    resp = seed_preemption(args.orch, body, args.dry_run)
                    event["alert"] = resp
                    last_alert_ts = now
                    print(
                        f"[{state}] urgency={clock_eta:.1f}s q2={q2_name} sev={severity} "
                        f"({q2_conf:.2f}) heads={heads} lat={lat} ALERT {resp}",
                        flush=True,
                    )
                except requests.RequestException as exc:
                    event["alert_error"] = str(exc)
                    print(f"[{state}] alert failed: {exc}", flush=True)
            else:
                rem = int(args.cooldown_sec - (now - last_alert_ts))
                print(
                    f"[{state}] eta={eta:.1f}s q2={q2_name} sev={severity} lat={lat} cooldown {rem}s",
                    flush=True,
                )
        elif state == "yellow":
            print(
                f"[{state}] eta={eta:.1f}s q2={q2_name} sev={severity} lat={lat} (advisory)",
                flush=True,
            )
        elif n % 10 == 0 or state != prev:
            eta_s = f"{eta:.1f}" if eta is not None else "—"
            print(f"[{state}] eta={eta_s}s q2={q2_name} sev={severity} lat={lat}", flush=True)

        if log_path:
            with log_path.open("a") as f:
                f.write(json.dumps(event) + "\n")

        time.sleep(args.interval)

    print(f"done after {n} samples", flush=True)


if __name__ == "__main__":
    main()
