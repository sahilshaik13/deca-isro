#!/usr/bin/env bash
# Compound overlap wave: campaign → rebuild → promote → soft-streak → trust + verify blinds.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
LOG=data/rpi-net/runs/compound_overlap_pipeline.log
exec > >(tee -a "$LOG") 2>&1

RUN_ID="${1:-compound_overlap_$(date +%Y%m%d_%H%M)}"
PER_PE1="${2:-4}"
# Optional 3rd arg: weighted schedule, e.g. "tunnel_degradation=4,congestion_breach=4,bgp_route_flap=0"
# Overrides PER_PE1 when set — consolidate a gain on specific PE1 legs without
# diluting others with more compounds of a type that isn't the target this round.
COUNTS="${3:-}"
if [ -n "${COUNTS}" ]; then
  echo "=== PIPELINE compound overlap run_id=${RUN_ID} counts=${COUNTS} ==="
else
  echo "=== PIPELINE compound overlap run_id=${RUN_ID} per_pe1=${PER_PE1} ==="
fi

python3 - <<'PY'
import sys
sys.path.insert(0, "scripts")
import deca_fault_campaign as dfc
dfc.clear_all_faults()
dfc.run_ssh(dfc.PE1_SSH, "pkill iperf3", quiet=True)
dfc.run_ssh(dfc.PE2_SSH, "pkill iperf3", quiet=True)
print("lab cleared (faults + iperf)")
PY

if [ -n "${COUNTS}" ]; then
  python3 scripts/deca_compound_overlap_campaign.py --run-id "${RUN_ID}" --counts "${COUNTS}" --retry 2
else
  python3 scripts/deca_compound_overlap_campaign.py --run-id "${RUN_ID}" --per-pe1 "${PER_PE1}" --retry 2
fi

echo "=== REBUILD ==="
python3 scripts/rebuild_unified.py --all-rpi-runs

echo "=== SCHOOL EXAM PROMOTE ==="
python3 scripts/deca_school_exam_train.py --auto-promote --baseline-macro-f1 0.717

echo "=== SOFT STREAK ==="
python3 scripts/deca_score_temporal.py --soft-streak

python3 - <<'PY'
import json
from pathlib import Path
ex = json.loads(Path("models/school_exam/latest_exam.json").read_text())
g = ex.get("gate") or {}
print(f"PROMOTE gate_ok={ex.get('gate_ok')} candidate={g.get('candidate_macro_f1')} bar={g.get('bar_macro_f1')}")
PY

echo "=== TRUST: 20m control ==="
CTRL="control_post_overlap_$(date +%Y%m%d_%H%M)_20m"
bash scripts/deca_blind_test.sh "${CTRL}" "" 20 -- --control --near-misses 2

echo "=== VERIFY: tunnel+VRF compound blind ==="
BLIND_TUN="blind_compound_tunnel_recheck_$(date +%Y%m%d_%H%M)_40m"
bash scripts/deca_blind_test.sh "${BLIND_TUN}" "" 40 -- \
  --min-events 2 --max-events 2 --near-misses 1 --compound-prob 1.0 \
  --compound-pe1 tunnel_degradation

echo "=== VERIFY: BGP+VRF compound blind ==="
BLIND_BGP="blind_compound_bgp_recheck_$(date +%Y%m%d_%H%M)_40m"
bash scripts/deca_blind_test.sh "${BLIND_BGP}" "" 40 -- \
  --min-events 2 --max-events 2 --near-misses 1 --compound-prob 1.0 \
  --compound-pe1 bgp_route_flap

for rid in "${CTRL}" "${BLIND_TUN}" "${BLIND_BGP}"; do
  mkdir -p "data/rpi-net/blind-tests/${rid}"
  cp -a "data/rpi-net/live/${rid}/." "data/rpi-net/blind-tests/${rid}/"
done

python3 - <<PY
import json
from pathlib import Path
promote = json.loads(Path("models/school_exam/latest_exam.json").read_text())
g = promote.get("gate") or {}
print(f"PROMOTE gate_ok={promote.get('gate_ok')} candidate={g.get('candidate_macro_f1')} bar={g.get('bar_macro_f1')}")
for rid in ("${CTRL}", "${BLIND_TUN}", "${BLIND_BGP}"):
    sc = json.loads(Path(f"data/rpi-net/live/{rid}/scorecard.json").read_text())
    s = sc.get("summary", sc)
    print(f"GRADE {rid}: detect={s.get('detected')}/{s.get('circumstances_created')} "
          f"class={s.get('class_accuracy')} spur={s.get('spurious_false_alarms')} "
          f"nm_fa={s.get('near_miss_false_alarms')}")
    for e in sc.get("events") or []:
        print(f"  {e.get('fault_type')} @{e.get('host')} det={e.get('detected')} pred={e.get('predicted_class')}")
Path("/tmp/deca_overlap_pipeline_done").write_text("${RUN_ID}\n")
PY

echo "=== PIPELINE COMPLETE run_id=${RUN_ID} ==="
