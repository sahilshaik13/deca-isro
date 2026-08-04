"""Orchestrates live Prometheus feed, feature buffer, and ML predictions."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import pandas as pd

import config
from deca_pipeline import DECAPipeline
from feature_buffer import LiveFeatureBuffer
from prometheus_feed import fetch_live_network, finite_float, raw_to_display


class TelemetryService:
    def __init__(self, pipeline: DECAPipeline) -> None:
        self.pipeline = pipeline
        self.feature_buffer = LiveFeatureBuffer()
        self.history: deque[dict[str, Any]] = deque(maxlen=config.TELEMETRY_HISTORY_LEN)
        self._parquet_cursor = 0
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0
        self._cache_ttl_sec = 2.5
        self._seed_feature_buffer()

    def _seed_feature_buffer(self) -> None:
        if not config.DATASET_PATH.is_file():
            return
        try:
            df = pd.read_parquet(config.DATASET_PATH)
            network = df[df["source"] == "network"]
            if network.empty:
                network = df[df["source"] == "synthetic"].tail(config.SEQ_LEN * 2)
            seed = network.tail(config.SEQ_LEN * 2)
            self.feature_buffer.seed_from_dataframe(seed)
        except Exception as exc:
            print(f"Warning: could not seed feature buffer from dataset: {exc}")

    def _fallback_from_dataset(self) -> dict[str, Any] | None:
        if not config.DATASET_PATH.is_file():
            return None
        try:
            df = pd.read_parquet(config.DATASET_PATH)
            if df.empty:
                return None
            start = self._parquet_cursor
            end = start + 1
            if end > len(df):
                self._parquet_cursor = 0
                start = 0
                end = 1
            row = df.iloc[start]
            self._parquet_cursor = end

            display = {
                "network_throughput_in": finite_float(row.get("ifInOctets_rolling_mean", 0)) * 8 / 1e6,
                "network_throughput_out": finite_float(row.get("ifOutOctets_rolling_mean", 0)) * 8 / 1e6,
                "link_jitter": finite_float(row.get("jitter_ms_rolling_mean", 0)),
                "packet_loss": finite_float(row.get("packet_loss_pct_rolling_mean", 0)),
                "routing_updates": finite_float(row.get("bgp_update_rate_rolling_mean", 0)),
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return {
                "timestamp": display["timestamp"],
                "source": "dataset_fallback",
                "prometheus_reachable": False,
                "stations": [
                    {"id": s, "host": s, "status": "offline", "metrics": {}}
                    for s in config.RPI_STATIONS
                ],
                "raw": None,
                "display": display,
            }
        except Exception:
            return None

    def poll(self) -> dict[str, Any]:
        now = time.time()
        if self._cache is not None and (now - self._cache_at) < self._cache_ttl_sec:
            return self._cache

        live = fetch_live_network()
        source = live["source"]

        if live.get("raw"):
            raw = live["raw"]
            self.feature_buffer.add_raw_sample(live["timestamp"], raw)
            display = raw_to_display(raw, live["timestamp"])
        else:
            fallback = self._fallback_from_dataset()
            if fallback:
                live = fallback
                display = fallback["display"]
                source = fallback["source"]
            else:
                display = {
                    "network_throughput_in": 0.0,
                    "network_throughput_out": 0.0,
                    "link_jitter": 0.0,
                    "packet_loss": 0.0,
                    "routing_updates": 0.0,
                    "cpu_usage": 0.0,
                    "memory_usage": 0.0,
                    "timestamp": live["timestamp"],
                }

        self.history.append(display)

        feature_df = self.feature_buffer.to_prediction_frame()
        if self.feature_buffer.ready and not feature_df.empty:
            try:
                prediction = self.pipeline.predict(feature_df)
            except Exception as exc:
                print(f"Warning: ML prediction failed: {exc}")
                prediction = self.pipeline._empty_result("prediction error")
        else:
            prediction = self.pipeline._empty_result("insufficient feature window")

        result = {
            "success": True,
            "source": source,
            "prometheus_reachable": live.get("prometheus_reachable", False),
            "stations": live.get("stations", []),
            "metrics": display,
            "history": list(self.history),
            "prediction": prediction,
            "last_updated": display["timestamp"],
        }
        self._cache = result
        self._cache_at = time.time()
        return result
