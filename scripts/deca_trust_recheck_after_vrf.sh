#!/usr/bin/env bash
# After VRF-recall promote: re-check trust bar (must not reopen cry-wolf).
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
LOG=/tmp/trust_recheck_after_vrf.log
exec > >(tee -a "$LOG") 2>&1

clear_lab() {
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
}

archive_exam() {
  local rid="$1"
  local stamp
  stamp=$(date +%Y%m%d_%H%M)
  local src="data/rpi-net/live/${rid}"
  local arch="data/rpi-net/blind-tests/${rid}_${stamp}"
  mkdir -p "$arch"
  if [[ -d "$src" ]]; then
    for f in scorecard.json exam_report.json exam_phases.jsonl ground_truth.sealed.jsonl \
             declarations.jsonl run_meta.json chaos_run.log bgp_update_samples.csv; do
      [[ -f "$src/$f" ]] && cp -a "$src/$f" "$arch/" || true
    done
    [[ -f "$src/operator_feed.log" ]] && tail -n 300 "$src/operator_feed.log" > "$arch/operator_feed.tail.log" || true
  fi
  python3 scripts/deca_blind_exam_report.py --run-id "$rid" 2>&1 || true
  [[ -f "$src/exam_report.json" ]] && cp -a "$src/exam_report.json" "$arch/" || true
  echo "archived $rid -> $arch"
}

echo "[$(date -Is)] === Trust re-check after VRF-recall promote ==="
clear_lab

echo "[$(date -Is)] === Exam v1 ==="
rm -rf data/rpi-net/live/specificity_exam_v1
bash scripts/deca_blind_test.sh specificity_exam_v1 "" 40 -- \
  --playlist scripts/playlists/specificity_exam_v1.json
archive_exam specificity_exam_v1
clear_lab

echo "[$(date -Is)] === Exam v2 ==="
rm -rf data/rpi-net/live/specificity_exam_v2
bash scripts/deca_blind_test.sh specificity_exam_v2 "" 45 -- \
  --playlist scripts/playlists/specificity_exam_v2.json
archive_exam specificity_exam_v2
clear_lab

echo "[$(date -Is)] === Short control 30m ==="
CTRL="control_after_vrf_$(date +%Y%m%d_%H%M)"
bash scripts/deca_blind_test.sh "$CTRL" "" 30 -- --control --near-misses 4
mkdir -p "data/rpi-net/blind-tests/${CTRL}"
for f in scorecard.json ground_truth.sealed.jsonl declarations.jsonl run_meta.json chaos_run.log; do
  [[ -f "data/rpi-net/live/${CTRL}/$f" ]] && cp -a "data/rpi-net/live/${CTRL}/$f" "data/rpi-net/blind-tests/${CTRL}/" || true
done
echo "[$(date -Is)] Trust re-check complete."
