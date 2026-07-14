#!/bin/bash
# Fix the two confirmed failures from deca_debug_vpn_prom.sh:
#   A) Prometheus lastError=out of bounds  → wipe TSDB head (clocks are fine; window poisoned)
#   B) VPN ping fail / BGP VPNv4 0 prefixes → restore RT+redistribute + static VRF safety nets
set -euo pipefail

echo "======== A) Prometheus TSDB reset (out of bounds) ========"
echo "Clocks match; Telegraf has no timestamps → classic poisoned head/minValidTime."
echo "Stopping prometheus, clearing /var/lib/prometheus/metrics2, restarting..."

if systemctl is-active --quiet prometheus 2>/dev/null || pgrep -x prometheus >/dev/null; then
  sudo systemctl stop prometheus 2>/dev/null || sudo killall prometheus 2>/dev/null || true
  sleep 1
fi
sudo rm -rf /var/lib/prometheus/metrics2/*
sudo mkdir -p /var/lib/prometheus/metrics2
# Service runs as User=prometheus (NOT nobody) — wrong owner ⇒ panic on queries.active
sudo chown -R prometheus:prometheus /var/lib/prometheus/metrics2
sudo chmod 0755 /var/lib/prometheus/metrics2

# Prefer systemd; fall back to common manual binary if unit fails
if sudo systemctl start prometheus 2>/dev/null; then
  echo "  started via systemd"
elif command -v prometheus >/dev/null && [ -f /etc/prometheus/prometheus.yml ]; then
  echo "  systemd start failed — launching /usr/bin/prometheus in background"
  sudo -u nobody /usr/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/metrics2 \
    >/tmp/prometheus.log 2>&1 &
  sleep 2
else
  echo "  WARN: could not start Prometheus automatically"
fi
sleep 5

if curl -sf --max-time 3 http://localhost:9090/-/ready >/dev/null; then
  echo "  Prometheus ready"
  curl -sf http://localhost:9090/api/v1/targets | python3 -c '
import sys,json
ups=0
for t in json.load(sys.stdin)["data"]["activeTargets"]:
    h=t["health"]; print(" ", t["labels"].get("instance"), h, t.get("lastError","")[:60])
    ups += h=="up"
print(f"  up={ups}")
'
else
  echo "  Prometheus not ready — run:"
  echo "    sudo systemctl start prometheus"
  echo "    # or: sudo systemctl status prometheus ; journalctl -u prometheus -n 30"
  echo "    curl -s localhost:9090/-/ready ; curl -s localhost:9090/api/v1/targets | head"
fi

echo
echo "======== B) VPN / BGP VPNv4 heal ========"
echo "Evidence: vrf-mission only has LOCAL CE routes; VPNv4 PfxRcd=0 ⇒ no path to 10.100.2.1"

# Snapshot AF negotiation
echo "--- before ---"
ssh -T station1 'sudo vtysh -c "show bgp ipv4 vpn summary"' | sed 's/^/  /'

# Ensure route-targets + redistribute connected/static into VRF BGP on both PEs
# Distinct RDs per PE; shared RT 65001:100 (lab convention from campaign scripts)
echo "--- configure station1 VRF BGP advertise ---"
ssh -T station1 "sudo vtysh <<'VTY'
configure terminal
router bgp 65001 vrf vrf-mission
 address-family ipv4 unicast
  redistribute connected
  redistribute static
  rd 65001:1
  route-target import 65001:100
  route-target export 65001:100
 exit-address-family
exit
write memory
VTY"

echo "--- configure station2 VRF BGP advertise ---"
ssh -T station2 "sudo vtysh <<'VTY'
configure terminal
router bgp 65001 vrf vrf-mission
 address-family ipv4 unicast
  redistribute connected
  redistribute static
  rd 65001:2
  route-target import 65001:100
  route-target export 65001:100
 exit-address-family
exit
write memory
VTY"

# CORE often reflects / RR — soft clear everywhere
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo vtysh -c "clear bgp * soft"' 2>/dev/null || true
done
sleep 5

echo "--- after BGP ---"
ssh -T station1 'sudo vtysh -c "show bgp ipv4 vpn summary"; echo; sudo vtysh -c "show bgp ipv4 vpn"; echo; sudo vtysh -c "show ip route vrf vrf-mission"' | sed 's/^/  /'

# Safety net: VRF routes to remote CE via underlay LAN (nexthop-vrf default → eth0 / IPsec)
echo "--- static safety net (vrf-mission via underlay) ---"
ssh -T station1 'sudo vtysh << "VTY"
configure terminal
vrf vrf-mission
 ip route 10.100.2.1/32 192.168.50.20 nexthop-vrf default
 ip route 10.10.2.0/30 192.168.50.20 nexthop-vrf default
exit
write memory
VTY'
ssh -T station2 'sudo vtysh << "VTY"
configure terminal
vrf vrf-mission
 ip route 10.100.1.1/32 192.168.50.10 nexthop-vrf default
 ip route 10.10.1.0/30 192.168.50.10 nexthop-vrf default
exit
write memory
VTY'

# Persist VRF statics (FRR 10.x uses "write", not "write memory")
echo "--- persist FRR config ---"
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo vtysh -c "write"' 2>/dev/null || true
done


echo
echo "======== VPN ping ========"
if ssh -T station1 'sudo ip netns exec ce-a ping -c 4 -W 2 10.100.2.1'; then
  echo "PASS: CE-A → CE-B dataplane"
else
  echo "FAIL: still down — next dig:"
  echo "  ssh station1 'sudo ipsec statusall | head -50'"
  echo "  ssh station1 'sudo tcpdump -ni eth0 -c 20 esp or icmp'"
  echo "  ssh station1 'sudo vtysh -c \"show bgp ipv4 vpn\"'"
fi

echo
echo "======== Re-check Prometheus ========"
sleep 3
curl -sf http://localhost:9090/api/v1/targets 2>/dev/null | python3 -c '
import sys,json
try:
  d=json.load(sys.stdin)
except Exception:
  print("  Prometheus API not up"); raise SystemExit
ups=0
for t in d["data"]["activeTargets"]:
  print(" ", t["labels"].get("instance"), t["health"], t.get("lastError","")[:60]); ups+=t["health"]=="up"
print(f"  up={ups}/3")
' || true

echo "Done. Full diag: bash ~/deca_diagnostic.sh"
