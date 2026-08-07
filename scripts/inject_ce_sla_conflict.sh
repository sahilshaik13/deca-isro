#!/usr/bin/env bash
# inject_ce_sla_conflict.sh — Bronze CE burst vs Gold TT&C (ISRO mentor CE↔CE SLA conflict).
# Ctrl+C kills remote SSH inject loop + iperf (healthy).
set -euo pipefail

HOST=station1
ROGUE_NS=ce-mauritius
VICTIM_NS=ce-a
DST_SAC=10.100.2.1
ROGUE_TOS=128
VICTIM_TOS=136
ROGUE_START=2
ROGUE_END=20
STEPS=5
STEP_SEC=18
HOLD_SEC=0
VICTIM_MBIT=1
CLEAR_ONLY=0
FORCE_CLEAR=0
MODE=continuous
PIDFILE=/tmp/deca_ce_sla_conflict.pid
SSH_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --rogue-ns) ROGUE_NS="$2"; shift 2 ;;
    --victim-ns) VICTIM_NS="$2"; shift 2 ;;
    --rogue-mbit|--end-mbit) ROGUE_END="$2"; shift 2 ;;
    --start-mbit) ROGUE_START="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --hold-sec) HOLD_SEC="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    --force-clear) FORCE_CLEAR=1; shift ;;
    --coarse) MODE=coarse; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
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

clear_ce() {
  echo "Clearing CE SLA conflict injectors on $HOST (healthy)"
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
pkill -f 'deca_ce_sla_' 2>/dev/null || true
ip netns exec ce-mauritius pkill -f iperf3 2>/dev/null || true
ip netns exec ce-a pkill -f 'iperf3.*--tos' 2>/dev/null || true
echo cleared
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  clear_ce
  exit 0
fi

on_interrupt() {
  echo
  echo "Interrupted — killing remote inject, restoring healthy on $HOST"
  kill_ssh
  clear_ce
  exit 130
}
trap on_interrupt INT TERM

if pgrep -f 'inject_bgp_flap.sh|inject_cpu_stress.sh|inject_rain_fade.sh' >/dev/null 2>&1; then
  if [[ "$FORCE_CLEAR" -ne 1 ]]; then
    echo "WARN: another inject/campaign fault appears active on brain."
    echo "      Refusing to stack CE conflict (pass --force-clear to override)."
    exit 3
  fi
fi

if [[ "$HOLD_SEC" -le 0 ]]; then
  HOLD_SEC=$((STEPS * STEP_SEC))
fi

echo "CE SLA conflict mode=$MODE rogue=$ROGUE_NS →${ROGUE_END}Mbit :5006; victim=$VICTIM_NS TT&C ${VICTIM_MBIT}M hold=${HOLD_SEC}s [CAPTURE_CONTRACT]"
echo "(Ctrl+C kills remote loop + iperf → healthy)"

TMP="$(mktemp /tmp/deca_ce_sla_remote.XXXXXX)"

if [[ "$MODE" == "coarse" ]]; then
  cat >"$TMP" <<EOF
set -euo pipefail
ROGUE_NS='$ROGUE_NS'; VICTIM_NS='$VICTIM_NS'; DST='$DST_SAC'
ROGUE_TOS=$ROGUE_TOS; VICTIM_TOS=$VICTIM_TOS
STEPS=$STEPS; STEP_SEC=$STEP_SEC; START_MBIT=$ROGUE_START; END_MBIT=$ROGUE_END
VICTIM_MBIT=$VICTIM_MBIT; ROGUE_PORT=5006; VICTIM_PORT=5201
PIDFILE=$PIDFILE

cleanup() {
  ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
  ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
  rm -f "\$PIDFILE"
  echo "[\$(date -u +%H:%M:%S)] CE SLA coarse cleared (healthy)"
}
trap cleanup EXIT INT TERM HUP
echo \$\$ > "\$PIDFILE"

ssh -o BatchMode=yes -o ConnectTimeout=5 192.168.50.20 \
  'sudo bash -c "ip netns exec ce-b iperf3 -s -D -p 5006 2>/dev/null || true; ip netns exec ce-b iperf3 -s -D -p 5201 2>/dev/null || true"' \
  2>/dev/null || true
TOTAL=\$(( STEPS * STEP_SEC + 5 ))
ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
ip netns exec "\$VICTIM_NS" iperf3 -c "\$DST" -u -b "\${VICTIM_MBIT}M" -t "\$TOTAL" --tos "\$VICTIM_TOS" -p "\$VICTIM_PORT" \
  >/tmp/deca_ce_sla_victim.log 2>&1 &
for i in \$(seq 0 \$((STEPS - 1))); do
  if [[ "\$STEPS" -eq 1 ]]; then mbit=\$END_MBIT
  else mbit=\$(( START_MBIT + (END_MBIT - START_MBIT) * i / (STEPS - 1) )); fi
  echo "[\$(date -u +%H:%M:%S)] COARSE rogue step \$i/\$STEPS \${mbit}Mbit"
  ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
  sleep 1
  ip netns exec "\$ROGUE_NS" iperf3 -c "\$DST" -P 2 -b "\${mbit}M" -t "\$STEP_SEC" -p "\$ROGUE_PORT" \
    >/tmp/deca_ce_sla_rogue.log 2>&1 &
  sleep "\$STEP_SEC"
done
echo "[\$(date -u +%H:%M:%S)] CE SLA coarse complete — cleanup will restore healthy"
EOF
else
  cat >"$TMP" <<EOF
set -euo pipefail
ROGUE_NS='$ROGUE_NS'; VICTIM_NS='$VICTIM_NS'; DST='$DST_SAC'
ROGUE_TOS=$ROGUE_TOS; VICTIM_TOS=$VICTIM_TOS
HOLD_SEC=$HOLD_SEC; END_MBIT=$ROGUE_END; VICTIM_MBIT=$VICTIM_MBIT
ROGUE_PORT=5006; VICTIM_PORT=5201
PIDFILE=$PIDFILE
TOTAL=\$(( HOLD_SEC + 8 ))

cleanup() {
  ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
  ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
  rm -f "\$PIDFILE"
  echo "[\$(date -u +%H:%M:%S)] CE SLA continuous cleared (healthy)"
}
trap cleanup EXIT INT TERM HUP
echo \$\$ > "\$PIDFILE"

ssh -o BatchMode=yes -o ConnectTimeout=5 192.168.50.20 \
  'sudo bash -c "ip netns exec ce-b iperf3 -s -D -p 5006 2>/dev/null || true; ip netns exec ce-b iperf3 -s -D -p 5201 2>/dev/null || true"' \
  2>/dev/null || true

: > /tmp/deca_ce_sla_schedule.jsonl
now=\$(date +%s)
printf '{"ts_unix":%s,"phase":"plateau","rogue_mbit":%s,"hold_sec":%s}\n' \
  "\$now" "\$END_MBIT" "\$HOLD_SEC" >> /tmp/deca_ce_sla_schedule.jsonl

ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
sleep 1

echo "[\$(date -u +%H:%M:%S)] start victim TT&C \${VICTIM_MBIT}M + rogue plateau \${END_MBIT}Mbit for \${HOLD_SEC}s"
ip netns exec "\$VICTIM_NS" iperf3 -c "\$DST" -u -b "\${VICTIM_MBIT}M" -t "\$TOTAL" --tos "\$VICTIM_TOS" -p "\$VICTIM_PORT" \
  >/tmp/deca_ce_sla_victim.log 2>&1 &
ip netns exec "\$ROGUE_NS" iperf3 -c "\$DST" -P 2 -b "\${END_MBIT}M" -t "\$TOTAL" -p "\$ROGUE_PORT" \
  >/tmp/deca_ce_sla_rogue.log 2>&1 &
sleep "\$HOLD_SEC"
echo "[\$(date -u +%H:%M:%S)] CE SLA continuous plateau complete — cleanup will restore healthy"
tail -5 /tmp/deca_ce_sla_rogue.log 2>/dev/null || true
EOF
fi

ssh -T "$HOST" "sudo bash -s" <"$TMP" &
SSH_PID=$!
wait "$SSH_PID" || true
SSH_PID=""
rm -f "$TMP"
trap - INT TERM
echo "[$(date -u +%H:%M:%S)] CE SLA conflict finished — injectors cleared (healthy)."
