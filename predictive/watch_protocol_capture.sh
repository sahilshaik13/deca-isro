#!/usr/bin/env bash
# watch_protocol_capture.sh — keep protocol Prom capture honest across Pi outages.
#
# Checks every INTERVAL seconds:
#   1) campaign + capture_live still running
#   2) series CSV growing and last N rows have latency_gre_ms
#   3) host Prometheus ready + key Q1 query non-empty
#   4) telemetry docker (kafka / bridge) running
#   5) Pi stations ping + Telegraf :9273 (power-outage gate)
#
# On lab outage (Pis down / Prom empty):
#   - write capture_paused.json + DECA_CAPTURE_PAUSE_FILE latch
#   - SIGSTOP capture_live + campaign shells (freeze inject timers)
#   - clear injectors best-effort
# When stations + Prom are healthy for RECOVER_STREAK checks:
#   - optional lab heal, SIGCONT, remove pause latch
#
# Soft heal (empty feed while not paused):
#   docker compose restart telemetry-bridge
#
# Usage:
#   STAMP=20260729T202832Z INTERVAL=30 bash predictive/watch_protocol_capture.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="${STAMP:-20260729T202832Z}"
OUT_ROOT="$ROOT/data/deca/predictive/protocol/$STAMP"
L0="$OUT_ROOT/L0_normal/iter_01"
LOG="${WATCH_LOG:-$OUT_ROOT/capture_watchdog.log}"
STATUS_JSON="${WATCH_STATUS:-$OUT_ROOT/capture_health.json}"
PAUSE_JSON="${PAUSE_STATUS:-$OUT_ROOT/capture_paused.json}"
PAUSE_LATCH="${PAUSE_LATCH:-$OUT_ROOT/CAPTURE_PAUSE}"
PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
INTERVAL="${INTERVAL:-30}"
EMPTY_STREAK_HEAL="${EMPTY_STREAK_HEAL:-3}"
OUTAGE_STREAK_PAUSE="${OUTAGE_STREAK_PAUSE:-2}"   # consecutive bad checks → pause
RECOVER_STREAK="${RECOVER_STREAK:-3}"             # consecutive good → resume (~90s)
TAIL_N="${TAIL_N:-30}"
COMPOSE="$ROOT/lab/telemetry-pipeline/docker-compose.yml"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
STATIONS_CSV="${DECA_STATIONS:-192.168.50.10,192.168.50.20,192.168.50.30}"
HOST_SSH="${DECA_INJECT_HOST:-station1}"

mkdir -p "$OUT_ROOT"
export DECA_CAPTURE_PAUSE_FILE="$PAUSE_LATCH"
exec >>"$LOG" 2>&1
echo "=== watchdog start $(date -u +%Y-%m-%dT%H:%M:%SZ) pid=$$ stamp=$STAMP interval=${INTERVAL}s ==="

empty_streak=0
outage_streak=0
recover_streak=0
last_heal_epoch=0
paused=0
if [[ -f "$PAUSE_LATCH" ]]; then
  paused=1
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) INFO found existing pause latch — starting paused"
fi

latest_series() {
  local f
  # Prefer newest series under any L*/iter_* (not only L0)
  f="$(find "$OUT_ROOT" -type f \( -name 'series_cont_*.csv' -o -name 'series_cont.csv' -o -name 'series.csv' \) 2>/dev/null \
    | xargs -r ls -1t 2>/dev/null | head -1 || true)"
  if [[ -n "$f" ]]; then
    echo "$f"
    return
  fi
  echo ""
}

proc_ok() {
  pgrep -f "resume_from_l0.sh" >/dev/null 2>&1 \
    || pgrep -f "resume_active_protocol.sh" >/dev/null 2>&1 \
    || pgrep -f "run_protocol_campaign.sh" >/dev/null 2>&1
}

capture_ok() {
  pgrep -f "predictive.capture_live" >/dev/null 2>&1
}

prom_ready() {
  curl -sf --max-time 3 "$PROM/-/ready" >/dev/null 2>&1
}

docker_ok() {
  docker inspect -f '{{.State.Running}}' deca-telemetry-kafka-1 2>/dev/null | grep -q true \
    && docker inspect -f '{{.State.Running}}' deca-telemetry-telemetry-bridge-1 2>/dev/null | grep -q true
}

# Returns: stations_up telegraf_up (space-separated counts)
lab_station_health() {
  local IFS=',' ip up=0 tg=0
  for ip in $STATIONS_CSV; do
    if ping -c1 -W1 "$ip" >/dev/null 2>&1; then
      up=$((up + 1))
      if curl -sf --max-time 2 "http://${ip}:9273/metrics" >/dev/null 2>&1; then
        tg=$((tg + 1))
      fi
    fi
  done
  echo "$up $tg"
}

campaign_pids() {
  pgrep -f "predictive.capture_live" 2>/dev/null || true
  pgrep -f "run_q2_campaign.sh" 2>/dev/null || true
  pgrep -f "run_protocol_campaign.sh" 2>/dev/null || true
  pgrep -f "run_chaos_campaign.sh" 2>/dev/null || true
  pgrep -f "inject_rain_fade.sh|inject_cpu_stress.sh|inject_bgp_flap.sh|inject_loss_progression.sh|inject_util_congestion.sh" 2>/dev/null || true
}

sig_campaign() {
  local sig="$1" pid
  for pid in $(campaign_pids | sort -u); do
    # never signal ourselves
    [[ "$pid" == "$$" ]] && continue
    kill "-$sig" "$pid" 2>/dev/null || true
  done
}

clear_injectors_best_effort() {
  bash "$ROOT/scripts/inject_cpu_stress.sh" --clear --host "$HOST_SSH" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_bgp_flap.sh" --clear --host "$HOST_SSH" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_rain_fade.sh" --clear --host "$HOST_SSH" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_loss_progression.sh" --clear --host "$HOST_SSH" >/dev/null 2>&1 || true
  bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST_SSH" >/dev/null 2>&1 || true
}

write_pause() {
  local reason="$1" stations_up="$2" telegraf_up="$3"
  date -u +%Y-%m-%dT%H:%M:%SZ >"$PAUSE_LATCH"
  python3 - <<PY
import json, time
from pathlib import Path
Path("$PAUSE_JSON").write_text(json.dumps({
  "paused": True,
  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "reason": """$reason""",
  "stamp": "$STAMP",
  "stations_up": int("$stations_up"),
  "telegraf_up": int("$telegraf_up"),
}, indent=2) + "\n")
PY
}

clear_pause() {
  rm -f "$PAUSE_LATCH"
  python3 - <<PY
import json, time
from pathlib import Path
Path("$PAUSE_JSON").write_text(json.dumps({
  "paused": False,
  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "reason": "lab healthy — resumed",
  "stamp": "$STAMP",
}, indent=2) + "\n")
PY
}

enter_pause() {
  local reason="$1" stations_up="$2" telegraf_up="$3"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) PAUSE $reason stations_up=$stations_up telegraf_up=$telegraf_up"
  write_pause "$reason" "$stations_up" "$telegraf_up"
  clear_injectors_best_effort
  sig_campaign STOP
  paused=1
  recover_streak=0
}

exit_pause() {
  # Honor operator manual pause — do not auto-resume
  if [[ -f "$PAUSE_JSON" ]] && grep -q '"manual": true' "$PAUSE_JSON" 2>/dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) HOLD manual pause latch present — skip auto-resume"
    recover_streak=0
    return 0
  fi
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) RESUME lab healthy — SIGCONT + heal"
  # Best-effort restore dataplane/exporters after power return
  if [[ -x "$ROOT/lab/deca_ops.sh" ]]; then
    bash "$ROOT/lab/deca_ops.sh" heal >/dev/null 2>&1 || true
  fi
  if [[ -f "$COMPOSE" ]]; then
    docker compose -f "$COMPOSE" restart telemetry-bridge >/dev/null 2>&1 || true
  fi
  sleep 5
  sig_campaign CONT
  clear_pause
  paused=0
  outage_streak=0
  recover_streak=0
  empty_streak=0
}

check_once() {
  local series rows age good fill prom_lat targets_up ok_msg level
  local stations_up telegraf_up lab_ok=1 outage=0
  series="$(latest_series)"
  rows=0
  age=9999
  good=0
  fill=0
  prom_lat=""
  targets_up=0
  level=OK
  ok_msg="healthy"

  read -r stations_up telegraf_up <<<"$(lab_station_health)"
  # Require all 3 stations ping + station1 telegraf at minimum for capture host
  if [[ "$stations_up" -lt 3 || "$telegraf_up" -lt 1 ]]; then
    lab_ok=0
    outage=1
  fi

  if [[ -n "$series" && -f "$series" ]]; then
    rows=$(($(wc -l < "$series") - 1))
    age=$(python3 -c "import time,os; print(int(time.time()-os.path.getmtime('$series')))")
    good=$("$PY" - <<PY
import csv
from pathlib import Path
p=Path("$series")
rows=list(csv.DictReader(p.open()))[-$TAIL_N:]
print(sum(1 for r in rows if (r.get("latency_gre_ms") or "")!=""))
PY
)
    fill=$good
  fi

  if prom_ready; then
    prom_lat=$(curl -sg --max-time 3 \
      --data-urlencode 'query=sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",host="station1",path="gre",src="edge"}' \
      "$PROM/api/v1/query" \
      | python3 -c 'import sys,json; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")' 2>/dev/null || true)
    targets_up=$(curl -sf --max-time 3 "$PROM/api/v1/targets" \
      | python3 -c 'import sys,json; print(sum(1 for t in json.load(sys.stdin)["data"]["activeTargets"] if t.get("health")=="up"))' 2>/dev/null || echo 0)
  fi

  local capture_alive=0 resume_alive=0 docker_alive=0 prom_alive=0
  capture_ok && capture_alive=1
  proc_ok && resume_alive=1
  docker_ok && docker_alive=1
  prom_ready && prom_alive=1

  if [[ "$outage" -eq 1 ]]; then
    level=CRIT
    ok_msg="lab stations down (${stations_up}/3 ping, ${telegraf_up}/3 telegraf)"
  elif [[ "$resume_alive" -eq 0 && "$capture_alive" -eq 0 ]]; then
    level=CRIT
    ok_msg="resume/capture processes missing"
  elif [[ "$capture_alive" -eq 0 ]]; then
    level=WARN
    ok_msg="capture_live not running (ok if between stages)"
  elif [[ "$prom_alive" -eq 0 ]]; then
    level=CRIT
    ok_msg="prometheus not ready"
    outage=1
  elif [[ -z "$prom_lat" ]]; then
    level=CRIT
    ok_msg="prom Q1 latency empty"
    outage=1
  elif [[ "$paused" -eq 0 && "$fill" -lt $((TAIL_N * 8 / 10)) ]]; then
    level=CRIT
    ok_msg="csv fill ${fill}/${TAIL_N} below 80%"
  elif [[ "$paused" -eq 0 && "$age" -gt $((INTERVAL * 3)) ]]; then
    level=CRIT
    ok_msg="csv stale age=${age}s"
  elif [[ "$docker_alive" -eq 0 ]]; then
    level=WARN
    ok_msg="kafka/bridge docker not running"
  elif [[ "$targets_up" -lt 4 ]]; then
    level=WARN
    ok_msg="only ${targets_up} prom targets up"
  fi

  if [[ "$paused" -eq 1 && "$level" == OK ]]; then
    ok_msg="paused but lab looks healthy (recovering)"
    level=WARN
  elif [[ "$paused" -eq 1 ]]; then
    level=CRIT
    ok_msg="paused: $ok_msg"
  fi

  python3 - <<PY
import json, time
from pathlib import Path
Path("$STATUS_JSON").write_text(json.dumps({
  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "level": "$level",
  "msg": "$ok_msg",
  "stamp": "$STAMP",
  "series": "$series",
  "rows": $rows,
  "csv_age_s": $age,
  "tail_fill": $fill,
  "tail_n": $TAIL_N,
  "prom_latency_gre_ms": "$prom_lat",
  "targets_up": $targets_up,
  "stations_up": $stations_up,
  "telegraf_up": $telegraf_up,
  "capture_alive": $capture_alive,
  "resume_alive": $resume_alive,
  "prom_alive": $prom_alive,
  "docker_alive": $docker_alive,
  "paused": $paused,
}, indent=2) + "\n")
PY

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $level $ok_msg rows=$rows age=${age}s fill=${fill}/${TAIL_N} lat=${prom_lat:-none} targets=$targets_up stations=${stations_up}/3 telegraf=${telegraf_up}/3 capture=$capture_alive paused=$paused"

  # --- pause / resume state machine ---
  if [[ "$outage" -eq 1 ]]; then
    outage_streak=$((outage_streak + 1))
    recover_streak=0
  else
    outage_streak=0
    if [[ "$paused" -eq 1 && -n "$prom_lat" && "$stations_up" -ge 3 && "$telegraf_up" -ge 1 ]]; then
      recover_streak=$((recover_streak + 1))
    else
      recover_streak=0
    fi
  fi

  if [[ "$paused" -eq 0 && "$outage_streak" -ge "$OUTAGE_STREAK_PAUSE" ]]; then
    enter_pause "$ok_msg" "$stations_up" "$telegraf_up"
  elif [[ "$paused" -eq 1 && "$recover_streak" -ge "$RECOVER_STREAK" ]]; then
    exit_pause
  fi

  if [[ "$paused" -eq 0 && "$level" == CRIT && "$ok_msg" =~ (latency empty|csv fill|csv stale|prometheus not ready) ]]; then
    empty_streak=$((empty_streak + 1))
  else
    empty_streak=0
  fi

  now_epoch=$(date +%s)
  if [[ "$paused" -eq 0 && "$empty_streak" -ge "$EMPTY_STREAK_HEAL" && $((now_epoch - last_heal_epoch)) -ge 600 ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) HEAL restarting telemetry-bridge (empty_streak=$empty_streak)"
    if [[ -f "$COMPOSE" ]]; then
      docker compose -f "$COMPOSE" restart telemetry-bridge || true
    fi
    last_heal_epoch=$now_epoch
    empty_streak=0
  fi
}

while true; do
  check_once || echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) WARN check_once failed"
  sleep "$INTERVAL"
done
