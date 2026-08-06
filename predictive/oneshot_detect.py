"""One-shot Q2 detection snapshot for NOC demo faults.

Samples live Prom briefly, builds a Q2 window, runs frozen severity (+ BGP
specialist), and prints JSON for the orchestrator to attach on Decide cards.

Usage:
  .venv-predictive/bin/python -m predictive.oneshot_detect \\
    --fault-id rain_fade --samples 12 --interval 0.5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]

DEFAULT_Q2 = REPO / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
DEFAULT_BGP = (
    REPO
    / "data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/bgp_3a3b_locked.joblib"
)

# What each dashboard Simple fault should light up (human + model fingerprint).
FAULT_FINGERPRINTS: dict[str, dict[str, Any]] = {
    "rain_fade": {
        "expect_severities": ["1A", "1B", "1C"],
        "watch": ["latency_gre_ms", "jitter_gre_ms", "path_asymmetry"],
        "blurb": "GRE delay / asymmetry rising toward TT&C ≤25 ms",
    },
    "cpu_stress": {
        "expect_severities": ["2A", "2B"],
        "watch": ["cpu_usage_user", "cpu_usage_system", "latency_gre_ms"],
        "blurb": "PE cpu_usage_user elevated (crypto / forwarding pressure)",
    },
    "bgp_flap": {
        "expect_severities": ["3A", "3B"],
        "watch": ["bgp_flap_count", "latency_gre_ms"],
        "blurb": "BGP flap counter / route instability",
    },
    "loss_progression": {
        "expect_severities": ["4A", "4B"],
        "watch": ["loss_gre_pct", "latency_gre_ms"],
        "blurb": "GRE packet loss climbing toward Payload 2%",
    },
    "ce_sla_conflict": {
        "expect_severities": ["5A", "5B", "6A", "6B"],
        "watch": ["util_gre_mbps", "cpu_usage_user", "latency_gre_ms"],
        "blurb": "Bronze rogue util pressure vs Gold / TT&C on shared PE",
    },
}


def _sample_loop(n: int, interval: float, fabric: str) -> list[dict[str, float]]:
    from .prom_export import Q1_QUERIES, Q2_QUERIES, prom_url_for_fabric, sample_bundle

    prom = prom_url_for_fabric(fabric)
    queries = {**Q1_QUERIES, **Q2_QUERIES}
    buf: list[dict[str, float]] = []
    for _ in range(max(1, n)):
        row = sample_bundle(prom, queries)
        # normalize None → 0 for window math
        clean = {k: float(v) if v is not None else 0.0 for k, v in row.items()}
        buf.append(clean)
        if interval > 0 and _ + 1 < n:
            time.sleep(interval)
    return buf


def detect(
    *,
    fault_id: str = "",
    samples: int = 12,
    interval: float = 0.5,
    fabric: str = "pi",
    q2_path: Path = DEFAULT_Q2,
    bgp_path: Path | None = DEFAULT_BGP,
) -> dict[str, Any]:
    import joblib

    from .bgp_specialist import refine_3a_3b
    from .infer_q1_q2_live import window_features
    from .severity_label import ID_TO_SEVERITY, SEVERITY_NAMES, SEVERITY_TO_ROOT

    if not q2_path.is_file():
        return {"ok": False, "error": f"q2_missing:{q2_path}", "fault_id": fault_id}

    t0 = time.time()
    buf = _sample_loop(samples, interval, fabric)
    last = buf[-1] if buf else {}

    bundle = joblib.load(q2_path)
    model = bundle["model"]
    feat_cols = list(bundle["feature_cols"])
    id_to_sev = bundle.get("id_to_severity") or ID_TO_SEVERITY
    sev_to_root = bundle.get("severity_to_root") or SEVERITY_TO_ROOT
    label_names = bundle.get("label_names") or {}

    feats = window_features(buf, feat_cols)
    X = np.asarray([[float(feats.get(c, 0.0)) for c in feat_cols]], dtype=float)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)[0]
        q2_label = int(np.argmax(proba))
        q2_conf = float(proba[q2_label])
    else:
        q2_label = int(model.predict(X)[0])
        q2_conf = 0.75
        proba = None

    severity = str(id_to_sev.get(q2_label, "0"))
    # contig→raw remap if needed
    contig_to_raw = bundle.get("contig_to_raw") or {}
    if contig_to_raw and q2_label in contig_to_raw:
        raw_id = int(contig_to_raw[q2_label])
        severity = str(ID_TO_SEVERITY.get(raw_id, severity))

    bgp_note = None
    if bgp_path and Path(bgp_path).is_file():
        try:
            bgp_bundle = joblib.load(bgp_path)
            before = severity
            severity = refine_3a_3b(severity, feats, bundle=bgp_bundle)
            if severity != before:
                bgp_note = f"bgp_specialist {before}→{severity}"
        except Exception as exc:  # noqa: BLE001
            bgp_note = f"bgp_specialist_skip:{exc}"

    q2_name = SEVERITY_NAMES.get(severity, label_names.get(q2_label, str(q2_label)))
    root_label = int(sev_to_root.get(severity, 0))

    # Top live Prom signals (human-readable)
    watch = (FAULT_FINGERPRINTS.get(fault_id) or {}).get("watch") or [
        "latency_gre_ms",
        "cpu_usage_user",
        "loss_gre_pct",
        "util_gre_mbps",
        "bgp_flap_count",
    ]
    top_signals = []
    for name in watch:
        if name in last:
            top_signals.append({"name": name, "value": round(float(last[name]), 4)})

    # Feature last/slope for watched bases if present
    feature_highlights = []
    for name in watch:
        for agg in ("_last", "_mean", "_slope", "_max"):
            key = f"{name}{agg}"
            if key in feats:
                feature_highlights.append(
                    {"feature": key, "value": round(float(feats[key]), 4)}
                )

    fp = FAULT_FINGERPRINTS.get(fault_id) or {}
    expect = list(fp.get("expect_severities") or [])
    matches = (not expect) or (severity in expect) or (
        severity != "0" and any(severity.startswith(e[0]) for e in expect if e)
    )

    # Top class probabilities (for Decide)
    top_classes: list[dict[str, Any]] = []
    if proba is not None:
        class_ids = list(bundle.get("class_ids") or range(len(proba)))
        ranked = sorted(
            (
                (
                    float(proba[i]),
                    str(id_to_sev.get(int(class_ids[i]) if i < len(class_ids) else i, i)),
                )
                for i in range(len(proba))
            ),
            reverse=True,
        )
        for p, sev in ranked[:4]:
            top_classes.append(
                {
                    "severity": sev,
                    "name": SEVERITY_NAMES.get(sev, sev),
                    "proba": round(p, 4),
                }
            )

    explanation = (
        f"Q2 ({Path(q2_path).parent.name}) classed live Prom as "
        f"{severity} {q2_name} (p={q2_conf:.2f})"
    )
    if fault_id:
        explanation += f" while demo fault `{fault_id}` was injecting"
        if fp.get("blurb"):
            explanation += f" — looking for: {fp['blurb']}"
    if top_signals:
        bits = ", ".join(f"{s['name']}={s['value']}" for s in top_signals[:4])
        explanation += f". Live signals: {bits}."
    if bgp_note:
        explanation += f" ({bgp_note})"

    return {
        "ok": True,
        "fault_id": fault_id or None,
        "generation_path": "q2_oneshot_frozen_d2",
        "model": str(q2_path),
        "bgp_specialist": str(bgp_path) if bgp_path else None,
        "fabric": fabric,
        "samples": len(buf),
        "elapsed_sec": round(time.time() - t0, 2),
        "severity": severity,
        "q2_name": q2_name,
        "q2_confidence": round(q2_conf, 4),
        "root_label": root_label,
        "matches_demo_fault": bool(matches),
        "expected_severities": expect,
        "fingerprint_blurb": fp.get("blurb"),
        "prom_snapshot": {k: round(float(v), 4) for k, v in last.items()},
        "top_signals": top_signals,
        "feature_highlights": feature_highlights[:12],
        "top_classes": top_classes,
        "bgp_note": bgp_note,
        "explanation": explanation,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fault-id", default="")
    ap.add_argument("--samples", type=int, default=12)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--fabric", default=os.environ.get("DECA_FABRIC", "pi"))
    ap.add_argument("--q2-model", default=str(DEFAULT_Q2))
    ap.add_argument("--bgp-specialist", default=str(DEFAULT_BGP))
    args = ap.parse_args()
    bgp = Path(args.bgp_specialist) if args.bgp_specialist else None
    out = detect(
        fault_id=args.fault_id,
        samples=args.samples,
        interval=args.interval,
        fabric=args.fabric,
        q2_path=Path(args.q2_model),
        bgp_path=bgp if bgp and bgp.is_file() else None,
    )
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    raise SystemExit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
