#!/usr/bin/env bash
# run_q2_campaign.sh — capture Prom series while injecting a Q2 fault class.
#
# Labels: 0=normal 1=rain_fade 2=cpu_stress 3=bgp_flap 4=loss_progression 5=util_congestion
#
# Optional --recipe-json FILE overrides inject endpoints (variant campaigns).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
LABEL=""
HOST=station1
BASELINE_SEC=20
INJECT_SEC=90
POST_SEC=20
SECONDS_ONLY=0
PY="${DECA_PRED_PYTHON:-python3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RECIPE_JSON=""

# Variant knobs (defaults = legacy fixed recipe)
START_MS=2
END_MS=45
STEP_SEC=5
JITTER_MS=5
WORKERS=0
PERIOD_SEC=5
CYCLES=0
LINK_BOUNCE=0
START_PCT=0
END_PCT=3.5
START_MBIT=5
END_MBIT=38
PARALLEL=2
TRAFFIC_PROFILE=idle
ROGUE_MBIT=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --baseline-sec) BASELINE_SEC="$2"; shift 2 ;;
    --inject-sec) INJECT_SEC="$2"; shift 2 ;;
    --post-sec) POST_SEC="$2"; shift 2 ;;
    --seconds) SECONDS_ONLY="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --recipe-json) RECIPE_JSON="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

[[ -n "$LABEL" ]] || { echo "--label required (0|1|2|3|4|5|6)"; exit 2; }

if [[ -n "$RECIPE_JSON" ]]; then
  eval "$("$PY" - <<PY
import json
r=json.load(open("$RECIPE_JSON"))
def e(k, default=None):
    v=r.get(k, default)
    if v is None: return
    if isinstance(v, bool):
        print(f'{k.upper()}={"1" if v else "0"}')
    else:
        print(f"{k.upper()}={v!r}")
# map recipe keys → shell vars
mapping={
  "baseline_sec":"BASELINE_SEC","inject_sec":"INJECT_SEC","post_sec":"POST_SEC",
  "seconds":"SECONDS_ONLY","start_ms":"START_MS","end_ms":"END_MS","step_sec":"STEP_SEC",
  "jitter_ms":"JITTER_MS","workers":"WORKERS","period_sec":"PERIOD_SEC","cycles":"CYCLES",
  "link_bounce":"LINK_BOUNCE","start_pct":"START_PCT","end_pct":"END_PCT",
  "start_mbit":"START_MBIT","end_mbit":"END_MBIT","parallel":"PARALLEL",
  "traffic_profile":"TRAFFIC_PROFILE","rogue_mbit":"ROGUE_MBIT",
}
for rk, sk in mapping.items():
    if rk in r:
        v=r[rk]
        if isinstance(v, bool):
            print(f'{sk}={"1" if v else "0"}')
        elif isinstance(v, str):
            print(f"{sk}={v!r}")
        else:
            print(f"{sk}={v}")
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

OUT="${DECA_PRED_OUT:-$ROOT/data/deca/predictive/q2_captures/${STAMP}_L${LABEL}_${NAME}}"
mkdir -p "$OUT"

if [[ "$LABEL" -eq 0 ]]; then
  TOTAL_SEC="${SECONDS_ONLY:-90}"
  [[ "$TOTAL_SEC" -le 0 ]] && TOTAL_SEC=90
  BASELINE_SEC=0
  INJECT_SEC=0
  POST_SEC="$TOTAL_SEC"
else
  TOTAL_SEC=$((BASELINE_SEC + INJECT_SEC + POST_SEC))
fi

echo "=== Q2 campaign label=$LABEL ($NAME) ==="
echo "out=$OUT total≈${TOTAL_SEC}s prom=$PROM recipe=${RECIPE_JSON:-legacy}"

clear_injectors() {
  bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_bgp_flap.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_ce_sla_conflict.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/run_capture_traffic.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
}

clear_injectors

# L0 always idle; L5/CE own traffic path
if [[ "$LABEL" -eq 0 || "$LABEL" -eq 5 || "$LABEL" -eq 6 ]]; then
  TRAFFIC_PROFILE=idle
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$PY" -m predictive.capture_live \
  --prom "$PROM" \
  --out "$OUT/series.csv" \
  --seconds "$TOTAL_SEC" \
  --interval 1 \
  >"$OUT/capture.log" 2>&1 &
CAP_PID=$!
echo "capture pid=$CAP_PID"

TRAFFIC_PID=0
cleanup() {
  clear_injectors
  [[ "$TRAFFIC_PID" -gt 0 ]] && kill "$TRAFFIC_PID" 2>/dev/null || true
  if kill -0 "$CAP_PID" 2>/dev/null; then
    wait "$CAP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$BASELINE_SEC" -gt 0 ]]; then
  echo "=== baseline ${BASELINE_SEC}s ==="
  sleep "$BASELINE_SEC"
fi

# Background traffic for fault×traffic matrix (parallel with inject)
if [[ "$LABEL" -ne 0 && "$TRAFFIC_PROFILE" != "idle" ]]; then
  echo "=== background traffic profile=$TRAFFIC_PROFILE ${INJECT_SEC}s ==="
  bash "$ROOT/scripts/run_capture_traffic.sh" --host "$HOST" \
    --profile "$TRAFFIC_PROFILE" --seconds "$INJECT_SEC" \
    >"$OUT/traffic.log" 2>&1 &
  TRAFFIC_PID=$!
fi

if [[ "$LABEL" -eq 1 ]]; then
  echo "=== inject rain fade ${INJECT_SEC}s end_ms=$END_MS ==="
  STEPS=$(( INJECT_SEC / STEP_SEC ))
  [[ "$STEPS" -lt 8 ]] && STEPS=8
  bash "$ROOT/scripts/inject_rain_fade.sh" \
    --host "$HOST" --steps "$STEPS" --step-sec "$STEP_SEC" \
    --start-ms "$START_MS" --end-ms "$END_MS" --jitter-ms "$JITTER_MS" \
    >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 2 ]]; then
  echo "=== inject cpu stress ${INJECT_SEC}s workers=$WORKERS ==="
  CPU_ARGS=(--host "$HOST" --seconds "$INJECT_SEC")
  [[ "$WORKERS" -gt 0 ]] && CPU_ARGS+=(--workers "$WORKERS")
  bash "$ROOT/scripts/inject_cpu_stress.sh" "${CPU_ARGS[@]}" \
    >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 3 ]]; then
  echo "=== inject bgp flap ${INJECT_SEC}s period=$PERIOD_SEC ==="
  if [[ "$CYCLES" -le 0 ]]; then
    CYCLES=$(( INJECT_SEC / PERIOD_SEC ))
  fi
  [[ "$CYCLES" -lt 6 ]] && CYCLES=6
  BGP_ARGS=(--host "$HOST" --cycles "$CYCLES" --period-sec "$PERIOD_SEC")
  [[ "$LINK_BOUNCE" == "1" ]] && BGP_ARGS+=(--link-bounce)
  bash "$ROOT/scripts/inject_bgp_flap.sh" "${BGP_ARGS[@]}" \
    >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 4 ]]; then
  echo "=== inject loss ${INJECT_SEC}s end_pct=$END_PCT ==="
  STEPS=$(( INJECT_SEC / STEP_SEC ))
  [[ "$STEPS" -lt 12 ]] && STEPS=12
  bash "$ROOT/scripts/inject_loss_progression.sh" \
    --host "$HOST" --steps "$STEPS" --step-sec "$STEP_SEC" \
    --start-pct "$START_PCT" --end-pct "$END_PCT" \
    >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 5 ]]; then
  echo "=== inject util ${INJECT_SEC}s end_mbit=$END_MBIT ==="
  STEPS=$(( INJECT_SEC / STEP_SEC ))
  [[ "$STEPS" -lt 6 ]] && STEPS=6
  bash "$ROOT/scripts/inject_util_congestion.sh" \
    --host "$HOST" --steps "$STEPS" --step-sec "$STEP_SEC" \
    --start-mbit "$START_MBIT" --end-mbit "$END_MBIT" --parallel "$PARALLEL" \
    >"$OUT/inject.log" 2>&1 &
  wait $! || true
elif [[ "$LABEL" -eq 6 ]]; then
  echo "=== inject CE SLA conflict ${INJECT_SEC}s rogue_mbit=$ROGUE_MBIT ==="
  STEPS=$(( INJECT_SEC / 18 ))
  [[ "$STEPS" -lt 4 ]] && STEPS=4
  bash "$ROOT/scripts/inject_ce_sla_conflict.sh" --host "$HOST" --force-clear \
    --start-mbit "${START_MBIT:-2}" --rogue-mbit "$ROGUE_MBIT" \
    --steps "$STEPS" --step-sec 18 \
    >"$OUT/inject.log" 2>&1 &
  wait $! || true
fi

if [[ "$TRAFFIC_PID" -gt 0 ]]; then
  wait "$TRAFFIC_PID" 2>/dev/null || true
  TRAFFIC_PID=0
fi
bash "$ROOT/scripts/run_capture_traffic.sh" --clear --host "$HOST" >/dev/null 2>&1 || true


if [[ "$POST_SEC" -gt 0 && "$LABEL" -ne 0 ]]; then
  echo "=== post ${POST_SEC}s ==="
  sleep "$POST_SEC"
elif [[ "$LABEL" -eq 0 ]]; then
  wait "$CAP_PID" || true
fi

echo "=== clear injectors ==="
clear_injectors
tee -a "$OUT/clear.log" </dev/null >/dev/null || true
wait "$CAP_PID" || true
trap - EXIT

# Rich label metadata (includes full recipe when present)
"$PY" - <<PY
import json, time
from pathlib import Path
out = Path("$OUT")
meta = {
  "label": int("$LABEL"),
  "name": "$NAME",
  "host": "$HOST",
  "total_sec": int("$TOTAL_SEC"),
  "baseline_sec": int("$BASELINE_SEC"),
  "inject_sec": int("$INJECT_SEC"),
  "post_sec": int("$POST_SEC"),
  "prom": "$PROM",
  "finished_unix": time.time(),
  "variant": True if "$RECIPE_JSON" else False,
}
rp = "$RECIPE_JSON"
if rp:
    meta["recipe"] = json.loads(Path(rp).read_text())
(out / "label.json").write_text(json.dumps(meta, indent=2) + "\n")
print("wrote", out / "label.json")
PY

echo "=== build Q2 windows ==="
set +e
"$PY" -m predictive.q2_windows --capture "$OUT/series.csv" --label "$LABEL" --out-dir "$OUT" \
  | tee "$OUT/windows_summary.json"
set -e

echo
echo "Q2 campaign complete: $OUT"
