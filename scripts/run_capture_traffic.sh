#!/usr/bin/env bash
# run_capture_traffic.sh — controlled background traffic during fault captures.
#
# Profiles (Pi station1 → station2). Does NOT replace L5 util inject.
# L0 must use --profile idle only.
#
#   bash scripts/run_capture_traffic.sh --profile ttc_light --seconds 90
#   bash scripts/run_capture_traffic.sh --clear
set -euo pipefail

HOST=station1
PEER=192.168.50.20
NS=ce-a
PEER_NS=ce-b
DST=10.100.2.1
PORT=5201
PROFILE=idle
SECONDS_RUN=60
CLEAR_ONLY=0
TAG=deca-cap-traffic

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --seconds) SECONDS_RUN="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s"; }

clear_traffic() {
  run <<EOF
pkill -f '$TAG' 2>/dev/null || true
ip netns exec $NS pkill -f '$TAG' 2>/dev/null || true
ip netns exec ce-mauritius pkill -f '$TAG' 2>/dev/null || true
echo cleared capture traffic
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  clear_traffic
  exit 0
fi

case "$PROFILE" in
  idle)
    clear_traffic >/dev/null 2>&1 || true
    echo "traffic profile=idle (no background flows)"
    exit 0
    ;;
  ttc_light|payload_medium|mixed) ;;
  *) echo "profile must be idle|ttc_light|payload_medium|mixed"; exit 2 ;;
esac

clear_traffic >/dev/null 2>&1 || true

echo "traffic profile=$PROFILE on $HOST for ${SECONDS_RUN}s"
run <<EOF
set -euo pipefail
TAG='$TAG'
NS='$NS'
DST='$DST'
PORT=$PORT
SECS=$SECONDS_RUN
PROFILE='$PROFILE'
PEER='$PEER'
PEER_NS='$PEER_NS'

# Far-end iperf3 server
ssh -o BatchMode=yes -o ConnectTimeout=5 "\$PEER" \
  "sudo ip netns exec \$PEER_NS bash -c 'pgrep -x iperf3 >/dev/null || iperf3 -s -D -p \$PORT'" \
  2>/dev/null || true

cleanup() {
  pkill -f "\$TAG" 2>/dev/null || true
  ip netns exec "\$NS" pkill -f "\$TAG" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

start_flow() {
  local name="\$1" tos="\$2" mbit="\$3"
  # cmdline includes TAG for --clear
  ip netns exec "\$NS" bash -c "exec -a \${TAG}-\${name} iperf3 -c \$DST -u -b \${mbit}M -t \$SECS --tos \$tos -p \$PORT" \
    >/tmp/\${TAG}_\${name}.log 2>&1 &
}

case "\$PROFILE" in
  ttc_light)
    start_flow ttc 136 1
    ;;
  payload_medium)
    # Moderate payload — below L5 congestion ramps so fault texture still dominates
    start_flow payload 128 8
    ;;
  mixed)
    start_flow ttc 136 1
    start_flow payload 128 5
    ;;
esac

sleep "\$SECS"
cleanup
echo "[\$(date -u +%H:%M:%S)] traffic profile \$PROFILE done"
EOF
