#!/usr/bin/env bash
# inject_bgp_flap.sh — Route-flap / underlay instability profile (Q2 label 3).
# Ctrl+C kills remote SSH loop and restores gre-te-core UP (healthy).
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deca_cli_bridge.sh
source "$_SCRIPT_DIR/deca_cli_bridge.sh"

HOST=station1
NEIGHBOR=10.1.3.1
DEV=gre-te-core
CYCLES=18
PERIOD_SEC=5
DOWN_SEC=2
LINK_BOUNCE=0
HOLD_SEC=0
CLEAR_ONLY=0
SCHEDULE_OUT="${DECA_BGP_SCHEDULE_OUT:-}"
PIDFILE=/tmp/deca_bgp_flap.pid
SSH_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --neighbor) NEIGHBOR="$2"; shift 2 ;;
    --dev) DEV="$2"; shift 2 ;;
    --cycles) CYCLES="$2"; shift 2 ;;
    --period-sec) PERIOD_SEC="$2"; shift 2 ;;
    --down-sec) DOWN_SEC="$2"; shift 2 ;;
    --hold-sec) HOLD_SEC="$2"; shift 2 ;;
    --link-bounce) LINK_BOUNCE=1; shift ;;
    --schedule-out) SCHEDULE_OUT="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
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

ensure_up() {
  echo "Restoring $HOST $DEV UP (healthy)"
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
ip link set $DEV up 2>/dev/null || true
ip -br link show $DEV || true
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  ensure_up
  DECA_CLI_FAULT_ID="bgp_flap"
  DECA_CLI_ATTACHED=1
  deca_cli_end cli_clear || true
  exit 0
fi

on_interrupt() {
  echo
  echo "Interrupted — killing remote inject, restoring healthy on $HOST/$DEV"
  kill_ssh
  ensure_up
  deca_cli_end cli_interrupted || true
  exit 130
}
trap on_interrupt INT TERM

TOTAL=$((CYCLES * PERIOD_SEC + HOLD_SEC))
MODE="soft-clear"
[[ "$LINK_BOUNCE" -eq 1 ]] && MODE="link-bounce+$MODE"
echo "BGP flap on $HOST nbr=$NEIGHBOR: ${CYCLES}×${PERIOD_SEC}s + hold ${HOLD_SEC}s (~${TOTAL}s) mode=$MODE"
echo "(Ctrl+C kills remote loop + restores $DEV UP → healthy)"
SUMMARY="bgp_flap ${CYCLES}×${PERIOD_SEC}s hold=${HOLD_SEC}s mode=$MODE"
deca_cli_attach bgp_flap "$TOTAL" "$SUMMARY"
ensure_up >/dev/null 2>&1 || true

TMP="$(mktemp /tmp/deca_bgp_remote.XXXXXX)"
cat >"$TMP" <<EOF
set -euo pipefail
NEIGHBOR='$NEIGHBOR'
DEV='$DEV'
CYCLES=$CYCLES
PERIOD_SEC=$PERIOD_SEC
DOWN_SEC=$DOWN_SEC
LINK_BOUNCE=$LINK_BOUNCE
HOLD_SEC=$HOLD_SEC
PIDFILE=$PIDFILE

restore() {
  rm -f "\$PIDFILE"
  ip link set "\$DEV" up 2>/dev/null || true
  echo "[\$(date -u +%H:%M:%S)] restored \$DEV UP (healthy)"
}
trap restore EXIT INT TERM HUP
echo \$\$ > "\$PIDFILE"

: > /tmp/deca_bgp_flap_schedule.jsonl
for i in \$(seq 1 "\$CYCLES"); do
  now=\$(date +%s)
  echo "[\$(date -u +%H:%M:%S)] flap \$i/\$CYCLES clear bgp \$NEIGHBOR soft"
  vtysh -c "clear bgp \$NEIGHBOR soft" >/dev/null
  printf '{"ts_unix":%s,"event":"soft_clear","cycle":%s,"period_sec":%s,"link_bounce":%s}\n' \
    "\$now" "\$i" "\$PERIOD_SEC" "\$LINK_BOUNCE" >> /tmp/deca_bgp_flap_schedule.jsonl
  if [[ "\$LINK_BOUNCE" -eq 1 ]]; then
    echo "[\$(date -u +%H:%M:%S)] link bounce \$DEV down \${DOWN_SEC}s"
    ip link set "\$DEV" down
    sleep "\$DOWN_SEC"
    ip link set "\$DEV" up
  fi
  rem=\$PERIOD_SEC
  if [[ "\$LINK_BOUNCE" -eq 1 ]]; then
    rem=\$(( PERIOD_SEC - DOWN_SEC ))
  fi
  [[ \$rem -lt 1 ]] && rem=1
  sleep "\$rem"
done

if [[ "\$HOLD_SEC" -gt 0 ]]; then
  echo "[\$(date -u +%H:%M:%S)] storm done — Approve hold \${HOLD_SEC}s (slow flaps)"
  end=\$(( \$(date +%s) + HOLD_SEC ))
  n=0
  while [[ \$(date +%s) -lt \$end ]]; do
    n=\$((n + 1))
    echo "[\$(date -u +%H:%M:%S)] hold flap \$n clear bgp \$NEIGHBOR soft"
    vtysh -c "clear bgp \$NEIGHBOR soft" >/dev/null || true
    sleep 12
  done
fi

echo "[\$(date -u +%H:%M:%S)] flap campaign complete — cleanup will restore healthy"
ip -br link show "\$DEV" || true
EOF

deca_cli_run_remote "$HOST" "$TMP"
rm -f "$TMP"
trap - INT TERM
deca_cli_end cli_hold_done || true

if [[ -n "$SCHEDULE_OUT" ]]; then
  mkdir -p "$(dirname "$SCHEDULE_OUT")"
  scp -q "${HOST}:/tmp/deca_bgp_flap_schedule.jsonl" "$SCHEDULE_OUT" \
    && echo "wrote schedule $SCHEDULE_OUT" \
    || echo "WARN: could not scp BGP flap schedule from $HOST"
fi

echo "BGP flap finished — $DEV UP (healthy)."
