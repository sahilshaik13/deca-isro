#!/usr/bin/env bash
# DECA blind live-network test orchestrator.
#
# Hands-off path: arms the live operator and the blind chaos scheduler together,
# waits for chaos to finish, stops the operator cleanly, then grades the run.
# For the full "watch it think" experience prefer the two-terminal manual path
# in docs/DECA_BLIND_TEST.md; this wrapper streams the operator feed to a log.
#
# Usage:
#   scripts/deca_blind_test.sh [RUN_ID] [START_AT HH:MM] [MINUTES] [-- CHAOS_ARGS...]
#   scripts/deca_blind_test.sh blind_2359 23:00 90
#   scripts/deca_blind_test.sh                       # run now, 90 min
#   scripts/deca_blind_test.sh ctrl_2359 "" 60 -- --control --near-misses 4
#   scripts/deca_blind_test.sh specificity_exam_v1 "" 40 -- --playlist scripts/playlists/specificity_exam_v1.json
set -euo pipefail

RUN_ID="${1:-blind_$(date +%Y%m%d_%H%M%S)}"
START_AT="${2:-}"
MINUTES="${3:-90}"
# Anything after a literal `--` is forwarded verbatim to the chaos scheduler
# (e.g. --control for an all-healthy run, or --seed / --near-misses).
EXTRA_CHAOS_ARGS=()
if [[ "${4:-}" == "--" ]]; then
  EXTRA_CHAOS_ARGS=("${@:5}")
fi

cd "$(dirname "$0")/.."
RUN_DIR="data/rpi-net/live/${RUN_ID}"
mkdir -p "${RUN_DIR}"
OP_LOG="${RUN_DIR}/operator_feed.log"

echo "=============================================================="
echo " DECA BLIND TEST  run_id=${RUN_ID}  start_at=${START_AT:-now}  budget=${MINUTES}m"
echo "=============================================================="
echo "Pre-flight: run 'bash ~/deca_diagnostic.sh' and confirm all green,"
echo "and that Prometheus is healthy: curl -s localhost:9090/-/ready"
echo "Operator NOC feed will stream to: ${OP_LOG}  (tail -f to watch)"
echo

OP_ARGS=(--run-id "${RUN_ID}")
# Opt into the plain+wm agreement ensemble (#5) with DECA_OP_ENSEMBLE=1.
if [[ "${DECA_OP_ENSEMBLE:-0}" == "1" ]]; then
  OP_ARGS+=(--ensemble)
fi
CH_ARGS=(--run-id "${RUN_ID}" --minutes "${MINUTES}")
if [[ -n "${START_AT}" ]]; then
  OP_ARGS+=(--start-at "${START_AT}")
  CH_ARGS+=(--start-at "${START_AT}")
fi
if [[ ${#EXTRA_CHAOS_ARGS[@]} -gt 0 ]]; then
  CH_ARGS+=("${EXTRA_CHAOS_ARGS[@]}")
fi

# Live operator in the background (reads only Prometheus + bgp pulses).
python3 scripts/deca_live_operator.py "${OP_ARGS[@]}" >"${OP_LOG}" 2>&1 &
OP_PID=$!
trap 'kill -INT "${OP_PID}" 2>/dev/null || true' EXIT
echo "Operator armed (pid ${OP_PID}). tail -f ${OP_LOG}"

# Blind chaos in the foreground — its stdout is the injection timeline.
python3 scripts/deca_blind_chaos.py "${CH_ARGS[@]}"

echo "Chaos finished; letting the operator settle for 30s before stopping..."
sleep 30
# TensorFlow / CUDA stubs often swallow SIGINT inside C extensions, so INT alone
# can hang forever on ``wait``. Escalate: INT → TERM → KILL with short budgets.
stop_operator() {
  local pid="$1"
  kill -INT "${pid}" 2>/dev/null || return 0
  for _ in 1 2 3 4 5; do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 1
  done
  echo "Operator ignored SIGINT — sending TERM..."
  kill -TERM "${pid}" 2>/dev/null || return 0
  for _ in 1 2 3; do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 1
  done
  echo "Operator ignored SIGTERM — sending KILL..."
  kill -KILL "${pid}" 2>/dev/null || true
}
stop_operator "${OP_PID}"
wait "${OP_PID}" 2>/dev/null || true
trap - EXIT

echo
echo "Grading..."
python3 scripts/deca_blind_scorecard.py --run-id "${RUN_ID}"

# Deterministic playlist exams get a phase-aware pass-bar report.
if [[ -f "${RUN_DIR}/exam_phases.jsonl" ]]; then
  echo
  echo "Exam report (specificity pass bar)..."
  python3 scripts/deca_blind_exam_report.py --run-id "${RUN_ID}"
fi
