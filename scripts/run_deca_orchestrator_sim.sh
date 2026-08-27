#!/usr/bin/env bash
# DECA Orchestrator ultimate simulation (Phases 0–6).
# Triggered by Next.js "Start Simulation" → FastAPI background subprocess.
#
# Timings aligned to live lab/deca_sdwan_controller.py
# (docs/EDGE_POLICY_LAYERS.md):
#   TT&C ≤25ms / ≤5ms / ≤0.1%, Payload ≤80ms / ≤15ms / ≤2%,
#   enter_k=3, exit_k=10, poll=5s
#
# Env:
#   DECA_SIM_DRY=1          — skip SSH/lab; advance phases + seed HITL alert only
#   DECA_SIM_STATUS=path    — JSON status file (default data/deca/simulation_status.json)
#   DECA_SIM_ORCH_URL       — orchestrator API (default http://127.0.0.1:8000)
#   DECA_SIM_CTRL_URL       — controller (default http://127.0.0.1:9280)
#   DECA_SIM_HITL_TIMEOUT=90 — seconds to wait for Approve in Phase 4
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATUS_PATH="${DECA_SIM_STATUS:-$ROOT/data/deca/simulation_status.json}"
LOG_PATH="${DECA_SIM_LOG:-$ROOT/data/deca/simulation.log}"
ORCH_URL="${DECA_SIM_ORCH_URL:-http://127.0.0.1:8000}"
CTRL_URL="${DECA_SIM_CTRL_URL:-http://127.0.0.1:9280}"
HITL_TIMEOUT="${DECA_SIM_HITL_TIMEOUT:-90}"
DRY="${DECA_SIM_DRY:-0}"
STARTED_EPOCH="$(date +%s)"
STOP_FLAG="${DECA_SIM_STOP_FLAG:-$ROOT/data/deca/simulation.stop}"

mkdir -p "$(dirname "$STATUS_PATH")"
: >"$LOG_PATH"
rm -f "$STOP_FLAG"

log() {
  local msg="$*"
  printf '[%s] %s\n' "$(date -Is)" "$msg"
}

should_stop() {
  [[ -f "$STOP_FLAG" ]]
}

write_status() {
  local phase="$1"
  local name="$2"
  local message="$3"
  local waiting="${4:-false}"
  local ui="${5:-}"
  python3 - "$STATUS_PATH" "$phase" "$name" "$message" "$waiting" "$ui" "$STARTED_EPOCH" "$LOG_PATH" <<'PY'
import json, sys, time
from pathlib import Path
path, phase, name, message, waiting, ui, started, log_path = sys.argv[1:9]
tail = []
try:
    lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-40:]
except OSError:
    pass
payload = {
    "running": True,
    "phase": int(phase),
    "phase_name": name,
    "message": message,
    "ui_expectation": ui,
    "waiting_for_approve": waiting.lower() in ("1", "true", "yes"),
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(started))),
    "elapsed_s": max(0, int(time.time()) - int(started)),
    "log_tail": tail,
    "finished": False,
    "ok": True,
}
Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

finish_status() {
  local ok="$1"
  local message="$2"
  python3 - "$STATUS_PATH" "$ok" "$message" "$STARTED_EPOCH" "$LOG_PATH" <<'PY'
import json, sys, time
from pathlib import Path
path, ok, message, started, log_path = sys.argv[1:6]
tail = []
try:
    lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-60:]
except OSError:
    pass
prev = {}
try:
    prev = json.loads(Path(path).read_text(encoding="utf-8"))
except Exception:
    pass
payload = {
    **prev,
    "running": False,
    "finished": True,
    "ok": ok.lower() in ("1", "true", "yes"),
    "message": message,
    "waiting_for_approve": False,
    "elapsed_s": max(0, int(time.time()) - int(started)),
    "log_tail": tail,
}
Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

sleep_until_abs() {
  # sleep until absolute seconds since STARTED_EPOCH
  local target="$1"
  while true; do
    should_stop && return 1
    local now
    now="$(date +%s)"
    local left=$((target - (now - STARTED_EPOCH)))
    (( left <= 0 )) && return 0
    if (( left > 2 )); then
      sleep 2
    else
      sleep "$left"
    fi
  done
}

ssh_lab() {
  local host="$1"
  shift
  if [[ "$DRY" == "1" ]]; then
    log "DRY ssh $host: $*"
    return 0
  fi
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$host" "$@"
}

run_remote() {
  local host="$1"
  local cmd="$2"
  log "→ $host :: $cmd"
  if ! ssh_lab "$host" "$cmd"; then
    log "WARN: ssh $host failed (continuing)"
    return 1
  fi
  return 0
}

seed_preemption_alert() {
  log "Seeding Orchestrator Preemption alert via $ORCH_URL"
  curl -sS -X POST "$ORCH_URL/api/v1/simulation/seed-preemption" \
    -H 'Content-Type: application/json' \
    -d '{"title":"Impending Congestion Detected","host":"station1","path":"eth0"}' \
    >>"$LOG_PATH" 2>&1 || log "WARN: seed-preemption failed (is API up?)"
}

wait_for_human_override() {
  local deadline=$(( $(date +%s) + HITL_TIMEOUT ))
  write_status 4 "AI Predictive Congestion & UI Override" \
    "Waiting for operator Approve (POST /action force_path)…" true \
    "Alert: Impending Congestion Detected — Approve steers preemptively to eth0"
  while (( $(date +%s) < deadline )); do
    should_stop && return 1
    if [[ "$DRY" == "1" ]]; then
      # Dry: auto-force after 8s so demos without controller still advance
      if (( $(date +%s) - STARTED_EPOCH >= 128 )); then
        curl -sS -X POST "$CTRL_URL/action" -H 'Content-Type: application/json' \
          -d '{"op":"force_path","path":"eth0","approved_by":"sim-dry","reason":"dry_preemption"}' \
          >>"$LOG_PATH" 2>&1 || true
        return 0
      fi
    fi
    if curl -sS "$CTRL_URL/metrics" 2>/dev/null | grep -q 'sdwan_human_override{path="eth0"} 1'; then
      log "HITL: human_override eth0 observed"
      return 0
    fi
    sleep 2
  done
  log "WARN: HITL timeout (${HITL_TIMEOUT}s) — continuing without force"
  return 0
}

fast_congestion_ramp() {
  # Demo-scale TBF ramp on PE1 eth0 (~60s). Full campaign precursor is multi-minute.
  log "Fast congestion ramp on station1 eth0 (demo scale)"
  if [[ "$DRY" == "1" ]]; then
    log "DRY: skip TBF ramp"
    return 0
  fi
  local rates=(80 55 35 20 12)
  local rate
  for rate in "${rates[@]}"; do
    should_stop && return 1
    run_remote station1 "sudo tc qdisc replace dev eth0 root tbf rate ${rate}mbit burst 32k latency 400ms" || true
    sleep 10
  done
}

cleanup_lab() {
  log "Teardown: kill iperf3 + clear sim impairments (keep HTB)"
  # gre-te-core: sim installs netem as root — delete it (do not leave stale delay/loss)
  run_remote station1 'sudo tc qdisc del dev gre-te-core root 2>/dev/null || true' || true
  # eth0: only remove TBF if the sim congestion ramp replaced root; never wipe HTB QoS
  run_remote station1 '
    root=$(tc qdisc show dev eth0 2>/dev/null | head -1 || true)
    if echo "$root" | grep -q " tbf "; then
      sudo tc qdisc del dev eth0 root 2>/dev/null || true
    fi
    sudo pkill -f iperf3 2>/dev/null || true
  ' || true
  run_remote station2 'sudo pkill -f iperf3 2>/dev/null || true' || true
}

reset_sdwan_state() {
  # Drop human gate + hysteresis so dashboard does not keep showing stale policy_conflict
  log "Resetting SD-WAN controller autonomy → prefer GRE"
  curl -sS -X POST "$CTRL_URL/action" -H 'Content-Type: application/json' \
    -d '{"op":"reset_autonomy","approved_by":"sim","reason":"sim_reset"}' >>"$LOG_PATH" 2>&1 \
    || curl -sS -X POST "$CTRL_URL/action" -H 'Content-Type: application/json' \
         -d '{"op":"clear_force","approved_by":"sim","reason":"sim_reset_fallback"}' >>"$LOG_PATH" 2>&1 \
    || log "WARN: controller reset failed (is :9280 up?)"
}

trap 'cleanup_lab; reset_sdwan_state; finish_status false "stopped"; exit 130' INT TERM

log "=== DECA orchestrator simulation start (DRY=$DRY) ==="
# Pin NOC fabric to Pi for this timeline
curl -sS -X POST "$ORCH_URL/api/v1/fabric" -H 'Content-Type: application/json' \
  -d '{"active":"pi","set_by":"pi-sim"}' >>"$LOG_PATH" 2>&1 || true
cleanup_lab
reset_sdwan_state
write_status 0 "Initialization" "Spinning up SAC receivers…" false \
  "Receivers on sac-srv :5004 / :5006 / :5201"

# ── Phase 0 @ T=0s ──────────────────────────────────────────────────────────
run_remote station2 'sudo pkill -9 iperf3 2>/dev/null || true; sleep 1
  sudo ip netns exec sac-srv iperf3 -s -p 5004 -D
  sudo ip netns exec sac-srv iperf3 -s -p 5006 -D
  sudo ip netns exec sac-srv iperf3 -s -p 5201 -D' || true

sleep_until_abs 5 || { finish_status false "stopped"; exit 0; }

# ── Phase 1 @ T=5s ──────────────────────────────────────────────────────────
write_status 1 "Clear Weather Traffic" "Baseline ISRO flows NRSC→SAC…" false \
  "Dashboard green. HTB drops bulk. Traffic on gre-te-core."
# DSCP PS13: TT&C ToS 0x88 (136), Payload ToS 0x80 (128) — no TRex
run_remote station1 'sudo ip netns exec nrsc-ws iperf3 -c 10.101.2.3 -u -b 1M -l 160 -p 5004 -t 400 --tos 136 >/dev/null 2>&1 &' || true
run_remote station1 'sudo ip netns exec nrsc-srv iperf3 -c 10.101.2.3 -u -b 50M -l 1200 -p 5006 -t 400 --tos 128 >/dev/null 2>&1 &' || true
run_remote station1 'sudo ip netns exec nrsc-srv iperf3 -c 10.101.2.3 -b 20M -p 5201 -t 400 >/dev/null 2>&1 &' || true

sleep_until_abs 30 || { finish_status false "stopped"; exit 0; }

# ── Phase 2 @ T=30s — soft delay: TT&C fails, Payload holds (≤80ms) ─────────
write_status 2 "Payload Tolerance Check" "Injecting 40ms netem on gre-te-core…" false \
  "Latency ~40ms. TT&C SLA red. Payload green. sdwan_policy_conflict=1."
run_remote station1 'sudo tc qdisc replace dev gre-te-core root netem delay 40ms 8ms' || true

sleep_until_abs 60 || { finish_status false "stopped"; exit 0; }

# ── Phase 3 @ T=60s — hard breach → enter_k=3 (~15s) ────────────────────────
write_status 3 "Hard Steer & Hysteresis" "Breaching TT&C SLA (delay+loss)…" false \
  "After enter_k=3 polls (~15s) active path flips; /32 OSPF steers ESP to eth0."
run_remote station1 'sudo tc qdisc replace dev gre-te-core root netem delay 35ms 15ms loss 2%' || true
# Let hysteresis fire before Phase 4
sleep_until_abs 120 || { finish_status false "stopped"; exit 0; }

# ── Phase 4 @ T=120s — clear physical fault, AI congestion, HITL preemption ─
write_status 4 "AI Predictive Congestion & UI Override" "Clearing netem; starting congestion precursor…" false \
  "LSTM-style alert: Impending Congestion Detected. Approve → POST /action."
run_remote station1 'sudo tc qdisc del dev gre-te-core root 2>/dev/null || true' || true
# Clear any prior human force so autonomy resumes briefly
curl -sS -X POST "$CTRL_URL/action" -H 'Content-Type: application/json' \
  -d '{"op":"clear_force","approved_by":"sim","reason":"phase4_reset"}' >>"$LOG_PATH" 2>&1 || true

seed_preemption_alert
# Ramp congestion in background while waiting for Approve
fast_congestion_ramp &
RAMP_PID=$!
wait_for_human_override || true
kill "$RAMP_PID" 2>/dev/null || true
wait "$RAMP_PID" 2>/dev/null || true

sleep_until_abs 180 || { finish_status false "stopped"; exit 0; }

# ── Phase 5 @ T=180s — clear human override; exit_k=10 recovery ─────────────
write_status 5 "Hysteresis Recovery" "Clearing human override; waiting exit_k=10…" false \
  "Traffic stays on backup until 10 consecutive clean GRE polls (~50s)."
curl -sS -X POST "$CTRL_URL/action" -H 'Content-Type: application/json' \
  -d '{"op":"clear_force","approved_by":"sim","reason":"phase5_clear"}' >>"$LOG_PATH" 2>&1 || true
# Clear congestion TBF so GRE can go clean
run_remote station1 'sudo tc qdisc del dev eth0 root 2>/dev/null || true' || true

sleep_until_abs 240 || { finish_status false "stopped"; exit 0; }

# ── Phase 6 @ T=240s ────────────────────────────────────────────────────────
write_status 6 "Teardown" "Cleaning lab environment…" false \
  "iperf clients/servers stopped; netem cleared."
cleanup_lab
reset_sdwan_state

log "=== Simulation complete ==="
write_status 6 "Teardown" "Simulation complete" false "Lab cleaned; SD-WAN autonomy reset."
finish_status true "Simulation complete"
exit 0
