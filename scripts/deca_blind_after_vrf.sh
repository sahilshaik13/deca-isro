#!/usr/bin/env bash
# Post–VRF-recall adversarial blind (detection re-check).
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
LOG=/tmp/blind_after_vrf.log
exec > >(tee -a "$LOG") 2>&1

STAMP=$(date +%Y%m%d_%H%M)
RID="blind_${STAMP}_60m"

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

echo "[$(date -Is)] === Adversarial blind ${RID} (post VRF-recall promote) ==="
bash scripts/deca_blind_test.sh "${RID}" "" 60 -- \
  --near-misses 2 --min-events 5 --max-events 6 --seed "$(date +%s)"

ARCH="data/rpi-net/blind-tests/${RID}"
mkdir -p "$ARCH"
SRC="data/rpi-net/live/${RID}"
for f in scorecard.json ground_truth.sealed.jsonl declarations.jsonl run_meta.json \
         chaos_run.log bgp_update_samples.csv; do
  [[ -f "${SRC}/$f" ]] && cp -a "${SRC}/$f" "$ARCH/" || true
done
[[ -f "${SRC}/operator_feed.log" ]] && tail -n 300 "${SRC}/operator_feed.log" > "$ARCH/operator_feed.tail.log" || true
echo "[$(date -Is)] Archived ${RID} -> ${ARCH}"
echo "[$(date -Is)] Blind complete — grade already printed above."
