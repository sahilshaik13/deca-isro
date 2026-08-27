#!/usr/bin/env bash
# Phase H — Full application-aware traffic: TT&C (0x88) / Payload (0x80) / Admin BE
# from site-LAN host netns. NO Cisco TRex — iperf3 only (ARM-safe).
# PE HTB uses swanctl copy_dscp=out so outer ESP retains ToS for underlay queues.
# Does NOT touch models/fault_classifier/.
set -euo pipefail

DUR="${1:-30}"
echo "=== Phase H: TT&C / Payload / Admin QoS (iperf3 --tos, no TRex) ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2

echo "=== Listeners on sac-srv ==="
ssh -T station2 'sudo bash -s' <<'EOF'
set +e
pkill -9 -f 'iperf3 -s' 2>/dev/null
sleep 1
ip netns exec sac-srv iperf3 -s -p 5004 -D
ip netns exec sac-srv iperf3 -s -p 5006 -D
ip netns exec sac-srv iperf3 -s -p 5201 -D
sleep 1
ip netns exec sac-srv ss -ltn | grep -E '5004|5006|5201'
EOF

echo "=== Apply PS13 HTB on PE eth0 ==="
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for H in station1 station2; do
  scp -q "$ROOT/lab/deca_htb_qos.sh" "$H:/tmp/deca_htb_qos.sh"
  ssh -T "$H" 'sudo FORCE=1 IF=eth0 bash /tmp/deca_htb_qos.sh'
done

echo "=== CE-uplink 3-class HTB (NRSC ce-a) — pre-IPsec ==="
ssh -T station1 'sudo bash -s' <<'EOF'
set -euo pipefail
ip netns exec ce-a tc qdisc del dev veth-cea-pe root 2>/dev/null || true
ip netns exec ce-a tc qdisc add dev veth-cea-pe root handle 1: htb default 20
ip netns exec ce-a tc class add dev veth-cea-pe parent 1: classid 1:1 htb rate 15mbit ceil 15mbit
ip netns exec ce-a tc class add dev veth-cea-pe parent 1:1 classid 1:10 htb rate 1mbit ceil 15mbit prio 1
ip netns exec ce-a tc class add dev veth-cea-pe parent 1:1 classid 1:15 htb rate 10mbit ceil 12mbit prio 2
ip netns exec ce-a tc class add dev veth-cea-pe parent 1:1 classid 1:20 htb rate 2mbit ceil 6mbit prio 5
ip netns exec ce-a tc qdisc add dev veth-cea-pe parent 1:10 handle 10: sfq perturb 10
ip netns exec ce-a tc qdisc add dev veth-cea-pe parent 1:15 handle 15: red \
  limit 200000 min 140000 max 170000 avpkt 1000 burst 20 probability 0.2 ecn 2>/dev/null \
  || ip netns exec ce-a tc qdisc add dev veth-cea-pe parent 1:15 handle 15: sfq perturb 10
ip netns exec ce-a tc qdisc add dev veth-cea-pe parent 1:20 handle 20: sfq perturb 10
ip netns exec ce-a tc filter add dev veth-cea-pe protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
ip netns exec ce-a tc filter add dev veth-cea-pe protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
ip netns exec ce-a tc class show dev veth-cea-pe | head -10
EOF

echo "=== Baseline: TT&C-only ${DUR}s (tos 136 / 0x88 @ 1M) ==="
ssh -T station1 "sudo ip netns exec nrsc-ws iperf3 -c 10.101.2.3 -p 5004 -u -b 1M -l 160 -t ${DUR} --tos 136 --bind 10.101.1.2" \
  | tee /tmp/deca-h-ttc-baseline.log | tail -12

echo "=== Contended: TT&C + Payload + Admin ${DUR}s ==="
ssh -T station1 'sudo bash -s' <<EOF
set +e
pkill -f 'iperf3 -c' 2>/dev/null
sleep 1
nohup ip netns exec nrsc-ws  iperf3 -c 10.101.2.3 -p 5004 -u -b 1M -l 160 -t ${DUR} --tos 136 --bind 10.101.1.2 >/tmp/deca-h-ttc-load.log 2>&1 &
nohup ip netns exec nrsc-srv iperf3 -c 10.101.2.3 -p 5006 -u -b 50M -l 1200 -t ${DUR} --tos 128 --bind 10.101.1.3 >/tmp/deca-h-payload-load.log 2>&1 &
nohup ip netns exec nrsc-srv iperf3 -c 10.101.2.3 -p 5201 -t ${DUR} -b 20M --bind 10.101.1.3 >/tmp/deca-h-admin-load.log 2>&1 &
sleep 2
ps aux | grep '[i]perf3 -c'
EOF

sleep $((DUR + 3))

echo "=== Results ==="
echo '--- TTC BASELINE ---'; grep -E 'receiver|sender' /tmp/deca-h-ttc-baseline.log | tail -4
ssh -T station1 'echo ---TTC LOAD---; grep -E "receiver|sender|error" /tmp/deca-h-ttc-load.log | tail -4
echo ---PAYLOAD LOAD---; grep -E "receiver|sender|error" /tmp/deca-h-payload-load.log | tail -4
echo ---ADMIN LOAD---; grep -E "SUM|receiver|sender|error" /tmp/deca-h-admin-load.log | tail -8
echo ---HTB ce-a---; sudo ip netns exec ce-a tc -s class show dev veth-cea-pe | grep -E "class htb 1:(10|15|20)" -A3'

echo "=== Phase H measure done ==="
