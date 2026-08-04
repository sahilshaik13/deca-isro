"""Active simulation fabric for the NOC (Pi lab vs GNS3).

Persists to data/deca/active_fabric.json so UI + inject + infer share one source.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

import config

FabricId = Literal["pi", "gns3"]
FABRICS: tuple[FabricId, ...] = ("pi", "gns3")

FABRIC_PATH = Path(
    os.environ.get(
        "DECA_ACTIVE_FABRIC_PATH",
        str(config.REPO_ROOT / "data" / "deca" / "active_fabric.json"),
    )
).resolve()

_lock = threading.Lock()

_CONTRACT_PATH = config.REPO_ROOT / "docs" / "edge_policy_contract.json"
_contract_cache: dict[str, Any] | None = None


def edge_policy_contract() -> dict[str, Any]:
    """Shared CE/PE/P/network contract (same budgets on Pi and GNS3)."""
    global _contract_cache
    if _contract_cache is not None:
        return _contract_cache
    try:
        _contract_cache = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _contract_cache = {}
    return _contract_cache


def _default() -> FabricId:
    raw = os.environ.get("DECA_FABRIC", "pi").strip().lower()
    return raw if raw in FABRICS else "pi"  # type: ignore[return-value]


def get_active() -> FabricId:
    with _lock:
        if FABRIC_PATH.is_file():
            try:
                data = json.loads(FABRIC_PATH.read_text(encoding="utf-8"))
                active = str(data.get("active") or "").strip().lower()
                if active in FABRICS:
                    return active  # type: ignore[return-value]
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return _default()


def set_active(fabric: str, *, set_by: str = "deca-ui") -> dict[str, Any]:
    fabric = str(fabric or "").strip().lower()
    if fabric not in FABRICS:
        return {
            "ok": False,
            "error": f"unknown fabric={fabric!r}; expected one of {list(FABRICS)}",
        }
    payload = {
        "active": fabric,
        "set_by": set_by,
        "fabrics": list(FABRICS),
    }
    with _lock:
        FABRIC_PATH.parent.mkdir(parents=True, exist_ok=True)
        FABRIC_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **payload, **describe(fabric)}  # type: ignore[arg-type]


def sla_profile(fabric: FabricId | None = None) -> dict[str, Any]:
    """AAR + CE SLA budgets — same numbers on Pi and GNS3 (mentor-aligned)."""
    active = fabric or get_active()
    c = edge_policy_contract()
    fab_meta = (c.get("fabrics") or {}).get(active) or {}
    classes = c.get("classes") or {
        "ttc": {
            "latency_ms": 25,
            "jitter_ms": 5,
            "loss_pct": 0.1,
            "tos": "0x88",
            "vrf": "vrf-mission",
            "primary": "gre-te-core",
            "backup": "eth0",
        },
        "payload": {
            "latency_ms": 80,
            "jitter_ms": 15,
            "loss_pct": 2.0,
            "tos": "0x80",
            "vrf": "vrf-mission",
            "primary": "gre-te-core",
            "backup": "eth0",
        },
        "admin": {
            "tos": "0x00",
            "vrf": "vrf-admin",
            "primary": "eth0",
            "backup": None,
        },
    }
    ce_tiers = c.get("ce_tiers") or {
        "ce-a": {"site": "NRSC", "tier": "Gold", "availability": 99.9},
        "ce-b": {"site": "SAC", "tier": "Silver", "availability": 99.5},
        "ce-mauritius": {
            "site": "Mauritius",
            "tier": "Bronze",
            "availability": 90.0,
        },
        "ce-mcf": {"site": "MCF", "tier": "Bronze", "availability": 90.0},
    }
    # API keeps compact CE tier fields for Decide / UI.
    ce_out = {
        k: {
            "site": v.get("site"),
            "tier": v.get("tier"),
            "availability": v.get("availability"),
        }
        for k, v in ce_tiers.items()
    }
    return {
        "fabric": active,
        "label": fab_meta.get(
            "label",
            "Pi live SLAs (production-like)"
            if active == "pi"
            else "GNS3 sim SLAs (aligned to Pi / mentor)",
        ),
        "classes": classes,
        "ce_tiers": ce_out,
        "layers": c.get("layers") or {},
        "wire": c.get("wire") or {},
        "conflict_priority": c.get("conflict_priority")
        or ["TT&C", "Gold", "Payload", "Silver", "Admin", "Bronze"],
        "chaos": fab_meta.get(
            "chaos",
            ["iperf3", "netem"]
            if active == "pi"
            else ["iperf3", "netem", "stress-ng", "bgp_soft_clear"],
        ),
    }


def prometheus_urls() -> dict[str, str]:
    """Dual Flow 2 Prometheus bases (Pi host :9090, GNS3 compose :9091)."""
    pi = os.environ.get(
        "DECA_PROM_URL_PI",
        os.environ.get("DECA_PROM_URL", "http://127.0.0.1:9090"),
    ).rstrip("/")
    gns3 = os.environ.get("DECA_PROM_URL_GNS3", "http://127.0.0.1:9091").rstrip(
        "/"
    )
    return {"pi": pi, "gns3": gns3}


def prom_url_for(fabric: FabricId | None = None) -> str:
    active = fabric or get_active()
    return prometheus_urls()[active]


def describe(fabric: FabricId | None = None) -> dict[str, Any]:
    active = fabric or get_active()
    prom = prometheus_urls()
    import topology as topology_mod

    exporter_ok = False
    if active == "gns3":
        try:
            import requests

            r = requests.get("http://127.0.0.1:9275/metrics", timeout=1.5)
            exporter_ok = r.status_code == 200
        except Exception:
            exporter_ok = False

    return {
        "active": active,
        "sla": sla_profile(active),
        "topology": topology_mod.layout(active),
        "prometheus": {
            "active": prom_url_for(active),
            "pi": prom["pi"],
            "gns3": prom["gns3"],
            "kafka_topics": {
                "pi": "sdwan_telemetry_pi",
                "gns3": "sdwan_telemetry_gns3",
            },
            "bridges": {
                "pi": "http://127.0.0.1:9274/metrics",
                "gns3": "http://127.0.0.1:9276/metrics",
            },
            "gns3_exporter": "http://127.0.0.1:9275/metrics",
            "gns3_exporter_ok": exporter_ok if active == "gns3" else None,
        },
        "flow": {
            "summary": (
                "NOC: select fabric → Start traffic → Simple fault → watch map/"
                "telemetry → Decide Approve. Chaos(iperf3|NetEM) → CE → HTB+AAR+"
                "IPsec → PE → vrf-mission CORE or vrf-admin eth0."
            ),
            "controller": "http://127.0.0.1:9280",
            "telemetry": (
                "SNMP+syslog+IPFIX+1Hz → Telegraf → Kafka (per-fabric topic) → "
                "bridge → Prom (:9090 Pi / :9091 GNS3) → Q1/Q2"
            ),
        },
        "fabrics": [
            {
                "id": "pi",
                "label": "Pi stations",
                "blurb": "Live Raspberry Pi SD-WAN fabric (station1–3)",
                "ready": True,
                "sla_label": "TT&C≤25ms · Gold 99.9%",
                "prometheus": prom["pi"],
            },
            {
                "id": "gns3",
                "label": "GNS3 sim",
                "blurb": "Headless GNS3 nodes · drive from NOC (no GUI required)",
                "ready": gns3_ready(),
                "sla_label": "TT&C≤25ms · Gold 99.9% (aligned)",
                "prometheus": prom["gns3"],
            },
        ],
        "edge_policy": {
            "doc": "docs/EDGE_POLICY_LAYERS.md",
            "contract": "docs/edge_policy_contract.json",
            "aligned_budgets": True,
        },
        "storage": {
            "gns3_root": os.environ.get(
                "DECA_GNS3_ROOT", "/media/brain/Shaik's/gns3"
            ),
            "gns3_mounted": _gns3_drive_mounted(),
        },
    }


def status() -> dict[str, Any]:
    return describe(get_active())


def _gns3_drive_mounted() -> bool:
    root = Path(
        os.environ.get("DECA_GNS3_ROOT", "/media/brain/Shaik's/gns3")
    )
    # Parent is the mount point with the apostrophe path
    drive = root.parent if root.name == "gns3" else root
    return drive.is_dir()


def gns3_ready() -> bool:
    """True when external storage exists and a project marker is present."""
    if not _gns3_drive_mounted():
        return False
    root = Path(os.environ.get("DECA_GNS3_ROOT", "/media/brain/Shaik's/gns3"))
    marker = root / "projects" / "DECA_READY"
    return marker.is_file()


def _gns3_ready() -> bool:
    return gns3_ready()


def prom_label_selector(fabric: FabricId | None = None) -> str:
    """PromQL label fragment for the active fabric (empty = no filter).

    Pi metrics historically omit `fabric=`; leave unfiltered until exporters
    stamp fabric=\"pi\". GNS3 always requires fabric=\"gns3\".
    """
    active = fabric or get_active()
    if active == "gns3":
        return 'fabric="gns3"'
    return ""


def env_fabric_export() -> str:
    """Value for DECA_FABRIC env used by infer / adapters."""
    return get_active()


def default_run_id(fabric: FabricId | None = None) -> str:
    """Canonical Decide run id per fabric (keeps Pi/GNS3 alert history separate)."""
    fab = fabric or get_active()
    return "sim-gns3" if fab == "gns3" else "sim-live"


def host_belongs(host: str | None, fabric: FabricId | None = None) -> bool:
    """True if alert/tick host belongs on the given fabric."""
    fab = fabric or get_active()
    h = str(host or "").strip().lower()
    if not h:
        return True
    if fab == "gns3":
        return h.startswith("gns3")
    return h.startswith("station")


def filter_rows_for_fabric(
    rows: list[dict],
    fabric: FabricId | None = None,
    *,
    host_key: str = "host",
) -> list[dict]:
    """Drop cross-fabric hosts (station* on GNS3, gns3-* on Pi)."""
    fab = fabric or get_active()
    out: list[dict] = []
    for row in rows or []:
        hs = str(row.get(host_key) or "").lower()
        if fab == "gns3" and hs.startswith("station"):
            continue
        if fab == "pi" and hs.startswith("gns3"):
            continue
        out.append(row)
    return out


def switch_cleanup(prev: str, new: str) -> dict[str, Any]:
    """Stop demos on previous fabric and bind the Decide run for the new one."""
    notes: list[str] = []
    if prev == new:
        return {
            "ok": True,
            "notes": ["same fabric"],
            "run_id": default_run_id(new),  # type: ignore[arg-type]
        }

    try:
        import traffic_demo

        traffic_demo.stop(reason=f"fabric_switch:{prev}->{new}", fabric=prev)
        notes.append(f"traffic stopped on {prev}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"traffic stop: {exc}")

    try:
        import fault_demo

        fault_demo.clear(reason=f"fabric_switch:{prev}->{new}", fabric=prev)
        notes.append(f"faults cleared on {prev}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"fault clear: {exc}")

    try:
        import simulation_runner

        st = simulation_runner.status()
        if st.get("running") and str(st.get("fabric") or prev) == prev:
            simulation_runner.stop(reason=f"fabric_switch:{prev}->{new}")
            notes.append(f"timeline stopped on {prev}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"sim stop: {exc}")

    run_id = default_run_id(new)  # type: ignore[arg-type]
    try:
        import repos

        repos.set_active_run(run_id, mode="live", notes=f"fabric_switch to {new}")
        notes.append(f"bound run {run_id}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"run bind: {exc}")

    return {"ok": True, "notes": notes, "run_id": run_id, "prev": prev, "active": new}
