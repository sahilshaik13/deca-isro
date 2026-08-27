#!/usr/bin/env bash
# Bridge laptop CLI inject scripts → DECA orchestrator (pipeline tabs + watch + Decide).
# Sourced by inject_*.sh — does not need dashboard FaultButtons.
#
# Env:
#   DECA_API_URL=http://127.0.0.1:8000
#   DECA_CLI_BRIDGE=0   # physics only (no UI/watch attach)

: "${DECA_API_URL:=http://127.0.0.1:8000}"
: "${DECA_CLI_BRIDGE:=1}"
DECA_CLI_FAULT_ID="${DECA_CLI_FAULT_ID:-}"
DECA_CLI_ATTACHED=0

deca_cli_attach() {
  local fid="$1"
  local duration_s="${2:-0}"
  local summary="${3:-}"
  local seed_delay="${4:-}"
  DECA_CLI_FAULT_ID="$fid"
  [[ "$DECA_CLI_BRIDGE" == "0" ]] && return 0
  local payload
  payload="$(FAULT_ID="$fid" DUR="$duration_s" SUM="$summary" SEED="$seed_delay" python3 - <<'PY'
import json, os
seed = os.environ.get("SEED", "").strip()
body = {
    "fault_id": os.environ["FAULT_ID"],
    "started_by": "cli",
    "duration_s": float(os.environ.get("DUR") or 0) or None,
    "cmd_summary": os.environ.get("SUM") or "",
}
if seed:
    try:
        body["seed_delay_s"] = float(seed)
    except ValueError:
        pass
print(json.dumps(body))
PY
)" || return 0
  if curl -sf --max-time 5 -X POST "${DECA_API_URL}/api/v1/faults/cli/attach" \
      -H "Content-Type: application/json" \
      -d "$payload" >/dev/null; then
    DECA_CLI_ATTACHED=1
    echo "[deca-cli] attached → backend ${fid} (pipeline tabs + watch + model Decide)"
  else
    echo "[deca-cli] warn: could not attach to ${DECA_API_URL} (UI/watch may stay idle)" >&2
  fi
}

deca_cli_log() {
  local line="${1:-}"
  [[ -z "$line" ]] && return 0
  [[ "$DECA_CLI_BRIDGE" == "0" || "$DECA_CLI_ATTACHED" != "1" ]] && return 0
  local payload
  payload="$(LINE="$line" FID="${DECA_CLI_FAULT_ID}" python3 - <<'PY'
import json, os
print(json.dumps({"line": os.environ.get("LINE", ""), "fault_id": os.environ.get("FID", "")}))
PY
)" || return 0
  curl -sf --max-time 3 -X POST "${DECA_API_URL}/api/v1/faults/cli/log" \
    -H "Content-Type: application/json" \
    -d "$payload" >/dev/null || true
}

deca_cli_end() {
  local reason="${1:-cli_hold_done}"
  [[ "$DECA_CLI_BRIDGE" == "0" || "$DECA_CLI_ATTACHED" != "1" ]] && return 0
  local payload
  payload="$(FID="${DECA_CLI_FAULT_ID}" REASON="$reason" python3 - <<'PY'
import json, os
print(json.dumps({"fault_id": os.environ.get("FID", ""), "reason": os.environ.get("REASON", "cli_hold_done")}))
PY
)" || return 0
  curl -sf --max-time 5 -X POST "${DECA_API_URL}/api/v1/faults/cli/end" \
    -H "Content-Type: application/json" \
    -d "$payload" >/dev/null || true
  DECA_CLI_ATTACHED=0
  echo "[deca-cli] ended (${reason})"
}

# Run remote sudo bash on HOST from TMP script; stream to terminal + Inject tab.
# Caller keeps SSH_PID for Ctrl+C handlers.
deca_cli_run_remote() {
  local host="$1"
  local tmp="$2"
  local fifo
  fifo="$(mktemp -u /tmp/deca_cli_fifo.XXXXXX)"
  mkfifo "$fifo"
  ssh -T "$host" "sudo bash -s" <"$tmp" >"$fifo" 2>&1 &
  SSH_PID=$!
  while IFS= read -r line || [[ -n "${line:-}" ]]; do
    printf '%s\n' "$line"
    deca_cli_log "$line"
  done <"$fifo"
  wait "$SSH_PID" || true
  SSH_PID=""
  rm -f "$fifo"
}
