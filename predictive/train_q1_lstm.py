"""Minimal Q1 LSTM trainer (optional TensorFlow).

Usage:
  python -m predictive.train_q1_lstm --data data/deca/predictive/captures/<stamp>/q1_windows_train.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def load_xy(paths: list[Path], seq_len: int | None = None):
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        raise SystemExit(f"no rows in {paths}")
    df = pd.concat(frames, ignore_index=True)
    xs, ys = [], []
    for _, row in df.iterrows():
        seq = json.loads(row["seq_json"])
        arr = np.asarray(seq, dtype=np.float32)
        if seq_len is not None and arr.shape[0] != seq_len:
            continue
        xs.append(arr)
        ys.append(float(row["eta_seconds"]))
    X = np.stack(xs, axis=0)
    y = np.asarray(ys, dtype=np.float32)
    return X, y, json.loads(df.iloc[0]["seq_feature_cols"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data",
        nargs="+",
        required=True,
        help="one or more q1_windows_train.csv paths",
    )
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--val-frac", type=float, default=0.2)
    args = ap.parse_args()

    try:
        import tensorflow as tf
        from tensorflow import keras
    except ImportError as exc:
        raise SystemExit(
            "TensorFlow not installed. pip install tensorflow in .venv-predictive"
        ) from exc

    data_paths = [Path(p).resolve() for p in args.data]
    out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else data_paths[0].parent / "lstm_q1"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    X, y, feat_cols = load_xy(data_paths)
    n = len(X)
    if n < 10:
        raise SystemExit(f"need ≥10 windows, got {n} — run more/longer campaigns")

    rng = np.random.default_rng(42)
    idx = rng.permutation(n)
    n_val = max(1, int(n * args.val_frac))
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]

    # Standardize per-feature using train set
    flat = X_train.reshape(-1, X_train.shape[-1])
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std[std < 1e-6] = 1.0
    X_train = (X_train - mean) / std
    X_val = (X_val - mean) / std

    model = keras.Sequential(
        [
            keras.layers.Input(shape=(X.shape[1], X.shape[2])),
            keras.layers.LSTM(32),
            keras.layers.Dense(16, activation="relu"),
            keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])
    cb = [
        keras.callbacks.EarlyStopping(
            monitor="val_mae", patience=8, restore_best_weights=True
        )
    ]
    hist = model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=args.epochs,
        batch_size=min(16, len(X_train)),
        callbacks=cb,
        verbose=1,
    )

    model_path = out_dir / "q1_tti_lstm.keras"
    model.save(model_path)
    np.savez(out_dir / "q1_scaler.npz", mean=mean, std=std, feature_cols=np.array(feat_cols))
    metrics = {
        "n_train": int(len(X_train)),
        "n_val": int(len(X_val)),
        "n_total": int(n),
        "sources": [str(p) for p in data_paths],
        "best_val_mae": float(min(hist.history.get("val_mae", [float("nan")]))),
        "model": str(model_path),
    }
    (out_dir / "train_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
