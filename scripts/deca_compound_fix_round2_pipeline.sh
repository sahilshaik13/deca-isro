#!/usr/bin/env bash
# Wait for compound_fix_r2 campaign, then rebuild + isolated eval.
# Does NOT promote. All artifacts under models/experiments/compound_fix_round_2/.
set -euo pipefail
cd /home/brain/deca-isro
source .venv/bin/activate
export PYTHONPATH=scripts

RUN_ID="${1:-compound_fix_r2_20260722_0435}"
CAMP_PID="${2:-}"
LOG=/tmp/deca_compound_fix_r2.log
PIPE_LOG=/tmp/deca_compound_fix_r2_pipeline.log
OUT=models/experiments/compound_fix_round_2

exec > >(tee -a "$PIPE_LOG") 2>&1

echo "=== PIPELINE START $(date -u -Iseconds) run_id=$RUN_ID camp_pid=${CAMP_PID:-unknown} ==="

if [[ -n "$CAMP_PID" ]]; then
  echo "Waiting for campaign pid $CAMP_PID..."
  while kill -0 "$CAMP_PID" 2>/dev/null; do
    sleep 60
    # progress breadcrumb
    if [[ -f "$LOG" ]]; then
      tail -n 2 "$LOG" | sed 's/^/  [camp] /'
    fi
  done
  echo "Campaign process exited."
fi

# Ensure campaign finished cleanly
if ! grep -q "COMPOUND OVERLAP CAMPAIGN DONE" "$LOG" 2>/dev/null; then
  echo "ERROR: campaign log missing DONE marker — check $LOG"
  tail -n 80 "$LOG" || true
  exit 1
fi

# Record campaign completion into meta
python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
p = Path("$OUT/campaign_meta.json")
meta = json.loads(p.read_text())
meta["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
meta["log"] = "$LOG"
# count completed legs from fault log
import csv
log = Path("data/rpi-net/runs/$RUN_ID/fault_injection_log.csv")
rows = list(csv.DictReader(log.open())) if log.exists() else []
from collections import Counter
meta["logged_fault_types"] = dict(Counter(r["fault_type"] for r in rows))
meta["log_rows"] = len(rows)
p.write_text(json.dumps(meta, indent=2))
print("campaign_meta updated:", meta.get("logged_fault_types"))
PY

echo "=== rebuild_unified.py --all-rpi-runs ==="
python3 scripts/rebuild_unified.py --all-rpi-runs

echo "=== isolated eval (mixed retrain + live-faithful) ==="
python3 scripts/deca_compound_fix_round2_eval.py

echo "=== write FINDINGS.md ==="
python3 scripts/deca_compound_fix_round2_write_findings.py

echo "=== PIPELINE COMPLETE $(date -u -Iseconds) ==="
