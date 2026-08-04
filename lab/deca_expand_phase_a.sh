#!/usr/bin/env bash
# Phase A — Mauritius distant-branch CE on PE1 + role-shaped baseline traffic.
# Does NOT touch models/fault_classifier/.
# Roles: CORE=Hub, SAC/ce-b=Datacenter, NRSC/ce-a=Branch, Mauritius=Distant branch.
set -euo pipefail

NETEM_DELAY_MS="${NETEM_DELAY_MS:-100}"  # each direction → ~200ms RTT (India↔Mauritius class)
MAU_AS=65013
PE_AS=65001

echo "=== Phase A expansion: ce-mauritius (netem ${NETEM_DELAY_MS}ms/dir) ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' 2>/dev/null \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2; need station3

# ---------------------------------------------------------------------------
# 1) systemd unit: ce-mauritius netns on station1 (sibling to ce-a)
# ---------------------------------------------------------------------------
echo "=== Writing deca-ns-mauritius.service on station1 ==="
ssh -T station1 "sudo tee /etc/systemd/system/deca-ns-mauritius.service > /dev/null" <<'EOF'
[Unit]
Description=Setup CE-Mauritius Network Namespace (Distant Branch)
After=systemd-networkd.service network-online.target deca-ns.service
Wants=network-online.target
Before=frr.service strongswan-starter.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/bash -c "ip link del veth-pe-cem 2>/dev/null; ip link del veth-cem-pe 2>/dev/null; for i in 1 2 3 4 5; do ip netns del ce-mauritius 2>/dev/null; ip netns list | grep -q '^ce-mauritius' || break; sleep 0.5; done; true"
ExecStart=/bin/bash -c "\
  ip netns add ce-mauritius && \
  ip link add veth-pe-cem type veth peer name veth-cem-pe && \
  ip link set veth-cem-pe netns ce-mauritius && \
  ip link set veth-pe-cem master vrf-mission && \
  ip addr add 10.10.3.2/30 dev veth-pe-cem && \
  ip link set veth-pe-cem up && \
  ip netns exec ce-mauritius ip addr add 10.10.3.1/30 dev veth-cem-pe && \
  ip netns exec ce-mauritius ip link set veth-cem-pe up && \
  ip netns exec ce-mauritius ip link set lo up && \
  ip netns exec ce-mauritius ip addr add 10.100.3.1/32 dev lo && \
  ip netns exec ce-mauritius ip route add default via 10.10.3.2 && \
  sysctl -w net.ipv4.conf.veth-pe-cem.forwarding=1 && \
  ip netns exec ce-mauritius iptables -F && \
  ip netns exec ce-mauritius iptables -P INPUT ACCEPT && \
  ip netns exec ce-mauritius iptables -P OUTPUT ACCEPT && \
  ip netns exec ce-mauritius iptables -P FORWARD ACCEPT && \
  tc qdisc replace dev veth-pe-cem root netem delay ${NETEM_DELAY_MS}ms && \
  ip netns exec ce-mauritius tc qdisc replace dev veth-cem-pe root netem delay ${NETEM_DELAY_MS}ms \
"
ExecStop=/bin/bash -c "ip netns del ce-mauritius 2>/dev/null; ip link del veth-pe-cem 2>/dev/null; true"

[Install]
WantedBy=multi-user.target
EOF

# Fix NETEM in unit — heredoc above left literal ${NETEM_DELAY_MS} inside remote file wrongly.
# Rewrite ExecStart with expanded delay:
ssh -T station1 "sudo sed -i 's/\${NETEM_DELAY_MS}/${NETEM_DELAY_MS}/g' /etc/systemd/system/deca-ns-mauritius.service"

ssh -T station1 'sudo systemctl daemon-reload
sudo systemctl enable deca-ns-mauritius.service
sudo systemctl restart deca-ns-mauritius.service
sleep 1
ip netns list | grep ce-mauritius
ip -br addr show veth-pe-cem
sudo ip netns exec ce-mauritius ip -br addr
tc qdisc show dev veth-pe-cem | head -2'

# ---------------------------------------------------------------------------
# 2) VRF statics (lab dataplane pattern) + IPsec selectors
# ---------------------------------------------------------------------------
echo "=== VRF statics for Mauritius /32 ==="
ssh -T station1 'sudo vtysh << "VTY"
configure terminal
vrf vrf-mission
 ip route 10.100.3.1/32 10.10.3.1
exit-vrf
router bgp 65001 vrf vrf-mission
 address-family ipv4 unicast
  network 10.10.3.0/30
  network 10.100.3.1/32
  neighbor 10.10.3.1 remote-as 65013
  neighbor 10.10.3.1 activate
 exit-address-family
exit
end
write memory
VTY'

ssh -T station2 'sudo vtysh << "VTY"
configure terminal
! Mauritius reachability is via BGP VPNv4 from PE1 — do not install cross-PE statics
end
write
VTY'

echo "=== Update IPsec leftsubnet/rightsubnet for Mauritius ==="
ssh -T station1 'sudo cp -a /etc/ipsec.conf /etc/ipsec.conf.bak.pre-mauritius
sudo sed -i "s|leftsubnet=10.100.1.1/32,10.10.1.0/30|leftsubnet=10.100.1.1/32,10.10.1.0/30,10.100.3.1/32,10.10.3.0/30|" /etc/ipsec.conf
grep leftsubnet /etc/ipsec.conf
sudo ipsec reload
sudo ipsec up deca-sdwan 2>/dev/null || sudo ipsec restart
sleep 2
sudo ipsec status | head -20'

ssh -T station2 'sudo cp -a /etc/ipsec.conf /etc/ipsec.conf.bak.pre-mauritius
sudo sed -i "s|rightsubnet=10.100.1.1/32,10.10.1.0/30|rightsubnet=10.100.1.1/32,10.10.1.0/30,10.100.3.1/32,10.10.3.0/30|" /etc/ipsec.conf
grep -E "leftsubnet|rightsubnet" /etc/ipsec.conf
sudo ipsec reload
sudo ipsec up deca-sdwan 2>/dev/null || sudo ipsec restart
sleep 2
sudo ipsec status | head -20'

# ---------------------------------------------------------------------------
# 3) BGP in ce-mauritius netns (real CE↔PE adjacency)
# ---------------------------------------------------------------------------
echo "=== FRR bgpd inside ce-mauritius netns ==="
ssh -T station1 "sudo mkdir -p /etc/frr-mauritius /var/run/frr-mauritius /var/log/frr-mauritius
sudo chown frr:frr /var/run/frr-mauritius /var/log/frr-mauritius 2>/dev/null || sudo chown root:root /var/run/frr-mauritius
sudo tee /etc/frr-mauritius/zebra.conf > /dev/null << 'Z'
hostname ce-mauritius
log file /var/log/frr-mauritius/zebra.log
!
interface veth-cem-pe
 ip address 10.10.3.1/30
!
interface lo
 ip address 10.100.3.1/32
!
ip route 0.0.0.0/0 10.10.3.2
!
Z
sudo tee /etc/frr-mauritius/bgpd.conf > /dev/null << 'B'
hostname ce-mauritius
log file /var/log/frr-mauritius/bgpd.log
!
router bgp ${MAU_AS}
 bgp router-id 10.100.3.1
 no bgp ebgp-requires-policy
 neighbor 10.10.3.2 remote-as ${PE_AS}
 !
 address-family ipv4 unicast
  network 10.100.3.1/32
  neighbor 10.10.3.2 activate
 exit-address-family
exit
!
B"

# Expand AS vars in remote file
ssh -T station1 "sudo sed -i 's/\${MAU_AS}/${MAU_AS}/g; s/\${PE_AS}/${PE_AS}/g' /etc/frr-mauritius/bgpd.conf"

ssh -T station1 'sudo tee /etc/systemd/system/deca-mauritius-bgp.service > /dev/null << "EOF"
[Unit]
Description=FRR BGP for ce-mauritius netns
After=deca-ns-mauritius.service
Requires=deca-ns-mauritius.service

[Service]
Type=forking
ExecStartPre=/bin/bash -c "mkdir -p /var/run/frr-mauritius; chown frr:frr /var/run/frr-mauritius 2>/dev/null || true; pkill -f \"frr-mauritius\" 2>/dev/null; ip netns exec ce-mauritius pkill zebra 2>/dev/null; ip netns exec ce-mauritius pkill bgpd 2>/dev/null; true"
ExecStart=/bin/bash -c "\
  ZEBRA=$(ls /usr/lib/frr/zebra /usr/libexec/frr/zebra 2>/dev/null | head -1); \
  BGPD=$(ls /usr/lib/frr/bgpd /usr/libexec/frr/bgpd 2>/dev/null | head -1); \
  ip netns exec ce-mauritius \$ZEBRA -d \
    -f /etc/frr-mauritius/zebra.conf \
    -i /var/run/frr-mauritius/zebra.pid \
    -z /var/run/frr-mauritius/zserv.api \
    -A 127.0.0.1 --vty_port 2705; \
  sleep 1; \
  ip netns exec ce-mauritius \$BGPD -d \
    -f /etc/frr-mauritius/bgpd.conf \
    -i /var/run/frr-mauritius/bgpd.pid \
    -z /var/run/frr-mauritius/zserv.api \
    -A 127.0.0.1 --vty_port 2706 \
"
ExecStop=/bin/bash -c "ip netns exec ce-mauritius pkill bgpd 2>/dev/null; ip netns exec ce-mauritius pkill zebra 2>/dev/null; true"
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable deca-mauritius-bgp.service
sudo systemctl restart deca-mauritius-bgp.service
sleep 3
sudo systemctl is-active deca-mauritius-bgp.service || sudo journalctl -u deca-mauritius-bgp.service -n 30 --no-pager
sudo vtysh -c "show bgp vrf vrf-mission summary" 2>/dev/null | head -30
sudo vtysh -c "show bgp vrf vrf-mission neighbors 10.10.3.1" 2>/dev/null | head -25'

# ---------------------------------------------------------------------------
# 4) Role-shaped baseline traffic
#    SAC Datacenter (ce-b): sustained bulk iperf server already; start client from PE1 host path
#    NRSC Branch: light only
# ---------------------------------------------------------------------------
echo "=== Role traffic: SAC Datacenter sustained bulk ==="
# Ensure iperf3 server in ce-b
ssh -T station2 'sudo ip netns exec ce-b pgrep iperf3 >/dev/null || sudo ip netns exec ce-b iperf3 -s -D
pgrep -af iperf3 | head -3'

# Long-running bulk from station1 default VRF toward SAC via VPN is complex;
# use ce-a light ping + from station2 host generate outbound to create throughput asymmetry.
# Datacenter generates high TX: iperf3 client FROM ce-b toward a listener on ce-a (reverse bulk).
ssh -T station1 'sudo ip netns exec ce-a pkill iperf3 2>/dev/null; sudo ip netns exec ce-a iperf3 -s -D; sleep 1'
ssh -T station2 'sudo pkill -f "iperf3 -c 10.100.1.1" 2>/dev/null || true
# 30+ min bulk; bandwidth capped high but not destroying SSH
nohup sudo ip netns exec ce-b iperf3 -c 10.100.1.1 -t 3600 -b 40M -P 2 >/tmp/deca-sac-bulk.log 2>&1 &
echo "sac_bulk_pid=$!"
sleep 2
tail -5 /tmp/deca-sac-bulk.log || true'

echo "=== Phase A deploy steps done — run verify next ==="
