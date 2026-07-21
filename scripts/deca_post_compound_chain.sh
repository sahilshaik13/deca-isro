#!/usr/bin/env bash
# Wait for compound series, lodge rollup, then isolated VRF proof blind.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
SERIES_LOG=data/rpi-net/live/compound_series_20260719.log
ROLLUP=data/rpi-net/blind-tests/compound_series_20260719_rollup.md

echo "[post] waiting for compound series (3 runs)..."
for _ in $(seq 1 400); do
  n=0
  if [[ -f /tmp/deca_compound_results.jsonl ]]; then
    n=$(wc -l < /tmp/deca_compound_results.jsonl)
  fi
  if [[ "$n" -ge 3 ]]; then
    echo "[post] compound series complete ($n runs)"
    break
  fi
  if grep -q 'ALL COMPLETE' "$SERIES_LOG" 2>/dev/null; then
    sleep 30
    break
  fi
  sleep 20
done

python3 scripts/deca_compound_series_rollup.py

python3 - <<'PY'
import sys
sys.path.insert(0, "scripts")
import deca_fault_campaign as dfc
dfc.clear_all_faults()
print("[post] lab cleared for vrf proof blind")
PY

VRF_ID="blind_vrf_isolated_$(date +%Y%m%d_%H%M)_45m"
echo "[post] launching isolated VRF proof: ${VRF_ID}"
nohup bash scripts/deca_blind_test.sh "${VRF_ID}" "" 45 -- \
  --min-events 2 --max-events 2 --near-misses 1 --compound-prob 0 \
  --fault-types vrf_leakage \
  > "data/rpi-net/live/${VRF_ID}_orchestrator.log" 2>&1 &
echo "${VRF_ID}" > /tmp/deca_vrf_isolated_run_id

for _ in $(seq 1 240); do
  if [[ -f "data/rpi-net/live/${VRF_ID}/scorecard.json" ]]; then
    mkdir -p "data/rpi-net/blind-tests/${VRF_ID}"
    cp -a "data/rpi-net/live/${VRF_ID}/." "data/rpi-net/blind-tests/${VRF_ID}/"
    python3 scripts/deca_blind_scorecard.py --run-id "${VRF_ID}" --no-prom 2>&1 | tail -20
    echo "${VRF_ID}" > /tmp/deca_vrf_isolated_done
    break
  fi
  sleep 15
done
echo "[post] chain complete"
