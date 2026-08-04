#!/usr/bin/env bash
# Phase B — Dual-cost underlay (GRE preferred / eth0 backup) + HTB capacity shaping.
# Not traffic engineering — see lab/deca_expand_phase_te.sh for OSPF-TE + SR-TE (PS13-O1.2).
# Does NOT touch models/fault_classifier/.
set -euo pipefail

echo "=== Phase B: dual-cost underlay + HTB reserved/scavenger ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' 2>/dev/null \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2; need station3

# ---------------------------------------------------------------------------
# 1) Dual-cost underlay: PE1↔CORE↔PE2 veth chain (preferred), eth0 high cost
#    Links: 10.50.1.0/30 (PE1↔CORE), 10.50.2.0/30 (CORE↔PE2)
# ---------------------------------------------------------------------------
echo "=== Creating TE veth path via CORE ==="

ssh -T station1 'sudo bash -s' <<'EOF'
set -euo pipefail
# GRE underlay PE1↔CORE (veth cannot span hosts)
ip tunnel del gre-te-core 2>/dev/null || true
ip tunnel add gre-te-core mode gre remote 192.168.50.30 local 192.168.50.10 ttl 64
ip addr add 10.50.1.1/30 dev gre-te-core
ip link set gre-te-core up
sysctl -w net.ipv4.conf.gre-te-core.forwarding=1
EOF

ssh -T station2 'sudo bash -s' <<'EOF'
set -euo pipefail
ip tunnel del gre-te-core 2>/dev/null || true
ip tunnel add gre-te-core mode gre remote 192.168.50.30 local 192.168.50.20 ttl 64
ip addr add 10.50.2.1/30 dev gre-te-core
ip link set gre-te-core up
sysctl -w net.ipv4.conf.gre-te-core.forwarding=1
EOF

ssh -T station3 'sudo bash -s' <<'EOF'
set -euo pipefail
ip tunnel del gre-te-pe1 2>/dev/null || true
ip tunnel del gre-te-pe2 2>/dev/null || true
ip tunnel add gre-te-pe1 mode gre remote 192.168.50.10 local 192.168.50.30 ttl 64
ip addr add 10.50.1.2/30 dev gre-te-pe1
ip link set gre-te-pe1 up
ip tunnel add gre-te-pe2 mode gre remote 192.168.50.20 local 192.168.50.30 ttl 64
ip addr add 10.50.2.2/30 dev gre-te-pe2
ip link set gre-te-pe2 up
sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv4.conf.gre-te-pe1.forwarding=1
sysctl -w net.ipv4.conf.gre-te-pe2.forwarding=1
# Persist soft: enable forwarding
EOF

# OSPF: low cost on GRE TE path, high cost on eth0
echo "=== OSPF costs: GRE=5 (preferred), eth0=50 (backup) ==="
ssh -T station1 'sudo vtysh << "VTY"
configure terminal
interface gre-te-core
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf cost 5
 no ip ospf passive
exit
interface eth0
 ip ospf cost 50
exit
router ospf
 network 10.50.1.0/30 area 0
exit
end
write memory
VTY'

ssh -T station2 'sudo vtysh << "VTY"
configure terminal
interface gre-te-core
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf cost 5
 no ip ospf passive
exit
interface eth0
 ip ospf cost 50
exit
router ospf
 network 10.50.2.0/30 area 0
exit
end
write memory
VTY'

ssh -T station3 'sudo vtysh << "VTY"
configure terminal
interface gre-te-pe1
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf cost 5
 no ip ospf passive
exit
interface gre-te-pe2
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf cost 5
 no ip ospf passive
exit
interface eth0
 ip ospf cost 50
exit
router ospf
 network 10.50.1.0/30 area 0
 network 10.50.2.0/30 area 0
exit
end
write memory
VTY'

sleep 5
echo "=== Preferred path check (expect via 10.50.x / CORE) ==="
ssh -T station1 'sudo vtysh -c "show ip route ospf" | head -40'
ssh -T station1 'ip route get 10.1.2.1 || true'

# ---------------------------------------------------------------------------
# 2) HTB on PE1 eth0: parent 40Mbit; reserved 20Mbit; scavenger 8Mbit
#    Classify PS13: TT&C (0x88) → 1:10 LLQ; Payload (0x80) → 1:15; else scavenger
# ---------------------------------------------------------------------------
echo "=== HTB PS13 QoS on station1 eth0 ==="
ssh -T station1 'sudo bash -s' <<'EOF'
set -euo pipefail
IF=eth0
tc qdisc del dev $IF root 2>/dev/null || true
tc qdisc add dev $IF root handle 1: htb default 20
tc class add dev $IF parent 1: classid 1:1 htb rate 40mbit ceil 40mbit
tc class add dev $IF parent 1:1 classid 1:10 htb rate 2mbit ceil 40mbit prio 1
tc class add dev $IF parent 1:1 classid 1:15 htb rate 28mbit ceil 34mbit prio 2
tc class add dev $IF parent 1:1 classid 1:20 htb rate 5mbit ceil 24mbit prio 5
tc qdisc add dev $IF parent 1:10 handle 10: sfq perturb 10
tc qdisc add dev $IF parent 1:15 handle 15: red limit 500000 min 350000 max 425000 avpkt 1000 burst 40 probability 0.2 ecn 2>/dev/null \
  || tc qdisc add dev $IF parent 1:15 handle 15: sfq perturb 10
tc qdisc add dev $IF parent 1:20 handle 20: sfq perturb 10
tc filter add dev $IF protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
tc filter add dev $IF protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
tc filter add dev $IF protocol ip parent 1:0 prio 3 u32 match ip tos 0xb8 0xfc flowid 1:10
tc qdisc show dev $IF
tc class show dev $IF
EOF

# Mirror on station2 eth0
ssh -T station2 'sudo bash -s' <<'EOF'
set -euo pipefail
IF=eth0
tc qdisc del dev $IF root 2>/dev/null || true
tc qdisc add dev $IF root handle 1: htb default 20
tc class add dev $IF parent 1: classid 1:1 htb rate 40mbit ceil 40mbit
tc class add dev $IF parent 1:1 classid 1:10 htb rate 2mbit ceil 40mbit prio 1
tc class add dev $IF parent 1:1 classid 1:15 htb rate 28mbit ceil 34mbit prio 2
tc class add dev $IF parent 1:1 classid 1:20 htb rate 5mbit ceil 24mbit prio 5
tc qdisc add dev $IF parent 1:10 handle 10: sfq perturb 10
tc qdisc add dev $IF parent 1:15 handle 15: red limit 500000 min 350000 max 425000 avpkt 1000 burst 40 probability 0.2 ecn 2>/dev/null \
  || tc qdisc add dev $IF parent 1:15 handle 15: sfq perturb 10
tc qdisc add dev $IF parent 1:20 handle 20: sfq perturb 10
tc filter add dev $IF protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
tc filter add dev $IF protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
tc qdisc show dev $IF | head -5
EOF

echo "=== Phase B deploy done — run rate proof next ==="
