#!/usr/bin/env python3
"""GNS3 fabric path exporter — same Prom schema as Pi, label fabric=\"gns3\".

Reads lab/gns3/state/chaos_state.json (written by inject adapters + traffic sims)
and exposes /metrics on :9275 for the telemetry Prometheus scrape.

Matches Flow 1 Chaos diagram: iperf3 + NetEM (+ CPU/BGP/util injects) drive these gauges.
TRex is not part of the DECA chaos stack.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # lab/gns3
STATE = Path(
    os.environ.get(
        "DECA_GNS3_CHAOS_STATE",
        str(ROOT / "state" / "chaos_state.json"),
    )
)
PORT = int(os.environ.get("DECA_GNS3_EXPORTER_PORT", "9275"))

_lock = threading.Lock()
_defaults = {
    "latency_gre_ms": 8.0,
    "latency_eth0_ms": 12.0,
    "jitter_gre_ms": 0.5,
    "loss_gre_pct": 0.0,
    "util_gre_mbps": 2.5,
    "cpu_usage_system": 5.0,
    "cpu_usage_user": 8.0,
    "mem_used_percent": 35.0,
    "bgp_flap_count": 0.0,
    "htb_payload_ceil_mbps": 34.0,
    "ce_util_mbps_bronze": 2.0,
    "ce_util_mbps_gold": 4.0,
    "fault_id": "",
    "updated_unix": 0,
}


def read_state() -> dict:
    with _lock:
        if not STATE.is_file():
            return dict(_defaults)
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(_defaults)
        out = dict(_defaults)
        out.update({k: data[k] for k in out if k in data})
        return out


def write_state(patch: dict) -> dict:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    cur = read_state()
    cur.update(patch)
    cur["updated_unix"] = time.time()
    with _lock:
        STATE.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
    return cur


def metrics_text() -> str:
    s = read_state()
    gre = float(s["latency_gre_ms"])
    eth = float(s["latency_eth0_ms"])
    asym = abs(gre - eth)
    fab = 'fabric="gns3"'
    job = 'job="deca_gns3_fabric"'
    host = 'host="gns3-pe1"'
    lines = [
        "# HELP sdwan_path_latency_ms Path RTT (GNS3 fabric)",
        "# TYPE sdwan_path_latency_ms gauge",
        f'sdwan_path_latency_ms{{{job},{host},path="gre",src="edge",{fab}}} {gre}',
        f'sdwan_path_latency_ms{{{job},{host},path="eth0",src="edge",{fab}}} {eth}',
        "# HELP sdwan_path_jitter_ms Path jitter",
        "# TYPE sdwan_path_jitter_ms gauge",
        f'sdwan_path_jitter_ms{{{job},{host},path="gre",{fab}}} {s["jitter_gre_ms"]}',
        "# HELP sdwan_path_loss_pct Path loss percent",
        "# TYPE sdwan_path_loss_pct gauge",
        f'sdwan_path_loss_pct{{{job},{host},path="gre",src="edge",{fab}}} {s["loss_gre_pct"]}',
        "# HELP sdwan_path_util_mbps Underlay util",
        "# TYPE sdwan_path_util_mbps gauge",
        f'sdwan_path_util_mbps{{{job},{host},path="gre",{fab}}} {s["util_gre_mbps"]}',
        # eth0 alias for CAPTURE_CONTRACT-shaped queries (same twin gauge until live eth0 TX exists)
        f'sdwan_path_util_mbps{{{job},{host},path="eth0",src="edge",{fab}}} {s["util_gre_mbps"]}',
        "# HELP cpu_usage_system PE CPU system",
        "# TYPE cpu_usage_system gauge",
        f'cpu_usage_system{{{job},{host},{fab}}} {s["cpu_usage_system"]}',
        "# HELP cpu_usage_user PE CPU user",
        "# TYPE cpu_usage_user gauge",
        f'cpu_usage_user{{{job},{host},{fab}}} {s["cpu_usage_user"]}',
        "# HELP mem_used_percent PE memory",
        "# TYPE mem_used_percent gauge",
        f'mem_used_percent{{{job},{host},{fab}}} {s["mem_used_percent"]}',
        "# HELP bgp_flap_count BGP flap counter",
        "# TYPE bgp_flap_count gauge",
        f'bgp_flap_count{{{job},{host},{fab}}} {s["bgp_flap_count"]}',
        "# HELP htb_payload_ceil_mbps Live HTB payload class (1:15) ceil",
        "# TYPE htb_payload_ceil_mbps gauge",
        f'htb_payload_ceil_mbps{{{job},{host},{fab}}} {s["htb_payload_ceil_mbps"]}',
        "# HELP path_asymmetry Absolute GRE−eth0 RTT (derived twin)",
        "# TYPE path_asymmetry gauge",
        f'path_asymmetry{{{job},{host},src="edge",{fab}}} {asym}',
        f'path_asymmetry_ms{{{job},{host},src="edge",{fab}}} {asym}',
        "# HELP ce_util_mbps CE site util",
        "# TYPE ce_util_mbps gauge",
        f'ce_util_mbps{{{job},ce="ce-mauritius",tier="bronze",{fab}}} {s["ce_util_mbps_bronze"]}',
        f'ce_util_mbps{{{job},ce="ce-a",tier="gold",{fab}}} {s["ce_util_mbps_gold"]}',
        "# HELP gns3_chaos_active 1 if a demo fault is active",
        "# TYPE gns3_chaos_active gauge",
        f'gns3_chaos_active{{{fab},fault_id="{s.get("fault_id") or "none"}"}} '
        f'{1.0 if s.get("fault_id") else 0.0}',
    ]
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        body = metrics_text().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    write_state({})  # ensure file exists
    httpd = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"gns3 path exporter on :{PORT} state={STATE}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
