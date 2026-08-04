#!/usr/bin/env bash
# Phase G — Site realism: internal /29 LANs + host netns per CE site,
#            plus MCF Hassan (Regional branch) as second CE on station2.
# Does NOT touch models/fault_classifier/.
set -euo pipefail

echo "=== Phase G: internal site LANs + MCF Hassan ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2; need station3

# ---------------------------------------------------------------------------
# Helper installed on Pis: build br-lan + 2 host netns inside a CE site
# Args: CE_NS SITE_TAG LAN_PREFIX GW_IP WS_IP SRV_IP
# ---------------------------------------------------------------------------
install_site_lan_helper() {
  ssh -T "$1" 'sudo tee /usr/local/bin/deca-site-lan.sh >/dev/null' <<'HELPER'
#!/usr/bin/env bash
# Usage: deca-site-lan.sh <ce-ns> <tag> <lan_cidr> <gw> <ws_ip> <srv_ip>
# Interface names kept <=15 chars (Linux IFNAMSIZ): v{tag}w / vb{tag}w etc.
set +e
CE="$1"; TAG="$2"; LAN="$3"; GW="$4"; WS="$5"; SRV="$6"
PFX="${LAN#*/}"
WS_NS="${TAG}-ws"; SRV_NS="${TAG}-srv"; BR=br-lan
VW="v${TAG}w"; VBW="vb${TAG}w"; VS="v${TAG}s"; VBS="vb${TAG}s"

ip netns list | grep -q "^${CE}" || { echo "missing ce ns $CE"; exit 1; }

ip netns exec "$CE" ip link add "$BR" type bridge 2>/dev/null
ip netns exec "$CE" ip link set "$BR" up
ip netns exec "$CE" ip addr replace "${GW}/${PFX}" dev "$BR"
ip netns exec "$CE" sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1
ip netns exec "$CE" iptables -P FORWARD ACCEPT 2>/dev/null
ip netns exec "$CE" iptables -P INPUT ACCEPT 2>/dev/null
ip netns exec "$CE" iptables -P OUTPUT ACCEPT 2>/dev/null

for HNS in "$WS_NS" "$SRV_NS"; do ip netns del "$HNS" 2>/dev/null; done
ip netns exec "$CE" ip link del "$VBW" 2>/dev/null
ip netns exec "$CE" ip link del "$VBS" 2>/dev/null

ip netns add "$WS_NS"
ip link add "$VW" type veth peer name "$VBW"
ip link set "$VW" netns "$WS_NS"
ip link set "$VBW" netns "$CE"
ip netns exec "$CE" ip link set "$VBW" master "$BR"
ip netns exec "$CE" ip link set "$VBW" up
ip netns exec "$WS_NS" ip addr add "${WS}/${PFX}" dev "$VW"
ip netns exec "$WS_NS" ip link set "$VW" up
ip netns exec "$WS_NS" ip link set lo up
ip netns exec "$WS_NS" ip route replace default via "$GW"
ip netns exec "$WS_NS" iptables -P INPUT ACCEPT
ip netns exec "$WS_NS" iptables -P OUTPUT ACCEPT

ip netns add "$SRV_NS"
ip link add "$VS" type veth peer name "$VBS"
ip link set "$VS" netns "$SRV_NS"
ip link set "$VBS" netns "$CE"
ip netns exec "$CE" ip link set "$VBS" master "$BR"
ip netns exec "$CE" ip link set "$VBS" up
ip netns exec "$SRV_NS" ip addr add "${SRV}/${PFX}" dev "$VS"
ip netns exec "$SRV_NS" ip link set "$VS" up
ip netns exec "$SRV_NS" ip link set lo up
ip netns exec "$SRV_NS" ip route replace default via "$GW"
ip netns exec "$SRV_NS" iptables -P INPUT ACCEPT
ip netns exec "$SRV_NS" iptables -P OUTPUT ACCEPT

echo "OK site-lan $TAG in $CE: gw=$GW ws=$WS srv=$SRV if=$VW/$VS"
HELPER
  ssh -T "$1" 'sudo chmod 0755 /usr/local/bin/deca-site-lan.sh'
}

install_site_lan_helper station1
install_site_lan_helper station2

echo "=== Site LANs on existing CEs ==="
# NRSC: 10.101.1.0/29
ssh -T station1 'sudo /usr/local/bin/deca-site-lan.sh ce-a nrsc 10.101.1.0/29 10.101.1.1 10.101.1.2 10.101.1.3'
# Mauritius: 10.101.3.0/29
ssh -T station1 'sudo /usr/local/bin/deca-site-lan.sh ce-mauritius mau 10.101.3.0/29 10.101.3.1 10.101.3.2 10.101.3.3'
# SAC: 10.101.2.0/29
ssh -T station2 'sudo /usr/local/bin/deca-site-lan.sh ce-b sac 10.101.2.0/29 10.101.2.1 10.101.2.2 10.101.2.3'

# ---------------------------------------------------------------------------
# MCF Hassan — second CE on station2 (Regional branch)
# Attach: 10.10.4.0/30, lo 10.100.4.1/32, LAN 10.101.4.0/29
# ---------------------------------------------------------------------------
echo "=== Creating ce-mcf (MCF Hassan) on station2 ==="
ssh -T station2 'sudo tee /etc/systemd/system/deca-ns-mcf.service >/dev/null' <<'EOF'
[Unit]
Description=Setup CE-MCF Network Namespace (MCF Hassan Regional Branch)
After=systemd-networkd.service network-online.target deca-ns.service
Wants=network-online.target
Before=frr.service strongswan-starter.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/bash -c "ip link del veth-pe-cemcf 2>/dev/null; for i in 1 2 3 4 5; do ip netns del ce-mcf 2>/dev/null; ip netns list | grep -q '^ce-mcf' || break; sleep 0.5; done; true"
ExecStart=/bin/bash -c "ip netns add ce-mcf && ip link add veth-pe-cemcf type veth peer name veth-cemcf-pe && ip link set veth-cemcf-pe netns ce-mcf && ip link set veth-pe-cemcf master vrf-mission && ip addr add 10.10.4.2/30 dev veth-pe-cemcf && ip link set veth-pe-cemcf up && ip netns exec ce-mcf ip addr add 10.10.4.1/30 dev veth-cemcf-pe && ip netns exec ce-mcf ip link set veth-cemcf-pe up && ip netns exec ce-mcf ip link set lo up && ip netns exec ce-mcf ip addr add 10.100.4.1/32 dev lo && ip netns exec ce-mcf ip route add default via 10.10.4.2 && sysctl -w net.ipv4.conf.veth-pe-cemcf.forwarding=1 && ip netns exec ce-mcf iptables -F && ip netns exec ce-mcf iptables -P INPUT ACCEPT && ip netns exec ce-mcf iptables -P OUTPUT ACCEPT && ip netns exec ce-mcf iptables -P FORWARD ACCEPT && ip netns exec ce-mcf sysctl -w net.ipv4.ip_forward=1"
ExecStop=/bin/bash -c "ip netns del ce-mcf 2>/dev/null; ip link del veth-pe-cemcf 2>/dev/null; true"
ExecStartPost=/bin/bash -c "/usr/local/bin/deca-site-lan.sh ce-mcf mcf 10.101.4.0/29 10.101.4.1 10.101.4.2 10.101.4.3 || true"

[Install]
WantedBy=multi-user.target
EOF

ssh -T station2 'sudo systemctl daemon-reload
sudo systemctl enable --now deca-ns-mcf.service
sleep 2
ip netns list
ip -br addr show veth-pe-cemcf
sudo /usr/local/bin/deca-site-lan.sh ce-mcf mcf 10.101.4.0/29 10.101.4.1 10.101.4.2 10.101.4.3'

# ---------------------------------------------------------------------------
# VRF statics + policy rules + IPsec selectors for site LANs + MCF
# ---------------------------------------------------------------------------
echo "=== Local VRF statics + BGP network ads (remote sites via VPNv4, not statics) ==="
ssh -T station1 'sudo bash -s' <<'EOF'
set -euo pipefail
ip link set vrf-mission up
vtysh <<'VTY'
configure terminal
vrf vrf-mission
 ip route 10.101.1.0/29 10.10.1.1
 ip route 10.101.3.0/29 10.10.3.1
exit-vrf
router bgp 65001 vrf vrf-mission
 address-family ipv4 unicast
  network 10.101.1.0/29
  network 10.101.3.0/29
  no redistribute static
 exit-address-family
exit
end
write
VTY
# policy rules into VRF table 100 (incl. local CE lo — required post-decrypt)
for p in 10.100.1.1/32 10.10.1.0/30 10.10.3.0/30 \
         10.101.1.0/29 10.101.2.0/29 10.101.3.0/29 10.101.4.0/29 \
         10.100.4.1/32 10.10.4.0/30; do
  bare=${p%/*}
  ip rule 2>/dev/null | grep -E "to ${bare}" >/dev/null || ip rule add to "$p" lookup 100 priority 980
done
# IPsec: extend left (local PE1) and right (SAC/MCF side)
CONF=/etc/ipsec.conf
cp -a "$CONF" "${CONF}.bak.pre-phase-g" 2>/dev/null || true
# Replace leftsubnet wholesale if Mauritius already present
if grep -q 'leftsubnet=' "$CONF"; then
  sed -i 's|leftsubnet=.*|leftsubnet=10.100.1.1/32,10.10.1.0/30,10.100.3.1/32,10.10.3.0/30,10.101.1.0/29,10.101.3.0/29|' "$CONF"
fi
if grep -q 'rightsubnet=' "$CONF"; then
  sed -i 's|rightsubnet=.*|rightsubnet=10.100.2.1/32,10.10.2.0/30,10.100.4.1/32,10.10.4.0/30,10.101.2.0/29,10.101.4.0/29|' "$CONF"
fi
grep -E 'leftsubnet|rightsubnet' "$CONF"
ipsec down deca-sdwan 2>/dev/null || true
sleep 1
ipsec up deca-sdwan || ipsec reload
sleep 2
ipsec status | head -20
EOF

ssh -T station2 'sudo bash -s' <<'EOF'
set -euo pipefail
ip link set vrf-mission up
vtysh <<'VTY'
configure terminal
vrf vrf-mission
 ip route 10.100.4.1/32 10.10.4.1
 ip route 10.101.2.0/29 10.10.2.1
 ip route 10.101.4.0/29 10.10.4.1
exit-vrf
router bgp 65001 vrf vrf-mission
 address-family ipv4 unicast
  network 10.10.4.0/30
  network 10.100.4.1/32
  network 10.101.2.0/29
  network 10.101.4.0/29
  no redistribute static
 exit-address-family
exit
end
write
VTY
for p in 10.101.1.0/29 10.101.2.0/29 10.101.3.0/29 10.101.4.0/29 10.100.4.1/32 10.10.4.0/30; do
  bare=${p%/*}
  ip rule 2>/dev/null | grep -E "to ${bare}" >/dev/null || ip rule add to "$p" lookup 100 priority 980
done
CONF=/etc/ipsec.conf
cp -a "$CONF" "${CONF}.bak.pre-phase-g" 2>/dev/null || true
if grep -q 'leftsubnet=' "$CONF"; then
  sed -i 's|leftsubnet=.*|leftsubnet=10.100.2.1/32,10.10.2.0/30,10.100.4.1/32,10.10.4.0/30,10.101.2.0/29,10.101.4.0/29|' "$CONF"
fi
if grep -q 'rightsubnet=' "$CONF"; then
  sed -i 's|rightsubnet=.*|rightsubnet=10.100.1.1/32,10.10.1.0/30,10.100.3.1/32,10.10.3.0/30,10.101.1.0/29,10.101.3.0/29|' "$CONF"
fi
grep -E 'leftsubnet|rightsubnet' "$CONF"
ipsec reload || true
ipsec up deca-sdwan 2>/dev/null || true
sleep 2
ipsec status | head -20
EOF

# Force IPsec renegotiate from PE1 after both confs updated
ssh -T station1 'sudo ipsec down deca-sdwan 2>/dev/null; sleep 1; sudo ipsec up deca-sdwan; sleep 2; sudo ipsec status | head -25'

echo "=== Phase G fabric ready — verify next ==="
