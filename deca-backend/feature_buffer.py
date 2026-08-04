"""Streaming feature engineering for live Prometheus samples."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import config


class LiveFeatureBuffer:
    """Maintain a rolling window of engineered features for DECAPipeline."""

    def __init__(self, maxlen: int | None = None) -> None:
        self.maxlen = maxlen or max(config.SEQ_LEN * 3, 120)
        self._raw: deque[dict] = deque(maxlen=self.maxlen)
        self._features: deque[dict] = deque(maxlen=self.maxlen)

    def seed_from_dataframe(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            self._features.append(row.to_dict())

    def add_raw_sample(self, timestamp: str, raw: dict[str, float]) -> dict | None:
        self._raw.append({"timestamp": timestamp, **raw})
        if len(self._raw) < 5:
            return None
        feature_row = self._engineer_latest()
        if feature_row:
            self._features.append(feature_row)
        return feature_row

    def _engineer_latest(self) -> dict | None:
        df = pd.DataFrame(list(self._raw))
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()

        step = config.FEATURE_STEP_SECONDS
        window = f"{config.FEATURE_WINDOW_MINUTES}min"
        metric_cols = [c for c in df.columns if c in (
            "ifInOctets", "ifOutOctets", "packet_loss_pct", "jitter_ms", "bgp_update_rate"
        )]
        if not metric_cols:
            return None

        parts = []
        for metric in metric_cols:
            series = df[metric].astype(float)
            g = series.to_frame("value")
            g[f"{metric}_slope"] = g["value"].diff() / step
            g[f"{metric}_rolling_std"] = g["value"].rolling(window, min_periods=3).std()
            g[f"{metric}_rolling_mean"] = g["value"].rolling(window, min_periods=3).mean()
            g[f"{metric}_accel"] = g[f"{metric}_slope"].diff() / step
            parts.append(g[[c for c in g.columns if c != "value"]])

        if not parts:
            return None

        features = pd.concat(parts, axis=1).dropna(how="any")
        if features.empty:
            return None
        row = features.iloc[-1].to_dict()
        row["run_id"] = "live_rpi_network"
        row["source"] = "network"
        return row

    def to_prediction_frame(self) -> pd.DataFrame:
        if not self._features:
            return pd.DataFrame()
        return pd.DataFrame(list(self._features))

    @property
    def ready(self) -> bool:
        return len(self._features) >= config.SEQ_LEN
