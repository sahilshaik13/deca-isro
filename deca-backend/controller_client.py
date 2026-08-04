"""HTTP client for SD-WAN controller /action + GNS3 mission twin."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config

GNS3_MISSION = Path(
    os.environ.get(
        "DECA_GNS3_MISSION",
        str(config.REPO_ROOT / "lab" / "gns3" / "state" / "mission_state.json"),
    )
)


def _active_fabric() -> str:
    try:
        import fabric as fabric_mod

        return (fabric_mod.get_active() or "pi").strip().lower()
    except Exception:
        return "pi"


def _read_gns3_mission() -> dict[str, Any]:
    if not GNS3_MISSION.is_file():
        return {
            "fabric": "gns3",
            "active_path": "gre",
            "human_override": None,
            "conflict": 0,
            "ttc_wanted": "gre",
            "payload_wanted": "gre",
            "last_reason": None,
            "path_latency_ms": {"gre": None, "eth0": None},
        }
    try:
        return json.loads(GNS3_MISSION.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"fabric": "gns3", "active_path": "gre", "human_override": None, "conflict": 0}


def _write_gns3_mission(data: dict[str, Any]) -> dict[str, Any]:
    GNS3_MISSION.parent.mkdir(parents=True, exist_ok=True)
    data = {**data, "fabric": "gns3", "updated_unix": time.time()}
    GNS3_MISSION.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _overlay_gns3_latencies(mission: dict[str, Any]) -> dict[str, Any]:
    """Pull live gre/eth0 RTT from GNS3 Prom exporter (not Pi controller)."""
    try:
        from prometheus_feed import _prom_base, _prom_query

        base = _prom_base()  # fabric-aware
        job = 'job="deca_gns3_fabric"'
        fab = 'fabric="gns3"'
        gre = _prom_query(f'sdwan_path_latency_ms{{{job},path="gre",{fab}}}', base)
        eth = _prom_query(f'sdwan_path_latency_ms{{{job},path="eth0",{fab}}}', base)
        loss = _prom_query(f'sdwan_path_loss_pct{{{job},path="gre",{fab}}}', base) or 0.0
        lat = dict(mission.get("path_latency_ms") or {})
        if gre is not None:
            lat["gre"] = float(gre)
        if eth is not None:
            lat["eth0"] = float(eth)
        mission["path_latency_ms"] = lat
        # Soft conflict hint when GRE delay breaches TT&C but Payload ok
        if gre is not None and gre > 25 and gre <= 80:
            mission["ttc_wanted"] = "eth0"
            mission["payload_wanted"] = "gre"  # Payload still inside ≤80ms
            mission["conflict"] = 1
        elif loss is not None and loss > 0.1 and gre is not None and gre > 25:
            mission["ttc_wanted"] = "eth0"
            # Payload only flees when loss/lat exceeds Payload SLA
            mission["payload_wanted"] = "eth0" if (loss > 2.0 or gre > 80) else "gre"
            mission["conflict"] = 1 if mission["ttc_wanted"] != mission["payload_wanted"] else 0
        elif not mission.get("human_override"):
            mission["ttc_wanted"] = "gre"
            mission["payload_wanted"] = "gre"
            if gre is not None and gre <= 25 and (loss or 0) <= 0.1:
                mission["conflict"] = 0
    except Exception:
        pass
    return mission


def post_action(
    *,
    op: str,
    path: str | None = None,
    reason: str = "orchestrator_approve",
    approved_by: str = "deca-ui",
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    if _active_fabric() == "gns3":
        return _post_gns3_action(op=op, path=path, reason=reason, approved_by=approved_by)

    url = f"{config.SDWAN_CONTROLLER_URL}/action"
    body: dict[str, Any] = {
        "op": op,
        "reason": reason,
        "approved_by": approved_by,
    }
    if path:
        body["path"] = path
    raw = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            data.setdefault("http_status", getattr(resp, "status", 200))
            return data
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {"error": detail}
        return {"ok": False, "http_status": exc.code, **parsed}
    except URLError as exc:
        return {"ok": False, "error": f"controller unreachable: {exc.reason}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _post_gns3_action(
    *,
    op: str,
    path: str | None,
    reason: str,
    approved_by: str,
) -> dict[str, Any]:
    """GNS3 twin of controller POST /action (force_path / clear / reset / soft-clear)."""
    cur = _read_gns3_mission()
    apply_note = ""
    if op == "force_path":
        if path not in ("gre", "eth0"):
            return {"ok": False, "error": "path must be gre|eth0", "fabric": "gns3"}
        cur["human_override"] = path
        cur["active_path"] = path
        cur["last_reason"] = reason or "force_path"
        apply_note = f"GNS3 mission underlay held → {path}"
    elif op in ("clear_force", "reset_autonomy"):
        cur["human_override"] = None
        cur["active_path"] = "gre"
        cur["last_reason"] = op
        cur["conflict"] = 0
        cur["ttc_wanted"] = "gre"
        cur["payload_wanted"] = "gre"
        apply_note = "GNS3 autonomy resumed → gre"
    elif op == "bgp_soft_clear":
        # Best-effort PE1 soft-clear (same as L3 inject); never blocks force_path
        try:
            import subprocess

            script = config.REPO_ROOT / "lab" / "gns3" / "inject" / "bgp_flap.sh"
            # one soft-clear cycle only
            subprocess.Popen(
                ["bash", "-c", f"CYCLES=1 PERIOD=1 bash '{script}'"],
                cwd=str(config.REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            apply_note = "GNS3 PE1 clear bgp neighbor soft (1 cycle)"
        except Exception as exc:  # noqa: BLE001
            apply_note = f"bgp_soft_clear skipped: {exc}"
    else:
        return {"ok": False, "error": f"unsupported op on GNS3: {op}", "fabric": "gns3"}

    _write_gns3_mission(cur)
    return {
        "ok": True,
        "op": op,
        "fabric": "gns3",
        "active_override": cur.get("human_override"),
        "active_path": cur.get("active_path"),
        "conflict": int(cur.get("conflict") or 0),
        "apply_output": apply_note,
        "approved_by": approved_by,
        "reason": reason,
    }


def _thresholds() -> dict[str, Any]:
    return {
        "ttc": {
            "latency_ms": 25,
            "jitter_ms": 5,
            "loss_pct": 0.1,
            "dscp": "0x88",
            "phb": "CS4",
            "tos_dec": 136,
            "htb": "1:10",
            "primary": "gre-te-core",
            "backup": "eth0",
        },
        "payload": {
            "latency_ms": 80,
            "jitter_ms": 15,
            "loss_pct": 2.0,
            "dscp": "0x80",
            "phb": "AF41",
            "tos_dec": 128,
            "htb": "1:15",
            "bw_share_pct": 70,
            "wred_util_pct": 85,
            "primary": "gre-te-core",
            "backup": "eth0",
        },
        "be": {
            "note": "admin/default — scavenger; pinned off mission MPLS; never steers",
            "dscp": "0x00",
            "phb": "BE",
            "htb": "1:20",
            "vrf": "vrf-admin",
            "vrf_ps13_alias": "vrf-default",
            "pinned": "eth0",
        },
        "hysteresis": {"enter_k": 3, "exit_k": 10},
        "governance": {
            "t_breach_warn_s": 180,
            "hitl_timeout_s": 90,
            "manual_override_supremacy": True,
            "air_gap": True,
        },
        "paths": {
            "preferred": "gre-te-core",
            "backup": "eth0",
            "ospf_pref": 5,
            "ospf_backup": 50,
        },
    }


def fetch_mission_metrics(timeout_sec: float = 5.0) -> dict[str, Any]:
    """Mission strip for NOC — Pi controller :9280 or GNS3 mission_state + Prom."""
    if _active_fabric() == "gns3":
        cur = _overlay_gns3_latencies(_read_gns3_mission())
        active = cur.get("active_path") or "gre"
        if cur.get("human_override") in ("gre", "eth0"):
            active = cur["human_override"]
        return {
            "ok": True,
            "fabric": "gns3",
            "active_path": active,
            "ttc_wanted": cur.get("ttc_wanted") or "gre",
            "payload_wanted": cur.get("payload_wanted") or "gre",
            "conflict": int(cur.get("conflict") or 0),
            "human_override": cur.get("human_override"),
            "last_reason": cur.get("last_reason"),
            "path_latency_ms": cur.get("path_latency_ms")
            or {"gre": None, "eth0": None},
            "thresholds": _thresholds(),
        }

    url = f"{config.SDWAN_CONTROLLER_URL}/metrics"
    try:
        with urlopen(url, timeout=timeout_sec) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "fabric": "pi"}

    def gauge(name: str, labels: dict[str, str]) -> float | None:
        for line in text.splitlines():
            if not line.startswith(name + "{"):
                continue
            if any(f'{k}="{v}"' not in line for k, v in labels.items()):
                continue
            try:
                return float(line.rsplit(" ", 1)[-1])
            except ValueError:
                return None
        return None

    active = "gre" if (gauge("sdwan_active_path_code", {"class": "ttc"}) or 0) >= 0.5 else "eth0"
    if gauge("sdwan_active_path_code", {"class": "ttc"}) is None:
        code = gauge("sdwan_active_path_code", {"class": "voice"})
        active = "gre" if (code or 0) >= 0.5 else "eth0"

    def wanted(cls: str) -> str:
        g = gauge("sdwan_class_wanted_path", {"class": cls, "path": "gre"})
        if g is None and cls == "ttc":
            g = gauge("sdwan_class_wanted_path", {"class": "voice", "path": "gre"})
        if g is None and cls == "payload":
            g = gauge("sdwan_class_wanted_path", {"class": "video", "path": "gre"})
        return "gre" if (g or 0) >= 0.5 else "eth0"

    conflict = gauge("sdwan_policy_conflict", {})
    if conflict is None:
        for line in text.splitlines():
            if line.startswith("sdwan_policy_conflict "):
                try:
                    conflict = float(line.split()[-1])
                except ValueError:
                    conflict = 0
                break

    human: str | None = None
    if (gauge("sdwan_human_override", {"path": "gre"}) or 0) >= 0.5:
        human = "gre"
    elif (gauge("sdwan_human_override", {"path": "eth0"}) or 0) >= 0.5:
        human = "eth0"

    last_reason = None
    for line in text.splitlines():
        if line.startswith("sdwan_last_switch_reason{") and 'class="ttc"' in line:
            m = re.search(r'reason="([^"]+)"', line)
            if m:
                last_reason = m.group(1)
            break
        if (
            line.startswith("sdwan_last_switch_reason{")
            and 'class="voice"' in line
            and last_reason is None
        ):
            m = re.search(r'reason="([^"]+)"', line)
            if m:
                last_reason = m.group(1)

    gre_lat = gauge("sdwan_path_latency_ms", {"path": "gre"})
    eth_lat = gauge("sdwan_path_latency_ms", {"path": "eth0"})

    return {
        "ok": True,
        "fabric": "pi",
        "active_path": active,
        "ttc_wanted": wanted("ttc"),
        "payload_wanted": wanted("payload"),
        "conflict": int(conflict or 0),
        "human_override": human,
        "last_reason": last_reason,
        "path_latency_ms": {"gre": gre_lat, "eth0": eth_lat},
        "thresholds": _thresholds(),
    }
