#!/usr/bin/env bash
# Watch Pi variant smoke → wake agent on done; 5m progress ticks.
set -euo pipefail
STAMP="${1:?stamp}"
BASE="/home/brain/deca-isro/data/deca/predictive/protocol/$STAMP"
while true; do
  if [[ -f "$BASE/ACTIVE_DONE" ]]; then
    echo "AGENT_LOOP_WAKE_variant_smoke {\"prompt\":\"Pi variant SMOKE finished stamp=$STAMP. Run predictive/verify_variant_smoke.py on that stamp. If PASS start GNS3 smoke; if FAIL diagnose before full. Do not start full yet. Keep watching.\"}"
    exit 0
  fi
  sleep 300
  nlab=$(find "$BASE" -path '*/iter_*/label.json' 2>/dev/null | wc -l)
  echo "AGENT_LOOP_TICK_variant_smoke {\"prompt\":\"Pi variant smoke stamp=$STAMP labels_done~${nlab}/12. Check campaign.log; ensure injects not flat. Brief status.\"}"
done
