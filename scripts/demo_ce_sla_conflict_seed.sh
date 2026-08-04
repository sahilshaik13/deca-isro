#!/usr/bin/env bash
# demo_ce_sla_conflict_seed.sh — seed Decide rail with CE↔CE SLA conflict card.
#
# Safe during protocol campaign (API-only; no inject). Pair with
# inject_ce_sla_conflict.sh when station1 injectors are free.
#
# Usage:
#   bash scripts/demo_ce_sla_conflict_seed.sh
#   DECA_API=http://127.0.0.1:8000 bash scripts/demo_ce_sla_conflict_seed.sh
set -euo pipefail

API="${DECA_API:-http://127.0.0.1:8000}"
ROGUE="${ROGUE_CE:-ce-mauritius}"
VICTIM="${VICTIM_CE:-ce-a}"
ROGUE_SLA="${ROGUE_SLA:-Bronze 90%}"
VICTIM_SLA="${VICTIM_SLA:-Gold 99.9%}"
PATH_STEER="${PATH_STEER:-eth0}"

curl -sf -X POST "$API/api/v1/simulation/seed-preemption" \
  -H 'Content-Type: application/json' \
  -d "$(python3 - <<PY
import json
print(json.dumps({
  "title": "CE SLA policy conflict — Bronze surge endangering Gold TT&C",
  "host": "station1",
  "path": "$PATH_STEER",
  "confidence": 0.93,
  "eta_minutes": 2.5,
  "alert_class": "policy_drift",
  "root_cause": "ce_sla_conflict",
  "severity": "5B",
  "rogue_ce": "$ROGUE",
  "victim_ce": "$VICTIM",
  "rogue_sla": "$ROGUE_SLA",
  "victim_sla": "$VICTIM_SLA",
  "summary": (
    "Lower-SLA CE ($ROGUE, $ROGUE_SLA) bandwidth surged toward ~20 Mbps while "
    "higher-SLA CE ($VICTIM, $VICTIM_SLA) shares PE1 underlay. "
    "NOC: identify rogue consumer, protect Gold TT&C before SLA breach."
  ),
  "affected_scope": [
    "rogue: $ROGUE ($ROGUE_SLA)",
    "victim: $VICTIM ($VICTIM_SLA)",
    "PE1 station1",
    "underlay gre-te-core / eth0 backup",
  ],
  "contributing_signals": {
    "ce_util_mbps_rogue": 20.0,
    "ce_baseline_mbps": 2.5,
    "sla_availability_victim": 99.9,
    "sla_availability_rogue": 90.0,
  },
  "enrich_q3": True,
}))
PY
)" | python3 -m json.tool

echo
echo "Seeded Decide CE SLA conflict (rogue=$ROGUE → victim=$VICTIM)."
echo "Open NOC UI :3000 → Approve to force_path→$PATH_STEER."
