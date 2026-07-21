#!/usr/bin/env bash
# Durability exam v2 → lean VRF recall campaign.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
LOG=/tmp/durability_then_vrf.log
exec > >(tee -a "$LOG") 2>&1

echo "[$(date -Is)] === LEG A: specificity_exam_v2 durability ==="
bash scripts/deca_blind_test.sh specificity_exam_v2 "" 45 -- \
  --playlist scripts/playlists/specificity_exam_v2.json

STAMP=$(date +%Y%m%d_%H%M)
SRC=data/rpi-net/live/specificity_exam_v2
ARCH=data/rpi-net/blind-tests/specificity_exam_v2_${STAMP}
mkdir -p "$ARCH"
if [[ -d "$SRC" ]]; then
  for f in scorecard.json exam_report.json exam_phases.jsonl ground_truth.sealed.jsonl \
           declarations.jsonl run_meta.json chaos_run.log bgp_update_samples.csv; do
    [[ -f "$SRC/$f" ]] && cp -a "$SRC/$f" "$ARCH/" || true
  done
  [[ -f "$SRC/operator_feed.log" ]] && tail -n 300 "$SRC/operator_feed.log" > "$ARCH/operator_feed.tail.log" || true
fi
python3 scripts/deca_blind_exam_report.py --run-id specificity_exam_v2 2>&1 || true
[[ -f "$SRC/exam_report.json" ]] && cp -a "$SRC/exam_report.json" "$ARCH/" || true
echo "[$(date -Is)] Exam v2 archived -> $ARCH"

echo "[$(date -Is)] === LEG B: VRF recall campaign (5 vrf + 2 tunnel) ==="
python3 -c "
import sys
sys.path.insert(0, 'scripts')
import deca_fault_campaign as c
c.clear_all_faults()
c.run_ssh(c.PE1_SSH, 'pkill iperf3', quiet=True)
c.run_ssh(c.PE2_SSH, 'pkill iperf3', quiet=True)
print('lab cleared')
"
sleep 10
RID="vrf_recall_$(date +%Y%m%d_%H%M)"
python scripts/deca_vrf_recall_campaign.py --run-id "$RID" --vrf 5 --tunnel 2
echo "[$(date -Is)] VRF campaign done -> data/rpi-net/runs/${RID}/"
echo "[$(date -Is)] Next: rebuild_unified --all-rpi-runs + school exam promote + soft-streak + re-check exams"
echo "[$(date -Is)] Pipeline leg A+B complete."
