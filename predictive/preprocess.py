"""Shared time-series preprocessing for Q1/Q2 training.

1. Align to 1 Hz + linear interpolate missing samples
2. EMA smooth on drift metrics (not cumulative counters)
3. Optional z-score scale (fit on train, persist scaler.npz)
4. Q2 tabular balance helpers (downsample majority / optional SMOTE)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .q2_windows import CUMULATIVE_COLS, FEATURE_COLS

SMOOTH_COLS = {
    "latency_gre_ms",
    "latency_eth0_ms",
    "jitter_gre_ms",
    "loss_gre_pct",
    "util_gre_mbps",
    "path_asymmetry_ms",
    "path_asymmetry",
    "cpu_usage_system",
    "cpu_usage_user",
    "mem_used_percent",
    "ipsec_rekey_events_1h",
}


def align_1hz(df: pd.DataFrame, ts_col: str = "ts_unix") -> pd.DataFrame:
    if ts_col not in df.columns:
        raise ValueError(f"missing {ts_col}")
    d = df.sort_values(ts_col).drop_duplicates(ts_col, keep="last").copy()
    d[ts_col] = d[ts_col].astype(int)
    t0, t1 = int(d[ts_col].iloc[0]), int(d[ts_col].iloc[-1])
    idx = pd.RangeIndex(t0, t1 + 1, step=1, name=ts_col)
    d = d.set_index(ts_col).reindex(idx)
    num_cols = [c for c in d.columns if pd.api.types.is_numeric_dtype(d[c])]
    d[num_cols] = d[num_cols].interpolate(method="linear", limit_direction="both")
    d = d.reset_index()
    # drop rows still all-NaN on feature cols
    feat = [c for c in FEATURE_COLS if c in d.columns]
    if feat:
        d = d.dropna(subset=feat, how="all").reset_index(drop=True)
    return d


def ema_smooth(df: pd.DataFrame, span: int = 5) -> pd.DataFrame:
    d = df.copy()
    # PS13-O2.2: derive path asymmetry before EMA so it is smoothed with peers
    if "latency_gre_ms" in d.columns and "latency_eth0_ms" in d.columns:
        gre = d["latency_gre_ms"].astype(float)
        eth = d["latency_eth0_ms"].astype(float)
        d["path_asymmetry_ms"] = (gre - eth).abs()
    for c in SMOOTH_COLS:
        if c in d.columns and c not in CUMULATIVE_COLS:
            d[c] = d[c].astype(float).ewm(span=span, adjust=False).mean()
    return d


def preprocess_series(
    df: pd.DataFrame,
    *,
    ema_span: int = 5,
    scale: bool = False,
    mean: np.ndarray | None = None,
    std: np.ndarray | None = None,
    scale_cols: list[str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    d = align_1hz(df)
    d = ema_smooth(d, span=ema_span)
    meta: dict = {"n_rows": int(len(d)), "ema_span": ema_span, "scaled": False}
    cols = scale_cols or [c for c in FEATURE_COLS if c in d.columns and c not in CUMULATIVE_COLS]
    if scale:
        if mean is None or std is None:
            mean = d[cols].astype(float).mean().to_numpy()
            std = d[cols].astype(float).std().replace(0, 1.0).to_numpy()
            std = np.where(std < 1e-6, 1.0, std)
        for i, c in enumerate(cols):
            d[c] = (d[c].astype(float) - float(mean[i])) / float(std[i])
        meta["scaled"] = True
        meta["scale_cols"] = cols
        meta["mean"] = [float(x) for x in mean]
        meta["std"] = [float(x) for x in std]
    return d, meta


def fit_zscore(dfs: list[pd.DataFrame]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    cols = [c for c in FEATURE_COLS if c not in CUMULATIVE_COLS]
    present = [c for c in cols if all(c in d.columns for d in dfs)]
    stacked = pd.concat([d[present].astype(float) for d in dfs], ignore_index=True)
    mean = stacked.mean().to_numpy()
    std = stacked.std().to_numpy()
    std = np.where(std < 1e-6, 1.0, std)
    return mean, std, present


def save_scaler(path: Path, mean: np.ndarray, std: np.ndarray, cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, mean=mean, std=std, feature_cols=np.array(cols))


def load_scaler(path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    data = np.load(path, allow_pickle=True)
    return (
        data["mean"].astype(np.float64),
        data["std"].astype(np.float64),
        [str(c) for c in data["feature_cols"].tolist()],
    )


def balance_windows(
    df: pd.DataFrame,
    *,
    label_col: str = "severity",
    max_per_class: int | None = None,
    smote: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    """Downsample majority classes; optionally SMOTE minority tabular rows."""
    if label_col not in df.columns:
        label_col = "label"
    counts = df[label_col].value_counts()
    if max_per_class is None:
        # match median class size (cap majority)
        max_per_class = int(max(counts.median(), counts.min()))
    parts = []
    rng = np.random.default_rng(seed)
    for lab, n in counts.items():
        sub = df[df[label_col] == lab]
        if len(sub) > max_per_class:
            idx = rng.choice(len(sub), size=max_per_class, replace=False)
            sub = sub.iloc[idx]
        parts.append(sub)
    out = pd.concat(parts, ignore_index=True)

    if smote:
        try:
            from imblearn.over_sampling import SMOTE
        except ImportError as exc:
            raise SystemExit("imblearn required for --smote: pip install imbalanced-learn") from exc
        skip = {
            "window_id",
            "start_idx",
            "end_idx",
            "start_ts",
            "end_ts",
            "label",
            "label_name",
            "severity",
            "severity_name",
            "source_capture",
            "root_label",
        }
        feat_cols = [
            c
            for c in out.columns
            if c not in skip and pd.api.types.is_numeric_dtype(out[c])
        ]
        X = out[feat_cols].astype(float).fillna(0.0).to_numpy()
        y = out[label_col].to_numpy()
        # SMOTE needs ≥2 neighbors; skip tiny classes
        min_c = int(pd.Series(y).value_counts().min())
        k = max(1, min(5, min_c - 1))
        if k >= 1 and len(np.unique(y)) > 1:
            X2, y2 = SMOTE(random_state=seed, k_neighbors=k).fit_resample(X, y)
            out = pd.DataFrame(X2, columns=feat_cols)
            out[label_col] = y2
    return out.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", required=True, help="input series.csv")
    ap.add_argument("--out", required=True, help="output cleaned series.csv")
    ap.add_argument("--ema-span", type=int, default=5)
    ap.add_argument("--scale", action="store_true")
    ap.add_argument("--scaler", default="", help="load/save scaler.npz path")
    ap.add_argument("--fit-scaler", action="store_true", help="fit scaler from this file")
    args = ap.parse_args()

    df = pd.read_csv(args.capture)
    mean = std = None
    cols = None
    if args.scaler and Path(args.scaler).exists() and not args.fit_scaler:
        mean, std, cols = load_scaler(Path(args.scaler))
    d, meta = preprocess_series(
        df,
        ema_span=args.ema_span,
        scale=args.scale or bool(mean is not None),
        mean=mean,
        std=std,
        scale_cols=cols,
    )
    if args.fit_scaler and args.scaler:
        m, s, c = fit_zscore([align_1hz(ema_smooth(df, args.ema_span))])
        save_scaler(Path(args.scaler), m, s, c)
        meta["scaler"] = args.scaler
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(out, index=False)
    meta["wrote"] = str(out)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
