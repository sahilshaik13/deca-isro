#!/usr/bin/env bash
# resume_active_protocol.sh — resume ACTIVE_STAMP after desktop power-cut / manual pause.
#
# Idempotent:
#   - if campaign already running → ensure watchdog, exit 0
#   - finish remaining L0 into series_cont*, merge, then L1–L5 + chaos
#   - clears pause latch (including manual) when intentionally resuming
#
# Usage:
#   bash predictive/resume_active_protocol.sh
#   STAMP=20260729T202832Z bash predictive/resume_active_protocol.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ACTIVE_JSON="$ROOT/data/deca/predictive/protocol/ACTIVE_STAMP.json"
STAMP="${STAMP:-}"
if [[ -z "$STAMP" && -f "$ACTIVE_JSON" ]]; then
  STAMP="$(python3 -c 'import json; print(json.load(open("'"$ACTIVE_JSON"'"))["active_stamp"])')"
fi
[[ -n "$STAMP" ]] || { echo "No STAMP / ACTIVE_STAMP.json"; exit 2; }

OUT_ROOT="$ROOT/data/deca/predictive/protocol/$STAMP"
L0="$OUT_ROOT/L0_normal/iter_01"
SERIES="$L0/series.csv"
LOG="$ROOT/data/deca/predictive/protocol/full_${STAMP}.resume.log"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
HOST="${DECA_INJECT_HOST:-station1}"
L0_TARGET=86400
MANIFEST="$OUT_ROOT/manifest.jsonl"
PAUSE_LATCH="$OUT_ROOT/CAPTURE_PAUSE"
PAUSE_JSON="$OUT_ROOT/capture_paused.json"
STATIONS_CSV="${DECA_STATIONS:-192.168.50.10,192.168.50.20,192.168.50.30}"

mkdir -p "$OUT_ROOT" "$L0"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"
export DECA_PROM_URL="$PROM"
export DECA_CAPTURE_PAUSE_FILE="$PAUSE_LATCH"

exec >>"$LOG" 2>&1
echo "=== resume_active start $(date -u +%Y-%m-%dT%H:%M:%SZ) pid=$$ stamp=$STAMP ==="

already_running() {
  pgrep -f "run_protocol_campaign.sh.*--stamp ${STAMP}" >/dev/null 2>&1 \
    || pgrep -f "predictive.capture_live.*${STAMP}" >/dev/null 2>&1 \
    || pgrep -f "resume_active_protocol.sh" >/dev/null 2>&1 \
       && pgrep -f "capture_live.*${STAMP}" >/dev/null 2>&1
}

ensure_watchdog() {
  if ! pgrep -f "watch_protocol_capture.sh" >/dev/null 2>&1; then
    echo "starting watchdog for $STAMP"
    setsid env STAMP="$STAMP" INTERVAL=30 \
      bash "$ROOT/predictive/watch_protocol_capture.sh" </dev/null >/dev/null 2>&1 &
  fi
}

# If a sibling resume already owns the work, just ensure watchdog
if pgrep -f "run_protocol_campaign.sh.*${STAMP}" >/dev/null 2>&1 \
  || pgrep -f "predictive.capture_live.*${STAMP}" >/dev/null 2>&1; then
  echo "campaign already running for $STAMP — ensuring watchdog only"
  # If SIGSTOP'd, CONT
  for pid in $(pgrep -f "run_protocol_campaign.sh|run_q2_campaign.sh|predictive.capture_live" || true); do
    kill -CONT "$pid" 2>/dev/null || true
  done
  rm -f "$PAUSE_LATCH"
  python3 - <<PY
import json, time
from pathlib import Path
Path("$PAUSE_JSON").write_text(json.dumps({
  "paused": False,
  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "reason": "resume_active: processes already present — CONT",
  "stamp": "$STAMP",
  "manual": False,
}, indent=2) + "\n")
PY
  ensure_watchdog
  exit 0
fi

clear_all() {
  bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_bgp_flap.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
}

wait_lab_healthy() {
  local tries=0 max_tries="${LAB_WAIT_TRIES:-60}"  # ~10 min @ 10s
  echo "waiting for lab healthy (Prom + 3 stations ping + telegraf)…"
  while (( tries < max_tries )); do
    local up=0 tg=0 ok_prom=0
    if curl -sf --max-time 3 "$PROM/-/ready" >/dev/null 2>&1; then
      local lat
      lat=$(curl -sg --max-time 3 \
        --data-urlencode 'query=sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",host="station1",path="gre",src="edge"}' \
        "$PROM/api/v1/query" \
        | python3 -c 'import sys,json; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")' 2>/dev/null || true)
      [[ -n "$lat" ]] && ok_prom=1
    fi
    local IFS=',' ip
    for ip in $STATIONS_CSV; do
      if ping -c1 -W1 "$ip" >/dev/null 2>&1; then
        up=$((up + 1))
        curl -sf --max-time 2 "http://${ip}:9273/metrics" >/dev/null 2>&1 && tg=$((tg + 1)) || true
      fi
    done
    echo "  try=$((tries+1)) stations=$up/3 telegraf=$tg/3 prom_q1=$ok_prom"
    if [[ "$up" -ge 3 && "$tg" -ge 1 && "$ok_prom" -eq 1 ]]; then
      echo "lab healthy"
      return 0
    fi
    # best-effort telemetry bridge nudge every ~2 min
    if (( tries > 0 && tries % 12 == 0 )) && [[ -f "$ROOT/lab/telemetry-pipeline/docker-compose.yml" ]]; then
      docker compose -f "$ROOT/lab/telemetry-pipeline/docker-compose.yml" restart telemetry-bridge >/dev/null 2>&1 || true
    fi
    tries=$((tries + 1))
    sleep 10
  done
  echo "WARN: lab not fully healthy after wait — proceeding cautiously"
  return 0
}

# Clear manual/auto pause latch — this is an intentional resume
rm -f "$PAUSE_LATCH"
python3 - <<PY
import json, time
from pathlib import Path
Path("$PAUSE_JSON").write_text(json.dumps({
  "paused": False,
  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "reason": "resume_active_protocol intentional start",
  "stamp": "$STAMP",
  "manual": False,
}, indent=2) + "\n")
PY

wait_lab_healthy
clear_all
ensure_watchdog

# --- L0 finish ---
HAVE=0
if [[ -f "$SERIES" ]]; then
  HAVE=$(($(wc -l < "$SERIES") - 1))
fi
shopt -s nullglob
for f in "$L0"/series_cont*.csv; do
  n=$(($(wc -l < "$f") - 1))
  [[ "$n" -gt 0 ]] && HAVE=$((HAVE + n))
  echo "partial $f rows=$n"
done
REMAIN=$((L0_TARGET - HAVE))
[[ "$REMAIN" -lt 0 ]] && REMAIN=0
echo "L0 have=$HAVE remain=$REMAIN target=$L0_TARGET"

if [[ ! -f "$L0/label.json" || "$REMAIN" -gt 0 ]]; then
  CONT_NEW="$L0/series_cont_$(date -u +%Y%m%dT%H%M%SZ).csv"
  if [[ "$REMAIN" -gt 0 ]]; then
    # Ensure header exists for merge if series.csv missing
    if [[ ! -f "$SERIES" ]]; then
      echo "ts_unix" >"$SERIES"  # capture_live will write full header on cont; merge handles carefully
    fi
    echo "=== continue L0 capture ${REMAIN}s → $CONT_NEW ==="
    "$PY" -m predictive.capture_live \
      --prom "$PROM" \
      --out "$CONT_NEW" \
      --seconds "$REMAIN" \
      --interval 1 \
      >"$L0/capture_cont.log" 2>&1
  fi

  echo "=== merge series (base + cont parts) ==="
  if [[ -f "$SERIES" ]] && [[ $(wc -l < "$SERIES") -gt 1 ]]; then
    {
      head -n 1 "$SERIES"
      tail -n +2 "$SERIES"
      for f in "$L0"/series_cont*.csv; do
        # skip header mismatch: use first cont header if base only had stub
        tail -n +2 "$f"
      done
    } >"$L0/series_merged.csv"
  else
    # adopt newest cont as base
    first=""
    for f in "$L0"/series_cont*.csv; do first="$f"; break; done
    {
      head -n 1 "$first"
      for f in "$L0"/series_cont*.csv; do
        tail -n +2 "$f"
      done
    } >"$L0/series_merged.csv"
  fi
  mv "$L0/series_merged.csv" "$SERIES"
  rm -f "$L0"/series_cont*.csv
  echo "merged rows=$(($(wc -l < "$SERIES") - 1))"

  echo "{\"label\": 0, \"name\": \"normal\", \"host\": \"$HOST\", \"total_sec\": $L0_TARGET, \"resumed\": true}" >"$L0/label.json"
  echo "=== build Q2 windows for L0 ==="
  "$PY" -m predictive.q2_windows --capture "$SERIES" --label 0 --out-dir "$L0" \
    | tee "$L0/windows_summary.json" || true

  ENDED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  touch "$MANIFEST"
  if ! grep -q '"label":0' "$MANIFEST" 2>/dev/null; then
    echo "{\"label\":0,\"name\":\"normal\",\"iteration\":1,\"path\":\"$L0\",\"ended\":\"$ENDED\",\"mode\":\"full\",\"resumed\":true,\"host\":\"$HOST\"}" >>"$MANIFEST"
  fi
else
  echo "L0 already complete — skip"
fi

# --- L1–L5 + chaos (skip finished labels via --only of what's missing) ---
ONLY_LIST=()
[[ ! -f "$OUT_ROOT/L1_rain_fade/iter_10/label.json" ]] && ONLY_LIST+=(1)
[[ ! -f "$OUT_ROOT/L2_cpu_stress/iter_10/label.json" ]] && ONLY_LIST+=(2)
[[ ! -f "$OUT_ROOT/L3_bgp_flap/iter_10/label.json" ]] && ONLY_LIST+=(3)
[[ ! -f "$OUT_ROOT/L4_loss_progression/iter_08/label.json" ]] && ONLY_LIST+=(4)
[[ ! -f "$OUT_ROOT/L5_util_congestion/iter_08/label.json" ]] && ONLY_LIST+=(5)

SKIP_CHAOS=()
if [[ -f "$OUT_ROOT/chaos/label.json" ]]; then
  SKIP_CHAOS=(--skip-chaos)
fi

if [[ ${#ONLY_LIST[@]} -eq 0 ]]; then
  if [[ ${#SKIP_CHAOS[@]} -eq 0 ]]; then
    echo "=== only chaos remaining ==="
    bash "$ROOT/predictive/run_chaos_campaign.sh" \
      --out "$OUT_ROOT/chaos" --seconds $((12 * 3600)) --host "$HOST" --prom "$PROM" \
      --stamp "$STAMP"
  else
    echo "=== stamp already complete ==="
  fi
else
  ONLY_CSV=$(IFS=,; echo "${ONLY_LIST[*]}")
  echo "=== continue protocol labels=$ONLY_CSV ${SKIP_CHAOS[*]:-} ==="
  # run_protocol_campaign.sh skips any iter that already has label.json.
  bash "$ROOT/predictive/run_protocol_campaign.sh" \
    --full --stamp "$STAMP" --only "$ONLY_CSV" --resume \
    --host "$HOST" --prom "$PROM" \
    "${SKIP_CHAOS[@]}"
fi

echo "=== resume_active complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
