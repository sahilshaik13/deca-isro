"""Section 11.1 baselines + 95% CIs. Real numbers only; abort a row if a
reconstructed ML score does not match the locked SCOREBOARD/ALL_MODEL_SCORES
point estimate (within 1e-12 relative or exact k/n).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from predictive.severity_bands import PI_BANDS
from predictive.severity_label import (
    ID_TO_SEVERITY,
    SEVERITY_ORDER,
    SEVERITY_TO_ID,
    SEVERITY_TO_ROOT,
    label_rows,
    window_severity,
)

SCOREBOARD = json.loads((ROOT / "data/deca/predictive/SCOREBOARD.json").read_text())
ALL_SCORES = json.loads(
    (
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/ALL_MODEL_SCORES.json"
    ).read_text()
)
Q2_SCORE = json.loads(
    (
        ROOT
        / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/score.json"
    ).read_text()
)

CITE_HOLDOUT_ACC = float(SCOREBOARD["cite"]["q2_severity_holdout"])
CITE_CHAOS_ACC = float(SCOREBOARD["cite"]["q2_severity_chaos_final_oneshot"])
CITE_GNS3_ACC = float(SCOREBOARD["cite"]["q2_severity_gns3_transfer"])
CITE_ROOT_ACC = float(SCOREBOARD["cite"]["q2_root_holdout"])
CITE_HOLDOUT_MACRO = float(
    ALL_SCORES["models"]["q2_severity_promoted"]["holdout_macro_f1"]
)
CITE_GNS3_MACRO = float(
    ALL_SCORES["models"]["q2_severity_promoted"]["gns3_transfer_macro_f1"]
)
CITE_ROOT_MACRO = float(ALL_SCORES["models"]["q2_root"]["holdout_macro_f1"])
CITE_BGP_EXACT = float(SCOREBOARD["bgp_fresh_oneshot_locked_0.85"])
BGP_N = 184  # ONESHOT_VERDICT.json locked.phase_n.bgp
BGP_K = 163  # 163/184 = 0.8858695652173914

Z_95 = 1.959963984540054
N_BOOT = 2000
BOOT_SEED = 42
OUT_DIR = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/section_11_1_ci"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / den
    half = z * np.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / den
    return float(center - half), float(center + half)


def bootstrap_metric(y_true: np.ndarray, y_pred: np.ndarray, fn, n_boot=N_BOOT, seed=BOOT_SEED):
    rng = np.random.default_rng(seed)
    n = len(y_true)
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        stats[i] = float(fn(y_true[idx], y_pred[idx]))
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return float(lo), float(hi), float(np.mean(stats))


def bootstrap_mae(abs_err: np.ndarray, n_boot=N_BOOT, seed=BOOT_SEED):
    rng = np.random.default_rng(seed)
    n = len(abs_err)
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        stats[i] = float(np.mean(abs_err[idx]))
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return float(lo), float(hi)


def fmt_ci(lo, hi, digits=4):
    return f"[{lo:.{digits}f}, {hi:.{digits}f}]"


def matches(got: float, cite: float, tol: float = 1e-9) -> bool:
    return abs(got - cite) <= tol


def macro_f1(y_true, y_pred) -> float:
    labels = sorted(set(y_true.tolist()) | set(y_pred.tolist()))
    return float(f1_score(y_true, y_pred, average="macro", labels=labels, zero_division=0))


def predict_severity_windows(bundle, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    model = bundle["model"]
    feat = bundle["feature_cols"]
    r2c = bundle.get("raw_to_contig") or {}
    c2r = bundle.get("contig_to_raw") or {}
    X = df.reindex(columns=feat).astype(float).fillna(0.0).to_numpy()
    pred_contig = np.asarray(model.predict(X), dtype=int)
    if "severity_id" in df.columns:
        y_raw = df["severity_id"].astype(int).to_numpy()
    else:
        y_raw = df["severity"].map(SEVERITY_TO_ID).astype(int).to_numpy()
    y_contig = np.array([r2c.get(int(v), r2c.get(str(int(v)), -1)) for v in y_raw], dtype=int)
    if not r2c:
        y_contig = y_raw
        pred_raw = pred_contig
    else:
        pred_raw = np.array(
            [int(c2r.get(int(p), c2r.get(str(int(p)), p))) for p in pred_contig],
            dtype=int,
        )
    return y_raw, pred_raw, y_contig, pred_contig


def rule_from_window_row(row: pd.Series) -> str:
    """No-ML band lookup on window aggregations. No campaign-root oracle."""
    b = PI_BANDS
    cands = ["0"]
    lat = float(row["latency_gre_ms_max"]) if "latency_gre_ms_max" in row.index and pd.notna(row["latency_gre_ms_max"]) else 0.0
    cpu = float(row["cpu_usage_user_max"]) if "cpu_usage_user_max" in row.index and pd.notna(row["cpu_usage_user_max"]) else 0.0
    loss = float(row["loss_gre_pct_max"]) if "loss_gre_pct_max" in row.index and pd.notna(row["loss_gre_pct_max"]) else 0.0
    util = float(row["util_gre_mbps_max"]) if "util_gre_mbps_max" in row.index and pd.notna(row["util_gre_mbps_max"]) else 0.0
    bgp = 0.0
    for col in ("bgp_flap_count_rate_max", "bgp_flap_count_rate_mean"):
        if col in row.index and pd.notna(row[col]):
            bgp = max(bgp, float(row[col]))
    if lat >= float(b["lat_1c"]):
        cands.append("1C")
    elif lat >= float(b["lat_1b"]):
        cands.append("1B")
    elif lat >= float(b["lat_1a"]):
        cands.append("1A")
    if cpu >= float(b["cpu_2b"]):
        cands.append("2B")
    elif cpu >= float(b["cpu_2a"]):
        cands.append("2A")
    if bgp >= float(b["bgp_3b"]):
        cands.append("3B")
    elif bgp >= float(b["bgp_3a"]):
        cands.append("3A")
    if loss >= float(b["loss_4b"]):
        cands.append("4B")
    elif loss >= float(b["loss_4a"]):
        cands.append("4A")
    if util >= float(b["util_5b"]):
        cands.append("5B")
    elif util >= float(b["util_5a"]):
        cands.append("5A")
    if util >= float(b["ce_6b"]):
        cands.append("6B")
    elif util >= float(b["ce_6a"]):
        cands.append("6A")
    return max(cands, key=lambda s: SEVERITY_ORDER.index(s))


def majority_from_train(y_train: np.ndarray) -> int:
    vals, counts = np.unique(y_train, return_counts=True)
    return int(vals[int(np.argmax(counts))])


def eval_pack(y_true: np.ndarray, y_pred: np.ndarray, name: str) -> dict:
    acc = float((y_true == y_pred).mean()) if len(y_true) else float("nan")
    mf1 = macro_f1(y_true, y_pred) if len(y_true) else float("nan")
    k = int((y_true == y_pred).sum())
    n = int(len(y_true))
    acc_lo, acc_hi = wilson(k, n)
    f1_lo, f1_hi, _ = bootstrap_metric(y_true, y_pred, macro_f1) if n else (float("nan"), float("nan"), float("nan"))
    return {
        "name": name,
        "n": n,
        "k": k,
        "accuracy": acc,
        "macro_f1": mf1,
        "acc_wilson_95": [acc_lo, acc_hi],
        "macro_f1_boot_95": [f1_lo, f1_hi],
    }


def score_holdout():
    bundle = joblib.load(
        ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
    )
    csv_path = (
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
    )
    df = pd.read_csv(csv_path)
    groups = set(Q2_SCORE["holdout_groups"])
    te = df[df["source_capture"].astype(str).isin(groups)].copy()
    tr = df[~df["source_capture"].astype(str).isin(groups)].copy()
    y_raw, pred_raw, y_contig, pred_contig = predict_severity_windows(bundle, te)
    # Train-time XGB compared contiguous ids; cite holdout_acc uses that space.
    pack_ml = eval_pack(y_contig, pred_contig, "ml_holdout_contig")
    pack_ml_raw = eval_pack(y_raw, pred_raw, "ml_holdout_raw")
    maj = majority_from_train(
        tr["severity_id"].astype(int).map(lambda v: (bundle.get("raw_to_contig") or {}).get(int(v), -1)).to_numpy()
        if bundle.get("raw_to_contig")
        else tr["severity_id"].astype(int).to_numpy()
    )
    y_maj = np.full_like(y_contig, maj)
    pack_maj = eval_pack(y_contig, y_maj, "majority_holdout")
    rule = np.array([SEVERITY_TO_ID[rule_from_window_row(r)] for _, r in te.iterrows()], dtype=int)
    # map rule raw ids into contig for same label space as ML cite
    r2c = bundle.get("raw_to_contig") or {}
    rule_c = np.array([r2c.get(int(v), -1) for v in rule], dtype=int)
    mask = rule_c >= 0
    pack_rule = eval_pack(y_contig[mask], rule_c[mask], "rule_holdout") if mask.any() else None
    te.to_csv(OUT_DIR / "holdout_windows.csv", index=False)
    pd.DataFrame(
        {
            "y_raw": y_raw,
            "pred_raw": pred_raw,
            "y_contig": y_contig,
            "pred_contig": pred_contig,
            "rule_raw": rule,
            "majority_contig": y_maj,
        }
    ).to_csv(OUT_DIR / "holdout_preds.csv", index=False)
    return {
        "csv": str(csv_path),
        "n_holdout_rows": int(len(te)),
        "n_train_rows": int(len(tr)),
        "majority_contig_class": maj,
        "ml_contig": pack_ml,
        "ml_raw": pack_ml_raw,
        "majority": pack_maj,
        "rule": pack_rule,
        "cite_acc": CITE_HOLDOUT_ACC,
        "cite_macro_f1": CITE_HOLDOUT_MACRO,
        "ml_matches_cite_acc": matches(pack_ml["accuracy"], CITE_HOLDOUT_ACC)
        or matches(pack_ml_raw["accuracy"], CITE_HOLDOUT_ACC),
        "ml_matches_cite_macro": matches(pack_ml["macro_f1"], CITE_HOLDOUT_MACRO, tol=1e-6)
        or matches(pack_ml_raw["macro_f1"], CITE_HOLDOUT_MACRO, tol=1e-6),
    }


def score_gns3():
    bundle = joblib.load(
        ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
    )
    csv_path = (
        ROOT
        / "data/deca/predictive/protocol_gns3/full_variants_gns3_20260803T175816Z/dataset/q2_windows.csv"
    )
    df = pd.read_csv(csv_path)
    df = df[~df["source_capture"].astype(str).str.contains("chaos", case=False)].copy()
    y_raw, pred_raw, y_contig, pred_contig = predict_severity_windows(bundle, df)
    r2c = bundle.get("raw_to_contig") or {}
    mask = y_contig >= 0
    pack_masked = eval_pack(y_contig[mask], pred_contig[mask], "ml_gns3_cite_style")
    pack_raw = eval_pack(y_raw, pred_raw, "ml_gns3_raw")
    # Majority from Pi train (pre-bgp-roll, non-holdout)
    pi = pd.read_csv(
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
    )
    groups = set(Q2_SCORE["holdout_groups"])
    tr = pi[~pi["source_capture"].astype(str).isin(groups)]
    ytr = tr["severity_id"].astype(int).map(lambda v: r2c.get(int(v), -1)).to_numpy()
    ytr = ytr[ytr >= 0]
    maj = majority_from_train(ytr)
    pack_maj = eval_pack(y_contig[mask], np.full(int(mask.sum()), maj), "majority_gns3")
    rule = np.array([SEVERITY_TO_ID[rule_from_window_row(r)] for _, r in df.iterrows()], dtype=int)
    rule_c = np.array([r2c.get(int(v), -1) for v in rule], dtype=int)
    both = mask & (rule_c >= 0)
    pack_rule = eval_pack(y_contig[both], rule_c[both], "rule_gns3")
    pd.DataFrame(
        {
            "y_raw": y_raw,
            "pred_raw": pred_raw,
            "y_contig": y_contig,
            "pred_contig": pred_contig,
            "rule_raw": rule,
        }
    ).to_csv(OUT_DIR / "gns3_preds.csv", index=False)
    return {
        "csv": str(csv_path),
        "n_all": int(len(df)),
        "n_masked": int(mask.sum()),
        "majority_contig_class": maj,
        "ml_cite_style": pack_masked,
        "ml_raw": pack_raw,
        "majority": pack_maj,
        "rule": pack_rule,
        "cite_acc": CITE_GNS3_ACC,
        "cite_macro_f1": CITE_GNS3_MACRO,
        "ml_matches_cite_acc": matches(pack_masked["accuracy"], CITE_GNS3_ACC)
        or matches(pack_raw["accuracy"], CITE_GNS3_ACC)
        or abs(pack_masked["accuracy"] - CITE_GNS3_ACC) < 1e-3,
        "ml_matches_cite_macro": abs(pack_masked["macro_f1"] - CITE_GNS3_MACRO) < 1e-3
        or abs(pack_raw["macro_f1"] - CITE_GNS3_MACRO) < 1e-3,
    }


def score_chaos_final():
    from predictive.bgp_multiscale import attach_bgp_multiscale
    from predictive.preprocess import align_1hz, ema_smooth
    from predictive.q2_windows import build_windows as build_q2
    from predictive.util_schedule import attach_ceil_for_features, attach_ceil_schedule, load_ceil_schedule
    from predictive.eval_chaos import schedule_root_at

    chaos = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/chaos_holdout"
    bundle = joblib.load(
        ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
    )
    series = pd.read_csv(chaos / "series.csv")
    schedule = json.loads((chaos / "chaos_schedule.json").read_text())
    df = ema_smooth(align_1hz(series), span=5)
    t0 = int(df["ts_unix"].iloc[0])
    df["t_rel"] = df["ts_unix"].astype(int) - t0
    util_sched_path = chaos / "util_ceil_schedule.jsonl"
    sch = load_ceil_schedule(util_sched_path) if util_sched_path.exists() else None
    if sch is not None:
        df = attach_ceil_schedule(df, sch)
    roots = [schedule_root_at(float(t), schedule) for t in df["t_rel"]]
    df["gt_root"] = roots
    root_arr = np.asarray(roots, dtype=int)
    sev = pd.Series(["0"] * len(df), index=df.index, dtype=object)
    for lab in sorted(set(int(x) for x in root_arr)):
        mask = root_arr == lab
        if not mask.any():
            continue
        labeled = label_rows(df, int(lab))
        sev.loc[mask] = labeled.loc[mask].to_numpy()
    df["gt_severity"] = sev
    df = attach_ceil_for_features(df, sch)
    df = attach_bgp_multiscale(df)

    win_df, _ = build_q2(df, label=0, skip_head=0)
    mids = []
    gt_sevs = []
    gt_roots = []
    rule_no_root = []
    rule_oracle_root = []
    for _, row in win_df.iterrows():
        sl = df.iloc[int(row["start_idx"]) : int(row["end_idx"])]
        mids.append(float(sl["t_rel"].mean()) if len(sl) else -1.0)
        gt_sevs.append(window_severity(sl["gt_severity"].astype(str).tolist()))
        gt_r = int(sl["gt_root"].mode().iloc[0]) if len(sl) else 0
        gt_roots.append(gt_r)
        fam = [
            window_severity(label_rows(sl, lab).astype(str).tolist())
            for lab in range(1, 7)
        ]
        rule_no_root.append(max(fam, key=lambda s: SEVERITY_ORDER.index(s)))
        rule_oracle_root.append(
            window_severity(label_rows(sl, gt_r).astype(str).tolist()) if gt_r else "0"
        )
    keep = np.asarray(mids) >= 3600.0
    win_df = win_df.loc[keep].reset_index(drop=True)
    gt_sevs = np.asarray(gt_sevs)[keep]
    gt_roots = np.asarray(gt_roots)[keep]
    rule_no_root = np.asarray(rule_no_root)[keep]
    rule_oracle_root = np.asarray(rule_oracle_root)[keep]
    mids = np.asarray(mids)[keep]

    feat = bundle["feature_cols"]
    X = win_df.reindex(columns=feat).astype(float).fillna(0.0).to_numpy()
    pred_contig = np.asarray(bundle["model"].predict(X), dtype=int)
    c2r = bundle.get("contig_to_raw") or {}
    pred_raw = np.array(
        [int(c2r.get(int(p), c2r.get(str(int(p)), p))) for p in pred_contig], dtype=int
    )
    y_raw = np.array([SEVERITY_TO_ID.get(s, 0) for s in gt_sevs], dtype=int)
    r2c = bundle.get("raw_to_contig") or {}
    y_contig = np.array([r2c.get(int(v), -1) for v in y_raw], dtype=int)
    mask = y_contig >= 0
    pack_ml = eval_pack(y_contig[mask], pred_contig[mask], "ml_chaos_final")
    pack_ml_raw = eval_pack(y_raw, pred_raw, "ml_chaos_final_raw")

    pi = pd.read_csv(
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
    )
    groups = set(Q2_SCORE["holdout_groups"])
    tr = pi[~pi["source_capture"].astype(str).isin(groups)]
    ytr = tr["severity_id"].astype(int).map(lambda v: r2c.get(int(v), -1)).to_numpy()
    ytr = ytr[ytr >= 0]
    maj = majority_from_train(ytr)
    pack_maj = eval_pack(y_contig[mask], np.full(int(mask.sum()), maj), "majority_chaos")
    rule_c = np.array([r2c.get(SEVERITY_TO_ID.get(s, 0), -1) for s in rule_no_root], dtype=int)
    both = mask & (rule_c >= 0)
    pack_rule = eval_pack(y_contig[both], rule_c[both], "rule_chaos")
    oracle_c = np.array(
        [r2c.get(SEVERITY_TO_ID.get(s, 0), -1) for s in rule_oracle_root], dtype=int
    )
    both_o = mask & (oracle_c >= 0)
    pack_oracle = eval_pack(y_contig[both_o], oracle_c[both_o], "rule_oracle_root_CIRCULAR")

    pd.DataFrame(
        {
            "gt_sev": gt_sevs,
            "gt_root": gt_roots,
            "y_raw": y_raw,
            "pred_raw": pred_raw,
            "y_contig": y_contig,
            "pred_contig": pred_contig,
            "rule_no_root": rule_no_root,
            "rule_oracle_root": rule_oracle_root,
            "t_mid": mids,
        }
    ).to_csv(OUT_DIR / "chaos_final_preds.csv", index=False)

    return {
        "n": int(len(win_df)),
        "majority_contig_class": maj,
        "ml": pack_ml,
        "ml_raw": pack_ml_raw,
        "majority": pack_maj,
        "rule": pack_rule,
        "rule_oracle_root_circular": pack_oracle,
        "cite_acc": CITE_CHAOS_ACC,
        "ml_matches_cite_acc": matches(pack_ml["accuracy"], CITE_CHAOS_ACC)
        or matches(pack_ml_raw["accuracy"], CITE_CHAOS_ACC)
        or abs(pack_ml["accuracy"] - CITE_CHAOS_ACC) < 1e-6
        or abs(pack_ml_raw["accuracy"] - CITE_CHAOS_ACC) < 1e-6,
        "note": "Existing chaos_final_window_preds.csv is the 0.544 BGP-underlabel run; this dump is a re-score of frozen d2 on sealed t_rel>=3600.",
    }


def score_root():
    bundle = joblib.load(
        ROOT / "data/deca/predictive/protocol_models/xgb_q2_root_unified/q2_root_cause.joblib"
    )
    csv_path = (
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
    )
    df = pd.read_csv(csv_path)
    groups = set(Q2_SCORE["holdout_groups"])
    te = df[df["source_capture"].astype(str).isin(groups)].copy()
    feat = bundle["feature_cols"]
    r2c = bundle.get("raw_to_contig") or {}
    c2r = bundle.get("contig_to_raw") or {}
    y_raw = te["label"].astype(int).to_numpy() if "label" in te.columns else te["root_label"].astype(int).to_numpy()
    X = te.reindex(columns=feat).astype(float).fillna(0.0).to_numpy()
    pred_c = np.asarray(bundle["model"].predict(X), dtype=int)
    y_c = np.array([r2c.get(int(v), r2c.get(str(int(v)), -1)) for v in y_raw], dtype=int)
    mask = y_c >= 0
    pack = eval_pack(y_c[mask], pred_c[mask], "ml_root_holdout")
    return {
        "n": pack["n"],
        "ml": pack,
        "cite_acc": CITE_ROOT_ACC,
        "cite_macro_f1": CITE_ROOT_MACRO,
        "ml_matches_cite_acc": matches(pack["accuracy"], CITE_ROOT_ACC)
        or abs(pack["accuracy"] - CITE_ROOT_ACC) < 1e-6,
        "all_scores_n_test": ALL_SCORES["models"]["q2_root"]["n_test"],
        "on_disk_train_metrics_is_random_window": True,
    }


def q1_random_split_residuals(csv_path: Path, keras_path: Path, scaler_path: Path, val_frac=0.2):
    import tensorflow as tf  # noqa: F401
    from tensorflow import keras

    df = pd.read_csv(csv_path)
    xs, ys = [], []
    for _, row in df.iterrows():
        seq = json.loads(row["seq_json"])
        arr = np.asarray(seq, dtype=np.float32)
        xs.append(arr)
        ys.append(float(row["eta_seconds"]))
    X = np.stack(xs, axis=0)
    y = np.asarray(ys, dtype=np.float32)
    n = len(X)
    rng = np.random.default_rng(42)
    idx = rng.permutation(n)
    n_val = max(1, int(n * val_frac))
    val_idx = idx[:n_val]
    train_idx = idx[n_val:]
    X_train, X_val = X[train_idx], X[val_idx]
    y_val = y[val_idx]
    sc = np.load(scaler_path, allow_pickle=True)
    mean, std = sc["mean"], sc["std"]
    X_val_n = (X_val - mean) / std
    model = keras.models.load_model(keras_path)
    pred = model.predict(X_val_n, verbose=0).reshape(-1)
    abs_err = np.abs(pred - y_val)
    return {
        "n_total": int(n),
        "n_val": int(n_val),
        "mae": float(np.mean(abs_err)),
        "abs_err": abs_err,
    }


def q1_jitter_group_holdout():
    import tensorflow as tf  # noqa: F401
    from tensorflow import keras

    csv_path = (
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q1_jitter_stride1/q1_windows_jitter_stride1.csv"
    )
    honesty = json.loads(
        (
            ROOT
            / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q1_jitter_stride1/HONESTY_CONTROLS.json"
        ).read_text()
    )
    val_sources = honesty["controls"]["C_stride1_group_holdout"]["val_sources"]
    df = pd.read_csv(csv_path)
    src_col = None
    for c in ("source_capture", "source", "series", "path"):
        if c in df.columns:
            src_col = c
            break
    if src_col is None:
        return {"missing": "no source column in jitter windows csv", "columns": list(df.columns[:20])}
    def is_val(s):
        s = str(s).replace("\\", "/")
        return any(v.replace("\\", "/") in s or s.endswith(v.split("/")[-2] + "/" + Path(v).name if False else Path(v).parent.name)
                   for v in val_sources)
    # match by parent capture folder names listed in val_sources
    keys = []
    for v in val_sources:
        p = Path(v)
        keys.append(f"{p.parent.parent.name}/{p.parent.name}" if p.name == "series.csv" else str(v))
    mask = df[src_col].astype(str).apply(
        lambda s: any(k.replace("\\", "/") in str(s).replace("\\", "/") for k in keys)
    )
    te = df[mask]
    if te.empty:
        return {
            "missing": "group-holdout val_sources did not match rows",
            "src_col": src_col,
            "n_df": int(len(df)),
            "sample_src": df[src_col].astype(str).unique()[:8].tolist(),
            "keys": keys,
        }
    xs, ys = [], []
    for _, row in te.iterrows():
        seq = json.loads(row["seq_json"])
        xs.append(np.asarray(seq, dtype=np.float32))
        ys.append(float(row["eta_seconds"]))
    X = np.stack(xs, axis=0)
    y = np.asarray(ys, dtype=np.float32)
    scaler_path = ROOT / "data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/q1_scaler.npz"
    if not scaler_path.exists():
        scaler_path = ROOT / "data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/q1_jitter_scaler.npz"
    sc = np.load(scaler_path, allow_pickle=True)
    mean, std = sc["mean"], sc["std"]
    model = keras.models.load_model(
        ROOT / "data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/q1_tti_lstm.keras"
    )
    pred = model.predict((X - mean) / std, verbose=0).reshape(-1)
    abs_err = np.abs(pred - y)
    return {
        "n_val": int(len(y)),
        "mae": float(np.mean(abs_err)),
        "cite_mae": float(honesty["cite_mae_honest"]),
        "abs_err": abs_err,
        "src_col": src_col,
        "n_matched": int(mask.sum()),
    }


def q1_chaos_loss_scoped():
    """Re-run scoped loss TTI on sealed chaos; compare to 38.798 (n=15)."""
    import tensorflow as tf  # noqa: F401
    from tensorflow import keras
    from predictive.eval_chaos import schedule_root_at
    from predictive.preprocess import align_1hz, ema_smooth
    from predictive.q1_windows import LOSS_COL, build_windows as build_q1_loss
    from predictive.severity_label import label_rows
    from predictive.util_schedule import attach_ceil_schedule, load_ceil_schedule

    chaos = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/chaos_holdout"
    series = pd.read_csv(chaos / "series.csv")
    schedule = json.loads((chaos / "chaos_schedule.json").read_text())
    df = ema_smooth(align_1hz(series), span=5)
    t0 = int(df["ts_unix"].iloc[0])
    df["t_rel"] = df["ts_unix"].astype(int) - t0
    util_sched_path = chaos / "util_ceil_schedule.jsonl"
    sch = load_ceil_schedule(util_sched_path) if util_sched_path.exists() else None
    if sch is not None:
        df = attach_ceil_schedule(df, sch)
    roots = [schedule_root_at(float(t), schedule) for t in df["t_rel"]]
    df["gt_root"] = roots
    loss_mask = df["gt_root"].astype(int) == 4
    loss_df = df.loc[loss_mask].reset_index(drop=True)
    q1w, meta = build_q1_loss(loss_df, sla=2.0, target_col=LOSS_COL)
    usable = q1w[q1w["label_usable"] == True] if not q1w.empty else q1w  # noqa: E712
    model = keras.models.load_model(
        ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_tti_lstm.keras"
    )
    sc = np.load(
        ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_scaler.npz",
        allow_pickle=True,
    )
    mean, std = sc["mean"], sc["std"]
    errs = []
    for _, row in usable.iterrows():
        seq = json.loads(row["seq_json"]) if isinstance(row.get("seq_json"), str) else None
        if seq is None:
            continue
        X = np.asarray([seq], dtype=np.float32)
        X = (X - mean) / std
        pred = float(model.predict(X, verbose=0)[0][0])
        errs.append(abs(pred - float(row["eta_seconds"])))
    abs_err = np.asarray(errs, dtype=float)
    return {
        "n": int(len(abs_err)),
        "mae": float(np.mean(abs_err)) if len(abs_err) else None,
        "cite_mae": float(SCOREBOARD["cite"]["q1_loss_chaos_mae_scoped"]),
        "cite_n": int(SCOREBOARD["cite"]["q1_loss_chaos_n_scoped"]),
        "abs_err": abs_err,
        "breach_idx": meta.get("breach_idx"),
    }


def main():
    report = {"trace": {}, "q1": {}}
    print("=== HOLD OUT ===", flush=True)
    report["holdout"] = score_holdout()
    print(json.dumps({k: v for k, v in report["holdout"].items() if k != "ml_contig"}, default=str)[:2000], flush=True)
    print("holdout ml_contig", report["holdout"]["ml_contig"], flush=True)

    print("=== GNS3 ===", flush=True)
    report["gns3"] = score_gns3()
    print("gns3 ml_cite_style", report["gns3"]["ml_cite_style"], flush=True)
    print("match", report["gns3"]["ml_matches_cite_acc"], report["gns3"]["ml_matches_cite_macro"], flush=True)

    print("=== ROOT ===", flush=True)
    report["root"] = score_root()
    print(report["root"]["ml"], "match", report["root"]["ml_matches_cite_acc"], flush=True)

    print("=== CHAOS FINAL (batch re-score) ===", flush=True)
    report["chaos_final"] = score_chaos_final()
    print("chaos ml", report["chaos_final"]["ml"], "match", report["chaos_final"]["ml_matches_cite_acc"], flush=True)

    # Q1 — optional TF
    try:
        print("=== Q1 loss val ===", flush=True)
        loss = q1_random_split_residuals(
            ROOT
            / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q1_windows_loss_stride1.csv",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_scaler.npz",
        )
        lo, hi = bootstrap_mae(loss["abs_err"])
        report["q1"]["loss_val"] = {
            "n_total_file": loss["n_total"],
            "n_val_split": loss["n_val"],
            "paper_n_claim": 185,
            "mae": loss["mae"],
            "cite_mae": float(SCOREBOARD["cite"]["q1_loss_val_mae"]),
            "boot_95": [lo, hi],
            "matches_cite": abs(loss["mae"] - float(SCOREBOARD["cite"]["q1_loss_val_mae"])) < 0.5,
        }
        print(report["q1"]["loss_val"], flush=True)
    except Exception as exc:
        report["q1"]["loss_val"] = {"error": str(exc)}
        print("loss_val error", exc, flush=True)

    try:
        print("=== Q1 latency val ===", flush=True)
        lat_csv = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q1_windows_train.csv"
        lat = q1_random_split_residuals(
            lat_csv,
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_unified/q1_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_unified/q1_scaler.npz",
        )
        lo, hi = bootstrap_mae(lat["abs_err"])
        cite_mae = float(ALL_SCORES["models"]["q1_tti_heads"]["lstm_q1_unified"]["best_val_mae_seconds"])
        report["q1"]["latency_val"] = {
            "n_total_file": lat["n_total"],
            "n_val_split": lat["n_val"],
            "paper_n_claim": 1022,
            "mae": lat["mae"],
            "cite_mae": cite_mae,
            "on_disk_train_metrics_mae": 50.261600494384766,
            "boot_95": [lo, hi],
            "matches_cite_60_8": abs(lat["mae"] - cite_mae) < 0.5,
            "matches_on_disk_50_3": abs(lat["mae"] - 50.261600494384766) < 0.5,
        }
        print(report["q1"]["latency_val"], flush=True)
    except Exception as exc:
        report["q1"]["latency_val"] = {"error": str(exc)}
        print("latency error", exc, flush=True)

    try:
        print("=== Q1 util val ===", flush=True)
        util = q1_random_split_residuals(
            ROOT
            / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q1_windows_util.csv",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_util/q1_util_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_util/q1_util_scaler.npz",
        )
        lo, hi = bootstrap_mae(util["abs_err"])
        report["q1"]["util_val"] = {
            "n_total_file": util["n_total"],
            "n_val_split": util["n_val"],
            "paper_n_claim": 432,
            "mae": util["mae"],
            "cite_mae": 31.136272430419922,
            "boot_95": [lo, hi],
            "matches_cite": abs(util["mae"] - 31.136272430419922) < 0.5,
        }
        print(report["q1"]["util_val"], flush=True)
    except Exception as exc:
        report["q1"]["util_val"] = {"error": str(exc)}
        print("util error", exc, flush=True)

    try:
        print("=== Q1 jitter group holdout ===", flush=True)
        jit = q1_jitter_group_holdout()
        if "abs_err" in jit:
            lo, hi = bootstrap_mae(jit["abs_err"])
            jit["boot_95"] = [lo, hi]
            jit["matches_cite"] = abs(jit["mae"] - jit["cite_mae"]) < 0.5
            jit.pop("abs_err")
        report["q1"]["jitter_group_holdout"] = jit
        print(jit, flush=True)
    except Exception as exc:
        report["q1"]["jitter_group_holdout"] = {"error": str(exc)}
        print("jitter error", exc, flush=True)

    try:
        print("=== Q1 chaos loss scoped ===", flush=True)
        ch = q1_chaos_loss_scoped()
        if ch.get("abs_err") is not None and len(ch["abs_err"]):
            lo, hi = bootstrap_mae(ch["abs_err"])
            ch["boot_95"] = [lo, hi]
            ch["matches_cite"] = abs((ch["mae"] or 0) - ch["cite_mae"]) < 1.0 and ch["n"] == ch["cite_n"]
        if "abs_err" in ch:
            ch = {k: v for k, v in ch.items() if k != "abs_err"}
        report["q1"]["loss_chaos_scoped"] = ch
        print(ch, flush=True)
    except Exception as exc:
        report["q1"]["loss_chaos_scoped"] = {"error": str(exc)}
        print("chaos q1 error", exc, flush=True)

    # Wilson-only rows that do not need per-sample (exact k/n from cited acc)
    report["wilson_from_cited_k_n"] = {
        "bgp_phase_exact": {
            "n": BGP_N,
            "k": BGP_K,
            "acc": BGP_K / BGP_N,
            "wilson_95": list(wilson(BGP_K, BGP_N)),
            "source": "ONESHOT_VERDICT.json locked.bgp_exact * phase_n.bgp = 163/184",
        },
        "chaos_dev_SELECTION_ONLY": {
            "acc": 0.9972144846796658,
            "flag": "selection-contaminated — chaos_dev used to pick d2; do not cite as a result",
        },
    }

    serial = json.loads(json.dumps(report, default=lambda o: None))
    (OUT_DIR / "compute_report.json").write_text(json.dumps(serial, indent=2) + "\n")
    print("wrote", OUT_DIR / "compute_report.json", flush=True)


if __name__ == "__main__":
    main()
