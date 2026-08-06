#!/usr/bin/env bash
# run_chaos_campaign_gns3.sh — overlapping GNS3 faults for held-out validation (never train).
#
# Schedule (fraction of --seconds): same phases as Pi chaos.
# Usage:
#   bash predictive/run_chaos_campaign_gns3.sh --seconds 240 --out data/deca/predictive/protocol_gns3/.../chaos
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export DECA_FABRIC=gns3
PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
SECONDS_RUN=180
OUT=""
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
INJ="$ROOT/lab/gns3/inject"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seconds) SECONDS_RUN="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --host) shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

OUT="${OUT:-$ROOT/data/deca/predictive/protocol_gns3/${STAMP}/chaos}"
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
  "fabric": "gns3",
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
  bash "$INJ/clear_all.sh" >/dev/null 2>&1 || true
  bash "$INJ/util_congestion.sh" --clear >/dev/null 2>&1 || true
}

echo "=== GNS3 Chaos campaign ${SECONDS_RUN}s → $OUT ==="
clear_all

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$PY" -m predictive.capture_live \
  --fabric gns3 --prom "$PROM" --out "$OUT/series.csv" --seconds "$SECONDS_RUN" --interval 1 \
  >"$OUT/capture.log" 2>&1 &
CAP_PID=$!

cleanup() {
  clear_all
  wait "$CAP_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep "$T1"

RAIN_DUR=$(( T3 - T1 ))
RAIN_STEPS=$(( RAIN_DUR / 5 ))
[[ "$RAIN_STEPS" -lt 8 ]] && RAIN_STEPS=8
RAIN_STEP=$(( RAIN_DUR / RAIN_STEPS ))
[[ "$RAIN_STEP" -lt 1 ]] && RAIN_STEP=1
echo "=== chaos rain fade ${RAIN_DUR}s ==="
STEPS="$RAIN_STEPS" STEP_SEC="$RAIN_STEP" START_MS=2 END_MS=45 \
  bash "$INJ/rain_fade.sh" >"$OUT/rain.log" 2>&1 &
RAIN_PID=$!

sleep $(( T2 - T1 ))

CPU_DUR=$(( T3 - T2 ))
echo "=== chaos +CPU ${CPU_DUR}s ==="
DUR="$CPU_DUR" bash "$INJ/cpu_stress.sh" >"$OUT/cpu.log" 2>&1 &
CPU_PID=$!
sleep "$CPU_DUR"
wait "$CPU_PID" 2>/dev/null || true
wait "$RAIN_PID" 2>/dev/null || true

echo "=== chaos clear then loss progression ==="
bash "$INJ/rain_fade.sh" --clear >/dev/null 2>&1 || true
bash "$INJ/cpu_stress.sh" --clear >/dev/null 2>&1 || true

LOSS_DUR=$(( T4 - T3 ))
LOSS_STEPS=$(( LOSS_DUR / 5 ))
[[ "$LOSS_STEPS" -lt 12 ]] && LOSS_STEPS=12
LOSS_STEP=$(( LOSS_DUR / LOSS_STEPS ))
[[ "$LOSS_STEP" -lt 1 ]] && LOSS_STEP=1
STEPS="$LOSS_STEPS" STEP_SEC="$LOSS_STEP" END_LOSS=3.5 \
  bash "$INJ/loss_progression.sh" >"$OUT/loss.log" 2>&1 &
wait $! || true
bash "$INJ/loss_progression.sh" --clear >/dev/null 2>&1 || true

UTIL_DUR=$(( T5 - T4 ))
echo "=== chaos util congestion ${UTIL_DUR}s ==="
UTIL_STEPS=$(( UTIL_DUR / 20 ))
[[ "$UTIL_STEPS" -lt 6 ]] && UTIL_STEPS=6
UTIL_STEP_SEC=$(( UTIL_DUR / UTIL_STEPS ))
[[ "$UTIL_STEP_SEC" -lt 10 ]] && UTIL_STEP_SEC=10
STEPS="$UTIL_STEPS" STEP_SEC="$UTIL_STEP_SEC" START_MBIT=5 END_MBIT=24 PLATEAU_SEC=90 \
  bash "$INJ/util_congestion.sh" --schedule-out "$OUT/util_ceil_schedule.jsonl" >"$OUT/util.log" 2>&1 &
wait $! || true
bash "$INJ/util_congestion.sh" --clear >/dev/null 2>&1 || true

echo "=== chaos BGP ==="
BGP_DUR=$(( T6 - T5 ))
CYCLES=$(( BGP_DUR / 5 ))
[[ "$CYCLES" -lt 4 ]] && CYCLES=4
CYCLES="$CYCLES" PERIOD=5 bash "$INJ/bgp_flap.sh" >"$OUT/bgp.log" 2>&1 &
wait $! || true

clear_all
wait "$CAP_PID" || true
trap - EXIT

echo '{"train": false, "name": "chaos", "fabric": "gns3", "schema_version": 2}' >"$OUT/label.json"
echo "GNS3 Chaos complete: $OUT"
