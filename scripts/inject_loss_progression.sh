#!/usr/bin/env bash
# inject_loss_progression.sh — progressive packet loss on gre-te-core.
# Ctrl+C kills remote SSH loop, then clears netem (healthy).
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deca_cli_bridge.sh
source "$_SCRIPT_DIR/deca_cli_bridge.sh"

HOST=station1
DEV=gre-te-core
STEPS=24
STEP_SEC=5
START_PCT=0
END_PCT=3.5
HOLD_SEC=0
CLEAR_ONLY=0
PIDFILE=/tmp/deca_loss_progression.pid
SSH_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --dev) DEV="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-pct) START_PCT="$2"; shift 2 ;;
    --end-pct) END_PCT="$2"; shift 2 ;;
    --hold-sec) HOLD_SEC="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

kill_ssh() {
  if [[ -n "${SSH_PID}" ]] && kill -0 "$SSH_PID" 2>/dev/null; then
    kill -TERM "$SSH_PID" 2>/dev/null || true
    sleep 0.4
    kill -KILL "$SSH_PID" 2>/dev/null || true
    wait "$SSH_PID" 2>/dev/null || true
    SSH_PID=""
  fi
}

clear_netem() {
  echo "Clearing netem on $HOST $DEV (healthy)"
  ssh -T "$HOST" "sudo bash -s" <<EOF || true
if [[ -f $PIDFILE ]]; then
  pid=\$(cat $PIDFILE 2>/dev/null || true)
  if [[ -n "\$pid" ]]; then
    kill -TERM "\$pid" 2>/dev/null || true
    pkill -P "\$pid" 2>/dev/null || true
    sleep 0.2
    kill -KILL "\$pid" 2>/dev/null || true
  fi
  rm -f $PIDFILE
fi
tc qdisc del dev $DEV root 2>/dev/null || true
tc qdisc show dev $DEV 2>/dev/null || true
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  clear_netem
  DECA_CLI_FAULT_ID="loss_progression"
  DECA_CLI_ATTACHED=1
  deca_cli_end cli_clear || true
  exit 0
fi

on_interrupt() {
  echo
  echo "Interrupted — killing remote inject, restoring healthy on $HOST/$DEV"
  kill_ssh
  clear_netem
  deca_cli_end cli_interrupted || true
  exit 130
}
trap on_interrupt INT TERM

TOTAL=$((STEPS * STEP_SEC + HOLD_SEC))
echo "Loss progression on $HOST/$DEV: ${START_PCT}→${END_PCT}% over $((STEPS * STEP_SEC))s then hold ${HOLD_SEC}s (~${TOTAL}s)"
echo "(Ctrl+C kills remote loop + clears netem → healthy)"
SUMMARY="loss_progression ${START_PCT}→${END_PCT}% steps=${STEPS}×${STEP_SEC}s hold=${HOLD_SEC}s"
deca_cli_attach loss_progression "$TOTAL" "$SUMMARY"

TMP="$(mktemp /tmp/deca_loss_remote.XXXXXX)"
cat >"$TMP" <<EOF
set -euo pipefail
DEV="$DEV"
STEPS=$STEPS
STEP_SEC=$STEP_SEC
START_PCT=$START_PCT
END_PCT=$END_PCT
HOLD_SEC=$HOLD_SEC
PIDFILE=$PIDFILE

cleanup() {
  rm -f "\$PIDFILE"
  echo "[\$(date -u +%H:%M:%S)] clearing netem on \$DEV (healthy)"
  tc qdisc del dev "\$DEV" root 2>/dev/null || true
  tc qdisc show dev "\$DEV" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP
echo \$\$ > "\$PIDFILE"

tc qdisc del dev "\$DEV" root 2>/dev/null || true
for i in \$(seq 0 \$((STEPS - 1))); do
  pct=\$(awk -v s="\$START_PCT" -v e="\$END_PCT" -v i="\$i" -v n="\$STEPS" 'BEGIN{printf "%.3f", s+(e-s)*i/(n-1)}')
  echo "[\$(date -u +%H:%M:%S)] step \$i/\$STEPS loss \${pct}%"
  tc qdisc replace dev "\$DEV" root netem loss \${pct}%
  sleep "\$STEP_SEC"
done
echo "[\$(date -u +%H:%M:%S)] ramp done — holding loss=\${END_PCT}% for \${HOLD_SEC}s (Approve window)"
if [[ "\$HOLD_SEC" -gt 0 ]]; then
  sleep "\$HOLD_SEC"
fi
echo "[\$(date -u +%H:%M:%S)] hold done — cleanup will restore healthy"
EOF

deca_cli_run_remote "$HOST" "$TMP"
rm -f "$TMP"
trap - INT TERM
deca_cli_end cli_hold_done || true
echo "Loss progression finished — path cleared (healthy)."
