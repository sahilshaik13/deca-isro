#!/usr/bin/env bash
# run_protocol_campaign.sh — pinpoint volume protocol (pilot or full).
#
# Pilot (default): short isolated campaigns to prove the pipeline.
# Full (--full): 24h L0 · 10×2h L1 · 10×1h L2 · 10×1h L3 · 8×10m L4 loss · 8×10m L5 util · 12h chaos.
#
# Usage:
#   bash predictive/run_protocol_campaign.sh              # pilot
#   bash predictive/run_protocol_campaign.sh --full
#   bash predictive/run_protocol_campaign.sh --only 0,1   # subset of labels
#   bash predictive/run_protocol_campaign.sh --skip-chaos
#   bash predictive/run_protocol_campaign.sh --full --stamp STAMP --only 1,2,3 --resume
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
HOST=station1
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
MODE=pilot
ONLY=""
SKIP_CHAOS=0
RESUME=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) MODE=full; shift ;;
    --pilot) MODE=pilot; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    --skip-chaos) SKIP_CHAOS=1; shift ;;
    --resume) RESUME=1; shift ;;
    --host) HOST="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

OUT_ROOT="$ROOT/data/deca/predictive/protocol/$STAMP"
mkdir -p "$OUT_ROOT"
MANIFEST="$OUT_ROOT/manifest.jsonl"
if [[ "$RESUME" -eq 0 ]]; then
  : >"$MANIFEST"
else
  touch "$MANIFEST"
fi

# Durations (seconds)
if [[ "$MODE" == full ]]; then
  L0_SEC=$((24 * 3600))
  L1_ITERS=10; L1_INJECT=$((2 * 3600)); L1_BASE=60; L1_POST=60
  L2_ITERS=10; L2_INJECT=$((1 * 3600)); L2_BASE=30; L2_POST=30
  L3_ITERS=10; L3_INJECT=$((1 * 3600)); L3_BASE=30; L3_POST=30
  # L4/L5: adequate TTI corpora (8 progressions × ~12 min) — real loss + HTB util
  L4_ITERS=8; L4_INJECT=600; L4_BASE=60; L4_POST=60
  L5_ITERS=8; L5_INJECT=600; L5_BASE=60; L5_POST=60
  CHAOS_SEC=$((12 * 3600))
else
  # Pilot: hours → minutes-scale proof
  L0_SEC=180
  L1_ITERS=2; L1_INJECT=120; L1_BASE=20; L1_POST=20
  L2_ITERS=2; L2_INJECT=90;  L2_BASE=15; L2_POST=15
  L3_ITERS=2; L3_INJECT=90;  L3_BASE=15; L3_POST=15
  L4_ITERS=2; L4_INJECT=120; L4_BASE=20; L4_POST=20
  L5_ITERS=2; L5_INJECT=120; L5_BASE=20; L5_POST=20
  CHAOS_SEC=240
fi

want() {
  local lab="$1"
  [[ -z "$ONLY" ]] && return 0
  [[ ",$ONLY," == *",$lab,"* ]]
}

clear_all() {
  bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_bgp_flap.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
}

append_manifest() {
  # args: json object as single line
  echo "$1" >>"$MANIFEST"
}

echo "=== Protocol campaign mode=$MODE stamp=$STAMP ==="
echo "out=$OUT_ROOT"
clear_all

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"
export DECA_PROM_URL="$PROM"
# Pause latch for capture_live / watchdog (Pi power-outage freeze)
export DECA_CAPTURE_PAUSE_FILE="$OUT_ROOT/CAPTURE_PAUSE"

cat >"$OUT_ROOT/campaign_schema.json" <<EOF
{
  "stamp": "$STAMP",
  "mode": "$MODE",
  "schema_version": 2,
  "series_columns_extra": ["util_gre_mbps", "ipsec_rekey_events_1h", "ipsec_rekey_anomaly", "path_asymmetry"],
  "labels": {
    "0": "normal",
    "1": "rain_fade",
    "2": "cpu_stress",
    "3": "bgp_flap",
    "4": "loss_progression",
    "5": "util_congestion"
  },
  "notes": "PS13 adequacy: util through HTB, real loss netem, rekey + asymmetry in 1Hz series; asymmetry also derived gre−eth0 in preprocess."
}
EOF

run_labeled() {
  local label="$1" iter="$2" name="$3"
  local baseline="$4" inject="$5" post="$6" seconds_only="${7:-0}"
  local dest="$OUT_ROOT/L${label}_${name}/iter_$(printf '%02d' "$iter")"
  mkdir -p "$dest"
  # Skip completed iters on --resume (and always if label.json present) so power-cut
  # restarts do not redo finished L1–L5 work or clobber series.csv.
  if [[ -f "$dest/label.json" ]]; then
    local rows=0
    if [[ -f "$dest/series.csv" ]]; then
      rows=$(($(wc -l < "$dest/series.csv") - 1))
    fi
    echo "--- label=$label iter=$iter SKIP (label.json exists, series_rows=$rows) ---"
    return 0
  fi
  local started ended
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "--- label=$label iter=$iter → $dest ---"
  if [[ "$label" -eq 0 ]]; then
    DECA_PRED_OUT="$dest" bash "$ROOT/predictive/run_q2_campaign.sh" \
      --label 0 --seconds "$seconds_only" --host "$HOST" --prom "$PROM" \
      --stamp "${STAMP}_L0_i${iter}"
  else
    DECA_PRED_OUT="$dest" bash "$ROOT/predictive/run_q2_campaign.sh" \
      --label "$label" --baseline-sec "$baseline" --inject-sec "$inject" \
      --post-sec "$post" --host "$HOST" --prom "$PROM" \
      --stamp "${STAMP}_L${label}_i${iter}"
  fi
  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  clear_all
  append_manifest "$(cat <<EOF
{"label":$label,"name":"$name","iteration":$iter,"path":"$dest","started":"$started","ended":"$ended","baseline_sec":$baseline,"inject_sec":$inject,"post_sec":$post,"mode":"$MODE","prom":"$PROM","host":"$HOST"}
EOF
)"
}

# L0 healthy
if want 0; then
  run_labeled 0 1 normal 0 0 0 "$L0_SEC"
fi

# L1 rain fade iterations
if want 1; then
  for i in $(seq 1 "$L1_ITERS"); do
    run_labeled 1 "$i" rain_fade "$L1_BASE" "$L1_INJECT" "$L1_POST"
  done
fi

# L2 CPU
if want 2; then
  for i in $(seq 1 "$L2_ITERS"); do
    run_labeled 2 "$i" cpu_stress "$L2_BASE" "$L2_INJECT" "$L2_POST"
  done
fi

# L3 BGP
if want 3; then
  for i in $(seq 1 "$L3_ITERS"); do
    run_labeled 3 "$i" bgp_flap "$L3_BASE" "$L3_INJECT" "$L3_POST"
  done
fi

# L4 real loss progression (loss-TTI GT)
if want 4; then
  for i in $(seq 1 "$L4_ITERS"); do
    run_labeled 4 "$i" loss_progression "$L4_BASE" "$L4_INJECT" "$L4_POST"
  done
fi

# L5 util congestion through HTB (util-TTI GT)
if want 5; then
  for i in $(seq 1 "$L5_ITERS"); do
    run_labeled 5 "$i" util_congestion "$L5_BASE" "$L5_INJECT" "$L5_POST"
  done
fi

# Chaos (held-out)
if [[ "$SKIP_CHAOS" -eq 0 ]]; then
  echo "=== chaos validation (${CHAOS_SEC}s) ==="
  bash "$ROOT/predictive/run_chaos_campaign.sh" \
    --out "$OUT_ROOT/chaos" --seconds "$CHAOS_SEC" --host "$HOST" --prom "$PROM" \
    --stamp "$STAMP"
  append_manifest "{\"label\":\"chaos\",\"path\":\"$OUT_ROOT/chaos\",\"seconds\":$CHAOS_SEC,\"mode\":\"$MODE\",\"train\":false}"
fi

# Summary
cat >"$OUT_ROOT/protocol_summary.json" <<EOF
{
  "stamp": "$STAMP",
  "mode": "$MODE",
  "out": "$OUT_ROOT",
  "manifest": "$MANIFEST",
  "schema_version": 2,
  "pilot_defaults": {"L0_sec": 180, "L1_iters": 2, "L2_iters": 2, "L3_iters": 2, "L4_iters": 2, "L5_iters": 2, "chaos_sec": 240},
  "full_defaults": {"L0_sec": 86400, "L1_iters": 10, "L1_inject": 7200, "L2_iters": 10, "L2_inject": 3600, "L3_iters": 10, "L3_inject": 3600, "L4_iters": 8, "L4_inject": 600, "L5_iters": 8, "L5_inject": 600, "chaos_sec": 43200}
}
EOF

echo
echo "Protocol complete: $OUT_ROOT"
echo "  manifest: $MANIFEST"
echo "  Next: python -m predictive.build_protocol_dataset --protocol-dir $OUT_ROOT"
