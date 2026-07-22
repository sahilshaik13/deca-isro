#!/usr/bin/env bash
# Compound fix continuation (round 3): wait for campaign → rebuild → isolated eval.
# Does NOT promote. Artifacts under COMPOUND_FIX_OUT (default: compound_fix_round_3).
set -euo pipefail
cd /home/brain/deca-isro
source .venv/bin/activate
export PYTHONPATH=scripts

RUN_ID="${1:?run-id required}"
CAMP_PID="${2:-}"
OUT="${COMPOUND_FIX_OUT:-models/experiments/compound_fix_round_3}"
export COMPOUND_FIX_OUT="$OUT"
LOG="${COMPOUND_FIX_LOG:-/tmp/deca_compound_fix_r3.log}"
PIPE_LOG="${COMPOUND_FIX_PIPE_LOG:-/tmp/deca_compound_fix_r3_pipeline.log}"

mkdir -p "$OUT"
exec > >(tee -a "$PIPE_LOG") 2>&1

echo "=== PIPELINE START $(date -u -Iseconds) run_id=$RUN_ID camp_pid=${CAMP_PID:-unknown} out=$OUT ==="

if [[ -n "$CAMP_PID" ]]; then
  echo "Waiting for campaign pid $CAMP_PID..."
  while kill -0 "$CAMP_PID" 2>/dev/null; do
    sleep 60
    if [[ -f "$LOG" ]]; then
      tail -n 2 "$LOG" | sed 's/^/  [camp] /'
    fi
  done
  echo "Campaign process exited."
fi

if ! grep -q "COMPOUND OVERLAP CAMPAIGN DONE" "$LOG" 2>/dev/null; then
  echo "ERROR: campaign log missing DONE marker — check $LOG"
  tail -n 80 "$LOG" || true
  exit 1
fi

python3 - <<PY
import json, csv
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
p = Path("$OUT/campaign_meta.json")
meta = json.loads(p.read_text()) if p.exists() else {"run_id": "$RUN_ID"}
meta["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
meta["log"] = "$LOG"
log = Path("data/rpi-net/runs/$RUN_ID/fault_injection_log.csv")
rows = list(csv.DictReader(log.open())) if log.exists() else []
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
