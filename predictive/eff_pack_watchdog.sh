#!/usr/bin/env bash
# Dual-fabric efficiency-pack watchdog — keep capture moving until both packs finish.
# Detects: dead redo/pack, Prom-empty stall (written=0 + waiting), GNS3 PE1 down.
# Does NOT edit running scripts mid-flight beyond kill/resume of stuck children.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PI_STAMP=eff_pack_pi_20260804T092105Z
GNS_STAMP=eff_pack_gns3_20260804T094436Z
PI_OUT="$ROOT/data/deca/predictive/protocol/$PI_STAMP"
GNS_OUT="$ROOT/data/deca/predictive/protocol_gns3/$GNS_STAMP"
LOG="$PI_OUT/logs/eff_pack_watchdog.log"
mkdir -p "$PI_OUT/logs" "$GNS_OUT/logs"
PROJ=78f1223e-f45b-4f61-b131-8e103a8eaebb

exec >>"$LOG" 2>&1
echo "=== watchdog start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

pack_done() {
  local out="$1"
  # chaos_holdout series present + pack_state completed, or pack.log says DONE
  [[ -f "$out/chaos_holdout/series.csv" ]] && [[ -s "$out/chaos_holdout/series.csv" ]] && return 0
  grep -q '"status": "done"' "$out/pack_state.json" 2>/dev/null && return 0
  grep -qiE 'Efficiency pack (DONE|complete)' "$out/logs/pack.log" 2>/dev/null && return 0
  grep -qiE 'Efficiency pack (DONE|complete)' "$out/logs/pack_after_best.log" 2>/dev/null && return 0
  return 1
}

alive_for() {
  local stamp="$1"
  pgrep -f "redo_eff_pack_best.sh.*(pi|gns3)" >/dev/null 2>&1 && \
    pgrep -af "redo_eff_pack_best.sh" | grep -q "$stamp\|pi\|gns3" || true
  pgrep -f "run_efficiency_pack.sh.*$stamp" >/dev/null 2>&1 && return 0
  pgrep -f "run_q2_campaign.*$stamp" >/dev/null 2>&1 && return 0
  pgrep -f "capture_live.*$stamp\|capture_live.*/$stamp" >/dev/null 2>&1 && return 0
  # looser: any capture under out path
  pgrep -f "capture_live.*${stamp}" >/dev/null 2>&1 && return 0
  return 1
}

pi_alive() {
  pgrep -f "redo_eff_pack_best.sh pi" >/dev/null 2>&1 && return 0
  pgrep -f "run_efficiency_pack.sh --fabric pi --stamp $PI_STAMP" >/dev/null 2>&1 && return 0
  pgrep -f "run_q2_campaign.sh.*$PI_STAMP" >/dev/null 2>&1 && return 0
  pgrep -f "capture_live.*$PI_STAMP" >/dev/null 2>&1 && return 0
  return 1
}

gns_alive() {
  pgrep -f "redo_eff_pack_best.sh gns3" >/dev/null 2>&1 && return 0
  pgrep -f "run_efficiency_pack.sh --fabric gns3 --stamp $GNS_STAMP" >/dev/null 2>&1 && return 0
  pgrep -f "run_q2_campaign_gns3.sh.*$GNS_STAMP" >/dev/null 2>&1 && return 0
  pgrep -f "capture_live.*$GNS_STAMP" >/dev/null 2>&1 && return 0
  return 1
}

stall_score() {
  # echo paused_s if capture.log shows waiting with written=0; else 0
  local logf="$1"
  [[ -f "$logf" ]] || { echo 0; return; }
  local line
  line=$(grep 'waiting for Prom' "$logf" | tail -1 || true)
  if [[ -z "$line" ]]; then echo 0; return; fi
  if echo "$line" | grep -q 'written=0/'; then
    echo "$line" | sed -n 's/.*paused_s=\([0-9]*\).*/\1/p'
  else
    echo 0
  fi
}

ensure_gns3() {
  curl -sf -m5 -X POST "http://127.0.0.1:3080/v2/projects/$PROJ/open" >/dev/null 2>&1 || true
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qE 'GNS3\.PE1\.'; then
    echo "$(date -u +%H:%M:%SZ) PE1 down — start nodes"
    python3 - <<'PY' || true
import json, urllib.request
PROJ="78f1223e-f45b-4f61-b131-8e103a8eaebb"
base=f"http://127.0.0.1:3080/v2/projects/{PROJ}"
try:
    urllib.request.urlopen(urllib.request.Request(base+"/open", method="POST", data=b""), timeout=30)
except Exception:
    pass
try:
    nodes=json.load(urllib.request.urlopen(base+"/nodes", timeout=30))
except Exception:
    raise SystemExit(0)
for n in nodes:
    if n["name"].startswith(("PE","CORE","CE-","IPERF")):
        try:
            urllib.request.urlopen(urllib.request.Request(base+f"/nodes/{n['node_id']}/start", method="POST", data=b""), timeout=60)
        except Exception:
            pass
PY
  fi
}

resume_pi() {
  echo "$(date -u +%H:%M:%SZ) RESUME pi pack"
  setsid env DECA_FABRIC=pi nohup bash "$ROOT/predictive/run_efficiency_pack.sh" \
    --fabric pi --stamp "$PI_STAMP" --resume \
    >>"$PI_OUT/logs/pack_watchdog_resume.log" 2>&1 < /dev/null &
  echo "  pid=$!"
}

resume_gns() {
  echo "$(date -u +%H:%M:%SZ) RESUME gns3 pack"
  setsid env DECA_FABRIC=gns3 DECA_REQUIRE_LIVE=0 nohup bash "$ROOT/predictive/run_efficiency_pack.sh" \
    --fabric gns3 --stamp "$GNS_STAMP" --resume \
    >>"$GNS_OUT/logs/pack_watchdog_resume.log" 2>&1 < /dev/null &
  echo "  pid=$!"
}

# Kill a stuck capture under stamp that has written=0 for too long, then let parent fail/retry or resume
unstick_capture() {
  local stamp="$1" fabric="$2"
  echo "$(date -u +%H:%M:%SZ) UNSTICK capture stamp=$stamp fabric=$fabric (Prom-empty stall)"
  pkill -TERM -f "capture_live.*${stamp}" 2>/dev/null || true
  sleep 2
  pkill -KILL -f "capture_live.*${stamp}" 2>/dev/null || true
  if [[ "$fabric" == pi ]]; then
    pkill -TERM -f "run_q2_campaign.sh.*${stamp}" 2>/dev/null || true
  else
    pkill -TERM -f "run_q2_campaign_gns3.sh.*${stamp}" 2>/dev/null || true
  fi
}

RELAUNCH_COOLDOWN_PI=0
RELAUNCH_COOLDOWN_GNS=0

while true; do
  now=$(date +%s)
  pi_done=0; gns_done=0
  pack_done "$PI_OUT" && pi_done=1
  pack_done "$GNS_OUT" && gns_done=1
  if [[ "$pi_done" -eq 1 && "$gns_done" -eq 1 ]]; then
    echo "both packs done — exit $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
  fi

  ensure_gns3

  # Stall detect on active capture logs
  for pair in \
    "pi|$PI_STAMP|$PI_OUT" \
    "gns3|$GNS_STAMP|$GNS_OUT"; do
    IFS='|' read -r fab stamp out <<<"$pair"
    # find newest capture.log under stamp that is being written
    while IFS= read -r clog; do
      [[ -f "$clog" ]] || continue
      # only if a capture_live for this path is alive
      dest=$(dirname "$clog")
      if ! pgrep -f "capture_live.*${dest}" >/dev/null 2>&1; then
        continue
      fi
      ps=$(stall_score "$clog")
      ps=${ps:-0}
      if [[ "$ps" =~ ^[0-9]+$ ]] && [[ "$ps" -ge 120 ]]; then
        echo "$(date -u +%H:%M:%SZ) stall paused_s=$ps log=$clog"
        unstick_capture "$stamp" "$fab"
      fi
    done < <(find "$out" -name capture.log -mmin -30 2>/dev/null | head -20)
  done

  # Dead pack → resume (only after L4 is in; redo may still be running)
  if [[ "$pi_done" -eq 0 ]]; then
    if ! pi_alive; then
      if [[ "$now" -ge "$RELAUNCH_COOLDOWN_PI" ]]; then
        # If L3 redo still needed? If redo not alive and no efficiency pack — resume pack
        # (redo completes into resume itself; if both dead, resume pack is safe with --resume)
        echo "$(date -u +%H:%M:%SZ) pi dead — resume"
        resume_pi
        RELAUNCH_COOLDOWN_PI=$((now + 180))
      fi
    fi
  fi
  if [[ "$gns_done" -eq 0 ]]; then
    if ! gns_alive; then
      if [[ "$now" -ge "$RELAUNCH_COOLDOWN_GNS" ]]; then
        echo "$(date -u +%H:%M:%SZ) gns3 dead — resume"
        resume_gns
        RELAUNCH_COOLDOWN_GNS=$((now + 180))
      fi
    fi
  fi

  pi_a=0; gns_a=0
  pi_alive && pi_a=1
  gns_alive && gns_a=1
  echo "$(date -u +%H:%M:%SZ) tick pi_alive=$pi_a gns_alive=$gns_a pi_done=$pi_done gns_done=$gns_done"
  sleep 45
done
