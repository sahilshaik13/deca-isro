#!/usr/bin/env bash
# run_rainfade_campaign.sh — baseline + rain-fade + Prom capture + Q1 windows.
#
# Usage (from repo root, with predictive deps installed):
#   bash predictive/run_rainfade_campaign.sh
#   bash predictive/run_rainfade_campaign.sh --end-ms 45 --fade-steps 20
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${DECA_PRED_OUT:-$ROOT/data/deca/predictive/captures/$STAMP}"
BASELINE_SEC="${DECA_PRED_BASELINE_SEC:-30}"
POST_SEC="${DECA_PRED_POST_SEC:-20}"
FADE_STEPS=20
FADE_STEP_SEC=5
START_MS=2
END_MS=45
JITTER_MS=3
HOST=station1
PY="${DECA_PRED_PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --baseline-sec) BASELINE_SEC="$2"; shift 2 ;;
    --post-sec) POST_SEC="$2"; shift 2 ;;
    --fade-steps) FADE_STEPS="$2"; shift 2 ;;
    --step-sec) FADE_STEP_SEC="$2"; shift 2 ;;
    --start-ms) START_MS="$2"; shift 2 ;;
    --end-ms) END_MS="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

mkdir -p "$OUT"
FADE_SEC=$((FADE_STEPS * FADE_STEP_SEC))
TOTAL_SEC=$((BASELINE_SEC + FADE_SEC + POST_SEC))

echo "=== Rain-fade Q1 campaign ==="
echo "out=$OUT"
echo "baseline=${BASELINE_SEC}s fade=${FADE_SEC}s (${START_MS}→${END_MS}ms) post=${POST_SEC}s total≈${TOTAL_SEC}s"
echo "prom=$PROM"

# Ensure no leftover netem
bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true

# Start continuous capture in background
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$PY" -m predictive.capture_live \
  --prom "$PROM" \
  --out "$OUT/series.csv" \
  --seconds "$TOTAL_SEC" \
  --interval 1 \
  >"$OUT/capture.log" 2>&1 &
CAP_PID=$!
echo "capture pid=$CAP_PID"

cleanup() {
  bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  if kill -0 "$CAP_PID" 2>/dev/null; then
    wait "$CAP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=== baseline ${BASELINE_SEC}s ==="
sleep "$BASELINE_SEC"

echo "=== rain fade start ==="
# Run fade in background so capture keeps going; script blocks for FADE_SEC
bash "$ROOT/scripts/inject_rain_fade.sh" \
  --host "$HOST" \
  --steps "$FADE_STEPS" \
  --step-sec "$FADE_STEP_SEC" \
  --start-ms "$START_MS" \
  --end-ms "$END_MS" \
  >"$OUT/fade.log" 2>&1 &
FADE_PID=$!
wait "$FADE_PID" || true

echo "=== post-fade hold ${POST_SEC}s ==="
sleep "$POST_SEC"

echo "=== clear netem ==="
bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" | tee "$OUT/clear.log"
wait "$CAP_PID" || true
trap - EXIT

echo "=== build Q1 windows ==="
"$PY" -m predictive.q1_windows --capture "$OUT/series.csv" --out-dir "$OUT" | tee "$OUT/windows_summary.json"

echo
echo "Campaign complete: $OUT"
echo "  series.csv          raw 1 Hz Prom samples"
echo "  q1_windows_train.csv  labeled windows (eta_seconds)"
echo "  q1_meta.json        breach metadata"
