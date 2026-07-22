#!/usr/bin/env python3
"""Compound fix round 2 — isolated mixed retrain + live-faithful blind replay.

Does NOT touch models/fault_classifier/. Writes only under
models/experiments/compound_fix_round_2/.

Assumes rebuild_unified.py --all-rpi-runs has already folded the new campaign
into data/processed/deca_unified_dataset.parquet (with _z_* regenerated).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_live_common import fetch_telemetry_long, load_bgp_pulses
from deca_live_operator import build_host_features
from deca_school_exam_train import (
    _align_to_estimator_features,
    load_active_classifier,
    run_school_exam,
)

import os

OUT = Path(
    os.environ.get(
        "COMPOUND_FIX_OUT",
        str(MODELS_DIR / "experiments" / "compound_fix_round_2"),
    )
)
PROMOTED_PKL = MODELS_DIR / "fault_classifier" / "fault_classifier_xgb.pkl"
PROMOTED_THR = MODELS_DIR / "fault_classifier" / "decision_thresholds.json"
BASELINE_MACRO = 0.717

# Same blinds as drowning diagnosis (Tier-5c era)
BLINDS = {
    "tunnel_vrf": {
        "run_id": "blind_baseline_feature_tunnel_20260721_2302_40m",
        "legs": [
            {
                "host": "station2",
                "truth": "vrf_leakage",
                "t0": "2026-07-21T17:35:45+00:00",
                "t1": "2026-07-21T17:47:20+00:00",
                "prior_max_p_truth": 0.146,
                "prior_mean_p_truth": 0.021,
            },
            {
                "host": "station1",
                "truth": "tunnel_degradation",
                "t0": "2026-07-21T17:35:45+00:00",
                "t1": "2026-07-21T17:43:40+00:00",
                "prior_max_p_truth": 0.942,
                "prior_mean_p_truth": 0.652,
            },
        ],
    },
    "bgp_vrf": {
        "run_id": "blind_baseline_feature_bgp_20260721_2321_40m",
        "legs": [
            {
                "host": "station1",
                "truth": "bgp_route_flap",
                "t0": "2026-07-21T17:53:27+00:00",
                "t1": "2026-07-21T18:06:57+00:00",
                "prior_max_p_truth": 0.061,
                "prior_mean_p_truth": 0.015,
            },
            {
                "host": "station2",
                "truth": "vrf_leakage",
                "t0": "2026-07-21T17:53:27+00:00",
                "t1": "2026-07-21T18:05:15+00:00",
                "prior_max_p_truth": 0.915,
                "prior_mean_p_truth": 0.574,
            },
        ],
    },
    "control": {
        "run_id": "control_baseline_feature_20260721_2241_20m",
        # All-healthy control window (chaos_run.log armed→end). Score FA rate.
        "t0": "2026-07-21T17:12:00+00:00",
        "t1": "2026-07-21T17:31:00+00:00",
        "hosts": ["station1", "station2"],
        "legs": [],
    },
}


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _assert_promoted_untouched(before_mtime: float, before_prefix: bytes) -> None:
    if PROMOTED_PKL.stat().st_mtime != before_mtime or PROMOTED_PKL.read_bytes()[:64] != before_prefix:
        raise RuntimeError(
            "REFUSAL: models/fault_classifier/fault_classifier_xgb.pkl changed — aborting."
        )


def _save_isolated_candidate(rep: dict, out_dir: Path) -> dict:
    """Persist school-exam best head without promoting."""
    best = rep["best_payload"]
    class_to_idx = rep["class_to_idx"]
    le_classes = list(best["le_classes"])
    thr = best["thr"]
    family = best.get("family")
    rare_boost = best["row"]["rare_boost"]

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "gate": best["gate"],
        "full_clf": best["full_clf"],
        "healthy_idx": int(best["healthy_idx"]),
        "gate_thr": float(thr["gate_thr"]),
        "class_thr": {int(k): float(v) for k, v in thr["class_thr"].items()},
        "mode": "weighted_multiclass",
        "family": family,
        "rare_boost": rare_boost,
        "isolated_experiment": "compound_fix_round_2",
        "note": "ISOLATED dry-run — not promoted; do not copy into fault_classifier/",
    }
    joblib.dump(bundle, out_dir / "fault_classifier_xgb.pkl")
    joblib.dump(
        {"classes": le_classes, "smote": False, "isolated_experiment": True},
        out_dir / "label_encoder.pkl",
    )
    idx_to_class = {i: c for c, i in class_to_idx.items()}
    named_thr = {
        (idx_to_class[int(k)] if int(k) in idx_to_class else str(k)): float(v)
        for k, v in thr["class_thr"].items()
    }
    thr_doc = {
        "gate_thr": float(thr["gate_thr"]),
        "class_thr": named_thr,
        "family": family,
        "rare_boost": rare_boost,
        "experiment": "compound_fix_round_2",
        "note": "isolated — not promoted",
    }
    # Copy loom from promoted if present (decision path parity for streaming)
    if PROMOTED_THR.exists():
        prom_thr = json.loads(PROMOTED_THR.read_text())
        if "loom" in prom_thr:
            thr_doc["loom"] = prom_thr["loom"]
    (out_dir / "decision_thresholds.json").write_text(json.dumps(thr_doc, indent=2))

    gate = rep["gate"]
    gate_info = {
        "exam_macro_f1": float(gate["candidate_macro_f1"]),
        "exam_rare_recall": float(gate["candidate_mean_rare_recall"]),
        "gate_passed": bool(gate["passed"]),
        "bar_macro": float(gate["bar_macro_f1"]),
        "champion_same_paper_macro_f1": float(gate["champion_same_paper_macro_f1"]),
        "family": family,
        "rare_boost": rare_boost,
    }
    (out_dir / "exam_gate.json").write_text(json.dumps(gate_info, indent=2))
    # Strip non-serializable model objects from report copy
    slim = {k: v for k, v in rep.items() if k not in ("best_payload", "class_to_idx")}
    (out_dir / "school_exam_report.json").write_text(json.dumps(slim, indent=2, default=str))
    # Also copy weight_sweep if school_exam wrote one
    sweep_src = MODELS_DIR / "school_exam" / "weight_sweep.csv"
    if sweep_src.exists():
        shutil.copy2(sweep_src, out_dir / "weight_sweep.csv")
    return {"bundle": bundle, "classes": le_classes, "thr": thr_doc, "gate_info": gate_info}


def _load_model_bundle(pkl: Path, thr_path: Path, le_path: Path | None = None):
    bundle = joblib.load(pkl)
    thr = json.loads(thr_path.read_text())
    if le_path and le_path.exists():
        le = joblib.load(le_path)
        classes = list(le["classes"])
    else:
        # promoted path
        le = joblib.load(MODELS_DIR / "fault_classifier" / "label_encoder.pkl")
        classes = list(le["classes"])
    gate = bundle["gate"]
    full = bundle["full_clf"]
    gate_thr = float(thr.get("gate_thr", bundle.get("gate_thr", 0.5)))
    class_thr = {i: float(thr["class_thr"][c]) for i, c in enumerate(classes) if c in thr["class_thr"]}
    return gate, full, classes, gate_thr, class_thr


def score_one(gate, full, classes, gate_thr, class_thr, Xrow: pd.Series):
    X = Xrow.to_frame().T
    feats = [c for c in X.columns if c not in ("run_id", "source")]
    Xf = _align_to_estimator_features(full, X[feats])
    Xg = _align_to_estimator_features(gate, X[feats])
    p_anom = float(gate.predict_proba(Xg)[0, 1])
    p = full.predict_proba(Xf)[0]
    probs = {classes[int(cid)]: float(p[j]) for j, cid in enumerate(full.classes_)}
    if p_anom < gate_thr:
        pred = "healthy(gate)"
    else:
        scores = {n: probs[n] / max(class_thr.get(classes.index(n), 1.0), 1e-6) for n in probs}
        pred = max(scores, key=scores.get)
    return p_anom, probs, pred


def live_faithful_replay(
    *,
    run_id: str,
    host: str,
    truth: str,
    t0: str,
    t1: str,
    gate,
    full,
    classes,
    gate_thr,
    class_thr,
    lookback_min: float = 25.0,
    step_s: int = 30,
) -> dict:
    t0 = pd.Timestamp(t0)
    t1 = pd.Timestamp(t1)
    start = (t0 - timedelta(minutes=lookback_min + 2)).to_pydatetime()
    end = (t1 + timedelta(minutes=2)).to_pydatetime()
    raw = fetch_telemetry_long(start, end)
    bgp = load_bgp_pulses(run_id, start, end)
    if len(raw) == 0:
        return {"error": "no prom", "run_id": run_id, "host": host, "truth": truth}
    raw = raw.rename(columns={"timestamp": "ts"}) if "timestamp" in raw.columns else raw
    if len(bgp) and "timestamp" in bgp.columns:
        bgp = bgp.rename(columns={"timestamp": "ts"})

    rows = []
    for now in pd.date_range(t0, t1, freq=f"{step_s}s", inclusive="both"):
        w0 = now - timedelta(minutes=lookback_min)
        raw_w = raw[(raw["ts"] >= w0) & (raw["ts"] <= now)]
        if len(raw_w) == 0:
            continue
        bgp_w = bgp[(bgp["ts"] >= w0) & (bgp["ts"] <= now)] if len(bgp) else bgp
        frames = build_host_features(
            raw_w.rename(columns={"ts": "timestamp"}),
            bgp_w.rename(columns={"ts": "timestamp"}) if len(bgp_w) else bgp_w,
        )
        if host not in frames or len(frames[host]) == 0:
            continue
        Xh = frames[host]
        Xh = Xh[Xh.index <= now]
        if len(Xh) == 0:
            continue
        p_anom, probs, pred = score_one(gate, full, classes, gate_thr, class_thr, Xh.iloc[-1])
        rows.append(
            {
                "ts": str(now),
                "p_anom": p_anom,
                "pred": pred,
                **{f"p_{k}": v for k, v in probs.items()},
            }
        )
    if not rows:
        return {"error": "no frames", "run_id": run_id, "host": host, "truth": truth}
    df = pd.DataFrame(rows)
    truth_col = f"p_{truth}"
    max_t = float(df[truth_col].max()) if truth_col in df else 0.0
    mean_t = float(df[truth_col].mean()) if truth_col in df else 0.0
    elev = float((df[truth_col] >= 0.15).mean()) if truth_col in df else 0.0
    wins = float((df["pred"] == truth).mean())
    if max_t < 0.05 and elev < 0.05:
        diag = "zeroed_out"
    elif wins >= 0.4:
        diag = "would_win_raw"
    elif elev >= 0.15 or max_t >= 0.15:
        diag = "present_but_outvoted"
    else:
        diag = "zeroed_out"
    return {
        "run_id": run_id,
        "host": host,
        "truth": truth,
        "n": len(df),
        "pred_counts": df["pred"].value_counts().to_dict(),
        "mean_p_truth": mean_t,
        "max_p_truth": max_t,
        "frac_pred_truth": wins,
        "frac_p_truth_ge_0.15": elev,
        "diagnosis": diag,
        "winning_pred": max(df["pred"].value_counts().to_dict(), key=df["pred"].value_counts().to_dict().get),
        "frames": df,
    }


def confirm_z_features(campaign_substr: str) -> dict:
    lake = pd.read_parquet(PROCESSED_DIR / "deca_unified_dataset.parquet")
    rid = lake["run_id"].astype(str)
    m = rid.str.contains(campaign_substr, regex=False)
    sub = lake.loc[m]
    z_cols = [c for c in lake.columns if "_z_" in c]
    ortho_z = [
        c
        for c in z_cols
        if "vrf_route_count" in c or "bgp_flap_count" in c
    ]
    return {
        "campaign_rows": int(m.sum()),
        "by_label": sub["unified_label"].value_counts().to_dict() if len(sub) else {},
        "n_z_cols_in_lake": len(z_cols),
        "ortho_z_cols_present": ortho_z[:20],
        "ortho_z_nonnull_pct": {
            c: float(sub[c].notna().mean() * 100) for c in ortho_z[:8] if c in sub.columns
        }
        if len(sub)
        else {},
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before_mtime = PROMOTED_PKL.stat().st_mtime
    before_prefix = PROMOTED_PKL.read_bytes()[:64]
    before_sha = _sha16(PROMOTED_PKL)
    print(f"Promoted locked sha16={before_sha} mtime={before_mtime}")

    meta_path = OUT / "campaign_meta.json"
    if not meta_path.exists():
        raise SystemExit(f"Missing {meta_path} — run campaign first and write campaign_meta.json")
    meta = json.loads(meta_path.read_text())
    run_id = meta["run_id"]
    counts = meta["counts"]

    print("\n=== Confirm lake fold + _z_* companions ===")
    z_info = confirm_z_features(run_id.replace("compound_fix_r2_", "").split("_20")[0] if False else run_id)
    # match run id as used in lake: rpi_<run_id>_stationN
    z_info = confirm_z_features(run_id)
    print(json.dumps(z_info, indent=2))
    (OUT / "lake_fold_check.json").write_text(json.dumps(z_info, indent=2))

    print("\n=== Mixed school exam (full lake, dry-run, no promote) ===")
    # Prefer plain family for honest champion-on-same-paper parity with prior rounds;
    # still sweep β like the default school exam.
    rep = run_school_exam(
        rare_boosts=[1.0, 1.5, 2.0, 3.0],
        families=["plain", "wm"],
        baseline_macro_f1=BASELINE_MACRO,
        auto_promote=False,
        unit_test_active=True,
    )
    cand_dir = OUT / "candidate"
    saved = _save_isolated_candidate(rep, cand_dir)
    print(f"Candidate exam macro-F1={saved['gate_info']['exam_macro_f1']:.4f} "
          f"gate={'PASS' if saved['gate_info']['gate_passed'] else 'FAIL'}")

    # Models for replay
    prom_gate, prom_full, prom_classes, prom_gthr, prom_cthr = _load_model_bundle(
        PROMOTED_PKL, PROMOTED_THR
    )
    cand_gate, cand_full, cand_classes, cand_gthr, cand_cthr = _load_model_bundle(
        cand_dir / "fault_classifier_xgb.pkl",
        cand_dir / "decision_thresholds.json",
        cand_dir / "label_encoder.pkl",
    )

    print("\n=== Live-faithful sliding-lookback replay (promoted vs candidate) ===")
    replay_out: dict = {"promoted": {}, "candidate": {}, "control_fa": {}}
    for blind_key, blind in BLINDS.items():
        if not blind.get("legs"):
            continue
        for leg in blind["legs"]:
            key = f"{blind_key}__{leg['host']}__{leg['truth']}"
            for tag, (g, f, cls, gt, ct) in {
                "promoted": (prom_gate, prom_full, prom_classes, prom_gthr, prom_cthr),
                "candidate": (cand_gate, cand_full, cand_classes, cand_gthr, cand_cthr),
            }.items():
                print(f"  {tag} {key}...")
                res = live_faithful_replay(
                    run_id=blind["run_id"],
                    host=leg["host"],
                    truth=leg["truth"],
                    t0=leg["t0"],
                    t1=leg["t1"],
                    gate=g,
                    full=f,
                    classes=cls,
                    gate_thr=gt,
                    class_thr=ct,
                )
                frames = res.pop("frames", None)
                if frames is not None:
                    csv_path = OUT / f"live_faithful__{tag}__{key}_frames.csv"
                    frames.to_csv(csv_path, index=False)
                    res["csv"] = str(csv_path)
                if "prior_max_p_truth" in leg and tag == "candidate":
                    res["prior_max_p_truth"] = leg["prior_max_p_truth"]
                    res["prior_mean_p_truth"] = leg["prior_mean_p_truth"]
                    res["delta_max_p_truth"] = float(res.get("max_p_truth") or 0) - float(
                        leg["prior_max_p_truth"]
                    )
                    res["delta_mean_p_truth"] = float(res.get("mean_p_truth") or 0) - float(
                        leg["prior_mean_p_truth"]
                    )
                replay_out[tag][key] = res
                print(
                    f"    max_p={res.get('max_p_truth')} mean_p={res.get('mean_p_truth')} "
                    f"diag={res.get('diagnosis')} preds={res.get('pred_counts')}"
                )

    # Control regression: fraction of frames predicting a real fault class
    ctrl = BLINDS["control"]
    print("\n=== Control false-alarm rate (live-faithful) ===")
    for tag, (g, f, cls, gt, ct) in {
        "promoted": (prom_gate, prom_full, prom_classes, prom_gthr, prom_cthr),
        "candidate": (cand_gate, cand_full, cand_classes, cand_gthr, cand_cthr),
    }.items():
        host_stats = {}
        for host in ctrl["hosts"]:
            res = live_faithful_replay(
                run_id=ctrl["run_id"],
                host=host,
                truth="healthy",  # unused for FA; we inspect pred_counts
                t0=ctrl["t0"],
                t1=ctrl["t1"],
                gate=g,
                full=f,
                classes=cls,
                gate_thr=gt,
                class_thr=ct,
            )
            frames = res.pop("frames", None)
            if frames is None:
                host_stats[host] = res
                continue
            n = len(frames)
            faultish = frames["pred"].isin(
                ["congestion_breach", "tunnel_degradation", "bgp_route_flap", "vrf_leakage"]
            )
            fa = float(faultish.mean()) if n else None
            host_stats[host] = {
                "n": n,
                "fa_frac": fa,
                "pred_counts": frames["pred"].value_counts().to_dict(),
            }
            csv_path = OUT / f"live_faithful__{tag}__control__{host}_frames.csv"
            frames.to_csv(csv_path, index=False)
        replay_out["control_fa"][tag] = host_stats
        print(f"  {tag}: {host_stats}")

    (OUT / "live_faithful_replay.json").write_text(json.dumps(replay_out, indent=2, default=str))

    # Hard-stop assessment on the two failing legs
    fail_keys = [
        "tunnel_vrf__station2__vrf_leakage",
        "bgp_vrf__station1__bgp_route_flap",
    ]
    rises = {}
    for k in fail_keys:
        c = replay_out["candidate"].get(k, {})
        prior_max = float(c.get("prior_max_p_truth") or 0)
        new_max = float(c.get("max_p_truth") or 0)
        # "Meaningfully rises above baseline" — clear of near-baseline band (>0.25)
        # or at least +0.15 absolute vs prior diagnosis.
        meaningful = (new_max >= 0.25) or (new_max - prior_max >= 0.15)
        rises[k] = {
            "prior_max": prior_max,
            "new_max": new_max,
            "delta": new_max - prior_max,
            "meaningful_rise": meaningful,
            "diagnosis": c.get("diagnosis"),
        }
    hard_stop = not any(v["meaningful_rise"] for v in rises.values())

    summary = {
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "counts": counts,
        "lake_fold": z_info,
        "exam_gate": saved["gate_info"],
        "live_faithful_failing_legs": rises,
        "hard_stop": hard_stop,
        "promoted_untouched": {
            "sha16_before": before_sha,
            "sha16_after": _sha16(PROMOTED_PKL),
            "unchanged": _sha16(PROMOTED_PKL) == before_sha,
        },
        "note": "ISOLATED — not promoted",
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    _assert_promoted_untouched(before_mtime, before_prefix)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"Hard stop (neither leg rose meaningfully): {hard_stop}")
    print("Confirmed: promoted pkl untouched.")


if __name__ == "__main__":
    main()
