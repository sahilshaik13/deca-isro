"""Prometheus helpers for DECA predictive captures (dual Flow 2).

Pi fabric  → host Prom :9090 (DECA_PROM_URL_PI)
GNS3 fabric → compose Prom :9091 (DECA_PROM_URL_GNS3)
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import pandas as pd
import requests

DEFAULT_PROM_PI = "http://127.0.0.1:9090"
DEFAULT_PROM_GNS3 = "http://127.0.0.1:9091"
# Backward-compatible alias (Pi). Prefer prom_url_for_fabric().
DEFAULT_PROM = DEFAULT_PROM_PI

# Q1 golden signals (prefer edge PE probes via Kafka bridge).
Q1_QUERIES: dict[str, str] = {
    "latency_gre_ms": 'sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",host="station1",path="gre",src="edge"}',
    "latency_eth0_ms": 'sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",host="station1",path="eth0",src="edge"}',
    "jitter_gre_ms": 'sdwan_path_jitter_ms{job="deca_kafka_telemetry_bridge",host="station1",path="gre"}',
    "loss_gre_pct": 'sdwan_path_loss_pct{job="deca_kafka_telemetry_bridge",host="station1",path="gre",src="edge"}',
    # CAPTURE_CONTRACT: ceiling util = PE eth0 TX @1Hz (HTB egress). Never max(gre|eth0).
    # Column name util_gre_mbps kept for schema; semantics = eth0 post-HTB egress Mbps.
    "util_gre_mbps": 'sdwan_path_util_mbps{job="deca_kafka_telemetry_bridge",host="station1",path="eth0",src="edge"}',
    "net_bytes_recv_eth0": 'interface_net_bytes_recv{job="deca_kafka_telemetry_bridge",host="station1",ifName="eth0"}',
    "net_bytes_sent_eth0": 'interface_net_bytes_sent{job="deca_kafka_telemetry_bridge",host="station1",ifName="eth0"}',
}

# Q2 extras (captured alongside for later classifier training).
Q2_QUERIES: dict[str, str] = {
    "cpu_usage_system": 'cpu_usage_system{job="deca_kafka_telemetry_bridge",host="station1"}',
    "cpu_usage_user": 'cpu_usage_user{job="deca_kafka_telemetry_bridge",host="station1"}',
    "mem_used_percent": 'mem_used_percent{job="deca_kafka_telemetry_bridge",host="station1"}',
    "bgp_flap_count": 'bgp_flap_count{job="deca_kafka_telemetry_bridge",host="station1"}',
    "netflow_bulk_bytes": 'netflow_bulk_bytes{job="deca_kafka_telemetry_bridge",host="station1"}',
    "netflow_voice_bytes": 'netflow_voice_bytes{job="deca_kafka_telemetry_bridge",host="station1"}',
    # PS13 rekey anomaly (edge exporter via Kafka bridge)
    "ipsec_rekey_events_1h": 'ipsec_rekey_events_1h{job="deca_kafka_telemetry_bridge",host="station1"}',
    "ipsec_rekey_anomaly": 'ipsec_rekey_anomaly{job="deca_kafka_telemetry_bridge",host="station1"}',
    # Live HTB 1:15 ceil (deca-htb-payload-ceil.sh) — Q2 util 5A/5B feature.
    "htb_payload_ceil_mbps": 'htb_payload_ceil_mbps{job="deca_kafka_telemetry_bridge",host="station1"}',
    # CAPTURE_CONTRACT: edge 1Hz asymmetry only — never controller 5s hold.
    "path_asymmetry": 'path_asymmetry{job="deca_kafka_telemetry_bridge",host="station1",src="edge"}',
}

# On GNS3, path_asymmetry is exported from the fabric exporter (derived GRE−eth0).
_PATH_ASYM_GNS3 = 'path_asymmetry{job="deca_gns3_fabric",host="gns3-pe1",fabric="gns3"}'
# GNS3 util: twin exporter publishes path="gre" (chaos_state util_gre_mbps).
# CAPTURE_CONTRACT eth0 preference is Pi-side; GNS3 twin keeps gre gauge name parity.
_UTIL_GNS3 = 'sdwan_path_util_mbps{job="deca_gns3_fabric",host="gns3-pe1",path="gre",fabric="gns3"}'


def _fabric_from_env() -> str:
    """pi | gns3 — prefer DECA_FABRIC, else active_fabric.json when available."""
    raw = os.environ.get("DECA_FABRIC", "").strip().lower()
    if raw in ("pi", "gns3"):
        return raw
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        backend = str(root / "deca-backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        import fabric as fabric_mod  # type: ignore

        return fabric_mod.get_active()
    except Exception:  # noqa: BLE001
        return "pi"


def prom_url_for_fabric(fabric: str | None = None) -> str:
    """Base Prometheus URL for the active (or given) fabric.

    Override with DECA_PROM_URL_PI / DECA_PROM_URL_GNS3.
    Legacy DECA_PROM_URL still wins for Pi when DECA_PROM_URL_PI is unset.
    """
    fab = (fabric or _fabric_from_env()).strip().lower()
    if fab == "gns3":
        return os.environ.get("DECA_PROM_URL_GNS3", DEFAULT_PROM_GNS3).rstrip("/")
    return os.environ.get(
        "DECA_PROM_URL_PI",
        os.environ.get("DECA_PROM_URL", DEFAULT_PROM_PI),
    ).rstrip("/")


def with_fabric_label(promql: str, fabric: str | None = None) -> str:
    """Retarget PromQL for the active fabric.

    Pi: kafka bridge + station1 on :9090.
    GNS3: job=deca_gns3_fabric, host=gns3-pe1 on :9091 (query via prom_url_for_fabric).
    """
    fab = (fabric or _fabric_from_env()).strip().lower()
    if fab != "gns3":
        return promql
    # Dedicated twin gauges (CAPTURE_CONTRACT)
    if promql.strip().startswith("path_asymmetry{"):
        return _PATH_ASYM_GNS3
    if 'sdwan_path_util_mbps{' in promql and 'path="eth0"' in promql:
        return _UTIL_GNS3
    q = promql
    q = q.replace('job="deca_kafka_telemetry_bridge"', 'job="deca_gns3_fabric"')
    q = q.replace('host="station1"', 'host="gns3-pe1"')
    # Drop src="edge" on twin if exporter omits it
    q = q.replace(',src="edge"', "").replace('src="edge",', "")
    if 'fabric="' not in q and "fabric='" not in q:
        m = re.search(r"\{([^}]*)\}", q)
        if m:
            inner = m.group(1).strip()
            new_inner = f'{inner},fabric="gns3"' if inner else 'fabric="gns3"'
            q = q[: m.start()] + "{" + new_inner + "}" + q[m.end() :]
    return q


def active_queries() -> dict[str, str]:
    """Q1+Q2 queries filtered for the active fabric."""
    fab = _fabric_from_env()
    return {
        name: with_fabric_label(q, fab)
        for name, q in {**Q1_QUERIES, **Q2_QUERIES}.items()
    }


def query_instant(prom_url: str, promql: str, timeout: float = 3.0) -> float | None:
    try:
        resp = requests.get(
            f"{prom_url.rstrip('/')}/api/v1/query",
            params={"query": promql},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        results = payload.get("data", {}).get("result", [])
        if not results:
            return None
        return float(results[0]["value"][1])
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError):
        return None


def query_range(
    prom_url: str,
    promql: str,
    start: float,
    end: float,
    step: str = "1s",
    timeout: float = 30.0,
) -> list[tuple[float, float]]:
    """Return list of (unix_ts, value) from query_range (first series only)."""
    try:
        resp = requests.get(
            f"{prom_url.rstrip('/')}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        results = payload.get("data", {}).get("result", [])
        if not results:
            return []
        out: list[tuple[float, float]] = []
        for ts, val in results[0].get("values", []):
            try:
                out.append((float(ts), float(val)))
            except (TypeError, ValueError):
                continue
        return out
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError):
        return []


def sample_bundle(
    prom_url: str | None = None,
    queries: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One instant sample of all configured queries (fabric Prom if url omitted)."""
    url = (prom_url or prom_url_for_fabric()).rstrip("/")
    q = queries or active_queries()
    row: dict[str, Any] = {"ts_unix": time.time()}
    for name, promql in q.items():
        row[name] = query_instant(url, promql)
    return row


def range_bundle_to_frame(
    prom_url: str,
    start: float,
    end: float,
    step: str = "1s",
    queries: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Align multiple Prom range queries onto a 1 Hz frame (outer join on ts)."""
    q = queries or active_queries()
    frames: list[pd.DataFrame] = []
    for name, promql in q.items():
        pts = query_range(prom_url, promql, start, end, step=step)
        if not pts:
            continue
        df = pd.DataFrame(pts, columns=["ts_unix", name])
        df["ts_unix"] = df["ts_unix"].round().astype(int)
        frames.append(df.drop_duplicates("ts_unix", keep="last"))
    if not frames:
        return pd.DataFrame()
    out = frames[0]
    for df in frames[1:]:
        out = out.merge(df, on="ts_unix", how="outer")
    return out.sort_values("ts_unix").reset_index(drop=True)
