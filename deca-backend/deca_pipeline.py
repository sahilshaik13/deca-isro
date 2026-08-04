import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

class DECAPipeline:
    def __init__(self, models_dir="./models", feature_cols=None, seq_len=40):
        self.models_dir = Path(models_dir)
        manifest_path = self.models_dir / "manifest.json"
        self.manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        self.feature_cols = feature_cols or self.manifest.get("feature_columns", [])
        self.seq_len = seq_len

        # Load models
        self.iso = self._load("isolation_forest.pkl", joblib.load)
        self.scaler = self._load("feature_scaler.pkl", joblib.load)
        self.calibrator = self._load("confidence_calibrator.pkl", joblib.load)
        self.lstm = self._load_lstm()

        self.prophet_models = {}
        for p in self.models_dir.glob("prophet_*.pkl"):
            metric = p.stem.replace("prophet_", "")
            self.prophet_models[metric] = joblib.load(p)

    def _load(self, filename, loader):
        path = self.models_dir / filename
        if not path.exists():
            return None
        try:
            return loader(path)
        except Exception as e:
            print(f"Warning: failed to load {filename}: {e}")
            return None

    def _load_lstm(self):
        for filename in ("fault_lstm_v1.keras", "fault_lstm_v1.h5"):
            path = self.models_dir / filename
            if not path.exists():
                continue
            try:
                return tf.keras.models.load_model(path, compile=False)
            except Exception as e:
                print(f"Warning: failed to load {filename}: {e}")
        return None

    def source_breakdown(self):
        return self.manifest.get("row_counts_by_source", {})

    def predict(self, feature_window_df):
        if not self.feature_cols or len(feature_window_df) == 0:
            return self._empty_result("no feature columns or empty input")

        # Align live rows to the training schema (missing MPLS/synthetic cols -> 0).
        aligned = (
            feature_window_df.reindex(columns=self.feature_cols, fill_value=0.0)
            .fillna(0.0)
            .astype(float)
        )
        X_latest = aligned.iloc[[-1]]

        # Anomaly score
        anomaly_score = float(self.iso.decision_function(X_latest)[0]) if self.iso is not None else 0.0

        # Calibrated confidence
        if self.calibrator is not None:
            confidence = float(self.calibrator.predict_proba(X_latest)[:, 1][0])
        else:
            confidence = float(1 / (1 + np.exp(anomaly_score)))

        # Time to breach via LSTM
        time_to_impact = None
        if self.lstm is not None and self.scaler is not None and len(aligned) >= self.seq_len:
            seq_window = aligned.iloc[-self.seq_len :]
            seq = self.scaler.transform(seq_window)
            seq = seq.reshape(1, self.seq_len, len(self.feature_cols))
            time_to_impact = float(self.lstm.predict(seq, verbose=0)[0][0])

        # Feature attribution proxy
        z = (X_latest.iloc[0] - X_latest.iloc[0].mean()) / (X_latest.iloc[0].std() + 1e-6)
        top = z.abs().sort_values(ascending=False).head(3)
        total = top.sum() if top.sum() > 0 else 1.0
        contributing_signals = {k: round(float(v / total), 2) for k, v in top.items()}

        predicted_issue = "anomaly_detected" if confidence > 0.5 else "normal"

        return {
            "predicted_issue": predicted_issue,
            "confidence_score": round(confidence, 2),
            "time_to_impact_minutes": round(time_to_impact, 1) if time_to_impact is not None else None,
            "root_cause": "see contributing_signals",
            "affected_scope": [],
            "contributing_signals": contributing_signals,
            "recommended_actions": [],
            "trained_on_sources": self.source_breakdown(),
        }

    @staticmethod
    def _empty_result(reason):
        return {
            "predicted_issue": "INSUFFICIENT_CONTEXT", "confidence_score": 0.0,
            "time_to_impact_minutes": None, "root_cause": reason,
            "affected_scope": [], "contributing_signals": {}, "recommended_actions": [],
        }