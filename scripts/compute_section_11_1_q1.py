"""Q1 residual bootstrap. Isolated so a TF crash doesn't lose Q2 baseline work."""
from __future__ import annotations

import json
import os

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/section_11_1_ci"
N_BOOT = 2000
SEED = 42


def boot_mae(err):
    rng = np.random.default_rng(SEED)
    n = len(err)
    stats = np.empty(N_BOOT)
    for i in range(N_BOOT):
        stats[i] = float(np.mean(err[rng.integers(0, n, n)]))
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return float(lo), float(hi), float(np.mean(err))


def random_split_err(csv_path, keras_path, scaler_path, val_frac=0.2):
    from tensorflow import keras

    df = pd.read_csv(csv_path)
    xs, ys = [], []
    for _, row in df.iterrows():
        arr = np.asarray(json.loads(row["seq_json"]), dtype=np.float32)
        xs.append(arr)
        ys.append(float(row["eta_seconds"]))
    X = np.stack(xs, axis=0)
    y = np.asarray(ys, dtype=np.float32)
    n = len(X)
    rng = np.random.default_rng(42)
    idx = rng.permutation(n)
    n_val = max(1, int(n * val_frac))
    val_idx = idx[:n_val]
    sc = np.load(scaler_path, allow_pickle=True)
    mean, std = sc["mean"], sc["std"]
    model = keras.models.load_model(keras_path, compile=False)
    pred = model.predict((X[val_idx] - mean) / std, verbose=0).reshape(-1)
    err = np.abs(pred - y[val_idx])
    return n, n_val, err


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}

    jobs = {
        "loss": (
            ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q1_windows_loss_stride1.csv",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_scaler.npz",
            7.0916428565979,
            185,
        ),
        "latency": (
            ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q1_windows_train.csv",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_unified/q1_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_unified/q1_scaler.npz",
            60.79361343383789,
            1022,
        ),
        "util": (
            ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q1_windows_util.csv",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_util/q1_util_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_util/q1_util_scaler.npz",
            31.136272430419922,
            432,
        ),
        "jitter_random_leaky": (
            ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q1_jitter_stride1/q1_windows_jitter_stride1.csv",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/q1_tti_lstm.keras",
            ROOT / "data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/q1_scaler.npz",
            11.316802024841309,
            1026,
        ),
    }
    for name, (csv_p, keras_p, sc_p, cite, paper_n) in jobs.items():
        print("start", name, flush=True)
        try:
            if not sc_p.exists() and name.startswith("jitter"):
                sc_p = ROOT / "data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/q1_jitter_scaler.npz"
            n_tot, n_val, err = random_split_err(csv_p, keras_p, sc_p)
            lo, hi, mae = boot_mae(err)
            results[name] = {
                "n_total_file": n_tot,
                "n_val": n_val,
                "paper_n_claim": paper_n,
                "mae": mae,
                "cite_mae": cite,
                "boot_95": [lo, hi],
                "matches_cite": abs(mae - cite) < 0.75,
            }
            np.save(OUT / f"q1_{name}_val_abserr.npy", err)
            print(name, results[name], flush=True)
        except Exception as exc:
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            print("fail", name, exc, flush=True)

    (OUT / "q1_ci.json").write_text(json.dumps(results, indent=2) + "\n")
    print("wrote q1_ci.json")


if __name__ == "__main__":
    main()
