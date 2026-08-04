#!/usr/bin/env python3
"""
deca_sdwan_controller.py — SD-WAN dynamic path-selection policy loop (ISRO DECA).

Authoritative catalog: docs/DECA_SDWAN_POLICY_RULES.md

Lab AAR loop (implemented here):
  1. Classification — TT&C ToS 0x88 (PS13 CS4-class); Payload ToS 0x80;
     Admin/BE 0x00 on vrf-admin (PS13 vrf-default); ESP copy_dscp=out.
  2. HTB — TT&C → 1:10 LLQ; Payload → 1:15 (~70% + RED@~85%); BE → 1:20.
  3. AAR SLA — TT&C ≤25 ms / ≤5 ms jitter / ≤0.1% loss;
     Payload ≤80 ms / ≤15 ms / ≤2% loss; Bulk no SLA (eth0 / scavenger).
  4. Steer — gre-te-core preferred (OSPF 5) vs eth0 backup (OSPF 50);
     conflict → sdwan_policy_conflict=1 and TT&C wins (preempts Payload).
  5. Hysteresis — enter_k=3 failover; exit_k=10 recover; human /action
     suspends autonomy. HITL: force_path before SLA breach; Approve required.
  6. Underlay — vrf-mission RT 65001:100; SR-TE BSID 40001/40002; LDP on GRE.
     Traffic gen: iperf3 only (no Cisco TRex / DPDK).

Prometheus: primary labels class="ttc"|"payload"; dual-export class="voice"|"video"
so the promoted ML lake keeps working without a feature rebuild.

Does NOT touch models/fault_classifier/.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

# ── Shared loop / hysteresis (Rule 5) ─────────────────────────────────────
POLL_SECONDS = 5
ENTER_K = 3   # Degradation trigger — 3 consecutive SLA breaches
EXIT_K = 10   # Stability recovery — 10 consecutive clean primary probes
# PS13-P6.4 — when this flag exists, controller forces a misconfigured underlay
# (policy drift). Written by scripts/deca_fault_campaign.inject_policy_drift.
DRIFT_FLAG = Path(__file__).resolve().parents[1] / "data" / "rpi-net" / "sdwan_policy_drift.flag"

# AAR — TT&C critical command SLA
TTC_LATENCY_MAX_MS = 25.0
TTC_JITTER_MAX_MS = 5.0
TTC_LOSS_MAX_PCT = 0.1

# AAR — Mission Payload SLA
PAYLOAD_LATENCY_MAX_MS = 80.0
PAYLOAD_JITTER_MAX_MS = 15.0
PAYLOAD_LOSS_MAX_PCT = 2.0

# Legacy aliases (ML Prom queries / older docs)
VOICE_LATENCY_MAX_MS = TTC_LATENCY_MAX_MS
VOICE_JITTER_MAX_MS = TTC_JITTER_MAX_MS
VOICE_LOSS_MAX_PCT = TTC_LOSS_MAX_PCT
VIDEO_LATENCY_MAX_MS = PAYLOAD_LATENCY_MAX_MS
VIDEO_JITTER_MAX_MS = PAYLOAD_JITTER_MAX_MS
VIDEO_LOSS_MAX_PCT = PAYLOAD_LOSS_MAX_PCT

# Rule 3.3 / 4.3 — BE scavenger: never steers; rides TT&C/Payload-selected underlay.

PE1 = os.environ.get("DECA_SDWAN_PE1", "station1")
PE2_IP = "192.168.50.20"
GRE_VIA = "10.50.1.2"
GRE_DEV = "gre-te-core"
ETH_DEV = "eth0"
# Rule 4.1 — preferred GRE cost 5; when GRE is bad, raise cost above eth0 backup (50)
GRE_COST_PREF = 5
GRE_COST_BAD = 100
ETH_COST_BACKUP = 50  # documented lab OSPF cost on eth0 (set on PE, not rewritten here)

# Human-gated override from DECA orchestrator (None = fully autonomous).
_HUMAN_FORCE: Optional[str] = None  # "gre" | "eth0"
_HUMAN_META: dict[str, Any] = {}
_ACTION_PE1 = PE1

PROM_URL = os.environ.get("DECA_PROMETHEUS_URL", "http://127.0.0.1:9090")
METRICS_PORT = int(os.environ.get("DECA_SDWAN_METRICS_PORT", "9280"))
LOG_PATH = Path(
    os.environ.get(
        "DECA_SDWAN_LOG",
        str(Path(__file__).resolve().parents[1] / "data" / "rpi-net" / "sdwan_controller.log"),
    )
)


@dataclass
class PathSample:
    name: str
    latency_ms: float
    jitter_ms: float
    loss_pct: float
    util_mbps: float
    detail: str = ""
    # False when ping produced no RTT line — lat/jit are held-over or unset, not measured.
    rtt_valid: bool = True

    def ok_for(self, lat_max: float, jit_max: float, loss_max: float) -> bool:
        if not self.rtt_valid:
            # Missing RTT is not "infinite latency"; treat as unhealthy only via loss,
            # otherwise a parse glitch would force eth0. High loss still fails the path.
            return self.loss_pct <= loss_max
        return (
            self.latency_ms <= lat_max
            and self.jitter_ms <= jit_max
            and self.loss_pct <= loss_max
        )


@dataclass
class ClassState:
    name: str  # ttc | payload  (legacy aliases: voice | video)
    lat_max: float
    jit_max: float
    loss_max: float
    wanted_path: str = "gre"  # gre | eth0 — class preference before conflict resolve
    gre_bad_streak: int = 0
    gre_good_streak: int = 0
    switch_count: int = 0
    last_reason: str = "init"


@dataclass
class ControllerState:
    active_path: str = "gre"  # shared underlay actually applied
    conflict: int = 0
    last_decision: str = "start"
    last_reason: str = "init"
    gre: Optional[PathSample] = None
    eth0: Optional[PathSample] = None
    ttc: ClassState = field(
        default_factory=lambda: ClassState(
            "ttc", TTC_LATENCY_MAX_MS, TTC_JITTER_MAX_MS, TTC_LOSS_MAX_PCT
        )
    )
    payload: ClassState = field(
        default_factory=lambda: ClassState(
            "payload", PAYLOAD_LATENCY_MAX_MS, PAYLOAD_JITTER_MAX_MS, PAYLOAD_LOSS_MAX_PCT
        )
    )

    # Legacy property aliases so older call sites / mental model still work.
    @property
    def voice(self) -> ClassState:
        return self.ttc

    @property
    def video(self) -> ClassState:
        return self.payload
    lock: threading.Lock = field(default_factory=threading.Lock)


STATE = ControllerState()
_STOP = threading.Event()


def _ssh(host: str, cmd: str, timeout: int = 20) -> str:
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-T", host, cmd]
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(
            f"ssh {host} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}"
        )
    return r.stdout


def _prom_query(expr: str) -> Optional[float]:
    try:
        q = urlencode({"query": expr})
        with urlopen(f"{PROM_URL}/api/v1/query?{q}", timeout=4) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("data", {}).get("result", [])
        if not results:
            return None
        return float(results[0]["value"][1])
    except Exception:
        return None


def _parse_ping(text: str) -> tuple[Optional[float], Optional[float], float]:
    """Return (latency_ms, jitter_ms, loss_pct).

    Latency/jitter are ``None`` when the ping summary has no RTT line (timeout /
    100% loss / parse miss). Callers must **not** substitute a numeric sentinel
    like 9999 — that poisons Prometheus gauges and MAD/z-score features.

    Important: when the RTT line is present but the ``% packet loss`` line was
    clipped from the capture window, do **not** default loss to 100 — that pairs
    a good latency with fake total loss and thrashing the underlay selector.
    """
    lat: Optional[float] = None
    jit: Optional[float] = None
    m = re.search(
        r"rtt min/avg/max/(?:mdev|stddev) = "
        r"([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)",
        text,
    )
    if m:
        lat = float(m.group(2))
        jit = float(m.group(4))
    loss_m = re.search(r"(\d+(?:\.\d+)?)% packet loss", text)
    if loss_m:
        loss = float(loss_m.group(1))
    elif lat is not None:
        loss = 0.0
    else:
        loss = 100.0
    return lat, jit, loss


def _hold_rtt(
    name: str,
    lat: Optional[float],
    jit: Optional[float],
    loss: float,
    util: float,
    prev: Optional[PathSample],
) -> PathSample:
    """Build a PathSample; hold last-good RTT when this poll had no parseable RTT."""
    if lat is not None and jit is not None:
        return PathSample(name, lat, jit, loss, util, rtt_valid=True)
    if prev is not None and prev.rtt_valid:
        # Hold the previous *health* snapshot — do not attach loss=100 from a
        # failed poll onto a held-good latency (Prom/feature poison).
        return PathSample(
            name,
            prev.latency_ms,
            prev.jitter_ms,
            prev.loss_pct,
            util,
            detail="rtt_held_last_good",
            rtt_valid=False,
        )
    # No prior good sample — leave zeros but mark invalid so exporters omit RTT.
    return PathSample(
        name, 0.0, 0.0, loss, util, detail="rtt_missing", rtt_valid=False
    )


def _iface_utils_mbps(host: str, ifaces: tuple[str, ...]) -> dict[str, float]:
    def snapshot() -> dict[str, int]:
        out = _ssh(
            host,
            "python3 - <<'PY'\n"
            "import json\n"
            f"want={list(ifaces)!r}\n"
            "d={}\n"
            "for line in open('/proc/net/dev'):\n"
            "    if ':' not in line: continue\n"
            "    name, rest = line.split(':', 1)\n"
            "    name = name.strip()\n"
            "    if name not in want: continue\n"
            "    parts = rest.split()\n"
            "    d[name] = int(parts[0]) + int(parts[8])\n"
            "print(json.dumps(d))\n"
            "PY",
        )
        try:
            return {str(k): int(v) for k, v in json.loads(out.strip()).items()}
        except Exception:
            return {i: 0 for i in ifaces}

    s0 = snapshot()
    time.sleep(1.0)
    s1 = snapshot()
    return {
        i: max(0.0, (s1.get(i, 0) - s0.get(i, 0)) * 8.0 / 1e6) for i in ifaces
    }


def probe_paths(pe1: str) -> tuple[PathSample, PathSample]:
    # Capture full ping summaries (do not tail-clip — loss line must stay with RTT).
    combined = _ssh(
        pe1,
        f"echo GRE; ping -c 5 -i 0.2 -W 1 -I {GRE_DEV} {GRE_VIA} 2>&1; "
        f"echo ETH; ping -c 5 -i 0.2 -W 1 -I {ETH_DEV} {PE2_IP} 2>&1",
    )
    gre_ping = combined.split("ETH", 1)[0]
    eth_ping = combined.split("ETH", 1)[-1] if "ETH" in combined else ""
    g_lat, g_jit, g_loss = _parse_ping(gre_ping)
    e_lat, e_jit, e_loss = _parse_ping(eth_ping)

    try:
        utils = _iface_utils_mbps(pe1, (GRE_DEV, ETH_DEV))
        g_util = utils.get(GRE_DEV, 0.0)
        e_util = utils.get(ETH_DEV, 0.0)
    except Exception:
        g_util = e_util = 0.0

    prom_lat = _prom_query(
        f'ping_average_response_ms{{host="station1",url="{PE2_IP}"}}'
    )
    with STATE.lock:
        prev_g, prev_e = STATE.gre, STATE.eth0
    gre = _hold_rtt("gre", g_lat, g_jit, g_loss, g_util, prev_g)
    gre.detail = f"prom_pe2_lat={prom_lat}"
    eth = _hold_rtt("eth0", e_lat, e_jit, e_loss, e_util, prev_e)
    return gre, eth


def apply_path(pe1: str, path: str) -> str:
    if path == "gre":
        script = (
            f"vtysh -c 'configure terminal' -c 'interface {GRE_DEV}' "
            f"-c 'ip ospf cost {GRE_COST_PREF}' -c 'end' -c 'write memory'; "
            f"ip route replace {PE2_IP}/32 via {GRE_VIA} dev {GRE_DEV}; "
            f"echo ROUTE; ip route get {PE2_IP}; "
            f"echo OSPF; vtysh -c 'show ip route 10.1.2.1'"
        )
    else:
        script = (
            f"vtysh -c 'configure terminal' -c 'interface {GRE_DEV}' "
            f"-c 'ip ospf cost {GRE_COST_BAD}' -c 'end' -c 'write memory'; "
            f"ip route del {PE2_IP}/32 via {GRE_VIA} dev {GRE_DEV} 2>/dev/null || true; "
            f"echo ROUTE; ip route get {PE2_IP}; "
            f"echo OSPF; vtysh -c 'show ip route 10.1.2.1'"
        )
    return _ssh(pe1, f"sudo bash -c {_shell_quote(script)}")


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def update_class_want(
    cls: ClassState, gre: PathSample, eth: PathSample
) -> tuple[str, str]:
    """
    Update per-class wanted_path with hysteresis.
    Returns (decision, reason) for this class only.
    decision ∈ {hold, prefer_eth0, prefer_gre}
    """
    gre_ok = gre.ok_for(cls.lat_max, cls.jit_max, cls.loss_max)
    eth_ok = eth.ok_for(cls.lat_max, cls.jit_max, cls.loss_max)

    if cls.wanted_path == "gre":
        if not gre_ok:
            cls.gre_bad_streak += 1
            cls.gre_good_streak = 0
        else:
            cls.gre_good_streak += 1
            cls.gre_bad_streak = 0
        if cls.gre_bad_streak >= ENTER_K and eth_ok:
            cls.wanted_path = "eth0"
            reason = (
                f"{cls.name}: gre unhealthy {cls.gre_bad_streak}x "
                f"(lat={gre.latency_ms:.1f} jit={gre.jitter_ms:.1f} "
                f"loss={gre.loss_pct:.0f}%); eth0 ok"
            )
            cls.last_reason = reason
            return "prefer_eth0", reason
        if cls.gre_bad_streak >= ENTER_K and not eth_ok:
            reason = (
                f"{cls.name}: gre unhealthy but eth0 also bad — stay gre "
                f"(gre lat={gre.latency_ms:.1f} eth lat={eth.latency_ms:.1f})"
            )
            cls.last_reason = reason
            return "hold", reason
        reason = (
            f"{cls.name}: gre ok/streak_bad={cls.gre_bad_streak} "
            f"lat={gre.latency_ms:.1f} jit={gre.jitter_ms:.1f}"
        )
        cls.last_reason = reason
        return "hold", reason

    # wanted eth0 — look for gre recovery
    if gre_ok:
        cls.gre_good_streak += 1
        cls.gre_bad_streak = 0
    else:
        cls.gre_good_streak = 0
        cls.gre_bad_streak += 1
    if cls.gre_good_streak >= EXIT_K:
        cls.wanted_path = "gre"
        reason = (
            f"{cls.name}: gre recovered {cls.gre_good_streak}x "
            f"(lat={gre.latency_ms:.1f}); hysteresis exit_k={EXIT_K}"
        )
        cls.last_reason = reason
        return "prefer_gre", reason
    reason = (
        f"{cls.name}: on eth0; gre_good_streak={cls.gre_good_streak}/{EXIT_K} "
        f"gre_lat={gre.latency_ms:.1f}"
    )
    cls.last_reason = reason
    return "hold", reason


def read_policy_drift_force() -> Optional[str]:
    """Return forced underlay path when P6.4 drift flag is present."""
    if not DRIFT_FLAG.exists():
        return None
    try:
        txt = DRIFT_FLAG.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "eth0"
    if txt in ("eth0", "gre"):
        return txt
    return "eth0"


def resolve_underlay(st: ControllerState) -> tuple[str, int, str]:
    """
    TT&C wins on conflict. Returns (active_path, conflict_flag, reason).
    BE scavenger never participates in steer.
    Precedence: human gate → policy-drift flag → autonomous TT&C/Payload.
    """
    if _HUMAN_FORCE in ("gre", "eth0"):
        by = _HUMAN_META.get("approved_by", "deca-ui")
        return (
            _HUMAN_FORCE,
            1,
            f"HUMAN_FORCE path={_HUMAN_FORCE} by={by}",
        )
    force = read_policy_drift_force()
    if force:
        other = "gre" if force == "eth0" else "eth0"
        st.ttc.wanted_path = force
        st.payload.wanted_path = other
        return (
            force,
            1,
            f"POLICY_DRIFT force_path={force} (controller misconfiguration)",
        )
    ttc_p, pay_p = st.ttc.wanted_path, st.payload.wanted_path
    if ttc_p == pay_p:
        return ttc_p, 0, f"agree path={ttc_p} (ttc+payload)"
    # conflict: TT&C always wins
    return (
        ttc_p,
        1,
        f"conflict ttc_wants={ttc_p} payload_wants={pay_p}; ttc_wins→{ttc_p}",
    )


def _prom_label(value: str) -> str:
    """Sanitize a free-text reason into a Prometheus label value."""
    s = re.sub(r"[^a-zA-Z0-9_.:/=+\-]", "_", str(value or "none"))
    return (s[:120] or "none")


def _influx_tag(value: str) -> str:
    """Sanitize for Influx line-protocol tag values (no '=' ',' ' ' or ':').

    Telegraf rejects the whole exec batch if one tag is illegal — that is what
    made Prometheus SD-WAN graphs show 'No data points' while :9280 still worked.
    """
    s = re.sub(r"[^a-zA-Z0-9_]", "_", str(value or "none"))
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:80] or "none")


def _dual_class_labels(mission: str) -> tuple[str, str]:
    """Return (mission_label, legacy_alias) for Prom dual-export."""
    if mission == "ttc":
        return "ttc", "voice"
    if mission == "payload":
        return "payload", "video"
    return mission, mission


def metrics_text(st: ControllerState) -> str:
    """Prometheus text exposition. Dual-export ttc/payload and voice/video aliases."""
    gre_on = 1 if st.active_path == "gre" else 0
    eth_on = 1 if st.active_path == "eth0" else 0
    ttc_gre = 1 if st.ttc.wanted_path == "gre" else 0
    ttc_eth = 1 if st.ttc.wanted_path == "eth0" else 0
    pay_gre = 1 if st.payload.wanted_path == "gre" else 0
    pay_eth = 1 if st.payload.wanted_path == "eth0" else 0
    ttc_ok_g = (
        1 if st.gre and st.gre.ok_for(TTC_LATENCY_MAX_MS, TTC_JITTER_MAX_MS, TTC_LOSS_MAX_PCT) else 0
    )
    pay_ok_g = (
        1
        if st.gre and st.gre.ok_for(PAYLOAD_LATENCY_MAX_MS, PAYLOAD_JITTER_MAX_MS, PAYLOAD_LOSS_MAX_PCT)
        else 0
    )
    ttc_ok_e = (
        1 if st.eth0 and st.eth0.ok_for(TTC_LATENCY_MAX_MS, TTC_JITTER_MAX_MS, TTC_LOSS_MAX_PCT) else 0
    )
    pay_ok_e = (
        1
        if st.eth0
        and st.eth0.ok_for(PAYLOAD_LATENCY_MAX_MS, PAYLOAD_JITTER_MAX_MS, PAYLOAD_LOSS_MAX_PCT)
        else 0
    )

    def path_gauges(cls: str, gre_v: int, eth_v: int, code: int, sw: int, reason: str,
                    bad: int, good: int) -> list[str]:
        return [
            f'sdwan_active_path{{class="{cls}",path="gre"}} {gre_on}',
            f'sdwan_active_path{{class="{cls}",path="eth0"}} {eth_on}',
            f'sdwan_active_path_code{{class="{cls}"}} {code}',
            f'sdwan_class_wanted_path{{class="{cls}",path="gre"}} {gre_v}',
            f'sdwan_class_wanted_path{{class="{cls}",path="eth0"}} {eth_v}',
            f'sdwan_path_switch_count{{class="{cls}"}} {sw}',
            f'sdwan_last_switch_reason{{class="{cls}",reason="{_prom_label(reason)}"}} 1',
            f'sdwan_gre_bad_streak{{class="{cls}"}} {bad}',
            f'sdwan_gre_good_streak{{class="{cls}"}} {good}',
        ]

    lines = [
        "# HELP sdwan_active_path Shared underlay selection (ESP); 1=active",
        "# TYPE sdwan_active_path gauge",
        "# HELP sdwan_active_path_code 1 when active underlay is GRE",
        "# TYPE sdwan_active_path_code gauge",
        "# HELP sdwan_class_wanted_path Per-class preference before conflict resolve",
        "# TYPE sdwan_class_wanted_path gauge",
        "# HELP sdwan_path_switch_count Cumulative underlay switches attributed per class",
        "# TYPE sdwan_path_switch_count counter",
        "# HELP sdwan_policy_conflict 1 when TT&C and Payload disagree on wanted path",
        "# TYPE sdwan_policy_conflict gauge",
        f"sdwan_policy_conflict {st.conflict}",
        "# HELP sdwan_human_override 1 when DECA dashboard human gate holds a path",
        "# TYPE sdwan_human_override gauge",
        f'sdwan_human_override{{path="gre"}} {1 if _HUMAN_FORCE == "gre" else 0}',
        f'sdwan_human_override{{path="eth0"}} {1 if _HUMAN_FORCE == "eth0" else 0}',
        "# HELP sdwan_last_switch_reason Info metric; reason encoded in label",
        "# TYPE sdwan_last_switch_reason gauge",
        "# HELP sdwan_path_latency_ms Controller probe latency",
        "# TYPE sdwan_path_latency_ms gauge",
        "# HELP path_asymmetry_ms abs(GRE−eth0) RTT differential (PS13-O2.2)",
        "# TYPE path_asymmetry_ms gauge",
        "# HELP path_asymmetry abs(GRE−eth0) RTT differential alias",
        "# TYPE path_asymmetry gauge",
    ]
    # Mission labels + legacy aliases (identical values for ML lake)
    for cls, gre_v, eth_v, sw, reason, bad, good in (
        ("ttc", ttc_gre, ttc_eth, st.ttc.switch_count, st.ttc.last_reason, st.ttc.gre_bad_streak, st.ttc.gre_good_streak),
        ("voice", ttc_gre, ttc_eth, st.ttc.switch_count, st.ttc.last_reason, st.ttc.gre_bad_streak, st.ttc.gre_good_streak),
        ("payload", pay_gre, pay_eth, st.payload.switch_count, st.payload.last_reason, st.payload.gre_bad_streak, st.payload.gre_good_streak),
        ("video", pay_gre, pay_eth, st.payload.switch_count, st.payload.last_reason, st.payload.gre_bad_streak, st.payload.gre_good_streak),
    ):
        lines += path_gauges(cls, gre_v, eth_v, gre_on, sw, reason, bad, good)

    if st.gre:
        if st.gre.rtt_valid:
            lines += [
                f'sdwan_path_latency_ms{{path="gre"}} {st.gre.latency_ms}',
                f'sdwan_path_jitter_ms{{path="gre"}} {st.gre.jitter_ms}',
            ]
        lines += [
            f'sdwan_path_loss_pct{{path="gre"}} {st.gre.loss_pct}',
            f'sdwan_path_util_mbps{{path="gre"}} {st.gre.util_mbps}',
        ]
        for cls, ok in (("ttc", ttc_ok_g), ("voice", ttc_ok_g), ("payload", pay_ok_g), ("video", pay_ok_g)):
            lines.append(f'sdwan_path_healthy{{path="gre",class="{cls}"}} {ok}')
    if st.eth0:
        if st.eth0.rtt_valid:
            lines += [
                f'sdwan_path_latency_ms{{path="eth0"}} {st.eth0.latency_ms}',
                f'sdwan_path_jitter_ms{{path="eth0"}} {st.eth0.jitter_ms}',
            ]
        lines += [
            f'sdwan_path_loss_pct{{path="eth0"}} {st.eth0.loss_pct}',
            f'sdwan_path_util_mbps{{path="eth0"}} {st.eth0.util_mbps}',
        ]
        for cls, ok in (("ttc", ttc_ok_e), ("voice", ttc_ok_e), ("payload", pay_ok_e), ("video", pay_ok_e)):
            lines.append(f'sdwan_path_healthy{{path="eth0",class="{cls}"}} {ok}')
    if st.gre and st.eth0 and st.gre.rtt_valid and st.eth0.rtt_valid:
        asym = abs(float(st.gre.latency_ms) - float(st.eth0.latency_ms))
        lines += [
            f"path_asymmetry_ms {asym}",
            f"path_asymmetry {asym}",
        ]
    return "\n".join(lines) + "\n"



def influx_metrics_text(st: ControllerState) -> str:
    """Telegraf/Influx line protocol pushed to PE1. Dual-export ttc+voice / payload+video."""
    gre_on = 1 if st.active_path == "gre" else 0
    eth_on = 1 if st.active_path == "eth0" else 0
    lines: list[str] = [f"sdwan_policy_conflict value={st.conflict}"]
    for cls, cstate in (
        ("ttc", st.ttc),
        ("voice", st.ttc),
        ("payload", st.payload),
        ("video", st.payload),
    ):
        reason = _influx_tag(cstate.last_reason)
        lines += [
            f"sdwan_active_path,class={cls},path=gre value={gre_on}",
            f"sdwan_active_path,class={cls},path=eth0 value={eth_on}",
            f"sdwan_active_path_code,class={cls} value={gre_on}",
            f"sdwan_class_wanted_path,class={cls},path=gre value={1 if cstate.wanted_path == 'gre' else 0}",
            f"sdwan_class_wanted_path,class={cls},path=eth0 value={1 if cstate.wanted_path == 'eth0' else 0}",
            f"sdwan_path_switch_count,class={cls} value={cstate.switch_count}i",
            f"sdwan_last_switch_reason,class={cls},reason={reason} value=1",
            f"sdwan_gre_bad_streak,class={cls} value={cstate.gre_bad_streak}i",
            f"sdwan_gre_good_streak,class={cls} value={cstate.gre_good_streak}i",
        ]
    if st.gre:
        if st.gre.rtt_valid:
            lines += [
                f"sdwan_path_latency_ms,path=gre value={st.gre.latency_ms}",
                f"sdwan_path_jitter_ms,path=gre value={st.gre.jitter_ms}",
            ]
        ttc_ok = 1 if st.gre.ok_for(TTC_LATENCY_MAX_MS, TTC_JITTER_MAX_MS, TTC_LOSS_MAX_PCT) else 0
        pay_ok = 1 if st.gre.ok_for(PAYLOAD_LATENCY_MAX_MS, PAYLOAD_JITTER_MAX_MS, PAYLOAD_LOSS_MAX_PCT) else 0
        lines += [
            f"sdwan_path_loss_pct,path=gre value={st.gre.loss_pct}",
            f"sdwan_path_util_mbps,path=gre value={st.gre.util_mbps}",
            f"sdwan_path_healthy,path=gre,class=ttc value={ttc_ok}",
            f"sdwan_path_healthy,path=gre,class=voice value={ttc_ok}",
            f"sdwan_path_healthy,path=gre,class=payload value={pay_ok}",
            f"sdwan_path_healthy,path=gre,class=video value={pay_ok}",
        ]
    if st.eth0:
        if st.eth0.rtt_valid:
            lines += [
                f"sdwan_path_latency_ms,path=eth0 value={st.eth0.latency_ms}",
                f"sdwan_path_jitter_ms,path=eth0 value={st.eth0.jitter_ms}",
            ]
        ttc_ok = 1 if st.eth0.ok_for(TTC_LATENCY_MAX_MS, TTC_JITTER_MAX_MS, TTC_LOSS_MAX_PCT) else 0
        pay_ok = 1 if st.eth0.ok_for(PAYLOAD_LATENCY_MAX_MS, PAYLOAD_JITTER_MAX_MS, PAYLOAD_LOSS_MAX_PCT) else 0
        lines += [
            f"sdwan_path_loss_pct,path=eth0 value={st.eth0.loss_pct}",
            f"sdwan_path_util_mbps,path=eth0 value={st.eth0.util_mbps}",
            f"sdwan_path_healthy,path=eth0,class=ttc value={ttc_ok}",
            f"sdwan_path_healthy,path=eth0,class=voice value={ttc_ok}",
            f"sdwan_path_healthy,path=eth0,class=payload value={pay_ok}",
            f"sdwan_path_healthy,path=eth0,class=video value={pay_ok}",
        ]
    return "\n".join(lines) + "\n"


def push_metrics_to_pe(pe1: str, st: ControllerState) -> None:
    body = influx_metrics_text(st)
    b64 = base64.b64encode(body.encode()).decode()
    _ssh(
        pe1,
        "sudo mkdir -p /var/lib/deca && "
        f"echo {b64} | base64 -d | sudo tee /var/lib/deca/sdwan_metrics.influx >/dev/null",
    )


def apply_human_action(payload: dict[str, Any], pe1: str) -> dict[str, Any]:
    """Apply localhost-only orchestrator approve action. Does not use drift flag."""
    global _HUMAN_FORCE, _HUMAN_META
    op = str(payload.get("op") or "").strip()
    path = str(payload.get("path") or "").strip().lower()
    approved_by = str(payload.get("approved_by") or "deca-ui")
    reason = str(payload.get("reason") or "orchestrator_approve")
    if op == "clear_force":
        _HUMAN_FORCE = None
        _HUMAN_META = {"cleared_by": approved_by, "reason": reason}
        logging.getLogger("sdwan").info("HUMAN clear_force by=%s reason=%s", approved_by, reason)
        return {"ok": True, "op": op, "active_override": None, "active_path": STATE.active_path}
    if op == "reset_autonomy":
        # Demo/sim heal: drop human gate, clear hysteresis, prefer GRE again.
        _HUMAN_FORCE = None
        _HUMAN_META = {"reset_by": approved_by, "reason": reason}
        out = apply_path(pe1, "gre")
        with STATE.lock:
            STATE.active_path = "gre"
            STATE.conflict = 0
            STATE.last_reason = f"RESET_AUTONOMY by={approved_by}"
            STATE.last_decision = "switch_to_gre"
            for cls in (STATE.ttc, STATE.payload):
                cls.wanted_path = "gre"
                cls.gre_bad_streak = 0
                cls.gre_good_streak = 0
                cls.last_reason = "reset_prefer_gre"
        logging.getLogger("sdwan").info(
            "HUMAN reset_autonomy by=%s reason=%s\n%s", approved_by, reason, out.strip()
        )
        return {
            "ok": True,
            "op": op,
            "active_override": None,
            "active_path": "gre",
            "conflict": 0,
            "apply_output": out.strip()[:500],
        }
    if op == "bgp_soft_clear":
        # REMEDIATION: one-shot soft-clear to stabilize RIB / refresh routes.
        # Do NOT reuse inject_bgp_flap.sh's multi-cycle flap loop (that induces
        # flaps for training GT). Neighbor defaults to CORE loopback.
        neighbor = str(payload.get("neighbor") or "10.1.3.1").strip()
        script = (
            f"echo REMEDIATION_ONE_SHOT_SOFT_CLEAR neighbor={neighbor}; "
            f"vtysh -c 'clear bgp {neighbor} soft'; "
            f"vtysh -c 'show bgp summary' | head -40"
        )
        out = _ssh(pe1, f"sudo bash -c {_shell_quote(script)}")
        logging.getLogger("sdwan").info(
            "HUMAN bgp_soft_clear (remediation one-shot) nbr=%s by=%s reason=%s\n%s",
            neighbor,
            approved_by,
            reason,
            out.strip(),
        )
        return {
            "ok": True,
            "op": op,
            "neighbor": neighbor,
            "intent": "remediation_stabilize_one_shot",
            "apply_output": out.strip()[:800],
        }
    if op != "force_path":
        raise ValueError(
            f"unsupported op={op!r}; use force_path|bgp_soft_clear|clear_force|reset_autonomy"
        )
    if path not in ("gre", "eth0"):
        raise ValueError("path must be gre|eth0")
    out = apply_path(pe1, path)
    with STATE.lock:
        STATE.active_path = path
        _HUMAN_FORCE = path
        _HUMAN_META = {
            "approved_by": approved_by,
            "reason": reason,
            "path": path,
        }
    logging.getLogger("sdwan").info(
        "HUMAN force_path=%s by=%s reason=%s\n%s", path, approved_by, reason, out.strip()
    )
    return {
        "ok": True,
        "op": op,
        "active_override": path,
        "active_path": path,
        "apply_output": out.strip()[:500],
        "meta": dict(_HUMAN_META),
    }


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        with STATE.lock:
            body = metrics_text(STATE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        # Localhost-only human gate for DECA orchestrator.
        if self.path.rstrip("/") != "/action":
            self.send_response(404)
            self.end_headers()
            return
        peer = self.client_address[0]
        if peer not in ("127.0.0.1", "::1"):
            body = json.dumps({"ok": False, "error": "localhost_only"}).encode()
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            if not payload.get("approved_by"):
                raise ValueError("approved_by required")
            result = apply_human_action(payload, _ACTION_PE1)
            code = 200
            out = json.dumps(result).encode()
        except Exception as exc:  # noqa: BLE001
            code = 400
            out = json.dumps({"ok": False, "error": str(exc)}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, fmt, *args):
        return


def start_metrics_server(port: int) -> HTTPServer:
    httpd = HTTPServer(("0.0.0.0", port), _MetricsHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(path),
            logging.StreamHandler(sys.stdout),
        ],
    )


def loop(pe1: str, once: bool = False) -> None:
    log = logging.getLogger("sdwan")
    log.info(
        "start multi-class ttc(lat<=%.1f jit<=%.1f loss<=%.1f) "
        "payload(lat<=%.1f jit<=%.1f loss<=%.1f) enter_k=%d exit_k=%d poll=%ds "
        "be=scavenger conflict=ttc_wins",
        TTC_LATENCY_MAX_MS,
        TTC_JITTER_MAX_MS,
        TTC_LOSS_MAX_PCT,
        PAYLOAD_LATENCY_MAX_MS,
        PAYLOAD_JITTER_MAX_MS,
        PAYLOAD_LOSS_MAX_PCT,
        ENTER_K,
        EXIT_K,
        POLL_SECONDS,
    )
    try:
        out = apply_path(pe1, "gre")
        log.info("init path=gre\n%s", out.strip())
        with STATE.lock:
            STATE.active_path = "gre"
            STATE.ttc.wanted_path = "gre"
            STATE.payload.wanted_path = "gre"
            STATE.last_reason = "init_prefer_gre"
            STATE.last_decision = "switch_to_gre"
    except Exception as e:
        log.error("init apply_path failed: %s", e)

    while not _STOP.is_set():
        t0 = time.time()
        try:
            gre, eth = probe_paths(pe1)
            with STATE.lock:
                STATE.gre, STATE.eth0 = gre, eth
                vd, vr = update_class_want(STATE.ttc, gre, eth)
                vid_d, vid_r = update_class_want(STATE.payload, gre, eth)
                new_path, conflict, resolve_r = resolve_underlay(STATE)
                prev = STATE.active_path
                STATE.conflict = conflict
                STATE.last_reason = resolve_r
                STATE.last_decision = (
                    f"hold_{new_path}" if new_path == prev else f"switch_to_{new_path}"
                )
            log.info(
                "poll gre[lat=%.2f jit=%.2f loss=%.0f] "
                "eth0[lat=%.2f jit=%.2f loss=%.0f] "
                "ttc_want=%s(%s) payload_want=%s(%s) "
                "active=%s conflict=%d | %s | %s | %s",
                gre.latency_ms,
                gre.jitter_ms,
                gre.loss_pct,
                eth.latency_ms,
                eth.jitter_ms,
                eth.loss_pct,
                STATE.ttc.wanted_path,
                vd,
                STATE.payload.wanted_path,
                vid_d,
                prev,
                conflict,
                vr,
                vid_r,
                resolve_r,
            )
            if new_path != prev:
                out = apply_path(pe1, new_path)
                with STATE.lock:
                    STATE.active_path = new_path
                    # Attribute switch to the class that drove the shared path
                    if STATE.ttc.wanted_path == new_path:
                        STATE.ttc.switch_count += 1
                    if STATE.payload.wanted_path == new_path and not conflict:
                        STATE.payload.switch_count += 1
                    if new_path == "gre":
                        STATE.ttc.gre_bad_streak = 0
                        STATE.payload.gre_bad_streak = 0
                    else:
                        STATE.ttc.gre_good_streak = 0
                        # payload may still be recovering independently
                log.info(
                    "SWITCH %s -> %s conflict=%d reason=%s\n%s",
                    prev,
                    new_path,
                    conflict,
                    resolve_r,
                    out.strip(),
                )
            try:
                with STATE.lock:
                    push_metrics_to_pe(pe1, STATE)
            except Exception as pe:
                log.warning("push metrics to PE failed: %s", pe)
        except Exception as e:
            log.exception("poll error: %s", e)

        if once:
            break
        elapsed = time.time() - t0
        _STOP.wait(max(1.0, POLL_SECONDS - elapsed))


def main() -> int:
    global _ACTION_PE1
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pe1", default=PE1)
    ap.add_argument("--once", action="store_true", help="single poll then exit")
    ap.add_argument("--metrics-port", type=int, default=METRICS_PORT)
    ap.add_argument("--log", default=str(LOG_PATH))
    args = ap.parse_args()

    _ACTION_PE1 = args.pe1
    setup_logging(Path(args.log))
    httpd = start_metrics_server(args.metrics_port)
    logging.info("metrics on :%d/metrics; POST /action localhost-only", args.metrics_port)

    def _sig(_s, _f):
        _STOP.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        loop(args.pe1, once=args.once)
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
