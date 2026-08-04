#!/usr/bin/env bash
# inject_util_congestion.sh — ramp Payload iperf THROUGH HTB 1:15.
#
# Primary: TCP :5006 (lab HTB dport filter → flowid 1:15). Live fabric often
# strips/ignores --tos, so we do not rely on DSCP marks.
# Underlay util is read as max(gre, eth0) in predictive/prom_export.py.
#
# Usage:
#   bash scripts/inject_util_congestion.sh
#   bash scripts/inject_util_congestion.sh --clear
set -euo pipefail

HOST=station1
PEER=station2
NS=ce-a
PEER_NS=ce-b
DST=10.100.2.1
PORT=5006
STEPS=6
STEP_SEC=20
START_MBIT=5
END_MBIT=30
PARALLEL=2
CLEAR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --peer) PEER="$2"; shift 2 ;;
    --ns) NS="$2"; shift 2 ;;
    --dst) DST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-mbit) START_MBIT="$2"; shift 2 ;;
    --end-mbit) END_MBIT="$2"; shift 2 ;;
    --parallel) PARALLEL="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s"; }

ensure_peer_servers() {
  ssh -T -o BatchMode=yes -o ConnectTimeout=8 "$PEER" "sudo bash -s" <<EOF || true
set -euo pipefail
ip netns exec $PEER_NS bash -c '
  pkill -x iperf3 2>/dev/null || true
  sleep 1
  iperf3 -s -D -p 5006 || true
  iperf3 -s -D -p 5201 || true
  ss -lntp | grep -E ":5006|:5201" || true
'
EOF
}

stop_clients() {
  run <<'EOF' || true
ip netns exec ce-a pkill -f 'iperf3 -c' 2>/dev/null || true
pkill -f 'iperf3.*--tos' 2>/dev/null || true
echo cleared
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  echo "Stopping HTB-class util injectors on $HOST"
  stop_clients
  exit 0
fi

echo "Util congestion via HTB 1:15 (TCP :$PORT ×$PARALLEL): ${START_MBIT}→${END_MBIT} Mbit over $((STEPS*STEP_SEC))s"

for i in $(seq 0 $((STEPS - 1))); do
  mbit=$(( START_MBIT + (END_MBIT - START_MBIT) * i / (STEPS - 1) ))
  per=$(( mbit / PARALLEL ))
  [[ "$per" -lt 1 ]] && per=1
  echo "[$(date -u +%H:%M:%S)] step $i/$STEPS hold ${mbit}Mbit (${PARALLEL}×${per}M TCP :$PORT) for ${STEP_SEC}s (HTB 1:15)"
  ensure_peer_servers
  stop_clients >/dev/null
  sleep 1
  run <<EOF
set -euo pipefail
ip netns exec '$NS' iperf3 -c '$DST' -P $PARALLEL -b ${per}M -t $STEP_SEC -p $PORT \
  >/tmp/deca_util_cong.log 2>&1 &
sleep $STEP_SEC
ip netns exec '$NS' pkill -f 'iperf3 -c' 2>/dev/null || true
tail -8 /tmp/deca_util_cong.log 2>/dev/null || true
EOF
done

stop_clients >/dev/null
echo "[$(date -u +%H:%M:%S)] util ramp complete"
