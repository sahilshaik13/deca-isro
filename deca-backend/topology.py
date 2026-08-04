"""Static lab topology + blast-radius for Decide `affected_scope` (PS13-O4.1 partial).

Graph is small and static; blast radius is computed from adjacency, not
hardcoded per alert class. This is **not** a learned / streaming graph
correlation engine — see FINDINGS O4.1 downgrade.
NOC map layouts live in topology_layouts.json.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

_LAYOUTS_PATH = Path(__file__).resolve().parent / "topology_layouts.json"

# Directed edges: traffic / dependency direction Branch → PE → CORE → PE → sites
# eth0 is an alternate underlay between PEs (backup edge).
EDGES: list[tuple[str, str]] = [
    ("ce-a", "pe1"),
    ("ce-mauritius", "pe1"),
    ("pe1", "core"),
    ("core", "pe2"),
    ("pe2", "ce-b"),
    ("pe2", "ce-mcf"),
    ("pe1", "pe2"),  # eth0 backup underlay (direct)
]

GNS3_EDGES: list[tuple[str, str]] = [
    ("ce-a", "pe1"),
    ("ce-mauritius", "pe1"),
    ("ce-shadnagar", "pe1"),
    ("pe1", "core-n"),
    ("pe1", "core-s"),
    ("core-n", "pe2"),
    ("core-s", "pe2"),
    ("core-n", "core-s"),
    ("pe2", "ce-b"),
    ("pe2", "ce-mcf"),
    ("pe2", "ce-istrac"),
    ("pe3", "core-n"),
    ("ce-hq", "pe3"),
    ("ce-bhopal", "pe3"),
    ("pe1", "pe2"),
]

# Human-readable labels for Decide UI
NODE_LABELS: dict[str, str] = {
    "ce-a": "NRSC Branch CE (ce-a)",
    "ce-mauritius": "Mauritius CE (ce-mauritius)",
    "pe1": "PE1 station1",
    "pe2": "PE2 station2",
    "core": "CORE station3",
    "ce-b": "SAC Datacenter CE (ce-b)",
    "ce-mcf": "MCF Hub CE (ce-mcf)",
}

GNS3_NODE_LABELS: dict[str, str] = {
    **NODE_LABELS,
    "core": "CORE-N (primary P)",
    "core-n": "CORE-N (primary P)",
    "core-s": "CORE-S (optional dual-P)",
    "pe3": "PE3",
    "ce-shadnagar": "CE-Shadnagar",
    "ce-istrac": "CE-ISTRAC",
    "ce-hq": "CE-ISRO-HQ",
    "ce-bhopal": "CE-Bhopal",
}

HOST_TO_NODE: dict[str, str] = {
    "station1": "pe1",
    "station2": "pe2",
    "station3": "core",
    "pe1": "pe1",
    "pe2": "pe2",
    "pe3": "pe3",
    "core": "core",
    "core-n": "core-n",
    "gns3-pe1": "pe1",
    "gns3-pe2": "pe2",
}


@lru_cache(maxsize=1)
def _layouts_doc() -> dict[str, Any]:
    try:
        return json.loads(_LAYOUTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"fabrics": {}}


def layout(fabric: str | None = None) -> dict[str, Any]:
    """NOC SVG layout for the active (or requested) fabric."""
    fab = (fabric or "pi").strip().lower()
    if fab not in ("pi", "gns3"):
        fab = "pi"
    fabrics = _layouts_doc().get("fabrics") or {}
    data = fabrics.get(fab) or fabrics.get("pi") or {}
    return {"fabric": fab, **data}


def adjacency(fabric: str | None = None) -> dict[str, list[str]]:
    fab = (fabric or "pi").strip().lower()
    if fab == "gns3":
        labels = GNS3_NODE_LABELS
        edges = GNS3_EDGES
    else:
        labels = NODE_LABELS
        edges = EDGES
    g: dict[str, list[str]] = {n: [] for n in labels}
    for a, b in edges:
        g.setdefault(a, []).append(b)
        g.setdefault(b, [])
    return g


def resolve_fault_node(
    *,
    host: str = "",
    path: str = "",
    alert_class: str = "",
    fabric: str | None = None,
) -> str:
    """Map alert host/path/class → topology node that failed."""
    h = (host or "").strip().lower()
    fab = (fabric or "pi").strip().lower()
    if h in HOST_TO_NODE:
        node = HOST_TO_NODE[h]
        if fab == "gns3" and node == "core":
            return "core-n"
        return node
    if (path or "").lower() == "gre":
        if fab == "gns3":
            return "core-n"
        return "core" if "station3" in h else HOST_TO_NODE.get(h, "pe1")
    return HOST_TO_NODE.get(h, "pe1")


def blast_radius(fault_node: str, fabric: str | None = None) -> list[str]:
    """Downstream nodes reachable from fault_node (including itself)."""
    g = adjacency(fabric)
    if fault_node not in g:
        return [fault_node]
    seen: set[str] = set()
    stack = [fault_node]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(g.get(n, []))
    rest = sorted(seen - {fault_node})
    return [fault_node] + rest


def _labels(fabric: str | None = None) -> dict[str, str]:
    return GNS3_NODE_LABELS if (fabric or "pi") == "gns3" else NODE_LABELS


def affected_scope(
    *,
    host: str = "",
    path: str = "",
    alert_class: str = "",
    fabric: str | None = None,
) -> list[str]:
    """Decide payload list: human labels for blast radius."""
    node = resolve_fault_node(
        host=host, path=path, alert_class=alert_class, fabric=fabric
    )
    nodes = blast_radius(node, fabric=fabric)
    labels = _labels(fabric)
    return [labels.get(n, n) for n in nodes]


def affected_scope_ids(
    host: str = "",
    path: str = "",
    alert_class: str = "",
    fabric: str | None = None,
) -> list[str]:
    node = resolve_fault_node(
        host=host, path=path, alert_class=alert_class, fabric=fabric
    )
    return blast_radius(node, fabric=fabric)


def undirected_adjacency(fabric: str | None = None) -> dict[str, set[str]]:
    labels = _labels(fabric)
    edges = GNS3_EDGES if (fabric or "pi") == "gns3" else EDGES
    g: dict[str, set[str]] = {n: set() for n in labels}
    for a, b in edges:
        g.setdefault(a, set()).add(b)
        g.setdefault(b, set()).add(a)
    return g


def nodes_related(a: str, b: str, fabric: str | None = None) -> bool:
    """True if faults on a and b share a directed path / blast overlap."""
    if a == b:
        return True
    ra, rb = set(blast_radius(a, fabric)), set(blast_radius(b, fabric))
    if a in rb or b in ra or (ra & rb):
        return True
    u = undirected_adjacency(fabric)
    return b in u.get(a, set())


def correlate_with_active(
    *,
    host: str = "",
    path: str = "",
    alert_class: str = "",
    active_alerts: Iterable[dict],
    exclude_alert_id: int | None = None,
    max_age_sec: float = 1800.0,
    max_correlated: int = 5,
    fabric: str | None = None,
) -> dict:
    """Merge blast-radius with other active alerts that share topology."""
    from datetime import datetime, timezone

    fault = resolve_fault_node(
        host=host, path=path, alert_class=alert_class, fabric=fabric
    )
    nodes: set[str] = set(blast_radius(fault, fabric=fabric))
    correlated: list[int] = []
    reasons: list[str] = []
    peer_nodes: set[str] = set()
    now = datetime.now(timezone.utc)
    labels = _labels(fabric)

    def _fresh(a: dict) -> bool:
        ts = a.get("ts") or ""
        if not ts:
            return True
        try:
            raw = str(ts).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).total_seconds() <= max_age_sec
        except ValueError:
            return True

    for a in active_alerts:
        aid = a.get("id") or a.get("alert_id")
        if exclude_alert_id is not None and aid == exclude_alert_id:
            continue
        if (a.get("status") or "active") not in ("active", None, ""):
            continue
        if not _fresh(a):
            continue
        other = resolve_fault_node(
            host=str(a.get("host") or ""),
            path="",
            alert_class=str(a.get("class") or ""),
            fabric=fabric,
        )
        if not nodes_related(fault, other, fabric=fabric):
            continue
        if aid is not None:
            correlated.append(int(aid))
        peer_nodes.add(other)
        nodes.update(blast_radius(other, fabric=fabric))
        reasons.append(
            f"{labels.get(fault, fault)} correlates with "
            f"{labels.get(other, other)} (alert {aid})"
        )
        if len(correlated) >= max_correlated:
            break

    clique = {fault} | peer_nodes
    urgency_boost = 1 if len(clique) >= 2 else 0

    ordered = [fault] + sorted(nodes - {fault})
    return {
        "fault_node": fault,
        "affected_scope": [labels.get(n, n) for n in ordered],
        "correlated_alert_ids": correlated,
        "correlation_reason": "; ".join(reasons) if reasons else "",
        "urgency_boost": urgency_boost,
        "clique_nodes": sorted(clique),
    }
