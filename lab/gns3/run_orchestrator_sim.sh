#!/usr/bin/env bash
# GNS3 twin of scripts/run_deca_orchestrator_sim.sh (Phases 0–6).
# Uses Pi-identical chaos: iperf3 ToS via HTB · NetEM · util ramp · HITL force_path.
#
# Env (same as Pi sim):
#   DECA_SIM_DRY=1  DECA_SIM_STATUS=…  DECA_SIM_ORCH_URL=…  DECA_SIM_HITL_TIMEOUT=90
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATUS_PATH="${DECA_SIM_STATUS:-$ROOT/data/deca/simulation_status.json}"
LOG_PATH="${DECA_SIM_LOG:-$ROOT/data/deca/simulation.log}"
ORCH_URL="${DECA_SIM_ORCH_URL:-http://127.0.0.1:8000}"
HITL_TIMEOUT="${DECA_SIM_HITL_TIMEOUT:-90}"
DRY="${DECA_SIM_DRY:-0}"
STARTED_EPOCH="$(date +%s)"
STOP_FLAG="${DECA_SIM_STOP_FLAG:-$ROOT/data/deca/simulation.stop}"
MISSION="$ROOT/lab/gns3/state/mission_state.json"
INJECT="$ROOT/lab/gns3/inject"
TRAFFIC="$ROOT/lab/gns3/traffic_control.sh"

mkdir -p "$(dirname "$STATUS_PATH")" "$ROOT/lab/gns3/state"
: >"$LOG_PATH"
rm -f "$STOP_FLAG"

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }

should_stop() { [[ -f "$STOP_FLAG" ]]; }

write_status() {
  local phase="$1" name="$2" message="$3" waiting="${4:-false}" ui="${5:-}"
  python3 - "$STATUS_PATH" "$phase" "$name" "$message" "$waiting" "$ui" "$STARTED_EPOCH" "$LOG_PATH" <<'PY'
import json, sys, time
from pathlib import Path
path, phase, name, message, waiting, ui, started, log_path = sys.argv[1:9]
tail = []
try:
    tail = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
except OSError:
    pass
Path(path).write_text(json.dumps({
    "running": True, "phase": int(phase), "phase_name": name, "message": message,
    "ui_expectation": ui, "waiting_for_approve": waiting.lower() in ("1", "true", "yes"),
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(started))),
    "elapsed_s": max(0, int(time.time()) - int(started)),
    "log_tail": tail, "finished": False, "ok": True, "fabric": "gns3",
}, indent=2) + "\n", encoding="utf-8")
PY
}

finish_status() {
  local ok="$1" message="$2"
  python3 - "$STATUS_PATH" "$ok" "$message" "$STARTED_EPOCH" "$LOG_PATH" <<'PY'
import json, sys, time
from pathlib import Path
path, ok, message, started, log_path = sys.argv[1:6]
tail = []
try:
    tail = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
except OSError:
    pass
prev = {}
try:
    prev = json.loads(Path(path).read_text(encoding="utf-8"))
except Exception:
    pass
Path(path).write_text(json.dumps({
    **prev, "running": False, "finished": True,
    "ok": ok.lower() in ("1", "true", "yes"), "message": message,
    "waiting_for_approve": False,
    "elapsed_s": max(0, int(time.time()) - int(started)),
    "log_tail": tail, "fabric": "gns3",
}, indent=2) + "\n", encoding="utf-8")
PY
}

sleep_until_abs() {
  local target="$1"
  while true; do
    should_stop && return 1
    local now left
    now="$(date +%s)"
    left=$((target - (now - STARTED_EPOCH)))
    (( left <= 0 )) && return 0
    if (( left > 2 )); then sleep 2; else sleep "$left"; fi
  done
}

mission_action() {
  local op="$1" path="${2:-}"
  local body
  if [[ -n "$path" ]]; then
    body=$(printf '{"op":"%s","path":"%s","approved_by":"sim","reason":"gns3_sim"}' "$op" "$path")
  else
    body=$(printf '{"op":"%s","approved_by":"sim","reason":"gns3_sim"}' "$op")
  fi
  curl -sS -X POST "$ORCH_URL/api/v1/controller/action" \
    -H 'Content-Type: application/json' -d "$body" >>"$LOG_PATH" 2>&1 \
    || curl -sS -X POST "$ORCH_URL/api/v1/action" \
         -H 'Content-Type: application/json' -d "$body" >>"$LOG_PATH" 2>&1 \
    || python3 - "$MISSION" "$op" "$path" <<'PY'
import json, sys, time
from pathlib import Path
p, op, path = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
cur = {}
if p.exists():
    try: cur = json.loads(p.read_text())
    except Exception: cur = {}
cur.setdefault("fabric", "gns3")
if op == "force_path" and path:
    cur["human_override"] = path
    cur["active_path"] = path
    cur["last_reason"] = "sim_force"
elif op in ("clear_force", "reset_autonomy"):
    cur["human_override"] = None
    cur["active_path"] = "gre"
    cur["last_reason"] = op
    cur["conflict"] = 0
cur["updated_unix"] = time.time()
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cur, indent=2) + "\n")
print("mission_state updated", op, path)
PY
}

gns3_run() {
  local label="$1"; shift
  log "→ gns3 :: $label"
  if [[ "$DRY" == "1" ]]; then
    log "DRY: $*"
    return 0
  fi
  "$@" >>"$LOG_PATH" 2>&1 || { log "WARN: $label failed (continuing)"; return 1; }
}

cleanup_lab() {
  log "Teardown: stop traffic + clear NetEM (keep HTB)"
  gns3_run "netem clear" bash "$INJECT/clear_all.sh" || true
  gns3_run "traffic stop" bash "$TRAFFIC" stop || true
}

reset_sdwan_state() {
  log "Resetting GNS3 mission autonomy → prefer GRE"
  mission_action reset_autonomy
}

seed_preemption_alert() {
  log "Seeding GNS3 Preemption alert via $ORCH_URL"
  curl -sS -X POST "$ORCH_URL/api/v1/simulation/seed-preemption" \
    -H 'Content-Type: application/json' \
    -d '{"title":"Impending Congestion Detected","host":"gns3-pe1","path":"eth0"}' \
    >>"$LOG_PATH" 2>&1 || log "WARN: seed-preemption failed"
}

wait_for_human_override() {
  local deadline=$(( $(date +%s) + HITL_TIMEOUT ))
  write_status 4 "AI Predictive Congestion & UI Override" \
    "Waiting for operator Approve (force_path on GNS3)…" true \
    "Alert: Impending Congestion Detected — Approve steers preemptively to eth0"
  while (( $(date +%s) < deadline )); do
    should_stop && return 1
    if [[ "$DRY" == "1" ]] && (( $(date +%s) - STARTED_EPOCH >= 128 )); then
      mission_action force_path eth0
      return 0
    fi
    if python3 - "$MISSION" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
try:
    d = json.loads(p.read_text()) if p.exists() else {}
except Exception:
    d = {}
raise SystemExit(0 if d.get("human_override") == "eth0" else 1)
PY
    then
      log "HITL: human_override eth0 observed (GNS3 mission_state)"
      return 0
    fi
    sleep 2
  done
  log "WARN: HITL timeout (${HITL_TIMEOUT}s) — continuing without force"
  return 0
}

fast_congestion_ramp() {
  log "Util congestion ramp through HTB 1:15 (Pi twin)"
  if [[ "$DRY" == "1" ]]; then
    log "DRY: skip util ramp"
    return 0
  fi
  STEPS=5 STEP_SEC=8 START_MBIT=8 END_MBIT=28 bash "$INJECT/util_congestion.sh" >>"$LOG_PATH" 2>&1 || true
}

trap 'cleanup_lab; reset_sdwan_state; finish_status false "stopped"; exit 130' INT TERM

log "=== DECA GNS3 orchestrator simulation start (DRY=$DRY) ==="
# Ensure fabric selector is gns3
curl -sS -X POST "$ORCH_URL/api/v1/fabric" -H 'Content-Type: application/json' \
  -d '{"active":"gns3"}' >>"$LOG_PATH" 2>&1 || true

cleanup_lab
reset_sdwan_state
write_status 0 "Initialization" "Starting GNS3 iperf3 ToS receivers…" false \
  "IPERF-B :5004 / :5006 / :5201 · HTB on PE"

# ── Phase 0 ─────────────────────────────────────────────────────────────────
gns3_run "apply HTB (PE+CE; CORE clear for NetEM)" \
  env RATE=40mbit BEST_EFFORT=1 bash "$ROOT/lab/gns3/apply_sla_htb.sh" || true
sleep_until_abs 5 || { finish_status false "stopped"; exit 0; }

# ── Phase 1 ─────────────────────────────────────────────────────────────────
write_status 1 "Clear Weather Traffic" "Baseline ToS flows IPERF-A→B via HTB…" false \
  "Dashboard green. TT&C 0x88 / Payload 0x80 / Admin TCP. Underlay gre."
gns3_run "traffic mixed" bash "$TRAFFIC" start mixed 400 || true
# Keep chaos gauges reflecting live traffic so fleet/Wireshark stay interesting
python3 - "$ROOT/lab/gns3/state/chaos_state.json" <<'PY' || true
import json, time
from pathlib import Path
p = Path(__import__("sys").argv[1])
d = {}
try: d = json.loads(p.read_text())
except Exception: pass
d.update({"util_gre_mbps": 55.0, "latency_gre_ms": 2.0, "loss_gre_pct": 0.0,
          "fault_id": "", "updated_unix": time.time(), "traffic_profile": "mixed"})
p.write_text(json.dumps(d, indent=2) + "\n")
PY
sleep_until_abs 30 || { finish_status false "stopped"; exit 0; }

# ── Phase 2 — soft delay 40ms (Payload holds ≤80ms, TT&C red) ───────────────
write_status 2 "Payload Tolerance Check" "NetEM delay 40ms on CORE underlay…" false \
  "Latency ~40ms. TT&C SLA red. Payload green. policy conflict expected."
if [[ "$DRY" != "1" ]]; then
  # shellcheck source=/dev/null
  source "$INJECT/_common.sh"
  apply_netem_pe1 "delay 40ms 8ms distribution normal" || log "WARN: NetEM delay failed"
  patch_state fault_id=rain_fade latency_gre_ms=40 jitter_gre_ms=8
  python3 - "$MISSION" <<'PY' || true
import json, time, sys
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text()) if p.exists() else {}
d.update({"fabric":"gns3","active_path":"gre","conflict":1,"ttc_wanted":"eth0",
          "payload_wanted":"gre","path_latency_ms":{"gre":40.0,"eth0":12.0},
          "updated_unix": time.time()})
p.write_text(json.dumps(d, indent=2)+"\n")
PY
fi
sleep_until_abs 60 || { finish_status false "stopped"; exit 0; }

# ── Phase 3 — harder breach ─────────────────────────────────────────────────
write_status 3 "Hard Steer & Hysteresis" "NetEM delay+loss on CORE underlay…" false \
  "Delay+loss; Approve path will steer to eth0 backup after HITL."
if [[ "$DRY" != "1" ]]; then
  # shellcheck source=/dev/null
  source "$INJECT/_common.sh"
  apply_netem_pe1 "delay 35ms 15ms loss 2%" || log "WARN: NetEM delay+loss failed"
  patch_state fault_id=loss_progression latency_gre_ms=35 jitter_gre_ms=15 loss_gre_pct=2.0
  python3 - "$MISSION" <<'PY' || true
import json, time, sys
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text()) if p.exists() else {}
d.update({"fabric":"gns3","active_path":"gre","conflict":1,"ttc_wanted":"eth0",
          "payload_wanted":"gre","path_latency_ms":{"gre":35.0,"eth0":12.0},
          "updated_unix": time.time()})
p.write_text(json.dumps(d, indent=2)+"\n")
PY
fi
sleep_until_abs 120 || { finish_status false "stopped"; exit 0; }

# ── Phase 4 — clear fault, congestion precursor, HITL ───────────────────────
write_status 4 "AI Predictive Congestion & UI Override" "Clearing NetEM; util ramp…" false \
  "LSTM-style alert on gns3-pe1. Approve → force_path eth0."
if [[ "$DRY" != "1" ]]; then
  # shellcheck source=/dev/null
  source "$INJECT/_common.sh"
  apply_netem_pe1 clear || true
  patch_state fault_id=util_congestion latency_gre_ms=8 loss_gre_pct=0
fi
mission_action clear_force
seed_preemption_alert
# Ensure baseline traffic still running before util ramp (iperf may have exited)
gns3_run "traffic ensure" bash "$TRAFFIC" start mixed 300 || true
fast_congestion_ramp &
RAMP_PID=$!
wait_for_human_override || true
kill "$RAMP_PID" 2>/dev/null || true
wait "$RAMP_PID" 2>/dev/null || true
sleep_until_abs 180 || { finish_status false "stopped"; exit 0; }

# ── Phase 5 — recovery ──────────────────────────────────────────────────────
write_status 5 "Hysteresis Recovery" "Clearing human override…" false \
  "Autonomy resumes on gre after clear_force."
mission_action clear_force
if [[ "$DRY" != "1" ]]; then
  bash "$INJECT/util_congestion.sh" --clear >>"$LOG_PATH" 2>&1 || true
fi
sleep_until_abs 240 || { finish_status false "stopped"; exit 0; }

# ── Phase 6 ─────────────────────────────────────────────────────────────────
write_status 6 "Teardown" "Cleaning GNS3 traffic/NetEM…" false \
  "iperf stopped; NetEM cleared; HTB kept."
cleanup_lab
reset_sdwan_state
log "=== GNS3 simulation complete ==="
write_status 6 "Teardown" "Simulation complete" false "GNS3 cleaned; autonomy reset."
finish_status true "Simulation complete"
exit 0
