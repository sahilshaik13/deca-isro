#!/usr/bin/env bash
# run_compound_capture.sh — overlapping faults for train (labeled compound).
# Usage:
#   bash predictive/run_compound_capture.sh --recipe-json R.json --out DEST --host station1 --prom URL
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
HOST=station1
PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
OUT=""
RECIPE_JSON=""
FABRIC="${DECA_FABRIC:-pi}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recipe-json) RECIPE_JSON="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    *) echo "unknown $1"; exit 2 ;;
  esac
done
[[ -n "$RECIPE_JSON" && -n "$OUT" ]] || { echo "need --recipe-json and --out"; exit 2; }
mkdir -p "$OUT"

clear_all() {
  if [[ "$FABRIC" == gns3 ]]; then
    bash "$ROOT/lab/gns3/inject/clear_all.sh" >/dev/null 2>&1 || true
    bash "$ROOT/lab/gns3/inject/util_congestion.sh" --clear >/dev/null 2>&1 || true
    bash "$ROOT/lab/gns3/inject/capture_traffic.sh" --clear >/dev/null 2>&1 || true
  else
    for s in cpu_stress bgp_flap rain_fade loss_progression util_congestion; do
      bash "$ROOT/scripts/inject_${s}.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
    done
    bash "$ROOT/scripts/run_capture_traffic.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  fi
}

# Parse recipe
read -r TOTAL_SEC BASELINE_SEC FAULTS_CSV RAIN_END LOSS_END UTIL_END CPU_W BGP_P TRAFFIC < <(
"$PY" - <<PY
import json
r=json.load(open("$RECIPE_JSON"))
print(r["total_sec"], r.get("baseline_sec",10), ",".join(r["faults"]),
      r.get("rain_end_ms",45), r.get("loss_end_pct",3.5), r.get("util_end_mbit",35),
      r.get("cpu_workers",0), r.get("bgp_period_sec",5), r.get("traffic_profile","idle"))
PY
)

clear_all
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$PY" -m predictive.capture_live \
  ${FABRIC:+--fabric $FABRIC} \
  --prom "$PROM" --out "$OUT/series.csv" --seconds "$TOTAL_SEC" --interval 1 \
  >"$OUT/capture.log" 2>&1 &
CAP=$!
trap 'clear_all; wait $CAP 2>/dev/null || true' EXIT

echo "=== compound baseline ${BASELINE_SEC}s faults=$FAULTS_CSV ==="
[[ "$BASELINE_SEC" -gt 0 ]] && sleep "$BASELINE_SEC"
INJECT_SEC=$(( TOTAL_SEC - BASELINE_SEC - 15 ))
[[ "$INJECT_SEC" -lt 60 ]] && INJECT_SEC=60

TRAFFIC_PID=0
if [[ "$TRAFFIC" != "idle" ]]; then
  echo "=== compound background traffic=$TRAFFIC ${INJECT_SEC}s ==="
  if [[ "$FABRIC" == gns3 ]]; then
    PROFILE=$TRAFFIC DUR=$INJECT_SEC bash "$ROOT/lab/gns3/inject/capture_traffic.sh" >>"$OUT/inject.log" 2>&1 &
  else
    bash "$ROOT/scripts/run_capture_traffic.sh" --host "$HOST" --profile "$TRAFFIC" --seconds "$INJECT_SEC" >>"$OUT/inject.log" 2>&1 &
  fi
  TRAFFIC_PID=$!
fi

IFS=',' read -ra FAULTS <<<"$FAULTS_CSV"
PIDS=()
for f in "${FAULTS[@]}"; do
  echo "=== start compound fault=$f ==="
  if [[ "$FABRIC" == gns3 ]]; then
    case "$f" in
      rain_fade)
        STEPS=$((INJECT_SEC/5)); [[ $STEPS -lt 8 ]] && STEPS=8
        STEPS=$STEPS STEP_SEC=5 START_MS=2 END_MS=$RAIN_END \
          bash "$ROOT/lab/gns3/inject/rain_fade.sh" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      cpu_stress)
        DUR=$INJECT_SEC WORKERS=${CPU_W:-0} bash "$ROOT/lab/gns3/inject/cpu_stress.sh" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      bgp_flap)
        CYC=$((INJECT_SEC/BGP_P)); [[ $CYC -lt 6 ]] && CYC=6
        CYCLES=$CYC PERIOD=$BGP_P bash "$ROOT/lab/gns3/inject/bgp_flap.sh" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      loss_progression)
        STEPS=$((INJECT_SEC/5)); [[ $STEPS -lt 12 ]] && STEPS=12
        STEPS=$STEPS STEP_SEC=5 END_LOSS=$LOSS_END \
          bash "$ROOT/lab/gns3/inject/loss_progression.sh" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      util_congestion)
        STEPS=$((INJECT_SEC/15)); [[ $STEPS -lt 6 ]] && STEPS=6
        STEPS=$STEPS STEP_SEC=15 START_MBIT=5 END_MBIT=$UTIL_END \
          bash "$ROOT/lab/gns3/inject/util_congestion.sh" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
    esac
  else
    case "$f" in
      rain_fade)
        STEPS=$((INJECT_SEC/5)); [[ $STEPS -lt 8 ]] && STEPS=8
        bash "$ROOT/scripts/inject_rain_fade.sh" --host "$HOST" --steps "$STEPS" --step-sec 5 \
          --start-ms 2 --end-ms "$RAIN_END" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      cpu_stress)
        ARGS=(--host "$HOST" --seconds "$INJECT_SEC")
        [[ "$CPU_W" -gt 0 ]] && ARGS+=(--workers "$CPU_W")
        bash "$ROOT/scripts/inject_cpu_stress.sh" "${ARGS[@]}" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      bgp_flap)
        CYC=$((INJECT_SEC/BGP_P)); [[ $CYC -lt 6 ]] && CYC=6
        bash "$ROOT/scripts/inject_bgp_flap.sh" --host "$HOST" --cycles "$CYC" --period-sec "$BGP_P" \
          >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      loss_progression)
        STEPS=$((INJECT_SEC/5)); [[ $STEPS -lt 12 ]] && STEPS=12
        bash "$ROOT/scripts/inject_loss_progression.sh" --host "$HOST" --steps "$STEPS" --step-sec 5 \
          --start-pct 0 --end-pct "$LOSS_END" >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
      util_congestion)
        STEPS=$((INJECT_SEC/15)); [[ $STEPS -lt 6 ]] && STEPS=6
        bash "$ROOT/scripts/inject_util_congestion.sh" --host "$HOST" --steps "$STEPS" --step-sec 15 \
          --start-mbit 5 --end-mbit "$UTIL_END" --parallel 2 >>"$OUT/inject.log" 2>&1 &
        PIDS+=($!) ;;
    esac
  fi
  sleep 2
done

# Wait for inject window then clear
sleep "$INJECT_SEC" || true
for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
[[ "$TRAFFIC_PID" -gt 0 ]] && kill "$TRAFFIC_PID" 2>/dev/null || true
clear_all
wait "$CAP" || true
trap - EXIT

cp -a "$RECIPE_JSON" "$OUT/recipe.json"
"$PY" - <<PY
import json, time
from pathlib import Path
import pandas as pd
from predictive.compound_label import dominant_root_label
from predictive.q2_windows import build_windows

out=Path("$OUT")
r=json.loads(Path("$RECIPE_JSON").read_text())
series=out/"series.csv"
df=pd.read_csv(series)
root_lab, dbg = dominant_root_label(df, r.get("faults") or [])
meta={
  "label": int(root_lab),
  "label_name":"compound",
  "name":"compound",
  "train":True,
  "is_compound":True,
  "fabric":"$FABRIC",
  "host":"$HOST",
  "total_sec":int("$TOTAL_SEC"),
  "recipe":r,
  "dominant_label":dbg,
  "finished_unix":time.time(),
}
(out/"label.json").write_text(json.dumps(meta, indent=2)+"\n")
(out/"compound_label.json").write_text(json.dumps(dbg, indent=2)+"\n")
win_df, wmeta = build_windows(df, label=int(root_lab), skip_head=15)
if not win_df.empty:
    win_df = win_df.copy()
    win_df["is_compound"] = 1
    win_df["root_label"] = int(root_lab)
    win_df.to_csv(out/"q2_windows.csv", index=False)
    wmeta["is_compound"] = True
    wmeta["dominant_label"] = dbg
    (out/"q2_meta.json").write_text(json.dumps(wmeta, indent=2)+"\n")
print("compound complete", out, "dominant_root", root_lab, "windows", len(win_df))
PY
