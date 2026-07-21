#!/usr/bin/env bash
# DECA ultimate 60+60 — one blind night, then one all-healthy control night.
#
# Sequence (~2 hours wall clock):
#   1. 60 min adversarial blind run  (new seed, sealed truth)
#   2. 60 min all-healthy control    (zero real faults + near-miss baits)
#   3. Archive both under data/rpi-net/blind-tests/
#   4. Aggregate scorecards (archived + tonight) into a range
#
# Usage:
#   scripts/deca_ultimate_60_60.sh
#   scripts/deca_ultimate_60_60.sh --minutes 60          # both legs (default 60)
#   DECA_OP_ENSEMBLE=1 scripts/deca_ultimate_60_60.sh    # optional mild FA filter
#
# Watch live:
#   tail -f data/rpi-net/live/<blind_id>/operator_feed.log
#   tail -f data/rpi-net/live/<control_id>/operator_feed.log
set -euo pipefail

cd "$(dirname "$0")/.."

MINUTES=60
NEAR_MISSES_BLIND=2
NEAR_MISSES_CONTROL=4
# Keep isolated faults for this night so the aggregate with the archived
# 1537 run stays apples-to-apples. Compound is opt-in via DECA_COMPOUND_PROB.
COMPOUND_PROB="${DECA_COMPOUND_PROB:-0.0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --minutes) MINUTES="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

STAMP="$(date +%Y%m%d_%H%M)"
BLIND_ID="blind_${STAMP}_${MINUTES}m"
CONTROL_ID="control_${STAMP}_${MINUTES}m"
LOG_DIR="data/rpi-net/live"
ORCH_LOG="${LOG_DIR}/ultimate_${STAMP}_orchestrator.log"
mkdir -p "${LOG_DIR}"

{
  echo "=============================================================="
  echo " DECA ULTIMATE 60+60"
  echo "   blind   : ${BLIND_ID}   (${MINUTES} min, compound_prob=${COMPOUND_PROB})"
  echo "   control : ${CONTROL_ID} (${MINUTES} min, ${NEAR_MISSES_CONTROL} near-miss baits)"
  echo "   started : $(date -Is)"
  echo "   ensemble: ${DECA_OP_ENSEMBLE:-0}"
  echo "=============================================================="
  echo
  echo "Pre-flight Prometheus..."
  if ! curl -sf --max-time 5 localhost:9090/-/ready >/dev/null; then
    echo "ERROR: Prometheus not ready at localhost:9090" >&2
    exit 1
  fi
  echo "  Prometheus is Ready."
  echo

  # ── Leg 1: adversarial blind ───────────────────────────────────────
  echo ">>> LEG 1/2 — BLIND (${BLIND_ID})"
  CH_EXTRA=(--near-misses "${NEAR_MISSES_BLIND}" --seed "$(date +%s)")
  if awk "BEGIN{exit !(${COMPOUND_PROB} > 0)}"; then
    CH_EXTRA+=(--compound-prob "${COMPOUND_PROB}")
  fi
  bash scripts/deca_blind_test.sh "${BLIND_ID}" "" "${MINUTES}" -- "${CH_EXTRA[@]}"
  echo
  echo ">>> LEG 1/2 complete at $(date -Is)"
  echo

  # Brief settle so tc / iperf from chaos atexit are fully clear before control.
  echo "Settling lab 45s before control leg..."
  sleep 45
  python3 -c "
import sys
sys.path.insert(0, 'scripts')
import deca_fault_campaign as c
c.clear_all_faults()
c.run_ssh(c.PE1_SSH, 'pkill iperf3', quiet=True)
print('  lab cleared')
"

  # ── Leg 2: all-healthy control ─────────────────────────────────────
  echo
  echo ">>> LEG 2/2 — CONTROL (${CONTROL_ID})"
  bash scripts/deca_blind_test.sh "${CONTROL_ID}" "" "${MINUTES}" -- \
    --control --near-misses "${NEAR_MISSES_CONTROL}" --seed "$(($(date +%s) + 7))"
  echo
  echo ">>> LEG 2/2 complete at $(date -Is)"
  echo

  # ── Archive + aggregate ─────────────────────────────────────────────
  echo ">>> Archiving + aggregating"
  ARCHIVE_ROOT="data/rpi-net/blind-tests"
  mkdir -p "${ARCHIVE_ROOT}"
  for RID in "${BLIND_ID}" "${CONTROL_ID}"; do
    SRC="${LOG_DIR}/${RID}"
    DST="${ARCHIVE_ROOT}/${RID}"
    if [[ -d "${SRC}" ]]; then
      mkdir -p "${DST}"
      # Copy graded artifacts; skip huge operator logs if present (keep a stub note).
      for f in scorecard.json ground_truth.sealed.jsonl declarations.jsonl \
               run_meta.json chaos_run.log bgp_update_samples.csv; do
        [[ -f "${SRC}/${f}" ]] && cp -a "${SRC}/${f}" "${DST}/"
      done
      if [[ -f "${SRC}/operator_feed.log" ]]; then
        # Keep last 200 lines as a sample; full log stays under live/.
        tail -n 200 "${SRC}/operator_feed.log" > "${DST}/operator_feed.tail.log"
      fi
      echo "  archived ${RID} -> ${DST}"
    fi
  done

  echo
  echo ">>> Aggregate (tonight + any prior archived scorecards)"
  python3 scripts/deca_blind_aggregate.py \
    --glob "${ARCHIVE_ROOT}/*/scorecard.json" \
    --out "${ARCHIVE_ROOT}/aggregate_${STAMP}.json" || true

  echo
  echo "=============================================================="
  echo " DECA ULTIMATE 60+60 COMPLETE  $(date -Is)"
  echo "   blind scorecard   : ${LOG_DIR}/${BLIND_ID}/scorecard.json"
  echo "   control scorecard : ${LOG_DIR}/${CONTROL_ID}/scorecard.json"
  echo "   aggregate         : ${ARCHIVE_ROOT}/aggregate_${STAMP}.json"
  echo "=============================================================="
} 2>&1 | tee "${ORCH_LOG}"
