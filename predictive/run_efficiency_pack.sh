#!/usr/bin/env bash
# run_efficiency_pack.sh — supplement captures for thin classes + BGP bands.
#
# Fills gaps found on full_variants_* stamps:
#   L3 mild(3A) vs storm(3B) sustained flaps
#   L4 mild(4A thin) + deep(4B) for Q1 loss TTI
#   L1 rain extras for jitter
#   COMPOUND pairs covering BGP/loss/util
#   Fresh chaos_holdout with stronger BGP period (never train)
#
# Usage:
#   bash predictive/run_efficiency_pack.sh --fabric pi
#   bash predictive/run_efficiency_pack.sh --fabric gns3 --stamp STAMP
#   bash predictive/run_efficiency_pack.sh --fabric pi --stamp STAMP --resume
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
FABRIC=pi
HOST=station1
PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
STAMP=""
RESUME=0
Q2_SCRIPT="$ROOT/predictive/run_q2_campaign.sh"
INJ_GNS3="$ROOT/lab/gns3/inject"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric) FABRIC="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --resume) RESUME=1; shift ;;
    --host) HOST="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    *) echo "unknown $1"; exit 2 ;;
  esac
done

[[ "$FABRIC" == pi || "$FABRIC" == gns3 ]] || { echo "fabric must be pi|gns3"; exit 2; }
export DECA_FABRIC="$FABRIC"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$FABRIC" == gns3 ]]; then
  HOST=gns3-pe1
  PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
  Q2_SCRIPT="$ROOT/predictive/run_q2_campaign_gns3.sh"
  [[ -n "$STAMP" ]] || STAMP="eff_pack_gns3_$(date -u +%Y%m%dT%H%M%SZ)"
  OUT="$ROOT/data/deca/predictive/protocol_gns3/$STAMP"
  docker ps --format '{{.Names}}' | grep -qE 'GNS3\.PE1\.|PE1' \
    || { echo "ERROR: GNS3 PE1 not running"; exit 3; }
else
  [[ -n "$STAMP" ]] || STAMP="eff_pack_pi_$(date -u +%Y%m%dT%H%M%SZ)"
  OUT="$ROOT/data/deca/predictive/protocol/$STAMP"
fi

mkdir -p "$OUT"/{recipes,logs,L1_rain_fade,L3_bgp_flap,L4_loss_progression,COMPOUND,chaos_holdout}
MANIFEST="$OUT/manifest.jsonl"
STATE="$OUT/pack_state.json"
[[ "$RESUME" -eq 1 ]] || : >"$MANIFEST"

log() { echo "[$(date -u +%H:%M:%SZ)] $*"; echo "[$(date -u +%H:%M:%SZ)] $*" >>"$OUT/logs/pack.log"; }

done_job() {
  local id="$1"
  grep -q "\"id\":\"$id\"" "$MANIFEST" 2>/dev/null
}

mark_done() {
  local id="$1" path="$2"
  printf '{"id":"%s","path":"%s","ts":"%s"}\n' "$id" "$path" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$MANIFEST"
}

cat >"$OUT/PACK_PLAN.md" <<EOF
# Efficiency pack — $STAMP (fabric=$FABRIC)

**Isolation:** writes only under this stamp. Does not touch \`full_variants_*\` or \`protocol_models/\`.

| Block | Count | ~Wall |
| --- | ---: | ---: |
| L3 BGP mild/storm | 8 | ~85 min |
| L4 loss 4A+4B | 8 | ~95 min |
| L1 rain (jitter) | 3 | ~30 min |
| COMPOUND | 4 | ~60 min |
| chaos_holdout (never train) | 1×90 min | ~90 min |
| **Total capture** | | **~6–7 h** |
EOF

write_recipes() {
  local i=0
  # GNS3 flap counters move slower than Pi — use faster periods for band separation.
  if [[ "$FABRIC" == gns3 ]]; then
    STORM_PERIODS=(2 2 3 2)
    MILD_PERIODS=(5 6 5 6)
  else
    STORM_PERIODS=(3 4 5 3)
    MILD_PERIODS=(8 10 12 8)
  fi
  for p in "${STORM_PERIODS[@]}"; do
    i=$((i+1))
    cat >"$OUT/recipes/l3_storm_${i}.json" <<EOF
{"label":3,"name":"bgp_flap","baseline_sec":20,"inject_sec":600,"post_sec":20,"period_sec":$p,"cycles":$((600/p)),"link_bounce":false,"traffic_profile":"payload_medium","band_target":"3B_storm","pack":"eff","fabric":"$FABRIC"}
EOF
  done
  for p in "${MILD_PERIODS[@]}"; do
    i=$((i+1))
    cat >"$OUT/recipes/l3_mild_${i}.json" <<EOF
{"label":3,"name":"bgp_flap","baseline_sec":20,"inject_sec":600,"post_sec":20,"period_sec":$p,"cycles":$((600/p)),"link_bounce":false,"traffic_profile":"idle","band_target":"3A_mild","pack":"eff","fabric":"$FABRIC"}
EOF
  done
  i=0
  for e in 1.2 1.5 1.8 1.5; do
    i=$((i+1))
    cat >"$OUT/recipes/l4_mild_${i}.json" <<EOF
{"label":4,"name":"loss_progression","baseline_sec":60,"inject_sec":600,"post_sec":60,"start_pct":0.0,"end_pct":$e,"step_sec":5,"traffic_profile":"ttc_light","band_target":"4A","pack":"eff","fabric":"$FABRIC"}
EOF
  done
  for e in 8.0 12.0 15.0 20.0; do
    i=$((i+1))
    cat >"$OUT/recipes/l4_deep_${i}.json" <<EOF
{"label":4,"name":"loss_progression","baseline_sec":60,"inject_sec":720,"post_sec":60,"start_pct":0.0,"end_pct":$e,"step_sec":5,"traffic_profile":"mixed","band_target":"4B","pack":"eff","fabric":"$FABRIC"}
EOF
  done
  i=0
  for e in 35 45 40; do
    i=$((i+1))
    cat >"$OUT/recipes/l1_${i}.json" <<EOF
{"label":1,"name":"rain_fade","baseline_sec":20,"inject_sec":600,"post_sec":20,"start_ms":2,"end_ms":$e,"step_sec":5,"jitter_ms":5,"traffic_profile":"ttc_light","pack":"eff","fabric":"$FABRIC"}
EOF
  done
  cat >"$OUT/recipes/comp_bgp_loss.json" <<EOF
{"total_sec":900,"baseline_sec":20,"faults":["bgp_flap","loss_progression"],"bgp_period_sec":4,"loss_end_pct":8.0,"traffic_profile":"mixed","pack":"eff","fabric":"$FABRIC"}
EOF
  cat >"$OUT/recipes/comp_rain_bgp.json" <<EOF
{"total_sec":900,"baseline_sec":20,"faults":["rain_fade","bgp_flap"],"rain_end_ms":40,"bgp_period_sec":5,"traffic_profile":"ttc_light","pack":"eff","fabric":"$FABRIC"}
EOF
  cat >"$OUT/recipes/comp_loss_util.json" <<EOF
{"total_sec":900,"baseline_sec":20,"faults":["loss_progression","util_congestion"],"loss_end_pct":6.0,"util_end_mbit":38,"traffic_profile":"idle","pack":"eff","fabric":"$FABRIC"}
EOF
  cat >"$OUT/recipes/comp_bgp_util.json" <<EOF
{"total_sec":900,"baseline_sec":20,"faults":["bgp_flap","util_congestion"],"bgp_period_sec":4,"util_end_mbit":35,"traffic_profile":"idle","pack":"eff","fabric":"$FABRIC"}
EOF
}

write_recipes

clear_all_fabric() {
  if [[ "$FABRIC" == gns3 ]]; then
    bash "$INJ_GNS3/clear_all.sh" >/dev/null 2>&1 || true
    bash "$INJ_GNS3/util_congestion.sh" --clear >/dev/null 2>&1 || true
    bash "$INJ_GNS3/capture_traffic.sh" --clear >/dev/null 2>&1 || true
  else
    for s in cpu_stress bgp_flap rain_fade loss_progression util_congestion; do
      bash "$ROOT/scripts/inject_${s}.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
    done
  fi
}

run_labeled() {
  local id="$1" recipe="$2" dest="$3"
  if done_job "$id"; then log "SKIP $id"; return 0; fi
  log "START $id → $dest"
  mkdir -p "$(dirname "$dest")"
  DECA_PRED_OUT="$dest" bash "$Q2_SCRIPT" \
    --label "$( $PY -c "import json;print(json.load(open('$recipe'))['label'])" )" \
    --prom "$PROM" \
    --recipe-json "$recipe" \
    --stamp "${STAMP}_${id}" \
    >"$OUT/logs/${id}.log" 2>&1
  mark_done "$id" "$dest"
  log "DONE $id"
}

run_compound() {
  local id="$1" recipe="$2" dest="$3"
  if done_job "$id"; then log "SKIP $id"; return 0; fi
  log "START $id → $dest"
  mkdir -p "$dest"
  DECA_FABRIC="$FABRIC" bash "$ROOT/predictive/run_compound_capture.sh" \
    --fabric "$FABRIC" --recipe-json "$recipe" --out "$dest" --host "$HOST" --prom "$PROM" \
    >"$OUT/logs/${id}.log" 2>&1
  echo "{\"train\":true,\"compound\":true,\"fabric\":\"$FABRIC\",\"recipe\":\"$recipe\"}" >"$dest/label.json"
  mark_done "$id" "$dest"
  log "DONE $id"
}

run_chaos() {
  local id="chaos_holdout"
  local dest="$OUT/chaos_holdout"
  if done_job "$id"; then log "SKIP $id"; return 0; fi
  log "START $id (90m, BGP period=3) fabric=$FABRIC"
  SECONDS_RUN=5400
  mkdir -p "$dest"
  T1=$((SECONDS_RUN * 15 / 100))
  T2=$((SECONDS_RUN * 35 / 100))
  T3=$((SECONDS_RUN * 50 / 100))
  T4=$((SECONDS_RUN * 65 / 100))
  T5=$((SECONDS_RUN * 80 / 100))
  T6=$SECONDS_RUN
  cat >"$dest/chaos_schedule.json" <<EOF
{"stamp":"$STAMP","fabric":"$FABRIC","seconds":$SECONDS_RUN,"train":false,"schema_version":2,
 "bgp_period_sec":3,
 "phases":[
  {"name":"healthy","t_start":0,"t_end":$T1,"faults":[]},
  {"name":"rain_fade","t_start":$T1,"t_end":$T2,"faults":["rain_fade"]},
  {"name":"rain_plus_cpu","t_start":$T2,"t_end":$T3,"faults":["rain_fade","cpu_stress"]},
  {"name":"loss_progression","t_start":$T3,"t_end":$T4,"faults":["loss_progression"]},
  {"name":"util_congestion","t_start":$T4,"t_end":$T5,"faults":["util_congestion"]},
  {"name":"bgp_flap","t_start":$T5,"t_end":$T6,"faults":["bgp_flap"]}
]}
EOF
  clear_all_fabric
  "$PY" -m predictive.capture_live --fabric "$FABRIC" --prom "$PROM" --out "$dest/series.csv" \
    --seconds "$SECONDS_RUN" --interval 1 >"$dest/capture.log" 2>&1 &
  CAP=$!
  trap 'clear_all_fabric; wait $CAP 2>/dev/null || true' EXIT
  sleep "$T1"
  RAIN_DUR=$((T3 - T1)); RAIN_STEPS=$((RAIN_DUR / 5)); [[ $RAIN_STEPS -lt 8 ]] && RAIN_STEPS=8
  CPU_DUR=$((T3 - T2))
  LOSS_DUR=$((T4 - T3)); LOSS_STEPS=$((LOSS_DUR / 5)); [[ $LOSS_STEPS -lt 12 ]] && LOSS_STEPS=12
  UTIL_DUR=$((T5 - T4)); UTIL_STEPS=$((UTIL_DUR / 20)); [[ $UTIL_STEPS -lt 6 ]] && UTIL_STEPS=6
  UTIL_STEP=$((UTIL_DUR / UTIL_STEPS)); [[ $UTIL_STEP -lt 10 ]] && UTIL_STEP=10
  BGP_DUR=$((T6 - T5)); CYCLES=$((BGP_DUR / 3)); [[ $CYCLES -lt 4 ]] && CYCLES=4

  if [[ "$FABRIC" == gns3 ]]; then
    STEPS=$RAIN_STEPS STEP_SEC=5 START_MS=2 END_MS=45 bash "$INJ_GNS3/rain_fade.sh" >"$dest/rain.log" 2>&1 &
    RAIN_PID=$!
    sleep $((T2 - T1))
    DUR=$CPU_DUR bash "$INJ_GNS3/cpu_stress.sh" >"$dest/cpu.log" 2>&1 &
    CPU_PID=$!
    sleep "$CPU_DUR"
    wait "$CPU_PID" 2>/dev/null || true
    wait "$RAIN_PID" 2>/dev/null || true
    bash "$INJ_GNS3/clear_all.sh" >/dev/null 2>&1 || true
    STEPS=$LOSS_STEPS STEP_SEC=5 END_LOSS=8.0 bash "$INJ_GNS3/loss_progression.sh" >"$dest/loss.log" 2>&1 &
    wait $! || true
    bash "$INJ_GNS3/clear_all.sh" >/dev/null 2>&1 || true
    STEPS=$UTIL_STEPS STEP_SEC=$UTIL_STEP START_MBIT=5 END_MBIT=38 bash "$INJ_GNS3/util_congestion.sh" >"$dest/util.log" 2>&1 &
    wait $! || true
    bash "$INJ_GNS3/util_congestion.sh" --clear >/dev/null 2>&1 || true
    log "chaos BGP ${BGP_DUR}s period=3 cycles=$CYCLES"
    CYCLES=$CYCLES PERIOD=3 bash "$INJ_GNS3/bgp_flap.sh" >"$dest/bgp.log" 2>&1 &
    wait $! || true
  else
    bash "$ROOT/scripts/inject_rain_fade.sh" --host "$HOST" --steps "$RAIN_STEPS" --step-sec 5 --start-ms 2 --end-ms 45 \
      >"$dest/rain.log" 2>&1 &
    RAIN_PID=$!
    sleep $((T2 - T1))
    bash "$ROOT/scripts/inject_cpu_stress.sh" --host "$HOST" --seconds "$CPU_DUR" >"$dest/cpu.log" 2>&1 &
    CPU_PID=$!
    sleep "$CPU_DUR"
    wait "$CPU_PID" 2>/dev/null || true
    wait "$RAIN_PID" 2>/dev/null || true
    bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
    bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
    bash "$ROOT/scripts/inject_loss_progression.sh" --host "$HOST" --steps "$LOSS_STEPS" --step-sec 5 --start-pct 0 --end-pct 8.0 \
      >"$dest/loss.log" 2>&1 &
    wait $! || true
    bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
    bash "$ROOT/scripts/inject_util_congestion.sh" --host "$HOST" --steps "$UTIL_STEPS" --step-sec "$UTIL_STEP" \
      --start-mbit 5 --end-mbit 38 --schedule-out "$dest/util_ceil_schedule.jsonl" \
      >"$dest/util.log" 2>&1 &
    wait $! || true
    bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
    log "chaos BGP ${BGP_DUR}s period=3 cycles=$CYCLES"
    bash "$ROOT/scripts/inject_bgp_flap.sh" --host "$HOST" --cycles "$CYCLES" --period-sec 3 \
      >"$dest/bgp.log" 2>&1 &
    wait $! || true
  fi
  clear_all_fabric
  wait "$CAP" || true
  trap - EXIT
  echo "{\"train\":false,\"name\":\"chaos\",\"schema_version\":2,\"bgp_period_sec\":3,\"fabric\":\"$FABRIC\"}" >"$dest/label.json"
  mark_done "$id" "$dest"
  log "DONE $id"
}

log "=== Efficiency pack START stamp=$STAMP fabric=$FABRIC ==="
log "ETA ≈ 6–7h capture. Plan: $OUT/PACK_PLAN.md"
printf '{"stamp":"%s","fabric":"%s","started":"%s","eta_hours":6.5,"status":"running"}\n' \
  "$STAMP" "$FABRIC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATE"
if [[ "$FABRIC" == gns3 ]]; then
  echo "$STAMP" >"$ROOT/data/deca/predictive/protocol_gns3/ACTIVE_EFF_PACK_GNS3.json"
else
  echo "$STAMP" >"$ROOT/data/deca/predictive/protocol/ACTIVE_EFF_PACK.json"
fi

for r in "$OUT"/recipes/l3_storm_*.json "$OUT"/recipes/l3_mild_*.json; do
  base=$(basename "$r" .json)
  run_labeled "L3_${base}" "$r" "$OUT/L3_bgp_flap/${base}"
done
for r in "$OUT"/recipes/l4_mild_*.json "$OUT"/recipes/l4_deep_*.json; do
  base=$(basename "$r" .json)
  run_labeled "L4_${base}" "$r" "$OUT/L4_loss_progression/${base}"
done
for r in "$OUT"/recipes/l1_*.json; do
  base=$(basename "$r" .json)
  run_labeled "L1_${base}" "$r" "$OUT/L1_rain_fade/${base}"
done
run_compound "COMP_bgp_loss" "$OUT/recipes/comp_bgp_loss.json" "$OUT/COMPOUND/iter_01"
run_compound "COMP_rain_bgp" "$OUT/recipes/comp_rain_bgp.json" "$OUT/COMPOUND/iter_02"
run_compound "COMP_loss_util" "$OUT/recipes/comp_loss_util.json" "$OUT/COMPOUND/iter_03"
run_compound "COMP_bgp_util" "$OUT/recipes/comp_bgp_util.json" "$OUT/COMPOUND/iter_04"
run_chaos

printf '{"stamp":"%s","fabric":"%s","finished":"%s","status":"capture_complete"}\n' \
  "$STAMP" "$FABRIC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATE"
log "=== CAPTURE COMPLETE $STAMP fabric=$FABRIC ==="
echo "DONE $OUT"
