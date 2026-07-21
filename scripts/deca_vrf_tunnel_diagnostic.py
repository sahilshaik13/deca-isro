#!/usr/bin/env python3
"""Offline slice: is vrf_leakage vs tunnel_degradation a model or topology problem?

Runs before expensive data campaigns or retraining. Answers:
  - On station2 VRF-labeled frames, does the promoted head name tunnel?
  - Is the margin tight (feature overlap) or is VRF rarely top-1 at all?
  - Do blind declarations match the offline pattern?

Usage
-----
    python scripts/deca_vrf_tunnel_diagnostic.py
    python scripts/deca_vrf_tunnel_diagnostic.py --blind-run blind_vrfcheck_20260719_0210_45m
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from _paths import MODELS_DIR, PROCESSED_DIR, RPI_NET_DIR
from deca_school_exam_train import feature_columns, predict_weighted_multiclass_with_confidence


def load_promoted():
    clf_dir = MODELS_DIR / "fault_classifier"
    bundle = joblib.load(clf_dir / "fault_classifier_xgb.pkl")
    le = joblib.load(clf_dir / "label_encoder.pkl")
    classes = list(le["classes"])
    return bundle, classes


def host_from_run_id(run_id: str) -> str | None:
    s = str(run_id)
    if s.endswith("_station1"):
        return "station1"
    if s.endswith("_station2"):
        return "station2"
    if s.endswith("_ubuntu"):
        return "station2"
    return None


def adjusted_scores_row(p_full_row, full_classes, class_thr, target: str) -> float:
    class_id = {c: j for j, c in enumerate(full_classes)}
    j = class_id.get(target)
    if j is None:
        return 0.0
    cid = int(full_classes[j])
    thr = max(class_thr.get(cid, 1.0), 1e-6)
    return float(p_full_row[j] / thr)


def lake_slice(df: pd.DataFrame, bundle, classes) -> dict:
    gate = bundle["gate"]
    full_clf = bundle["full_clf"]
    healthy_idx = int(bundle["healthy_idx"])
    gate_thr = float(bundle["gate_thr"])
    class_thr = {int(k): float(v) for k, v in bundle.get("class_thr", {}).items()}
    feats = feature_columns(df)
    if not feats:
        raise SystemExit("No feature columns in unified dataset")

    work = df.copy()
    work["host"] = work["run_id"].map(host_from_run_id)
    s2 = work[work["host"] == "station2"].copy()
    if s2.empty:
        raise SystemExit("No station2 rows in lake")

    X = s2.reindex(columns=feats)
    # Gate pipeline imputes NaNs — do not drop rows (station2 often has partial BGP cols).

    preds, conf = predict_weighted_multiclass_with_confidence(
        gate, full_clf, X,
        healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr,
    )
    s2["pred"] = [classes[int(p)] for p in preds]
    s2["conf"] = conf

    vrf = s2[s2["unified_label"] == "vrf_leakage"]
    tun_on_s2 = s2[s2["unified_label"] == "tunnel_degradation"]

    def _summ(sub: pd.DataFrame, title: str) -> None:
        if sub.empty:
            print(f"  {title}: (empty)")
            return
        vc = sub["pred"].value_counts()
        print(f"  {title}: n={len(sub)}")
        for k, v in vc.items():
            print(f"    pred {k}: {v} ({100 * v / len(sub):.1f}%)")
        tunnel_wins = int((sub["pred"] == "tunnel_degradation").sum())
        vrf_wins = int((sub["pred"] == "vrf_leakage").sum())
        print(f"    tunnel wins: {tunnel_wins} ({100 * tunnel_wins / len(sub):.1f}%)")
        print(f"    vrf wins:    {vrf_wins} ({100 * vrf_wins / len(sub):.1f}%)")

    print("\n=== LAKE: station2 labeled frames (promoted head, no loom) ===")
    _summ(vrf, "true vrf_leakage")
    _summ(tun_on_s2, "true tunnel_degradation (station2 labels)")

    if len(vrf):
        p_full = full_clf.predict_proba(X.loc[vrf.index])
        full_classes = list(full_clf.classes_)
        margins = []
        for i in range(len(vrf)):
            vrf_s = adjusted_scores_row(p_full[i], full_classes, class_thr, "vrf_leakage")
            tun_s = adjusted_scores_row(p_full[i], full_classes, class_thr, "tunnel_degradation")
            margins.append(vrf_s - tun_s)
        margin = np.array(margins)
        print("\n  VRF vs tunnel score margin (true vrf rows, station2):")
        print(f"    mean margin (vrf−tunnel): {margin.mean():.3f}")
        print(f"    median: {np.median(margin):.3f}")
        print(
            f"    tunnel > vrf: {(margin < 0).sum()} / {len(margin)} "
            f"({100 * (margin < 0).mean():.1f}%)"
        )

    print("\n=== LAKE: vrf_leakage by campaign (station2) ===")
    if len(vrf):
        vrf = vrf.copy()
        vrf["campaign"] = vrf["run_id"].astype(str).str.replace(r"_station2$", "", regex=True)
        for camp, grp in vrf.groupby("campaign"):
            tw = int((grp["pred"] == "tunnel_degradation").sum())
            vw = int((grp["pred"] == "vrf_leakage").sum())
            print(f"  {camp}: n={len(grp)} tunnel_pred={tw} vrf_pred={vw}")

    return {
        "station2_vrf_rows": len(vrf),
        "station2_vrf_pred_tunnel_pct": float((vrf["pred"] == "tunnel_degradation").mean() * 100)
        if len(vrf) else None,
        "station2_vrf_pred_vrf_pct": float((vrf["pred"] == "vrf_leakage").mean() * 100)
        if len(vrf) else None,
    }


def blind_slice(run_id: str) -> None:
    base = None
    for candidate in (RPI_NET_DIR / "blind-tests" / run_id, RPI_NET_DIR / "live" / run_id):
        if (candidate / "ground_truth.sealed.jsonl").is_file():
            base = candidate
            break
    if base is None:
        print(f"\n=== BLIND {run_id}: not found ===")
        return

    gt = [json.loads(l) for l in (base / "ground_truth.sealed.jsonl").read_text().splitlines() if l.strip()]
    decl_path = base / "declarations.jsonl"
    decls = (
        [json.loads(l) for l in decl_path.read_text().splitlines() if l.strip()]
        if decl_path.is_file()
        else []
    )

    print(f"\n=== BLIND: {run_id} ===")
    for ev in gt:
        if ev.get("is_near_miss") or ev.get("fault_type") == "near_miss":
            continue
        ft = ev.get("fault_type")
        host = ev.get("host")
        cg = ev.get("compound_group")
        fs = pd.Timestamp(ev["fault_start"])
        bt = pd.Timestamp(ev["breach_time"])
        window = [
            d for d in decls
            if d.get("event") == "confirmed_raise"
            and d.get("host") == host
            and fs <= pd.Timestamp(d["ts"]) <= bt + pd.Timedelta(minutes=5)
        ]
        pred = window[0].get("confirmed") if window else None
        print(f"  {ft} @ {host} compound={cg or '-'}")
        print(f"    detected={'yes' if window else 'NO'} first_confirm={pred}")
        if ft == "vrf_leakage" and pred and pred != "vrf_leakage":
            print(f"    ** class confusion: declared {pred}")


def recommend(stats: dict) -> None:
    pct = stats.get("station2_vrf_pred_tunnel_pct")
    print("\n=== RECOMMENDATION (heuristic) ===")
    if pct is None:
        print("  Insufficient vrf_leakage rows on station2 in lake.")
        return
    if pct == 0:
        print("  Offline: promoted head never picks tunnel on true VRF (station2).")
        print("  Live vrfcheck tunnel confirm on station2 during PE1 tunnel compound")
        print("  matches cross-host echo — echo origin-lock should block that confirm.")
        print("  Next: (1) re-grade vrfcheck counterfactually with echo gate,")
        print("        (2) station2 vrf origin-lock (only PE2 may confirm vrf_leakage),")
        print("        (3) one isolated VRF blind — 0848 silent miss is separate from class confusion.")
    elif pct >= 50:
        print("  Feature overlap likely: tunnel wins on majority of true VRF frames.")
        print("  Next: compound-negative VRF data campaign OR station2 vrf origin-lock.")
    elif pct >= 25:
        print("  Mixed margin: threshold/loom or targeted negatives may suffice.")
    else:
        print("  Offline head mostly correct; live confusion may be loom/compound/echo.")


def main() -> None:
    parser = argparse.ArgumentParser(description="VRF vs tunnel offline diagnostic")
    parser.add_argument(
        "--blind-run",
        action="append",
        default=[],
        help="Blind run id to inspect declarations (repeatable)",
    )
    args = parser.parse_args()

    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    if not path.is_file():
        raise SystemExit(f"Missing {path}; run rebuild_unified.py --all-rpi-runs first")

    df = pd.read_parquet(path)
    bundle, classes = load_promoted()
    print(f"Promoted classes: {classes}")
    stats = lake_slice(df, bundle, classes)

    blind_runs = args.blind_run or [
        "blind_vrfcheck_20260719_0210_45m",
        "blind_20260718_0848_60m",
    ]
    for rid in blind_runs:
        blind_slice(rid)

    recommend(stats)


if __name__ == "__main__":
    main()
