#!/usr/bin/env bash
# inject_rain_fade.sh — slow latency drift on gre-te-core (Rain Fade profile).
#
# Ctrl+C kills the remote SSH inject loop, then clears netem (healthy).
#
# Usage:
#   bash scripts/inject_rain_fade.sh
#   bash scripts/inject_rain_fade.sh --clear
#   bash scripts/inject_rain_fade.sh --host station1 --steps 24 --step-sec 8 --hold-sec 120
set -euo pipefail

HOST=station1
DEV=gre-te-core
STEPS=24
STEP_SEC=5
START_MS=5
END_MS=100
JITTER_MS=5
HOLD_SEC=0
CLEAR_ONLY=0
PIDFILE=/tmp/deca_rain_fade.pid
SSH_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --dev) DEV="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-ms) START_MS="$2"; shift 2 ;;
    --end-ms) END_MS="$2"; shift 2 ;;
    --jitter-ms) JITTER_MS="$2"; shift 2 ;;
    --hold-sec) HOLD_SEC="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help)
      sed -n '2,10p' "$0"; exit 0 ;;
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
  exit 0
fi

on_interrupt() {
  echo
  echo "Interrupted — killing remote inject, restoring healthy on $HOST/$DEV"
  kill_ssh
  clear_netem
  exit 130
}
trap on_interrupt INT TERM

TOTAL=$((STEPS * STEP_SEC + HOLD_SEC))
echo "Rain fade on $HOST/$DEV: ${START_MS}→${END_MS}ms over $((STEPS * STEP_SEC))s then hold ${HOLD_SEC}s (~${TOTAL}s) (${STEPS}×${STEP_SEC}s)"
echo "(Ctrl+C kills remote loop + clears netem → healthy)"

TMP="$(mktemp /tmp/deca_rain_fade_remote.XXXXXX)"
cat >"$TMP" <<EOF
set -euo pipefail
DEV="$DEV"
STEPS=$STEPS
STEP_SEC=$STEP_SEC
START_MS=$START_MS
END_MS=$END_MS
JITTER_MS=$JITTER_MS
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
  delay=\$(( START_MS + (END_MS - START_MS) * i / (STEPS - 1) ))
  tc qdisc replace dev "\$DEV" root netem delay \${delay}ms \${JITTER_MS}ms distribution normal
  echo "[\$(date -u +%H:%M:%S)] delay=\${delay}ms"
  sleep "\$STEP_SEC"
done
echo "Fade ramp complete — holding peak \${END_MS}ms for \${HOLD_SEC}s (Approve window)"
if [[ "\$HOLD_SEC" -gt 0 ]]; then
  sleep "\$HOLD_SEC"
fi
echo "[\$(date -u +%H:%M:%S)] hold done — cleanup will restore healthy"
EOF

ssh -T "$HOST" "sudo bash -s" <"$TMP" &
SSH_PID=$!
wait "$SSH_PID" || true
SSH_PID=""
rm -f "$TMP"
trap - INT TERM
echo "Rain fade finished — path cleared (healthy)."
