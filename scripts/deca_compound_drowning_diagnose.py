#!/usr/bin/env python3
"""Compound-drowning diagnosis — isolated dry-run.

Replays Prom telemetry from recorded compound blind windows through the
FROZEN promoted gate+head, dumps per-class probabilities + orthogonal
feature values for missed legs. Writes only under
models/experiments/compound_drowning_fix/. Never touches fault_classifier/.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from _paths import MODELS_DIR
from deca_live_common import densify_bgp_pulses, fetch_telemetry_long, load_bgp_pulses
from deca_live_operator import build_host_features
from deca_school_exam_train import (
    RARE,
    _align_to_estimator_features,
    feature_columns,
    load_active_classifier,
)
from rebuild_unified import UNIFIED_LABELS

OUT = MODELS_DIR / "experiments" / "compound_drowning_fix"
BLIND_ROOT = Path("/home/brain/deca-isro/data/rpi-net/blind-tests")
PROMOTED_PKL = MODELS_DIR / "fault_classifier" / "fault_classifier_xgb.pkl"

# Post–Tier-5c blinds (current promoted model era) + the three scoreboard refs
RUNS = {
    "tunnel_vrf": "blind_baseline_feature_tunnel_20260721_2302_40m",
    "bgp_vrf": "blind_baseline_feature_bgp_20260721_2321_40m",
    "control": "control_baseline_feature_20260721_2241_20m",
    # earlier same-day compounds (pre- or peri-promotion) for extra missed-leg evidence
    "tunnel_vrf_earlier": "blind_compound_tunnel_recheck_20260721_2012_40m",
    "bgp_vrf_earlier": "blind_compound_bgp_recheck_20260721_2029_40m",
}


def _load_events(run_id: str):
    sc = json.loads((BLIND_ROOT / run_id / "scorecard.json").read_text())
    return sc["summary"], sc["events"]


def _window_for_run(run_id: str, pad_min: float = 12.0):
    meta = json.loads((BLIND_ROOT / run_id / "run_meta.json").read_text())
    # fall back to event span
    _, events = _load_events(run_id)
    if not events:
        # control: use chaos log bounds or meta
        start = pd.Timestamp(meta.get("started_at") or meta.get("start_at") or meta.get("armed_at"))
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        end = start + timedelta(minutes=float(meta.get("minutes", 20)))
        return start.to_pydatetime(), end.to_pydatetime()
    starts = [pd.Timestamp(e["fault_start"]) for e in events]
    ends = [pd.Timestamp(e.get("recovery_time") or e["breach_time"]) for e in events]
    start = min(starts) - timedelta(minutes=pad_min)
    end = max(ends) + timedelta(minutes=pad_min)
    return start.to_pydatetime(), end.to_pydatetime()


def _class_maps(bundle):
    le_path = MODELS_DIR / "fault_classifier" / "label_encoder.pkl"
    le = joblib.load(le_path)
    classes = list(le.get("classes") or UNIFIED_LABELS)
    # full_clf.classes_ are int indices matching training
    return classes


def score_frames(gate, full_clf, X, *, healthy_idx, gate_thr, class_thr, class_names):
    """Return DataFrame of per-frame gate p(anom) + raw multiclass probs + argmax."""
    Xg = _align_to_estimator_features(gate, X)
    Xf = _align_to_estimator_features(full_clf, X)
    p_anom = gate.predict_proba(Xg)[:, 1]
    p_full = full_clf.predict_proba(Xf)
    full_classes = list(full_clf.classes_)  # int ids
    idx_to_name = {i: class_names[i] if i < len(class_names) else str(i) for i in range(len(class_names))}
    # map column order
    cols = {}
    for j, cid in enumerate(full_classes):
        name = idx_to_name.get(int(cid), str(cid))
        cols[f"p_{name}"] = p_full[:, j]
    thr_adj = {}
    for j, cid in enumerate(full_classes):
        name = idx_to_name.get(int(cid), str(cid))
        thr_adj[f"adj_{name}"] = p_full[:, j] / max(class_thr.get(int(cid), 1.0), 1e-6)

    preds = []
    winners = []
    runnerups = []
    for i in range(len(p_anom)):
        if p_anom[i] < gate_thr:
            preds.append("healthy(gate)")
            winners.append(float(1.0 - p_anom[i]))
            runnerups.append(None)
            continue
        scores = [thr_adj[f"adj_{idx_to_name.get(int(cid), str(cid))}"][i] for cid in full_classes]
        order = np.argsort(scores)[::-1]
        best = int(full_classes[order[0]])
        preds.append(idx_to_name.get(best, str(best)))
        winners.append(float(scores[order[0]]))
        if len(order) > 1:
            runnerups.append(
                {
                    "class": idx_to_name.get(int(full_classes[order[1]]), str(full_classes[order[1]])),
                    "adj": float(scores[order[1]]),
                }
            )
        else:
            runnerups.append(None)

    out = pd.DataFrame(index=X.index)
    out["p_anom"] = p_anom
    out["gate_pass"] = p_anom >= gate_thr
    for k, v in cols.items():
        out[k] = v
    for k, v in thr_adj.items():
        out[k] = v
    out["pred"] = preds
    out["winner_adj"] = winners
    out["runnerup"] = runnerups
    return out


def summarize_leg(scored: pd.DataFrame, truth_class: str, host: str, t0, t1, orth_cols):
    """Aggregate diagnosis for one missed/hit leg window."""
    # index may be DatetimeIndex
    idx = scored.index
    if getattr(idx, "tz", None) is None and len(idx):
        scored = scored.copy()
        scored.index = pd.to_datetime(scored.index, utc=True)
    mask = (scored.index >= pd.Timestamp(t0)) & (scored.index <= pd.Timestamp(t1))
    w = scored.loc[mask]
    if w.empty:
        return {"host": host, "truth": truth_class, "n_frames": 0, "error": "no frames in window"}

    p_col = f"p_{truth_class}"
    adj_col = f"adj_{truth_class}"
    # healthy baseline for truth class outside? use min of window start
    mean_p = float(w[p_col].mean()) if p_col in w else float("nan")
    max_p = float(w[p_col].max()) if p_col in w else float("nan")
    mean_adj = float(w[adj_col].mean()) if adj_col in w else float("nan")
    max_adj = float(w[adj_col].max()) if adj_col in w else float("nan")
    gate_rate = float(w["gate_pass"].mean())
    # how often truth is runner-up or winner among fault classes
    pred_counts = w["pred"].value_counts().to_dict()
    # rank of truth among adj scores when gate passes
    ranks = []
    for _, row in w[w["gate_pass"]].iterrows():
        adj_cols = [c for c in w.columns if c.startswith("adj_") and c != "adj_healthy"]
        vals = sorted([(c.replace("adj_", ""), float(row[c])) for c in adj_cols], key=lambda x: -x[1])
        rank = next((i + 1 for i, (n, _) in enumerate(vals) if n == truth_class), None)
        ranks.append(rank)
    # orthogonal feature presence
    orth = {}
    for c in orth_cols:
        if c in w.columns:
            orth[c] = {
                "non_null_pct": float(w[c].notna().mean()) * 100,
                "mean": float(w[c].mean()) if w[c].notna().any() else None,
                "max": float(w[c].max()) if w[c].notna().any() else None,
                "std": float(w[c].std()) if w[c].notna().any() else None,
            }

    # Compare truth adj vs winning fault adj
    win_fault = None
    if gate_rate > 0:
        # most common non-healthy pred
        faults = {k: v for k, v in pred_counts.items() if k not in ("healthy(gate)", "healthy")}
        win_fault = max(faults, key=faults.get) if faults else None

    # elevated vs near-baseline: use mean p_healthy as contrast
    mean_p_healthy = float(w["p_healthy"].mean()) if "p_healthy" in w else None
    diagnosis = "unknown"
    if not np.isfinite(max_p):
        diagnosis = "no_prob_column"
    elif max_p < 0.08 and mean_p < 0.05:
        diagnosis = "zeroed_out"  # never elevates
    elif win_fault and win_fault != truth_class and max_adj > 0.15:
        diagnosis = "present_but_outvoted"
    elif gate_rate < 0.1:
        diagnosis = "gate_miss"  # never clears anomaly gate
    elif win_fault == truth_class:
        diagnosis = "would_win_raw_but_maybe_loom"  # argmax ok — loom/operator may suppress
    else:
        diagnosis = "mixed_weak"

    return {
        "host": host,
        "truth": truth_class,
        "n_frames": int(len(w)),
        "gate_pass_frac": gate_rate,
        "mean_p_truth": mean_p,
        "max_p_truth": max_p,
        "mean_adj_truth": mean_adj,
        "max_adj_truth": max_adj,
        "mean_p_healthy": mean_p_healthy,
        "pred_counts": pred_counts,
        "median_rank_when_gate_pass": float(np.median([r for r in ranks if r])) if ranks else None,
        "winning_fault_pred": win_fault,
        "orthogonal": orth,
        "diagnosis": diagnosis,
        "t0": str(t0),
        "t1": str(t1),
    }


def lake_compound_support():
    """Row counts of co-occurring fault labels in post-exporter compound campaigns."""
    lake = Path("/home/brain/deca-isro/data/processed/deca_unified_dataset.parquet")
    df = pd.read_parquet(lake, columns=["run_id", "unified_label"]).reset_index(drop=True)
    rid = df["run_id"].astype(str)
    camps = {
        "tunnel_cong_vrf": ["tier5_vrf_overlap_20260720_0252", "tier5_vrf_consolidate_20260720_1418"],
        "bgp_vrf": ["tier5_bgp_vrf_focus_20260721_0618", "tier5_bgp_vrf_focus2_20260721_1159"],
        "pre_exporter_compound": ["compound_overlap_20260719_1735", "compound_overlap_w2_20260719_2045"],
    }
    out = {}
    for name, keys in camps.items():
        m = pd.Series(False, index=df.index)
        for k in keys:
            m |= rid.str.contains(k, regex=False)
        sub = df[m]
        out[name] = {
            "rows": int(len(sub)),
            "by_label": sub["unified_label"].value_counts().to_dict(),
            "by_station": {
                s: int(rid[m].str.endswith(s).sum())
                for s in ("station1", "station2", "station3")
            },
        }
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    promoted_mtime = PROMOTED_PKL.stat().st_mtime
    promoted_prefix = PROMOTED_PKL.read_bytes()[:64]

    bundle = load_active_classifier()
    assert bundle is not None
    gate, full_clf = bundle["gate"], bundle["full_clf"]
    healthy_idx = int(bundle["healthy_idx"])
    thr = json.loads((MODELS_DIR / "fault_classifier" / "decision_thresholds.json").read_text())
    gate_thr = float(thr.get("gate_thr", bundle.get("gate_thr", 0.5)))
    class_thr_named = thr.get("class_thr", {})
    class_names = _class_maps(bundle)
    class_to_idx = {c: i for i, c in enumerate(class_names)}
    class_thr = {int(class_to_idx[c]): float(v) for c, v in class_thr_named.items() if c in class_to_idx}

    print(f"Promoted locked mtime={promoted_mtime}")
    print(f"gate_thr={gate_thr} classes={class_names}")

    all_reports = {}
    for tag, run_id in RUNS.items():
        print(f"\n{'='*70}\n{tag}: {run_id}\n{'='*70}")
        summary, events = _load_events(run_id)
        print("scorecard summary:", {k: summary[k] for k in (
            "detected", "missed", "class_accuracy", "near_miss_false_alarms", "spurious_false_alarms"
        ) if k in summary})
        start, end = _window_for_run(run_id)
        print(f"Prom window: {start} → {end}")
        raw = fetch_telemetry_long(start, end)
        print(f"  raw telemetry rows: {len(raw)}  metrics={sorted(raw['metric'].unique().tolist()) if len(raw) else []}")
        if len(raw) == 0:
            all_reports[tag] = {"error": "no prometheus data", "run_id": run_id}
            continue
        bgp = load_bgp_pulses(run_id, start, end)  # densify happens inside build_host_features
        host_frames = build_host_features(raw, bgp)
        print(f"  hosts with features: {sorted(host_frames)}")

        leg_reports = []
        for e in events:
            host = e["host"]
            truth = e["fault_type"]
            t0 = pd.Timestamp(e["fault_start"])
            t1 = pd.Timestamp(e.get("recovery_time") or e["breach_time"]) + timedelta(minutes=3)
            if host not in host_frames:
                leg_reports.append({"host": host, "truth": truth, "error": "no feature frame", "detected": e["detected"]})
                continue
            feats = host_frames[host]
            # keep feature cols the model expects
            X = feats.copy()
            scored = score_frames(
                gate, full_clf, X,
                healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr, class_names=class_names,
            )
            # attach orthogonal raw engineered cols if present
            orth_cols = [c for c in X.columns if c.startswith("vrf_route_count") or c.startswith("bgp_flap_count")]
            for c in orth_cols:
                scored[c] = X[c]
            rep = summarize_leg(scored, truth, host, t0, t1, orth_cols)
            rep["detected_in_scorecard"] = e["detected"]
            rep["scorecard_pred"] = e.get("predicted_class")
            leg_reports.append(rep)
            print(
                f"  LEG {truth}@{host} detected={e['detected']} → diagnosis={rep.get('diagnosis')} "
                f"max_p_truth={rep.get('max_p_truth')} gate_pass={rep.get('gate_pass_frac')} "
                f"preds={rep.get('pred_counts')}"
            )
            # dump frame-level CSV for this leg
            mask = (scored.index >= t0) & (scored.index <= t1)
            csv_path = OUT / f"{run_id}__{host}__{truth}_frames.csv"
            scored.loc[mask].to_csv(csv_path)
            print(f"    wrote {csv_path.name} ({mask.sum()} frames)")

        all_reports[tag] = {
            "run_id": run_id,
            "summary": summary,
            "legs": leg_reports,
        }

    support = lake_compound_support()
    print("\n=== Lake compound training support ===")
    print(json.dumps(support, indent=2, default=str))

    # Sensor placement note
    sensor_note = {
        "bgp_flap_count_exporter": "station1 only (neighbor 10.1.3.1)",
        "vrf_route_count_exporter": "station1 + station2",
        "implication": (
            "When diagnosing BGP+VRF compounds: BGP truth is on station1 — "
            "bgp_flap_count SHOULD be present on station1 frames. "
            "station2 never has bgp_flap_count; if a blind ever labeled BGP on station2, "
            "that leg is structurally undetectable via bgp_flap_count. "
            "Current blinds place bgp_route_flap on station1 — sensor gap is NOT the "
            "explanation for station1 BGP misses; it WOULD be if we expected station2 to see BGP."
        ),
    }

    report = {
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
        "isolated": True,
        "promoted_untouched_check_pending": True,
        "runs": all_reports,
        "lake_compound_support": support,
        "sensor_placement": sensor_note,
    }
    (OUT / "diagnosis_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {OUT / 'diagnosis_report.json'}")

    after_mtime = PROMOTED_PKL.stat().st_mtime
    after_prefix = PROMOTED_PKL.read_bytes()[:64]
    assert after_mtime == promoted_mtime and after_prefix == promoted_prefix
    print("Confirmed: promoted model untouched.")


if __name__ == "__main__":
    main()
