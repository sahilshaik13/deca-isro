"""ce_surge_detect.py — per-CE bandwidth anomaly (mentor: quiet 2–3 → ~20 Mbps).

Polls Prometheus for ce_util_mbps (or falls back to path util + demo mode).
When a Bronze/low-tier CE sustains util >= fire threshold while a Gold peer
is not the surging source, POST seed-preemption with rogue/victim fields.

Usage:
  .venv-predictive/bin/python -m predictive.ce_surge_detect --once
  .venv-predictive/bin/python -m predictive.ce_surge_detect --seconds 0
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

# CE SLA catalog (must match docs/EDGE_POLICY_LAYERS.md §2)
CE_SLA: dict[str, dict[str, Any]] = {
    "ce-a": {"site": "NRSC", "tier": "Gold", "availability": 99.9, "host": "station1"},
    "ce-b": {"site": "SAC", "tier": "Silver", "availability": 99.5, "host": "station2"},
    "ce-mauritius": {
        "site": "Mauritius",
        "tier": "Bronze",
        "availability": 90.0,
        "host": "station1",
    },
    "ce-mcf": {"site": "MCF", "tier": "Bronze", "availability": 90.0, "host": "station2"},
}

GOLD_VICTIM = "ce-a"
DEFAULT_BASELINE = 2.5
DEFAULT_FIRE = 15.0


def _prom_query(prom: str, query: str) -> list[dict[str, Any]]:
    url = f"{prom.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = json.loads(resp.read().decode())
    if body.get("status") != "success":
        return []
    return body.get("data", {}).get("result") or []


def fetch_ce_utils(prom: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in _prom_query(prom, "ce_util_mbps"):
        metric = row.get("metric") or {}
        ce = metric.get("ce")
        try:
            val = float((row.get("value") or [0, "nan"])[1])
        except (TypeError, ValueError):
            continue
        if ce:
            out[ce] = val
    return out


def pick_conflict(
    utils: dict[str, float],
    *,
    fire_mbps: float,
    baseline_mbps: float,
) -> Optional[dict[str, Any]]:
    """Return rogue/victim dict if a lower-tier CE is surging."""
    surging = [
        (ce, mbps)
        for ce, mbps in utils.items()
        if mbps >= fire_mbps and CE_SLA.get(ce, {}).get("tier") in {"Bronze", "Silver"}
    ]
    if not surging:
        return None
    surging.sort(key=lambda x: -x[1])
    rogue_ce, rogue_mbps = surging[0]
    victim_ce = GOLD_VICTIM
    # Prefer a Gold CE that is NOT the surger and shares host or is catalog Gold
    for ce, meta in CE_SLA.items():
        if meta.get("tier") == "Gold" and ce != rogue_ce:
            victim_ce = ce
            break
    rogue_meta = CE_SLA[rogue_ce]
    victim_meta = CE_SLA[victim_ce]
    return {
        "rogue_ce": rogue_ce,
        "victim_ce": victim_ce,
        "rogue_sla": f"{rogue_meta['tier']} {rogue_meta['availability']}%",
        "victim_sla": f"{victim_meta['tier']} {victim_meta['availability']}%",
        "rogue_mbps": rogue_mbps,
        "baseline_mbps": baseline_mbps,
        "host": rogue_meta.get("host") or "station1",
        "site_rogue": rogue_meta.get("site"),
        "site_victim": victim_meta.get("site"),
    }


def seed_decide(api: str, conflict: dict[str, Any], *, dry: bool = False) -> dict[str, Any]:
    body = {
        "title": (
            f"CE bandwidth anomaly — {conflict['rogue_ce']} surge "
            f"({conflict['rogue_mbps']:.1f} Mbps) vs {conflict['victim_ce']}"
        ),
        "host": conflict["host"],
        "path": "eth0",
        "confidence": 0.9,
        "eta_minutes": 3.0,
        "alert_class": "policy_drift",
        "root_cause": "ce_sla_conflict",
        "severity": "5B",
        "rogue_ce": conflict["rogue_ce"],
        "victim_ce": conflict["victim_ce"],
        "rogue_sla": conflict["rogue_sla"],
        "victim_sla": conflict["victim_sla"],
        "summary": (
            f"{conflict['site_rogue']} CE ({conflict['rogue_ce']}, {conflict['rogue_sla']}) "
            f"jumped from ~{conflict['baseline_mbps']} Mbps quiet baseline to "
            f"{conflict['rogue_mbps']:.1f} Mbps, endangering "
            f"{conflict['site_victim']} ({conflict['victim_ce']}, {conflict['victim_sla']}). "
            "NOC: name rogue CE, protect Gold SLA."
        ),
        "affected_scope": [
            f"rogue: {conflict['rogue_ce']} ({conflict['rogue_sla']})",
            f"victim: {conflict['victim_ce']} ({conflict['victim_sla']})",
            f"PE {conflict['host']}",
        ],
        "contributing_signals": {
            "ce_util_mbps_rogue": float(conflict["rogue_mbps"]),
            "ce_baseline_mbps": float(conflict["baseline_mbps"]),
        },
        "enrich_q3": True,
    }
    if dry:
        return {"dry": True, "body": body}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/v1/simulation/seed-preemption",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prom", default="http://127.0.0.1:9091")
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--fire-mbps", type=float, default=DEFAULT_FIRE)
    p.add_argument("--baseline-mbps", type=float, default=DEFAULT_BASELINE)
    p.add_argument("--hold-samples", type=int, default=30, help="Consecutive fires before seed")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--seconds", type=float, default=0.0, help="0 = forever")
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--cooldown-sec", type=float, default=300.0)
    args = p.parse_args(argv)

    streak = 0
    last_seed = 0.0
    t0 = time.time()
    while True:
        try:
            utils = fetch_ce_utils(args.prom)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"prom query failed: {exc}", file=sys.stderr)
            utils = {}

        conflict = pick_conflict(
            utils, fire_mbps=args.fire_mbps, baseline_mbps=args.baseline_mbps
        )
        if conflict:
            streak += 1
            print(
                f"surge streak={streak}/{args.hold_samples} "
                f"{conflict['rogue_ce']}={conflict['rogue_mbps']:.2f} Mbps"
            )
        else:
            if streak:
                print(f"surge cleared (was streak={streak}) utils={utils}")
            streak = 0

        if conflict and streak >= args.hold_samples:
            now = time.time()
            if now - last_seed >= args.cooldown_sec:
                try:
                    res = seed_decide(args.api, conflict, dry=args.dry_run)
                    print("seeded", json.dumps(res)[:400])
                    last_seed = now
                    streak = 0
                except Exception as exc:  # noqa: BLE001
                    print(f"seed failed: {exc}", file=sys.stderr)
            else:
                print(f"cooldown {args.cooldown_sec - (now - last_seed):.0f}s remaining")

        if args.once:
            return 0
        if args.seconds > 0 and (time.time() - t0) >= args.seconds:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
