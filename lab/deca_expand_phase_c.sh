#!/usr/bin/env bash
# Phase C — Application-aware QoS: NRSC Branch latency classes (EF/AF41) vs
# SAC Datacenter bulk BE, with PE HTB so Branch keeps low latency under saturation.
# Does NOT touch models/fault_classifier/.
set -euo pipefail

echo "=== Phase C: DSCP QoS Branch vs Datacenter bulk ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2

# HTB on both PE eth0: EF/AF41 → reserved; default → scavenger (tighten scavenger ceil)
for H in station1 station2; do
  ssh -T "$H" 'sudo bash -s' <<'EOF'
set -euo pipefail
IF=eth0
tc qdisc del dev $IF root 2>/dev/null || true
tc qdisc add dev $IF root handle 1: htb default 20
tc class add dev $IF parent 1: classid 1:1 htb rate 40mbit ceil 40mbit
tc class add dev $IF parent 1:1 classid 1:10 htb rate 15mbit ceil 40mbit prio 1
tc class add dev $IF parent 1:1 classid 1:20 htb rate 5mbit ceil 25mbit prio 5
tc qdisc add dev $IF parent 1:10 handle 10: sfq perturb 10
tc qdisc add dev $IF parent 1:20 handle 20: sfq perturb 10
tc filter add dev $IF protocol ip parent 1:0 prio 1 u32 match ip tos 0xb8 0xfc flowid 1:10
tc filter add dev $IF protocol ip parent 1:0 prio 2 u32 match ip tos 0x88 0xfc flowid 1:10
# UDP voice-like ports + interactive TCP demo ports
tc filter add dev $IF protocol ip parent 1:0 prio 3 u32 match ip dport 5004 0xffff flowid 1:10
tc filter add dev $IF protocol ip parent 1:0 prio 4 u32 match ip dport 5202 0xffff flowid 1:10
EOF
done

echo "=== Traffic generators ==="
# Listeners on SAC (ce-b): UDP 5004 (voice-like), TCP 5202 (interactive)
ssh -T station2 'sudo bash -s' <<'EOF'
set +e
ip netns exec ce-b bash -c 'fuser -k 5004/udp 2>/dev/null; fuser -k 5202/tcp 2>/dev/null; true'
sleep 1
# UDP sink
ip netns exec ce-b bash -c 'nohup iperf3 -s -p 5004 -D'
# TCP interactive sink  
ip netns exec ce-b bash -c 'fuser -k 5202/tcp 2>/dev/null; iperf3 -s -p 5202 -D'
# Ensure main iperf3 server still up for bulk
pgrep -x iperf3 >/dev/null || ip netns exec ce-b iperf3 -s -D
ss -ltnu | grep -E '5004|5202|5201' || ip netns exec ce-b ss -ltnu | grep -E '5004|5202|5201'
EOF

# From NRSC: EF UDP small packets + AF41 TCP interactive
# From SAC: bulk BE saturating
ssh -T station1 'sudo bash -s' <<'EOF'
set +e
for p in $(pgrep -f 'iperf3 -c 10.100.2.1'); do kill $p 2>/dev/null; done
sleep 1
# Voice-like: small UDP, DSCP EF (tos 184), modest rate
nohup ip netns exec ce-a iperf3 -c 10.100.2.1 -p 5004 -u -b 2M -l 160 -t 45 --tos 184 --bind 10.100.1.1 \
  >/tmp/deca-qos-ef.log 2>&1 &
# Interactive TCP AF41 (tos 136 = 0x88)
nohup ip netns exec ce-a iperf3 -c 10.100.2.1 -p 5202 -t 45 -b 5M --tos 136 --bind 10.100.1.1 \
  >/tmp/deca-qos-af41.log 2>&1 &
sleep 2
pgrep -af 'iperf3 -c' | head -10
EOF

ssh -T station2 'sudo bash -s' <<'EOF'
set +e
for p in $(pgrep -f 'iperf3 -c 10.100.1.1'); do kill $p 2>/dev/null; done
sleep 1
# Bulk BE from Datacenter (no DSCP) — saturate
nohup ip netns exec ce-b iperf3 -c 10.100.1.1 -t 45 -b 0 -P 3 --bind 10.100.2.1 \
  >/tmp/deca-qos-bulk.log 2>&1 &
sleep 2
pgrep -af 'iperf3 -c' | head -5
EOF

echo "=== Measure Branch latency under SAC saturation ==="
# Parallel: ping from NRSC while load runs (domestic path)
ssh -T station1 'sudo bash -s' <<'EOF'
set +e
# EF-path latency proxy: ping with QoS not available in ping easily; use plain ping + iperf jitter
ip netns exec ce-a ping -c 20 -W 1 -i 0.2 10.100.2.1 | tee /tmp/deca-qos-ping.log | tail -5
EOF

sleep 25
echo "=== Results ==="
ssh -T station1 'echo ---EF---; tail -20 /tmp/deca-qos-ef.log; echo ---AF41---; tail -20 /tmp/deca-qos-af41.log; echo ---PING---; tail -8 /tmp/deca-qos-ping.log'
ssh -T station2 'echo ---BULK---; tail -25 /tmp/deca-qos-bulk.log'
ssh -T station1 'echo ---HTB pe1---; sudo tc -s class show dev eth0 | grep -A5 "class htb 1:1"'
ssh -T station2 'echo ---HTB pe2---; sudo tc -s class show dev eth0 | grep -A5 "class htb 1:1"'

echo "=== Phase C deploy + measure done ==="
