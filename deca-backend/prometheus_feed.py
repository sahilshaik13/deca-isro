"""Pull live metrics from Prometheus for DECA RPi edge stations."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

import numpy as np
import requests

import config

_STATION_HOST_RE = re.compile(r"^station(\d+)$", re.IGNORECASE)


def finite_float(value: float | None, default: float = 0.0) -> float:
    """Coerce to float and replace NaN/Inf so JSON serialization succeeds."""
    try:
        number = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def sanitize_for_json(obj: Any) -> Any:
    """Recursively replace non-finite floats before FastAPI serializes the response."""
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(value) for value in obj]
    if isinstance(obj, float):
        return finite_float(obj)
    if isinstance(obj, (np.floating, np.integer)):
        return finite_float(float(obj))
    return obj


def _iface_clause(pattern: str | None = None) -> str:
    """Build PromQL interface filter from a pattern (regex or exact name)."""
    iface = pattern if pattern is not None else (config.THROUGHPUT_INTERFACE_REGEX or config.EDGE_INTERFACE)
    if not iface:
        return ""
    if "|" in iface or ".*" in iface or iface.startswith("^"):
        return f'interface=~"{iface}",'
    return f'interface="{iface}",'


def _prom_base() -> str:
    """Active-fabric Prometheus URL (:9090 Pi / :9091 GNS3)."""
    try:
        import fabric as fabric_mod

        return fabric_mod.prom_url_for().rstrip("/")
    except Exception:
        return (config.PROMETHEUS_URL or "http://127.0.0.1:9090").rstrip("/")


def _prom_query(promql: str, base: str | None = None) -> float | None:
    url = (base or _prom_base()).rstrip("/")
    try:
        resp = requests.get(
            f"{url}/api/v1/query",
            params={"query": promql},
            timeout=2,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            return None
        results = payload.get("data", {}).get("result", [])
        if not results:
            return None
        value = float(results[0]["value"][1])
        return value if math.isfinite(value) else None
    except (requests.RequestException, ValueError, TypeError, IndexError, KeyError):
        return None


def _station_instance(station: str) -> str | None:
    """Map station1 -> 192.168.50.10:9273 (DECA lab addressing)."""
    match = _STATION_HOST_RE.match(station)
    if not match:
        return None
    station_num = int(match.group(1))
    return f"192.168.50.{station_num * 10}:9273"


def _station_query_filters(station: str) -> list[str]:
    """Prometheus label filters — host name first, then instance IP (station2/3 use host=ubuntu)."""
    filters = [f'host="{station}"']
    instance = _station_instance(station)
    if instance:
        ip = instance.split(":")[0]
        filters.extend(
            [
                f'instance="{instance}"',
                f'instance=~"{re.escape(ip)}.*"',
            ]
        )
    return filters


def _station_host_query(station: str, metric_expr: str, iface_pattern: str | None = None) -> float | None:
    iface = _iface_clause(iface_pattern)
    jobs = list(dict.fromkeys([config.PROMETHEUS_JOB, *config.PROMETHEUS_JOBS]))
    for job in jobs:
        for filt in _station_query_filters(station):
            promql = metric_expr % {"job": job, "iface": iface, "filt": filt}
            value = _prom_query(promql)
            if value is not None:
                return value
    return None


def _rate_window() -> str:
    return config.PROMETHEUS_RATE_WINDOW or "1m"


def _ping_metric_for_station(station: str, metric: str) -> float | None:
    templates = {
        "jitter_ms": 'avg(ping_standard_deviation_ms{job="%(job)s",%(filt)s})',
        "packet_loss_pct": 'avg(ping_percent_packet_loss{job="%(job)s",%(filt)s})',
        "latency_ms": 'avg(ping_average_response_ms{job="%(job)s",%(filt)s})',
    }
    template = templates.get(metric)
    if not template:
        return None

    for job in dict.fromkeys([config.PROMETHEUS_JOB, *config.PROMETHEUS_JOBS]):
        for filt in _station_query_filters(station):
            promql = template % {"job": job, "filt": filt}
            value = _prom_query(promql)
            if value is not None:
                return value
    return None


def _interface_loss_for_station(station: str, iface_pattern: str) -> float | None:
    win = _rate_window()
    template = (
        f'100 * sum(rate(net_drop_out{{job="%(job)s",%(iface)s%(filt)s}}[{win}]))'
        f' / (sum(rate(net_packets_sent{{job="%(job)s",%(iface)s%(filt)s}}[{win}])) + 1e-9)'
    )
    return _station_host_query(station, template, iface_pattern)


def _loss_for_station(station: str) -> float | None:
    """Max of eth0 drop rate, mission NIC drops, and ICMP ping loss."""
    primary = config.THROUGHPUT_INTERFACE_REGEX or config.EDGE_INTERFACE
    candidates: list[float] = []
    for pattern in ("eth0", primary):
        if not pattern:
            continue
        val = _interface_loss_for_station(station, pattern)
        if val is not None:
            candidates.append(val)
    ping_loss = _ping_metric_for_station(station, "packet_loss_pct")
    if ping_loss is not None:
        candidates.append(ping_loss)
    return max(candidates) if candidates else None


def _jitter_for_station(station: str) -> float | None:
    """Best ICMP signal: max of RTT stddev and average RTT (netem delay shows on both)."""
    candidates: list[float] = []
    for metric in ("jitter_ms", "latency_ms"):
        val = _ping_metric_for_station(station, metric)
        if val is not None and val > 0:
            candidates.append(val)
    return max(candidates) if candidates else None


def _metric_for_station(station: str, metric: str) -> float | None:
    if metric == "packet_loss_pct":
        return _loss_for_station(station)
    if metric == "jitter_ms":
        return _jitter_for_station(station)

    win = _rate_window()
    templates = {
        "ifInOctets": f'sum(rate(net_bytes_recv{{job="%(job)s",%(iface)s%(filt)s}}[{win}]))',
        "ifOutOctets": f'sum(rate(net_bytes_sent{{job="%(job)s",%(iface)s%(filt)s}}[{win}]))',
        "bgp_update_rate": f'sum(rate(bgp_updates{{job="%(job)s",%(filt)s}}[{win}]))',
    }
    template = templates.get(metric)
    if not template:
        return None

    primary = config.THROUGHPUT_INTERFACE_REGEX or config.EDGE_INTERFACE
    if metric in ("ifInOctets", "ifOutOctets"):
        candidates: list[float] = []
        if primary:
            primary_val = _station_host_query(station, template, primary)
            if primary_val is not None:
                candidates.append(primary_val)
        if not primary or primary != "eth0":
            eth0_val = _station_host_query(station, template, "eth0")
            if eth0_val is not None:
                candidates.append(eth0_val)
        return max(candidates) if candidates else None

    return _station_host_query(station, template, primary)


def fetch_station_snapshot(station: str) -> dict[str, Any]:
    metrics = {
        "ifInOctets": _metric_for_station(station, "ifInOctets"),
        "ifOutOctets": _metric_for_station(station, "ifOutOctets"),
        "packet_loss_pct": _metric_for_station(station, "packet_loss_pct"),
        "jitter_ms": _metric_for_station(station, "jitter_ms"),
        "bgp_update_rate": _metric_for_station(station, "bgp_update_rate"),
    }
    online = any(v is not None for v in metrics.values())
    bytes_per_sec_to_mbps = 8 / 1e6
    clean = {k: finite_float(v) for k, v in metrics.items()}
    clean["throughput_in_mbps"] = clean["ifInOctets"] * bytes_per_sec_to_mbps
    clean["throughput_out_mbps"] = clean["ifOutOctets"] * bytes_per_sec_to_mbps
    clean["throughput_mbps"] = max(clean["throughput_in_mbps"], clean["throughput_out_mbps"])
    return {
        "id": station,
        "host": station,
        "status": "online" if online else "offline",
        "metrics": clean,
    }


def discover_hosts() -> list[str]:
    job = config.PROMETHEUS_JOB
    promql = f'sum by (host) (rate(net_bytes_recv{{job="{job}"}}[{_rate_window()}]))'
    try:
        resp = requests.get(
            f"{_prom_base()}/api/v1/query",
            params={"query": promql},
            timeout=2,
        )
        resp.raise_for_status()
        payload = resp.json()
        hosts = []
        for row in payload.get("data", {}).get("result", []):
            host = row.get("metric", {}).get("host")
            if host and _STATION_HOST_RE.match(host):
                hosts.append(host)
        return sorted(set(hosts))
    except requests.RequestException:
        return []


def _fetch_gns3_live() -> dict[str, Any]:
    """Build dashboard snapshot from GNS3 Prom (:9091) / path exporter series."""
    timestamp = datetime.now(timezone.utc).isoformat()
    base = _prom_base()
    fab = 'fabric="gns3"'
    job = 'job="deca_gns3_fabric"'

    def q(expr: str) -> float:
        return finite_float(_prom_query(expr, base), 0.0)

    lat_gre = q(f'sdwan_path_latency_ms{{{job},path="gre",{fab}}}')
    lat_eth = q(f'sdwan_path_latency_ms{{{job},path="eth0",{fab}}}')
    jit = q(f'sdwan_path_jitter_ms{{{job},path="gre",{fab}}}')
    loss = q(f'sdwan_path_loss_pct{{{job},path="gre",{fab}}}')
    util = q(f'sdwan_path_util_mbps{{{job},path="gre",{fab}}}')
    bronze = q(f'ce_util_mbps{{{job},ce="ce-mauritius",{fab}}}')
    gold = q(f'ce_util_mbps{{{job},ce="ce-a",{fab}}}')
    cpu = q(f'cpu_usage_user{{{job},{fab}}}')
    bgp = q(f'bgp_flap_count{{{job},{fab}}}')

    online = any(v > 0 for v in (lat_gre, lat_eth, util, gold, bronze)) or _prometheus_healthy()
    # Synthetic station rows so TelemetryGrid / Header keep working
    pe1 = {
        "id": "gns3-pe1",
        "host": "gns3-pe1",
        "status": "online" if online else "offline",
        "metrics": {
            "ifInOctets": util * 1e6 / 8,
            "ifOutOctets": util * 1e6 / 8,
            "packet_loss_pct": loss,
            "jitter_ms": jit or lat_gre,
            "bgp_update_rate": bgp,
            "throughput_in_mbps": util,
            "throughput_out_mbps": util,
            "throughput_mbps": util,
            "ce_util_gold_mbps": gold,
            "ce_util_bronze_mbps": bronze,
            "latency_gre_ms": lat_gre,
            "latency_eth0_ms": lat_eth,
        },
    }
    pe2 = {
        "id": "gns3-pe2",
        "host": "gns3-pe2",
        "status": pe1["status"],
        "metrics": {
            **pe1["metrics"],
            "throughput_mbps": max(util * 0.9, gold),
        },
    }
    pe3 = {
        "id": "gns3-pe3",
        "host": "gns3-pe3",
        "status": pe1["status"],
        "metrics": {
            **pe1["metrics"],
            "throughput_mbps": max(util * 0.75, gold * 0.8),
        },
    }
    core = {
        "id": "gns3-core",
        "host": "gns3-core",
        "status": pe1["status"],
        "metrics": {
            "ifInOctets": util * 1e6 / 8,
            "ifOutOctets": util * 1e6 / 8,
            "packet_loss_pct": loss,
            "jitter_ms": jit,
            "bgp_update_rate": bgp,
            "throughput_in_mbps": util,
            "throughput_out_mbps": util,
            "throughput_mbps": util,
            "cpu_usage": cpu,
            "latency_gre_ms": lat_gre,
            "latency_eth0_ms": lat_eth,
        },
    }
    raw = {
        "ifInOctets": util * 1e6 / 8,
        "ifOutOctets": util * 1e6 / 8,
        "packet_loss_pct": loss,
        "jitter_ms": max(jit, lat_gre * 0.1),
        "bgp_update_rate": bgp,
        "latency_gre_ms": lat_gre,
        "latency_eth0_ms": lat_eth,
        "ce_util_gold_mbps": gold,
        "ce_util_bronze_mbps": bronze,
    }
    return {
        "timestamp": timestamp,
        "source": "prometheus_gns3",
        "fabric": "gns3",
        "prometheus": base,
        "prometheus_reachable": _prometheus_healthy(base),
        "stations": [pe1, pe2, pe3, core],
        "raw": raw,
    }


def fetch_live_network() -> dict[str, Any]:
    try:
        import fabric as fabric_mod

        active = fabric_mod.get_active()
    except Exception:
        active = "pi"

    if active == "gns3":
        return _fetch_gns3_live()

    timestamp = datetime.now(timezone.utc).isoformat()
    configured = list(config.RPI_STATIONS)
    stations = [fetch_station_snapshot(s) for s in configured]

    if not any(s["status"] == "online" for s in stations) and config.RPI_AUTO_DISCOVER:
        discovered = discover_hosts()
        if discovered:
            stations = [fetch_station_snapshot(s) for s in discovered]

    online_stations = [s for s in stations if s["status"] == "online"]
    if not online_stations:
        return {
            "timestamp": timestamp,
            "source": "prometheus",
            "fabric": "pi",
            "prometheus": _prom_base(),
            "prometheus_reachable": _prometheus_healthy(),
            "stations": stations,
            "raw": None,
        }

    def _sum_metric(key: str) -> float:
        return sum(s["metrics"].get(key, 0.0) for s in online_stations)

    def _max_metric(key: str) -> float:
        vals = [s["metrics"].get(key, 0.0) for s in online_stations]
        return max(vals) if vals else 0.0

    raw = {
        "ifInOctets": _sum_metric("ifInOctets"),
        "ifOutOctets": _sum_metric("ifOutOctets"),
        "packet_loss_pct": _max_metric("packet_loss_pct"),
        "jitter_ms": _max_metric("jitter_ms"),
        "bgp_update_rate": _sum_metric("bgp_update_rate"),
    }

    return {
        "timestamp": timestamp,
        "source": "prometheus",
        "fabric": "pi",
        "prometheus": _prom_base(),
        "prometheus_reachable": True,
        "stations": stations,
        "raw": raw,
    }


def _prometheus_healthy(base: str | None = None) -> bool:
    url = (base or _prom_base()).rstrip("/")
    try:
        resp = requests.get(f"{url}/-/healthy", timeout=3)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def raw_to_display(raw: dict[str, float], timestamp: str) -> dict[str, Any]:
    bytes_per_sec_to_mbps = 8 / 1e6
    return {
        "network_throughput_in": finite_float(raw.get("ifInOctets", 0.0)) * bytes_per_sec_to_mbps,
        "network_throughput_out": finite_float(raw.get("ifOutOctets", 0.0)) * bytes_per_sec_to_mbps,
        "link_jitter": finite_float(raw.get("jitter_ms", 0.0)),
        "packet_loss": finite_float(raw.get("packet_loss_pct", 0.0)),
        "routing_updates": finite_float(raw.get("bgp_update_rate", 0.0)),
        "cpu_usage": 0.0,
        "memory_usage": 0.0,
        "timestamp": timestamp,
    }
