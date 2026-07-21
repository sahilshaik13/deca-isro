#!/usr/bin/env python3
"""Falsify multi-label (sigmoid per class) on compound overlap — before Tier 5.

Hypothesis: independent sigmoids on the existing ~20 traffic features can recover
the drowned leg in PE1+VRF compounds (≥10% in-window frames with miss prob > 0.5).

If this fails on held-out compound windows, architecture-only is falsified and
Tier 5 orthogonal protocol features are justified.

Usage
-----
    python scripts/deca_multilabel_falsification.py
    python scripts/deca_multilabel_falsification.py --threshold 0.5 --pass-pct 10

Writes: models/multilabel_falsification_report.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from _paths import MODELS_DIR, PROCESSED_DIR, RPI_NET_DIR
from deca_live_common import FAULT_HOST, fetch_telemetry_long, load_bgp_pulses, read_jsonl
from deca_live_operator import build_host_features
from deca_school_exam_train import (
    PLAIN_XGB,
    RANDOM_STATE,
    RARE,
    build_gate,
    feature_columns,
    inverse_frequency_weights,
    predict_weighted_multiclass_with_confidence,
    train_phase1,
    tune_thresholds,
    xgb_pipeline,
)
from rebuild_unified import UNIFIED_LABELS

FAULT_CLASSES = [c for c in UNIFIED_LABELS if c != "healthy"]
PE1_CLASSES = ("congestion_breach", "tunnel_degradation", "bgp_route_flap")
BLIND_COMPOUND_RUNS = [
    "blind_compound_bgp_route_flap_20260719_1239_40m",
    "blind_compound_congestion_breach_20260719_1256_40m",
    "blind_compound_tunnel_degradation_20260719_1317_40m",
    "blind_compound_bgp_recheck_20260719_1516_40m",
    "blind_compound_tunnel_recheck_20260719_2012_40m",
    "blind_compound_tunnel_recheck_20260720_0154_40m",
    "blind_compound_bgp_recheck_20260720_0213_40m",
]
REPORT_PATH = MODELS_DIR / "multilabel_falsification_report.json"


@dataclass
class CompoundWindow:
    window_id: str
    source: str  # lake_overlap | blind_replay
    pe1_class: str
    miss_class: str
    miss_host: str
    start: pd.Timestamp
    end: pd.Timestamp
    run_ref: str


def host_from_run_id(run_id: str) -> str | None:
    s = str(run_id)
    if s.endswith("_station1"):
        return "station1"
    if s.endswith("_station2"):
        return "station2"
    if s.endswith("_ubuntu"):
        return "station2"
    return None


def _group_id_from_run_id(run_id: str) -> str | None:
    for ft in FAULT_CLASSES:
        suffix = f"_{ft}"
        if run_id.endswith(suffix):
            return run_id[: -len(suffix)]
    return None


def is_drowned_target(win: CompoundWindow) -> bool:
    """Legs that fail in production compound blinds — the falsification target."""
    if win.miss_class == "vrf_leakage" and win.pe1_class in ("tunnel_degradation", "congestion_breach"):
        return True
    if win.miss_class == "bgp_route_flap" and win.pe1_class == "bgp_route_flap":
        return True
    return False


def compound_windows_from_fault_log(log_path: Path, *, source: str, run_ref: str) -> list[CompoundWindow]:
    if not log_path.is_file():
        return []
    df = pd.read_csv(log_path, parse_dates=["fault_start", "breach_time"])
    by_group: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        rid = str(row.get("run_id", ""))
        if not rid.startswith("compound_"):
            continue
        gid = _group_id_from_run_id(rid)
        if gid is None:
            continue
        by_group.setdefault(gid, []).append(row.to_dict())

    out: list[CompoundWindow] = []
    for gid, legs in by_group.items():
        pe1 = next((l for l in legs if l["fault_type"] in PE1_CLASSES), None)
        vrf = next((l for l in legs if l["fault_type"] == "vrf_leakage"), None)
        if not pe1 or not vrf:
            continue
        fs = max(pd.Timestamp(pe1["fault_start"]), pd.Timestamp(vrf["fault_start"]))
        bt = min(pd.Timestamp(pe1["breach_time"]), pd.Timestamp(vrf["breach_time"]))
        if fs >= bt:
            continue
        miss_class = vrf["fault_type"]
        miss_host = FAULT_HOST[miss_class]
        out.append(
            CompoundWindow(
                window_id=f"{run_ref}:{gid}",
                source=source,
                pe1_class=pe1["fault_type"],
                miss_class=miss_class,
                miss_host=miss_host,
                start=fs,
                end=bt,
                run_ref=run_ref,
            )
        )
        if pe1["fault_type"] == "bgp_route_flap":
            out.append(
                CompoundWindow(
                    window_id=f"{run_ref}:{gid}:pe1",
                    source=source,
                    pe1_class=pe1["fault_type"],
                    miss_class=pe1["fault_type"],
                    miss_host=FAULT_HOST[pe1["fault_type"]],
                    start=fs,
                    end=bt,
                    run_ref=run_ref,
                )
            )
    return out


def compound_windows_from_blind(run_id: str) -> list[CompoundWindow]:
    for base in (RPI_NET_DIR / "blind-tests", RPI_NET_DIR / "live"):
        gt_path = base / run_id / "ground_truth.sealed.jsonl"
        if gt_path.is_file():
            events = [e for e in read_jsonl(gt_path) if not e.get("is_near_miss")]
            by_cg: dict[str, list[dict]] = {}
            for ev in events:
                cg = ev.get("compound_group") or ev["event_id"]
                by_cg.setdefault(cg, []).append(ev)
            out: list[CompoundWindow] = []
            for cg, legs in by_cg.items():
                if len(legs) < 2:
                    continue
                pe1 = next((l for l in legs if l["fault_type"] in PE1_CLASSES), None)
                vrf = next((l for l in legs if l["fault_type"] == "vrf_leakage"), None)
                if not pe1 or not vrf:
                    continue
                fs = max(pd.Timestamp(pe1["fault_start"]), pd.Timestamp(vrf["fault_start"]))
                bt = min(pd.Timestamp(pe1["breach_time"]), pd.Timestamp(vrf["breach_time"]))
                if fs >= bt:
                    continue
                out.append(
                    CompoundWindow(
                        window_id=f"{run_id}:{cg}:vrf",
                        source="blind_replay",
                        pe1_class=pe1["fault_type"],
                        miss_class="vrf_leakage",
                        miss_host="station2",
                        start=fs,
                        end=bt,
                        run_ref=run_id,
                    )
                )
                out.append(
                    CompoundWindow(
                        window_id=f"{run_id}:{cg}:pe1",
                        source="blind_replay",
                        pe1_class=pe1["fault_type"],
                        miss_class=pe1["fault_type"],
                        miss_host=pe1["host"],
                        start=fs,
                        end=bt,
                        run_ref=run_id,
                    )
                )
            return out
    return []


def discover_compound_windows() -> list[CompoundWindow]:
    windows: list[CompoundWindow] = []
    runs_root = RPI_NET_DIR / "runs"
    if runs_root.is_dir():
        for run_dir in sorted(runs_root.iterdir()):
            if not run_dir.is_dir():
                continue
            windows.extend(
                compound_windows_from_fault_log(
                    run_dir / "fault_injection_log.csv",
                    source="lake_overlap",
                    run_ref=run_dir.name,
                )
            )
    for rid in BLIND_COMPOUND_RUNS:
        windows.extend(compound_windows_from_blind(rid))
    return windows


def load_network_lake() -> pd.DataFrame:
    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    if not path.is_file():
        raise SystemExit(f"Missing lake: {path} — run rebuild_unified.py first")
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    net = df[df["source"] == "network"].copy()
    net["host"] = net["run_id"].map(host_from_run_id)
    return net


def labels_to_multihot(y_single: pd.Series, class_to_idx: dict[str, int]) -> np.ndarray:
    n = len(y_single)
    k = len(FAULT_CLASSES)
    Y = np.zeros((n, k), dtype=np.float32)
    for i, lab in enumerate(y_single.astype(str)):
        if lab in class_to_idx:
            Y[i, class_to_idx[lab]] = 1.0
    return Y


def build_multilabel_head(X_fit, Y_fit, *, sample_weight: np.ndarray | None = None):
    """One binary XGB per fault class (sigmoid / BCE)."""
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    X_imp = imputer.fit_transform(X_fit)
    estimators = []
    for j in range(Y_fit.shape[1]):
        clf = make_xgb_binary()
        w = sample_weight
        if w is not None:
            clf.fit(X_imp, Y_fit[:, j], sample_weight=w)
        else:
            clf.fit(X_imp, Y_fit[:, j])
        estimators.append(clf)
    return imputer, estimators


def make_xgb_binary():
    params = dict(PLAIN_XGB)
    params.update(
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    return XGBClassifier(**params)


def multilabel_proba(imputer, estimators, X) -> np.ndarray:
    X_imp = imputer.transform(X)
    return np.column_stack([est.predict_proba(X_imp)[:, 1] for est in estimators])


def multiclass_miss_scores(gate, full_clf, X, miss_class: str, *, healthy_idx, gate_thr, class_thr, classes):
    _, conf = predict_weighted_multiclass_with_confidence(
        gate, full_clf, X,
        healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr,
    )
    p_full = full_clf.predict_proba(X)
    fc = list(full_clf.classes_)
    if miss_class not in classes:
        miss_adj = np.zeros(len(X))
    else:
        cid = int(classes.index(miss_class))
        j = fc.index(cid)
        thr = max(class_thr.get(cid, 1.0), 1e-6)
        miss_adj = p_full[:, j] / thr
    return miss_adj, conf


def lake_slice(net: pd.DataFrame, feats: list[str], win: CompoundWindow) -> pd.DataFrame:
    host = win.miss_host
    mask = (
        (net["host"] == host)
        & (net.index >= win.start)
        & (net.index <= win.end)
    )
    sub = net.loc[mask]
    if sub.empty:
        return sub
    return sub.reindex(columns=feats)


def replay_slice(win: CompoundWindow, feats: list[str], lookback_min: float = 45.0) -> pd.DataFrame | None:
    from datetime import timedelta

    start = win.start.to_pydatetime() - timedelta(minutes=lookback_min)
    end = win.end.to_pydatetime() + timedelta(minutes=1)
    raw = fetch_telemetry_long(start, end)
    if raw.empty:
        return None
    bgp = load_bgp_pulses(win.run_ref, start, end)
    hosts = build_host_features(raw, bgp)
    if win.miss_host not in hosts:
        return None
    g = hosts[win.miss_host]
    g = g.loc[(g.index >= win.start) & (g.index <= win.end)]
    if g.empty:
        return None
    return g.reindex(columns=feats)


def eval_window(
    win: CompoundWindow,
    *,
    net: pd.DataFrame,
    feats: list[str],
    imputer,
    estimators,
    gate,
    full_clf,
    class_to_idx: dict[str, int],
    healthy_idx: int,
    gate_thr: float,
    class_thr: dict,
    classes: list[str],
    threshold: float,
    chrono_cut: pd.Timestamp,
) -> dict:
    use_replay = win.source == "blind_replay"
    if use_replay:
        X_df = replay_slice(win, feats)
        prom_ok = X_df is not None and not X_df.empty
    else:
        X_df = lake_slice(net, feats, win)
        prom_ok = None
    if X_df is None or X_df.empty:
        return {
            "window_id": win.window_id,
            "source": win.source,
            "pe1_class": win.pe1_class,
            "miss_class": win.miss_class,
            "miss_host": win.miss_host,
            "n_frames": 0,
            "prometheus_ok": prom_ok,
            "skipped": True,
            "reason": "no_frames",
        }

    miss_idx = class_to_idx[win.miss_class]
    ml_p = multilabel_proba(imputer, estimators, X_df)
    miss_ml = ml_p[:, miss_idx]
    miss_mc, _ = multiclass_miss_scores(
        gate, full_clf, X_df, win.miss_class,
        healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr, classes=classes,
    )

    in_train = win.source == "lake_overlap" and win.end < chrono_cut
    bucket = "in_sample_overlap" if in_train else "held_out"

    return {
        "window_id": win.window_id,
        "source": win.source,
        "bucket": bucket,
        "pe1_class": win.pe1_class,
        "miss_class": win.miss_class,
        "miss_host": win.miss_host,
        "start": win.start.isoformat(),
        "end": win.end.isoformat(),
        "n_frames": int(len(X_df)),
        "prometheus_ok": prom_ok,
        "skipped": False,
        "ml_pct_above_thr": round(100.0 * float((miss_ml >= threshold).mean()), 1),
        "ml_peak": round(float(miss_ml.max()), 3),
        "ml_mean": round(float(miss_ml.mean()), 3),
        "mc_pct_above_thr": round(100.0 * float((miss_mc >= threshold).mean()), 1),
        "mc_peak": round(float(miss_mc.max()), 3),
        "mc_mean": round(float(miss_mc.mean()), 3),
        "drowned_target": is_drowned_target(win),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-label compound falsification")
    parser.add_argument("--threshold", type=float, default=0.5, help="Sigmoid/score threshold")
    parser.add_argument("--pass-pct", type=float, default=10.0, help="Pass if >= this %% frames above threshold")
    parser.add_argument("--chrono-frac", type=float, default=0.75, help="Train fraction (chrono)")
    parser.add_argument("--rare-boost", type=float, default=1.5)
    args = parser.parse_args()

    print("=== DECA MULTI-LABEL FALSIFICATION (compound overlap) ===\n")
    net = load_network_lake()
    feats = feature_columns(net)
    if not feats:
        raise SystemExit("No feature columns in lake")

    classes = list(UNIFIED_LABELS)
    class_to_idx = {c: i for i, c in enumerate(FAULT_CLASSES)}
    healthy_idx = classes.index("healthy")
    rare_ids = {classes.index(c) for c in RARE if c in classes}

    y_single = net["unified_label"].astype(str)
    Y = labels_to_multihot(y_single, class_to_idx)

    cut_i = int(len(net) * args.chrono_frac)
    chrono_cut = net.index[cut_i]
    X_train = net.iloc[:cut_i].reindex(columns=feats)
    Y_train = Y[:cut_i]
    y_train_single = y_single.iloc[:cut_i]
    X_test = net.iloc[cut_i:].reindex(columns=feats)
    y_test_single = y_single.iloc[cut_i:]

    print(f"Lake network rows: {len(net)}  features: {len(feats)}")
    print(f"Chrono cut @ {chrono_cut}  train={len(X_train)} test={len(X_test)}")

    # Gate + multiclass champion (same recipe as School Exam plain head)
    y_train_idx = y_train_single.map({c: classes.index(c) for c in classes}).astype(int)
    y_test_idx = y_test_single.map({c: classes.index(c) for c in classes}).astype(int)
    sw = inverse_frequency_weights(
        y_train_idx.to_numpy(), rare_ids=rare_ids, boost=args.rare_boost
    )
    gate = build_gate(X_train, y_train_idx.to_numpy(), healthy_idx=healthy_idx)
    gate, full_clf, thr = train_phase1(
        X_train, y_train_idx.to_numpy(), X_test, y_test_idx.to_numpy(),
        healthy_idx=healthy_idx, rare_ids=rare_ids, boost=args.rare_boost,
        family="plain", gate=gate,
    )
    gate_thr = thr["gate_thr"]
    class_thr = thr["class_thr"]

    mc_test = predict_weighted_multiclass_with_confidence(
        gate, full_clf, X_test,
        healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr,
    )[0]
    mc_macro = float(f1_score(y_test_idx, mc_test, average="macro", zero_division=0))
    print(f"Multiclass chrono-test macro-F1 (plain, retrained): {mc_macro:.3f}")

    # Multi-label head on train split only
    imputer, estimators = build_multilabel_head(X_train, Y_train, sample_weight=sw)
    ml_test_p = multilabel_proba(imputer, estimators, X_test)
    # micro-F1: any fault predicted vs any fault true
    y_test_fault = (y_test_idx.to_numpy() != healthy_idx).astype(int)
    ml_any_fault = (ml_test_p.max(axis=1) >= args.threshold).astype(int)
    gate_open = gate.predict_proba(X_test)[:, 1] >= gate_thr
    ml_any_fault = ml_any_fault & gate_open
    ml_anom_f1 = float(f1_score(y_test_fault, ml_any_fault, zero_division=0))
    print(f"Multi-label chrono-test anomaly F1 (any fault, gated): {ml_anom_f1:.3f}")

    windows = discover_compound_windows()
    print(f"\nCompound eval windows discovered: {len(windows)}")

    results = [
        eval_window(
            w,
            net=net,
            feats=feats,
            imputer=imputer,
            estimators=estimators,
            gate=gate,
            full_clf=full_clf,
            class_to_idx=class_to_idx,
            healthy_idx=healthy_idx,
            gate_thr=gate_thr,
            class_thr=class_thr,
            classes=classes,
            threshold=args.threshold,
            chrono_cut=chrono_cut,
        )
        for w in windows
    ]

    held = [r for r in results if not r.get("skipped") and r.get("bucket") == "held_out"]
    drowned = [r for r in held if r.get("drowned_target")]
    in_sample = [r for r in results if not r.get("skipped") and r.get("bucket") == "in_sample_overlap"]

    def _passes(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r.get("ml_pct_above_thr", 0) >= args.pass_pct]

    drowned_pass_ml = _passes(drowned)
    drowned_pass_mc = [r for r in drowned if r.get("mc_pct_above_thr", 0) >= args.pass_pct]

    falsified = len(drowned_pass_ml) == 0

    print("\n--- Drowned-target windows (held-out) — primary falsification set ---")
    for r in drowned:
        tag = "PASS" if r["ml_pct_above_thr"] >= args.pass_pct else "FAIL"
        print(
            f"  [{tag}] {r['window_id']}  {r['pe1_class']}+{r['miss_class']}@{r['miss_host']} "
            f"n={r['n_frames']}  ML {r['ml_pct_above_thr']}% peak={r['ml_peak']}  "
            f"MC {r['mc_pct_above_thr']}% peak={r['mc_peak']}  ({r['source']})"
        )

    other = [r for r in held if not r.get("drowned_target")]
    if other:
        print("\n--- Other held-out compound windows (control / loud leg) ---")
        for r in other[:8]:
            print(
                f"  {r['window_id']}  ML {r['ml_pct_above_thr']}% peak={r['ml_peak']}  "
                f"MC {r['mc_pct_above_thr']}%  drowned_target=False"
            )
        if len(other) > 8:
            print(f"  ... +{len(other) - 8} more")

    if in_sample:
        print("\n--- In-sample overlap campaign (sanity — can memorise?) ---")
        for r in in_sample[:6]:
            print(
                f"  {r['window_id']}  ML {r['ml_pct_above_thr']}% peak={r['ml_peak']}  "
                f"MC {r['mc_pct_above_thr']}% peak={r['mc_peak']}"
            )
        if len(in_sample) > 6:
            print(f"  ... +{len(in_sample) - 6} more")

    print("\n=== VERDICT (drowned-target legs only) ===")
    print(f"  Drowned-target held-out windows: {len(drowned)}  "
          f"ML pass (>={args.pass_pct}%): {len(drowned_pass_ml)}  MC pass: {len(drowned_pass_mc)}")
    if falsified:
        print("  FALSIFIED: multi-label sigmoids do NOT recover drowned compound legs.")
        print("  → Tier 5 orthogonal protocol features are justified.")
    else:
        print("  NOT FALSIFIED on drowned targets: at least one drowned window meets the pass bar.")
        print("  → Revisit dual-confirm operator before committing to Tier 5 lab work.")

    report = {
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "threshold": args.threshold,
        "pass_pct": args.pass_pct,
        "chrono_cut": chrono_cut.isoformat(),
        "multiclass_test_macro_f1": mc_macro,
        "multilabel_test_anomaly_f1": ml_anom_f1,
        "falsified": falsified,
        "drowned_target_windows": len(drowned),
        "drowned_target_ml_pass": len(drowned_pass_ml),
        "drowned_target_mc_pass": len(drowned_pass_mc),
        "held_out_windows": len(held),
        "windows": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
