#!/usr/bin/env bash
# Careful VRF recall live check: compound_prob=1 so every real slot includes PE2 VRF.
# Keeps budget modest (45m, 3-4 compounds + 2 near-misses) — not a full ultimate.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
LOG=/tmp/blind_vrf_force.log
exec > >(tee -a "$LOG") 2>&1

STAMP=$(date +%Y%m%d_%H%M)
RID="blind_vrfcheck_${STAMP}_45m"

python3 -c "
import sys
sys.path.insert(0, 'scripts')
import deca_fault_campaign as c
c.clear_all_faults()
c.run_ssh(c.PE1_SSH, 'pkill iperf3', quiet=True)
c.run_ssh(c.PE2_SSH, 'pkill iperf3', quiet=True)
print('lab cleared')
"
sleep 8

echo "[$(date -Is)] === VRF-forced blind ${RID} (compound_prob=1.0) ==="
echo "Every real circumstance = PE1 fault + PE2 vrf_leakage (tests recall without RNG miss)."
bash scripts/deca_blind_test.sh "${RID}" "" 45 -- \
  --near-misses 2 --min-events 3 --max-events 4 \
  --compound-prob 1.0 --seed "$(date +%s)"

ARCH="data/rpi-net/blind-tests/${RID}"
mkdir -p "$ARCH"
SRC="data/rpi-net/live/${RID}"
for f in scorecard.json ground_truth.sealed.jsonl declarations.jsonl run_meta.json \
         chaos_run.log bgp_update_samples.csv; do
  [[ -f "${SRC}/$f" ]] && cp -a "${SRC}/$f" "$ARCH/" || true
done
[[ -f "${SRC}/operator_feed.log" ]] && tail -n 300 "${SRC}/operator_feed.log" > "$ARCH/operator_feed.tail.log" || true

echo "[$(date -Is)] Archived ${RID}"
echo "[$(date -Is)] Reminder: append a row to data/rpi-net/blind-tests/CUMULATIVE.md after reading the scorecard."
