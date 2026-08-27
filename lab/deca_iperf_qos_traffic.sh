#!/usr/bin/env bash
# deca_iperf_qos_traffic.sh — ARM-safe multi-class traffic (NO Cisco TRex / DPDK).
#
# PS13 digital QoS signatures via iperf3 --tos:
#   TT&C:    UDP 1M  --tos 0x88 (136)  → :5004
#   Payload: UDP 50M --tos 0x80 (128)  → :5006
#   Admin:   TCP untagged BE           → :5201  (vrf-default / scavenger)
#
# Usage:
#   bash lab/deca_iperf_qos_traffic.sh start [duration_s]
#   bash lab/deca_iperf_qos_traffic.sh stop
#   bash lab/deca_iperf_qos_traffic.sh status
#
# Env overrides:
#   DECA_IPERF_DST=10.101.2.3  DECA_IPERF_SRC_HOST=station1  DECA_IPERF_DST_HOST=station2
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-start}"
DUR="${2:-3600}"
DST="${DECA_IPERF_DST:-10.101.2.3}"
SRC_HOST="${DECA_IPERF_SRC_HOST:-station1}"
DST_HOST="${DECA_IPERF_DST_HOST:-station2}"

# Decimal ToS for iperf3 (accepts int): 0x88=136, 0x80=128
TOS_TTC=136
TOS_PAYLOAD=128

run_ssh() {
  local host="$1"; shift
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$host" "$@"
}

stop_all() {
  echo "[iperf-qos] stopping clients/servers…"
  run_ssh "$SRC_HOST" 'sudo pkill -f "iperf3 -c" 2>/dev/null || true' || true
  run_ssh "$DST_HOST" 'sudo pkill -f "iperf3 -s" 2>/dev/null || true' || true
}

start_servers() {
  run_ssh "$DST_HOST" "sudo bash -s" <<EOF
set +e
pkill -9 -f 'iperf3 -s' 2>/dev/null
sleep 1
# Prefer site-LAN sac-srv; fall back to ce-b
if ip netns list 2>/dev/null | grep -q sac-srv; then
  ip netns exec sac-srv iperf3 -s -p 5004 -D
  ip netns exec sac-srv iperf3 -s -p 5006 -D
  ip netns exec sac-srv iperf3 -s -p 5201 -D
else
  ip netns exec ce-b iperf3 -s -p 5004 -D
  ip netns exec ce-b iperf3 -s -p 5006 -D
  ip netns exec ce-b iperf3 -s -p 5201 -D
fi
ss -ltn 2>/dev/null | grep -E '5004|5006|5201' || true
EOF
}

start_clients() {
  run_ssh "$SRC_HOST" "sudo bash -s" <<EOF
set +e
pkill -f 'iperf3 -c' 2>/dev/null
sleep 1
# TT&C critical command — CS4-class mark 0x88 @ 1 Mbps UDP
nohup ip netns exec nrsc-ws iperf3 -c ${DST} -u -b 1M -l 160 -p 5004 -t ${DUR} --tos ${TOS_TTC} \
  >/tmp/deca-iperf-ttc.log 2>&1 &
# Mission payload — AF41-class mark 0x80 @ 50 Mbps UDP
nohup ip netns exec nrsc-srv iperf3 -c ${DST} -u -b 50M -l 1200 -p 5006 -t ${DUR} --tos ${TOS_PAYLOAD} \
  >/tmp/deca-iperf-payload.log 2>&1 &
# Administrative / default — untagged TCP bulk (scavenger / vrf-admin path intent)
nohup ip netns exec nrsc-srv iperf3 -c ${DST} -b 20M -p 5201 -t ${DUR} \
  >/tmp/deca-iperf-admin.log 2>&1 &
sleep 1
pgrep -af 'iperf3 -c' || true
EOF
}

status() {
  echo "=== $SRC_HOST clients ==="
  run_ssh "$SRC_HOST" 'pgrep -af "iperf3 -c" || echo none' || true
  echo "=== $DST_HOST servers ==="
  run_ssh "$DST_HOST" 'pgrep -af "iperf3 -s" || echo none' || true
}

case "$CMD" in
  start)
    echo "[iperf-qos] PS13 generators (no TRex): TT&C tos=${TOS_TTC}/1M Payload tos=${TOS_PAYLOAD}/50M Admin untagged"
    start_servers
    start_clients
    status
    ;;
  stop) stop_all ;;
  status) status ;;
  *)
    echo "Usage: $0 start|stop|status [duration_s]" >&2
    exit 2
    ;;
esac
