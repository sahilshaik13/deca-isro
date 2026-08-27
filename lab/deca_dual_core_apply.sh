#!/usr/bin/env bash
# Apply dual-P CORE on station3: netns + one GRE each + FRR (zebra/ospfd/ldpd/bgpd).
# Follow-on to lab/deca_dual_core_bootstrap.sh.
#
# STATUS (2026-07-29): EXPERIMENTAL — first live cutover broke VPNv4/LDP because
# netns FRR stacks shared /var/run/frr incorrectly and host FRR was stopped.
# Lab was rolled back to single host CORE (10.1.3.1 + both GRE legs). Do NOT run
# mid-campaign without a maintenance window and a verified rollback plan.
#
# Mapping (intended):
#   core-north 10.1.3.1  ← gre-te-pe2 (PE2) + BGP RR
#   core-south 10.1.3.2  ← gre-te-pe1 (PE1)
#
# Usage:
#   ./lab/deca_dual_core_apply.sh                 # scp+ssh to station3
#   DECA_DUAL_CORE_LOCAL=1 sudo bash ...          # on station3
set -euo pipefail

if [[ "${DECA_DUAL_CORE_LOCAL:-0}" != "1" ]] && [[ "$(hostname -s 2>/dev/null || true)" != "station3" ]]; then
  REMOTE_HOST="${DECA_CORE_HOST:-station3}"
  echo "=== Shipping to ${REMOTE_HOST} ==="
  SCRIPT="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  scp -o BatchMode=yes -o ConnectTimeout=15 "$SCRIPT" "${REMOTE_HOST}:/tmp/deca_dual_core_apply.sh"
  exec ssh -o BatchMode=yes -o ConnectTimeout=15 -T "$REMOTE_HOST" "sudo DECA_DUAL_CORE_LOCAL=1 bash /tmp/deca_dual_core_apply.sh"
fi

echo "=== Dual-core FRR apply on $(hostname) ==="
set -euo pipefail

# ls may return non-zero when only one of two candidate paths exists (pipefail).
ZEBRA=$(ls /usr/lib/frr/zebra /usr/libexec/frr/zebra 2>/dev/null | head -1 || true)
OSPFD=$(ls /usr/lib/frr/ospfd /usr/libexec/frr/ospfd 2>/dev/null | head -1 || true)
LDPD=$(ls /usr/lib/frr/ldpd /usr/libexec/frr/ldpd 2>/dev/null | head -1 || true)
BGPD=$(ls /usr/lib/frr/bgpd /usr/libexec/frr/bgpd 2>/dev/null | head -1 || true)
[[ -n "$ZEBRA" && -n "$OSPFD" && -n "$LDPD" && -n "$BGPD" ]] || {
  echo "FAIL: missing FRR binaries (zebra=$ZEBRA ospfd=$OSPFD ldpd=$LDPD bgpd=$BGPD)"; exit 1
}
echo "binaries: zebra=$ZEBRA ospfd=$OSPFD ldpd=$LDPD bgpd=$BGPD"

sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.mpls.platform_labels=100000 >/dev/null 2>&1 || true

# --- 1) Bootstrap netns + backbone ---
ip netns add core-north 2>/dev/null || true
ip netns add core-south 2>/dev/null || true

if ! ip netns exec core-north ip link show veth-core-n >/dev/null 2>&1; then
  ip link del veth-core-n 2>/dev/null || true
  ip link del veth-core-s 2>/dev/null || true
  ip link add veth-core-n type veth peer name veth-core-s
  ip link set veth-core-n netns core-north
  ip link set veth-core-s netns core-south
fi

ip netns exec core-north bash -c '
  ip link set lo up
  ip addr replace 10.1.3.1/32 dev lo
  ip link set veth-core-n up
  ip addr replace 10.3.0.1/30 dev veth-core-n
'
ip netns exec core-south bash -c '
  ip link set lo up
  ip addr replace 10.1.3.2/32 dev lo
  ip link set veth-core-s up
  ip addr replace 10.3.0.2/30 dev veth-core-s
'

# --- 2) Stop host FRR (CORE role moves into netns) ---
systemctl stop frr 2>/dev/null || true
sleep 2
# Drop host lo RID so it doesn't conflict with core-north
ip addr del 10.1.3.1/32 dev lo 2>/dev/null || true

# --- 3) Move / recreate GRE legs into netns ---
# Delete host GRE if present, recreate inside target netns (outer eth0 stays on host).
recreate_gre() {
  local ns="$1" ifc="$2" local_ip="$3" remote_ip="$4" tun_cidr="$5"
  ip link del "$ifc" 2>/dev/null || true
  ip netns exec "$ns" ip link del "$ifc" 2>/dev/null || true
  # Create on host then move — gre needs host eth0 for outer encap
  ip tunnel add "$ifc" mode gre local "$local_ip" remote "$remote_ip" ttl 64
  ip link set "$ifc" netns "$ns"
  ip netns exec "$ns" bash -c "
    ip addr replace ${tun_cidr} dev ${ifc}
    ip link set ${ifc} up
    ip link set ${ifc} mtu 1400 2>/dev/null || true
  "
}

# gre-te-pe1 (PE1) → core-south ; gre-te-pe2 (PE2) → core-north
recreate_gre core-south gre-te-pe1 192.168.50.30 192.168.50.10 10.50.1.2/30
recreate_gre core-north gre-te-pe2 192.168.50.30 192.168.50.20 10.50.2.2/30

# MPLS input on GRE + inter-core
for ns_ifc in "core-south:gre-te-pe1" "core-south:veth-core-s" "core-north:gre-te-pe2" "core-north:veth-core-n"; do
  ns="${ns_ifc%%:*}"
  ifc="${ns_ifc##*:}"
  ip netns exec "$ns" sysctl -w "net.mpls.conf.${ifc}.input=1" >/dev/null 2>&1 || true
done
ip netns exec core-north sysctl -w net.mpls.platform_labels=100000 >/dev/null 2>&1 || true
ip netns exec core-south sysctl -w net.mpls.platform_labels=100000 >/dev/null 2>&1 || true

# --- 4) Private /var/run/frr per netns so `ip netns exec … vtysh` hits that stack ---
setup_ns_frr_run() {
  local ns="$1"
  mkdir -p "/run/frr-${ns}"
  chown frr:frr "/run/frr-${ns}" 2>/dev/null || chown root:root "/run/frr-${ns}"
  ip netns exec "$ns" bash -c "
    mkdir -p /var/run/frr
    mountpoint -q /var/run/frr 2>/dev/null || mount --bind /run/frr-${ns} /var/run/frr
    chown frr:frr /var/run/frr 2>/dev/null || true
  "
}
setup_ns_frr_run core-north
setup_ns_frr_run core-south

mkdir -p /etc/frr-core-north /etc/frr-core-south /var/log/frr-core-north /var/log/frr-core-south
chown -R frr:frr /var/log/frr-core-north /var/log/frr-core-south 2>/dev/null || true

# --- 5) FRR configs ---
cat >/etc/frr-core-north/zebra.conf <<'Z'
hostname core-north
log file /var/log/frr-core-north/zebra.log
!
interface lo
 ip address 10.1.3.1/32
!
interface gre-te-pe2
 ip address 10.50.2.2/30
 mpls enable
!
interface veth-core-n
 ip address 10.3.0.1/30
 mpls enable
!
ip forwarding
!
Z

cat >/etc/frr-core-north/ospfd.conf <<'O'
hostname core-north
log file /var/log/frr-core-north/ospfd.log
!
interface gre-te-pe2
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 4
!
interface veth-core-n
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 4
!
router ospf
 ospf router-id 10.1.3.1
 passive-interface default
 no passive-interface gre-te-pe2
 no passive-interface veth-core-n
 network 10.1.3.1/32 area 0
 network 10.50.2.0/30 area 0
 network 10.3.0.0/30 area 0
 capability opaque
 mpls-te on
 mpls-te router-address 10.1.3.1
 mpls-te export
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing prefix 10.1.3.1/32 index 3 no-php-flag
exit
!
O

cat >/etc/frr-core-north/ldpd.conf <<'L'
hostname core-north
log file /var/log/frr-core-north/ldpd.log
!
mpls ldp
 router-id 10.1.3.1
 ordered-control
 address-family ipv4
  discovery transport-address 10.1.3.1
  interface gre-te-pe2
  interface veth-core-n
 exit-address-family
exit
!
L

cat >/etc/frr-core-north/bgpd.conf <<'B'
hostname core-north
log file /var/log/frr-core-north/bgpd.log
!
router bgp 65001
 bgp router-id 10.1.3.1
 no bgp ebgp-requires-policy
 neighbor 10.1.1.1 remote-as 65001
 neighbor 10.1.1.1 update-source 10.1.3.1
 neighbor 10.1.2.1 remote-as 65001
 neighbor 10.1.2.1 update-source 10.1.3.1
 !
 address-family ipv4 vpn
  neighbor 10.1.1.1 activate
  neighbor 10.1.1.1 route-reflector-client
  neighbor 10.1.2.1 activate
  neighbor 10.1.2.1 route-reflector-client
 exit-address-family
exit
!
B

cat >/etc/frr-core-south/zebra.conf <<'Z'
hostname core-south
log file /var/log/frr-core-south/zebra.log
!
interface lo
 ip address 10.1.3.2/32
!
interface gre-te-pe1
 ip address 10.50.1.2/30
 mpls enable
!
interface veth-core-s
 ip address 10.3.0.2/30
 mpls enable
!
ip forwarding
!
Z

cat >/etc/frr-core-south/ospfd.conf <<'O'
hostname core-south
log file /var/log/frr-core-south/ospfd.log
!
interface gre-te-pe1
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 4
!
interface veth-core-s
 ip ospf area 0
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 4
!
router ospf
 ospf router-id 10.1.3.2
 passive-interface default
 no passive-interface gre-te-pe1
 no passive-interface veth-core-s
 network 10.1.3.2/32 area 0
 network 10.50.1.0/30 area 0
 network 10.3.0.0/30 area 0
 capability opaque
 mpls-te on
 mpls-te router-address 10.1.3.2
 mpls-te export
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing prefix 10.1.3.2/32 index 4 no-php-flag
exit
!
O

cat >/etc/frr-core-south/ldpd.conf <<'L'
hostname core-south
log file /var/log/frr-core-south/ldpd.log
!
mpls ldp
 router-id 10.1.3.2
 ordered-control
 address-family ipv4
  discovery transport-address 10.1.3.2
  interface gre-te-pe1
  interface veth-core-s
 exit-address-family
exit
!
L

# South: no BGP RR — north keeps 10.1.3.1 RR. Stub bgpd optional omitted.

start_stack() {
  local ns="$1" conf="$2" run="/run/frr-${ns}"
  local zserv="${run}/zserv.api"
  ip netns exec "$ns" pkill zebra 2>/dev/null || true
  ip netns exec "$ns" pkill ospfd 2>/dev/null || true
  ip netns exec "$ns" pkill ldpd 2>/dev/null || true
  ip netns exec "$ns" pkill bgpd 2>/dev/null || true
  sleep 0.5
  ip netns exec "$ns" "$ZEBRA" -d -f "${conf}/zebra.conf" \
    -i "${run}/zebra.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2601
  sleep 1
  ip netns exec "$ns" "$OSPFD" -d -f "${conf}/ospfd.conf" \
    -i "${run}/ospfd.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2604
  sleep 0.5
  ip netns exec "$ns" "$LDPD" -d -f "${conf}/ldpd.conf" \
    -i "${run}/ldpd.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2612
  if [[ -f "${conf}/bgpd.conf" ]]; then
    sleep 0.5
    ip netns exec "$ns" "$BGPD" -d -f "${conf}/bgpd.conf" \
      -i "${run}/bgpd.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2605
  fi
}

start_stack core-north /etc/frr-core-north
start_stack core-south /etc/frr-core-south

# systemd units for reboot persistence
cat >/etc/systemd/system/deca-dual-core.service <<'UNIT'
[Unit]
Description=DECA dual-core CORE-NORTH/SOUTH netns + FRR
After=network-online.target
Wants=network-online.target
Conflicts=frr.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/deca-dual-core-apply-local.sh
ExecStop=/bin/bash -c 'ip netns exec core-north pkill zebra ospfd ldpd bgpd 2>/dev/null; ip netns exec core-south pkill zebra ospfd ldpd 2>/dev/null; true'

[Install]
WantedBy=multi-user.target
UNIT

# Install local launcher (this script body is large; call apply with LOCAL=1 from brain copy later)
# For now write a thin wrapper that re-invokes configs + start_stack from installed helper.
cp -a /etc/frr-core-north /etc/frr-core-north.bak 2>/dev/null || true

cat >/usr/local/bin/deca-dual-core-start.sh <<'START'
#!/bin/bash
set -euo pipefail
# Re-bind run dirs + start daemons (netns/GRE assumed present from oneshot apply or boot hook)
for ns in core-north core-south; do
  mkdir -p "/run/frr-${ns}"
  chown frr:frr "/run/frr-${ns}" 2>/dev/null || true
  ip netns exec "$ns" bash -c "mkdir -p /var/run/frr; mountpoint -q /var/run/frr || mount --bind /run/frr-${ns} /var/run/frr"
done
ZEBRA=$(ls /usr/lib/frr/zebra /usr/libexec/frr/zebra 2>/dev/null | head -1 || true)
OSPFD=$(ls /usr/lib/frr/ospfd /usr/libexec/frr/ospfd 2>/dev/null | head -1 || true)
LDPD=$(ls /usr/lib/frr/ldpd /usr/libexec/frr/ldpd 2>/dev/null | head -1 || true)
BGPD=$(ls /usr/lib/frr/bgpd /usr/libexec/frr/bgpd 2>/dev/null | head -1 || true)
start_one() {
  local ns="$1" conf="$2" run="/run/frr-${ns}" zserv="${run}/zserv.api"
  ip netns exec "$ns" pgrep -x zebra >/dev/null && return 0
  ip netns exec "$ns" "$ZEBRA" -d -f "${conf}/zebra.conf" -i "${run}/zebra.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2601
  sleep 1
  ip netns exec "$ns" "$OSPFD" -d -f "${conf}/ospfd.conf" -i "${run}/ospfd.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2604
  sleep 0.5
  ip netns exec "$ns" "$LDPD" -d -f "${conf}/ldpd.conf" -i "${run}/ldpd.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2612
  if [[ -f "${conf}/bgpd.conf" ]]; then
    sleep 0.5
    ip netns exec "$ns" "$BGPD" -d -f "${conf}/bgpd.conf" -i "${run}/bgpd.pid" -z "$zserv" -A 127.0.0.1 --vty_port 2605
  fi
}
start_one core-north /etc/frr-core-north
start_one core-south /etc/frr-core-south
START
chmod +x /usr/local/bin/deca-dual-core-start.sh

systemctl daemon-reload

echo "--- netns ---"
ip netns list | grep -E 'core-north|core-south' || true
echo "--- LDP north ---"
sleep 5
ip netns exec core-north vtysh -c "show mpls ldp neighbor" 2>&1 || true
echo "--- LDP south ---"
ip netns exec core-south vtysh -c "show mpls ldp neighbor" 2>&1 || true
echo "=== dual-core apply done ==="
