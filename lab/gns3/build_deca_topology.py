#!/usr/bin/env python3
"""Build DECA GNS3 topology — scaled station architecture (15–20 nodes).

Same roles as the Pi lab Flow 1 mermaid, expanded for simulation:
  • Multiple P cores (CORE-N / CORE-S) with inter-core backbone
  • Multiple PE edges (PE1 / PE2 / PE3)
  • CEs on each PE (NRSC, Mauritius, SAC, MCF, + extras)
  • vrf-mission style: PE↔CORE MPLS/LDP preferred paths
  • vrf-admin style: PE↔PE direct backup
  • Chaos gens: IPERF-A/B + NetEM (Pi twin). No TRex.

Usage:
  python3 lab/gns3/build_deca_topology.py --wipe   # replace canvas
  python3 lab/gns3/build_deca_topology.py          # idempotent add
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

API = "http://127.0.0.1:3080/v2"
PROJECT_NAME = "DECA"


def req(method: str, path: str, body: dict | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise SystemExit(f"{method} {path} → {e.code}: {err}") from e


def ensure_templates() -> dict[str, str]:
    existing = {t["name"]: t for t in req("GET", "/templates")}
    specs = [
        {
            "name": "DECA-FRR",
            "template_type": "docker",
            "compute_id": "local",
            "image": "frrouting/frr:latest",
            "adapters": 10,
            "console_type": "telnet",
            "category": "router",
            "symbol": "router.svg",
            "start_command": "/usr/lib/frr/docker-start",
            "environment": "COLUMNS=80\nLINES=24",
            "default_name_format": "{name}",
            "usage": "FRR — P-CORE / PE (OSPF+LDP+BGP). vtysh in console.",
            "builtin": False,
        },
        {
            "name": "DECA-CE",
            "template_type": "docker",
            "compute_id": "local",
            "image": "alpine:3.20",
            "adapters": 2,
            "console_type": "telnet",
            "category": "guest",
            "symbol": "computer.svg",
            "start_command": "/bin/sh",
            "environment": "",
            "default_name_format": "{name}",
            "usage": "Branch CE — run iperf3 client/server here",
            "builtin": False,
        },
        {
            "name": "DECA-IPERF",
            "template_type": "docker",
            "compute_id": "local",
            "image": "alpine:3.20",
            "adapters": 2,
            "console_type": "telnet",
            "category": "guest",
            "symbol": "printer.svg",
            "start_command": "/bin/sh",
            "environment": "",
            "default_name_format": "{name}",
            "usage": "iperf3 host — apk add iperf3; ToS 0x88/0x80/BE",
            "builtin": False,
        },
    ]
    out: dict[str, str] = {}
    for spec in specs:
        name = spec["name"]
        if name in existing:
            tid = existing[name]["template_id"]
            # bump adapters / name format on existing FRR template
            body = dict(existing[name])
            body.update({k: spec[k] for k in spec if k != "builtin"})
            body["template_id"] = tid
            req("PUT", f"/templates/{tid}", body)
            out[name] = tid
            print(f"template updated: {name}")
        else:
            created = req("POST", "/templates", spec)
            out[name] = created["template_id"]
            print(f"template created: {name}")
    return out


def project_id() -> str:
    for p in req("GET", "/projects"):
        if p["name"] == PROJECT_NAME:
            if p["status"] != "opened":
                req("POST", f"/projects/{p['project_id']}/open")
            return p["project_id"]
    raise SystemExit(f"project {PROJECT_NAME} not found")


def wipe(pid: str) -> None:
    for link in req("GET", f"/projects/{pid}/links") or []:
        req("DELETE", f"/projects/{pid}/links/{link['link_id']}")
    for node in req("GET", f"/projects/{pid}/nodes") or []:
        req("DELETE", f"/projects/{pid}/nodes/{node['node_id']}")
        print(f"deleted {node['name']}")


def existing_nodes(pid: str) -> dict[str, dict]:
    return {n["name"]: n for n in req("GET", f"/projects/{pid}/nodes")}


def add_node(
    pid: str,
    templates: dict[str, str],
    *,
    name: str,
    template: str,
    x: int,
    y: int,
) -> dict:
    nodes = existing_nodes(pid)
    if name in nodes:
        print(f"node exists: {name}")
        return nodes[name]
    tmpl = next(t for t in req("GET", "/templates") if t["name"] == template)
    body = {
        "name": name,
        "node_type": "docker",
        "compute_id": "local",
        "x": x,
        "y": y,
        "template_id": templates[template],
        "properties": {
            "image": tmpl["image"],
            "adapters": tmpl.get("adapters", 2),
            "console_type": tmpl.get("console_type", "telnet"),
            "start_command": tmpl.get("start_command") or "",
            "environment": tmpl.get("environment") or "",
        },
    }
    n = req("POST", f"/projects/{pid}/nodes", body)
    if n.get("name") != name:
        props = dict(n.get("properties") or {})
        req(
            "PUT",
            f"/projects/{pid}/nodes/{n['node_id']}",
            {"name": name, "properties": props, "x": x, "y": y},
        )
        n["name"] = name
    print(f"node created: {name}")
    return n


def link_exists(pid: str, a_id: str, a_adapter: int, b_id: str, b_adapter: int) -> bool:
    for link in req("GET", f"/projects/{pid}/links"):
        nodes = link.get("nodes") or []
        if len(nodes) != 2:
            continue
        ends = {(n["node_id"], n["adapter_number"]) for n in nodes}
        if ends == {(a_id, a_adapter), (b_id, b_adapter)}:
            return True
    return False


def add_link(
    pid: str, a: dict, a_adapter: int, b: dict, b_adapter: int, *, label: str = ""
) -> None:
    if link_exists(pid, a["node_id"], a_adapter, b["node_id"], b_adapter):
        print(f"link exists: {a['name']}:{a_adapter} <-> {b['name']}:{b_adapter}")
        return
    body = {
        "nodes": [
            {"node_id": a["node_id"], "adapter_number": a_adapter, "port_number": 0},
            {"node_id": b["node_id"], "adapter_number": b_adapter, "port_number": 0},
        ]
    }
    req("POST", f"/projects/{pid}/links", body)
    tag = f" [{label}]" if label else ""
    print(f"link: {a['name']}:{a_adapter} <-> {b['name']}:{b_adapter}{tag}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--wipe",
        action="store_true",
        help="Delete all nodes/links in DECA then rebuild full fabric",
    )
    args = ap.parse_args()

    templates = ensure_templates()
    pid = project_id()
    print(f"project={PROJECT_NAME} id={pid}")
    if args.wipe:
        wipe(pid)

    # ----- Canvas layout (approx matches NOC map, scaled) -----
    # P cores (station3 dual-P in GNS3 — Pi as-built is single CORE)
    core_n = add_node(pid, templates, name="CORE-N", template="DECA-FRR", x=-40, y=-120)
    core_s = add_node(pid, templates, name="CORE-S", template="DECA-FRR", x=-40, y=120)

    # PE edges
    pe1 = add_node(pid, templates, name="PE1", template="DECA-FRR", x=-420, y=0)
    pe2 = add_node(pid, templates, name="PE2", template="DECA-FRR", x=360, y=0)
    pe3 = add_node(pid, templates, name="PE3", template="DECA-FRR", x=-40, y=280)

    # CEs — station1 side (PE1)
    nrsc = add_node(pid, templates, name="CE-NRSC", template="DECA-CE", x=-620, y=-160)
    mau = add_node(pid, templates, name="CE-Mauritius", template="DECA-CE", x=-620, y=40)
    shad = add_node(pid, templates, name="CE-Shadnagar", template="DECA-CE", x=-620, y=180)

    # CEs — station2 side (PE2)
    sac = add_node(pid, templates, name="CE-SAC", template="DECA-CE", x=560, y=-160)
    mcf = add_node(pid, templates, name="CE-MCF", template="DECA-CE", x=560, y=40)
    istrac = add_node(pid, templates, name="CE-ISTRAC", template="DECA-CE", x=560, y=180)

    # CEs — PE3 regional
    hq = add_node(pid, templates, name="CE-ISRO-HQ", template="DECA-CE", x=-200, y=400)
    bhopal = add_node(pid, templates, name="CE-Bhopal", template="DECA-CE", x=120, y=400)

    # Chaos gens sit on CE LANs (Flow 1: traffic enters at branch CE, exits DC CE).
    # Critical path = iperf3 + NetEM only (no TRex).
    iperf_a = add_node(pid, templates, name="IPERF-A", template="DECA-IPERF", x=-560, y=-280)
    iperf_b = add_node(pid, templates, name="IPERF-B", template="DECA-IPERF", x=720, y=-280)

    # ----- Links: vrf-mission preferred (PE <-> dual CORE, MPLS/LDP stand-in) -----
    add_link(pid, pe1, 0, core_n, 0, label="vrf-mission / MPLS north")
    add_link(pid, pe1, 1, core_s, 0, label="vrf-mission / MPLS south")
    add_link(pid, pe2, 0, core_n, 1, label="vrf-mission / MPLS north")
    add_link(pid, pe2, 1, core_s, 1, label="vrf-mission / MPLS south")
    add_link(pid, pe3, 0, core_n, 2, label="vrf-mission / MPLS")
    add_link(pid, pe3, 1, core_s, 2, label="vrf-mission / MPLS")

    # Inter-core backbone
    add_link(pid, core_n, 3, core_s, 3, label="inter-core backbone")

    # ----- Links: vrf-admin direct backup (PE <-> PE eth0-style) -----
    add_link(pid, pe1, 2, pe2, 2, label="vrf-admin direct backup")
    add_link(pid, pe1, 3, pe3, 2, label="vrf-admin PE1-PE3")
    add_link(pid, pe2, 3, pe3, 3, label="vrf-admin PE2-PE3")

    # ----- CE local attach -----
    add_link(pid, nrsc, 0, pe1, 4, label="CE attach")
    add_link(pid, mau, 0, pe1, 5, label="CE attach")
    add_link(pid, shad, 0, pe1, 6, label="CE attach")

    add_link(pid, sac, 0, pe2, 4, label="CE attach")
    add_link(pid, mcf, 0, pe2, 5, label="CE attach")
    add_link(pid, istrac, 0, pe2, 6, label="CE attach")

    add_link(pid, hq, 0, pe3, 4, label="CE attach")
    add_link(pid, bhopal, 0, pe3, 5, label="CE attach")

    # ----- Chaos gens (Flow 1: branch CE → fabric → DC CE) -----
    # iperf3: LAN behind CE-NRSC → PE1 → CORE → PE2 → CE-SAC LAN
    add_link(pid, iperf_a, 0, nrsc, 1, label="iperf3 → branch CE-NRSC LAN")
    add_link(pid, iperf_b, 0, sac, 1, label="iperf3 ← DC CE-SAC LAN")

    nlist = req("GET", f"/projects/{pid}/nodes")
    llist = req("GET", f"/projects/{pid}/links")
    print(f"\nOK nodes={len(nlist)} links={len(llist)}")
    print("Refresh GNS3 canvas. Start all nodes, then:")
    print("  iperf3: IPERF-A --CE-NRSC--> PE1-->CORE-->PE2 --CE-SAC--> IPERF-B")
    print("  NetEM / BGP / CPU / util: lab/gns3/inject/* (shared fault book with Pi)")
    print("  See lab/gns3/TOPOLOGY.md · docs/shared_fault_book.json")
    # Drop leftover TRex node if present from older builds
    for n in nlist or []:
        if (n.get("name") or "").upper() == "TREX":
            try:
                req("DELETE", f"/projects/{pid}/nodes/{n['node_id']}")
                print("removed leftover TRex node from canvas")
            except Exception as exc:
                print(f"WARN: could not delete TRex node: {exc}")


if __name__ == "__main__":
    main()
