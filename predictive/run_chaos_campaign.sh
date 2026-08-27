#!/usr/bin/env bash
# run_chaos_campaign.sh — overlapping faults for held-out validation (never train).
#
# Schedule (fraction of --seconds):
#   0–15%   healthy
#   15–35%  rain fade alone
#   35–50%  rain fade + CPU
#   50–65%  real loss progression
#   65–80%  util congestion (HTB)
#   80–100% BGP flap
#
# Usage:
#   bash predictive/run_chaos_campaign.sh --seconds 180 --out data/deca/predictive/protocol/.../chaos
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
HOST=station1
SECONDS_RUN=180
OUT=""
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seconds) SECONDS_RUN="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

OUT="${OUT:-$ROOT/data/deca/predictive/protocol/${STAMP}/chaos}"
mkdir -p "$OUT"

T0=0
T1=$(( SECONDS_RUN * 15 / 100 ))
T2=$(( SECONDS_RUN * 35 / 100 ))
T3=$(( SECONDS_RUN * 50 / 100 ))
T4=$(( SECONDS_RUN * 65 / 100 ))
T5=$(( SECONDS_RUN * 80 / 100 ))
T6=$SECONDS_RUN

cat >"$OUT/chaos_schedule.json" <<EOF
{
  "stamp": "$STAMP",
  "seconds": $SECONDS_RUN,
  "train": false,
  "schema_version": 2,
  "phases": [
    {"name": "healthy", "t_start": $T0, "t_end": $T1, "faults": []},
    {"name": "rain_fade", "t_start": $T1, "t_end": $T2, "faults": ["rain_fade"]},
    {"name": "rain_plus_cpu", "t_start": $T2, "t_end": $T3, "faults": ["rain_fade", "cpu_stress"]},
    {"name": "loss_progression", "t_start": $T3, "t_end": $T4, "faults": ["loss_progression"]},
    {"name": "util_congestion", "t_start": $T4, "t_end": $T5, "faults": ["util_congestion"]},
    {"name": "bgp_flap", "t_start": $T5, "t_end": $T6, "faults": ["bgp_flap"]}
  ]
}
EOF

clear_all() {
  bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_bgp_flap.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
}

echo "=== Chaos campaign ${SECONDS_RUN}s → $OUT ==="
clear_all

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$PY" -m predictive.capture_live \
  --prom "$PROM" --out "$OUT/series.csv" --seconds "$SECONDS_RUN" --interval 1 \
  >"$OUT/capture.log" 2>&1 &
CAP_PID=$!

cleanup() {
  clear_all
  wait "$CAP_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Phase 0: healthy
sleep "$T1"

# Phase 1: rain fade (leave netem for phase 2)
RAIN_DUR=$(( T3 - T1 ))
RAIN_STEPS=$(( RAIN_DUR / 5 ))
[[ "$RAIN_STEPS" -lt 8 ]] && RAIN_STEPS=8
echo "=== chaos rain fade ${RAIN_DUR}s ==="
bash "$ROOT/scripts/inject_rain_fade.sh" \
  --host "$HOST" --steps "$RAIN_STEPS" --step-sec 5 --start-ms 2 --end-ms 45 \
  >"$OUT/rain.log" 2>&1 &
RAIN_PID=$!

# Wait until T2 from start ≈ remaining until mid
sleep $(( T2 - T1 ))

# Phase 2: add CPU while rain continues
CPU_DUR=$(( T3 - T2 ))
echo "=== chaos +CPU ${CPU_DUR}s ==="
bash "$ROOT/scripts/inject_cpu_stress.sh" --host "$HOST" --seconds "$CPU_DUR" \
  >"$OUT/cpu.log" 2>&1 &
CPU_PID=$!
sleep "$CPU_DUR"
wait "$CPU_PID" 2>/dev/null || true
wait "$RAIN_PID" 2>/dev/null || true

# Clear rain/cpu before loss
echo "=== chaos clear then loss progression ==="
bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST" >/dev/null 2>&1 || true

LOSS_DUR=$(( T4 - T3 ))
LOSS_STEPS=$(( LOSS_DUR / 5 ))
[[ "$LOSS_STEPS" -lt 12 ]] && LOSS_STEPS=12
bash "$ROOT/scripts/inject_loss_progression.sh" \
  --host "$HOST" --steps "$LOSS_STEPS" --step-sec 5 --start-pct 0 --end-pct 3.5 \
  >"$OUT/loss.log" 2>&1 &
wait $! || true
bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST" >/dev/null 2>&1 || true

# Phase util congestion — schedule must reach end_mbit *inside* this phase so
# CAPTURE_CONTRACT 5B (ceil ≥ end_mbit) is observable on util-root GT windows.
# end_mbit=34 matches inject payload soft-ceil (~0.85×40); leave plateau margin.
UTIL_DUR=$(( T5 - T4 ))
echo "=== chaos util congestion ${UTIL_DUR}s ==="
PLATEAU_SEC=90
UTIL_RAMP_BUDGET=$(( UTIL_DUR - PLATEAU_SEC - 20 ))
[[ "$UTIL_RAMP_BUDGET" -lt 60 ]] && UTIL_RAMP_BUDGET=60
UTIL_STEPS=$(( UTIL_RAMP_BUDGET / 15 ))
[[ "$UTIL_STEPS" -lt 6 ]] && UTIL_STEPS=6
[[ "$UTIL_STEPS" -gt 24 ]] && UTIL_STEPS=24
UTIL_STEP_SEC=$(( UTIL_RAMP_BUDGET / UTIL_STEPS ))
[[ "$UTIL_STEP_SEC" -lt 8 ]] && UTIL_STEP_SEC=8
# Off-nominal vs idle payload ceil (34): end=24 so htb_payload_ceil feature
# separates 5B plateau from healthy/nominal 34. Offer auto = 2× end (inject).
bash "$ROOT/scripts/inject_util_congestion.sh" \
  --host "$HOST" --steps "$UTIL_STEPS" --step-sec "$UTIL_STEP_SEC" \
  --start-mbit 5 --end-mbit 24 --plateau-sec "$PLATEAU_SEC" \
  --schedule-out "$OUT/util_ceil_schedule.jsonl" \
  >"$OUT/util.log" 2>&1 &
wait $! || true
bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true

# BGP
echo "=== chaos BGP ==="
BGP_DUR=$(( T6 - T5 ))
CYCLES=$(( BGP_DUR / 5 ))
[[ "$CYCLES" -lt 4 ]] && CYCLES=4
bash "$ROOT/scripts/inject_bgp_flap.sh" --host "$HOST" --cycles "$CYCLES" --period-sec 5 \
  >"$OUT/bgp.log" 2>&1 &
wait $! || true

clear_all
wait "$CAP_PID" || true
trap - EXIT

echo '{"train": false, "name": "chaos", "schema_version": 2}' >"$OUT/label.json"
echo "Chaos complete: $OUT"
