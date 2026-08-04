#!/usr/bin/env bash
# run_q2_campaign_gns3.sh — GNS3 fabric Q2 capture (Prom :9091 + lab/gns3/inject).
# Optional --recipe-json for variant campaigns (same schema as Pi).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export DECA_FABRIC=gns3
PROM="${DECA_PROM_URL_GNS3:-${DECA_PROM_URL:-http://127.0.0.1:9091}}"
[[ "$PROM" == *":9090"* ]] && PROM="http://127.0.0.1:9091"
LABEL=""
BASELINE_SEC=20
INJECT_SEC=90
POST_SEC=20
SECONDS_ONLY=0
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
INJ="$ROOT/lab/gns3/inject"
RECIPE_JSON=""

START_MS=2; END_MS=45; STEP_SEC=5; JITTER_MS=5
WORKERS=0; PERIOD_SEC=5; CYCLES=0
START_PCT=0; END_PCT=3.5
START_MBIT=5; END_MBIT=38
TRAFFIC_PROFILE=idle; ROGUE_MBIT=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --host) shift 2 ;;
    --baseline-sec) BASELINE_SEC="$2"; shift 2 ;;
    --inject-sec) INJECT_SEC="$2"; shift 2 ;;
    --post-sec) POST_SEC="$2"; shift 2 ;;
    --seconds) SECONDS_ONLY="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --recipe-json) RECIPE_JSON="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

[[ -n "$LABEL" ]] || { echo "--label required"; exit 2; }

if [[ -n "$RECIPE_JSON" ]]; then
  eval "$("$PY" - <<PY
import json
r=json.load(open("$RECIPE_JSON"))
mapping={
  "baseline_sec":"BASELINE_SEC","inject_sec":"INJECT_SEC","post_sec":"POST_SEC",
  "seconds":"SECONDS_ONLY","start_ms":"START_MS","end_ms":"END_MS","step_sec":"STEP_SEC",
  "jitter_ms":"JITTER_MS","workers":"WORKERS","period_sec":"PERIOD_SEC","cycles":"CYCLES",
  "start_pct":"START_PCT","end_pct":"END_PCT","start_mbit":"START_MBIT","end_mbit":"END_MBIT",
  "traffic_profile":"TRAFFIC_PROFILE","rogue_mbit":"ROGUE_MBIT",
}
for rk, sk in mapping.items():
    if rk in r:
        v=r[rk]
        print(f"{sk}={v if not isinstance(v,str) else repr(v)}")
if "label" in r:
    print(f"LABEL={int(r['label'])}")
PY
)"
fi

case "$LABEL" in
  0) NAME=normal ;;
  1) NAME=rain_fade ;;
  2) NAME=cpu_stress ;;
  3) NAME=bgp_flap ;;
  4) NAME=loss_progression ;;
  5) NAME=util_congestion ;;
  6) NAME=ce_sla_conflict ;;
  *) echo "label must be 0..6"; exit 2 ;;
esac

OUT="${DECA_PRED_OUT:-$ROOT/data/deca/predictive/protocol_gns3/q2_captures/${STAMP}_L${LABEL}_${NAME}}"
mkdir -p "$OUT"

if [[ "$LABEL" -eq 0 ]]; then
  TOTAL_SEC="${SECONDS_ONLY:-90}"
  [[ "$TOTAL_SEC" -le 0 ]] && TOTAL_SEC=90
  BASELINE_SEC=0; INJECT_SEC=0; POST_SEC="$TOTAL_SEC"
else
  TOTAL_SEC=$((BASELINE_SEC + INJECT_SEC + POST_SEC))
fi

echo "=== GNS3 Q2 label=$LABEL ($NAME) total≈${TOTAL_SEC}s recipe=${RECIPE_JSON:-legacy} ==="

clear_injectors() {
  bash "$INJ/clear_all.sh" >/dev/null 2>&1 || true
  bash "$INJ/util_congestion.sh" --clear >/dev/null 2>&1 || true
  bash "$INJ/ce_sla_conflict.sh" --clear >/dev/null 2>&1 || true
  bash "$INJ/capture_traffic.sh" --clear >/dev/null 2>&1 || true
}
clear_injectors

if [[ "$LABEL" -eq 0 || "$LABEL" -eq 5 || "$LABEL" -eq 6 ]]; then
  TRAFFIC_PROFILE=idle
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PROM_URL_GNS3="$PROM"
"$PY" -m predictive.capture_live --fabric gns3 --prom "$PROM" \
  --out "$OUT/series.csv" --seconds "$TOTAL_SEC" --interval 1 \
  >"$OUT/capture.log" 2>&1 &
CAP_PID=$!
TRAFFIC_PID=0
trap 'clear_injectors; [[ ${TRAFFIC_PID:-0} -gt 0 ]] && kill $TRAFFIC_PID 2>/dev/null || true; wait $CAP_PID 2>/dev/null || true' EXIT

[[ "$BASELINE_SEC" -gt 0 ]] && { echo "=== baseline ${BASELINE_SEC}s ==="; sleep "$BASELINE_SEC"; }

if [[ "$LABEL" -ne 0 && "$TRAFFIC_PROFILE" != "idle" ]]; then
  echo "=== gns3 traffic profile=$TRAFFIC_PROFILE ==="
  PROFILE=$TRAFFIC_PROFILE DUR=$INJECT_SEC bash "$INJ/capture_traffic.sh" >"$OUT/traffic.log" 2>&1 &
  TRAFFIC_PID=$!
fi

if [[ "$LABEL" -eq 1 ]]; then
  STEPS=$(( INJECT_SEC / STEP_SEC )); [[ "$STEPS" -lt 8 ]] && STEPS=8
  STEPS=$STEPS STEP_SEC=$STEP_SEC START_MS=$START_MS END_MS=$END_MS \
    bash "$INJ/rain_fade.sh" >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 2 ]]; then
  DUR=$INJECT_SEC WORKERS=${WORKERS:-0} bash "$INJ/cpu_stress.sh" >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 3 ]]; then
  [[ "$CYCLES" -le 0 ]] && CYCLES=$(( INJECT_SEC / PERIOD_SEC ))
  [[ "$CYCLES" -lt 6 ]] && CYCLES=6
  CYCLES=$CYCLES PERIOD=$PERIOD_SEC bash "$INJ/bgp_flap.sh" >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 4 ]]; then
  STEPS=$(( INJECT_SEC / STEP_SEC )); [[ "$STEPS" -lt 12 ]] && STEPS=12
  STEPS=$STEPS STEP_SEC=$STEP_SEC END_LOSS=$END_PCT \
    bash "$INJ/loss_progression.sh" >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 5 ]]; then
  STEPS=$(( INJECT_SEC / STEP_SEC )); [[ "$STEPS" -lt 6 ]] && STEPS=6
  STEPS=$STEPS STEP_SEC=$STEP_SEC START_MBIT=$START_MBIT END_MBIT=$END_MBIT \
    bash "$INJ/util_congestion.sh" >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 6 ]]; then
  STEPS=$(( INJECT_SEC / 15 )); [[ "$STEPS" -lt 4 ]] && STEPS=4
  STEPS=$STEPS STEP_SEC=15 START_MBIT=${START_MBIT:-3} END_MBIT=$ROGUE_MBIT \
    bash "$INJ/ce_sla_conflict.sh" >"$OUT/inject.log" 2>&1 &
  wait $! || true
fi

if [[ "$TRAFFIC_PID" -gt 0 ]]; then
  wait "$TRAFFIC_PID" 2>/dev/null || true
  TRAFFIC_PID=0
fi
bash "$INJ/capture_traffic.sh" --clear >/dev/null 2>&1 || true

if [[ "$POST_SEC" -gt 0 && "$LABEL" -ne 0 ]]; then
  echo "=== post ${POST_SEC}s ==="; sleep "$POST_SEC"
elif [[ "$LABEL" -eq 0 ]]; then
  wait "$CAP_PID" || true
fi

clear_injectors
wait "$CAP_PID" || true
trap - EXIT

"$PY" - <<PY
import json, time
from pathlib import Path
out=Path("$OUT")
meta={"label":int("$LABEL"),"name":"$NAME","fabric":"gns3","host":"gns3-pe1",
      "total_sec":int("$TOTAL_SEC"),"variant":bool("$RECIPE_JSON"),
      "finished_unix":time.time()}
if "$RECIPE_JSON":
    meta["recipe"]=json.loads(Path("$RECIPE_JSON").read_text())
(out/"label.json").write_text(json.dumps(meta, indent=2)+"\n")
PY

set +eu
"$PY" -m predictive.q2_windows --capture "$OUT/series.csv" --label "$LABEL" --out-dir "$OUT" \
  | tee "$OUT/windows_summary.json" || true
set -eu
echo "GNS3 Q2 campaign complete: $OUT"
