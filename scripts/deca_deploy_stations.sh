#!/bin/bash
# DECA plug-and-play deploy — end-to-end lab restore that matches a green check_stations / deca_diagnostic.
#
# Proven stack (2026-07-14):
#   - clean deca-ns.service (one ExecStartPre) + Before=frr,strongswan
#   - FRR/strongSwan Requires=deca-ns
#   - deca-watchdog: reset-failed every boot + heal FRR/IPsec/Telegraf + VRF static safety-net
#   - VRF routes: remote CE via underlay nexthop-vrf default (fixes VPN when VPNv4 PfxRcd=0)
#   - laptop Prometheus: TSDB dir must be owned by prometheus:prometheus (not nobody)
#
# Run from laptop on lab LAN (USB eth 192.168.50.1):
#   bash ~/deca-deploy.sh
#   # or: bash ~/deca-isro/scripts/deca_deploy_stations.sh
set -euo pipefail

echo "=== DECA plug-and-play deploy ==="

need_host() {
  local h=$1
  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$h" 'true' 2>/dev/null; then
    echo "FAIL: cannot SSH to $h (USB lab NIC up? 192.168.50.0/24?)"
    exit 1
  fi
}

for H in station1 station2 station3; do
  need_host "$H"
done

# ---------------------------------------------------------------------------
# Station 1 — CE-A namespace
# ---------------------------------------------------------------------------
echo "=== Writing station1 deca-ns.service ==="
ssh -T station1 'sudo tee /etc/systemd/system/deca-ns.service > /dev/null << "EOF"
[Unit]
Description=Setup CE-A Network Namespace
After=systemd-networkd.service network-online.target
Wants=network-online.target
Before=frr.service strongswan-starter.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=2
ExecStartPre=/bin/bash -c "ip link del veth-pe-cea 2>/dev/null; ip link del veth-pe-ce1 2>/dev/null; ip netns del ce-1 2>/dev/null; for i in 1 2 3 4 5; do ip netns del ce-a 2>/dev/null; ip netns list | grep -q \"^ce-a\" || break; sleep 0.5; done; true"
ExecStart=/bin/bash -c "ip netns add ce-a && ip link add veth-pe-cea type veth peer name veth-cea-pe && ip link set veth-cea-pe netns ce-a && ip link set veth-pe-cea master vrf-mission && ip addr add 10.10.1.2/30 dev veth-pe-cea && ip link set veth-pe-cea up && ip netns exec ce-a ip addr add 10.10.1.1/30 dev veth-cea-pe && ip netns exec ce-a ip link set veth-cea-pe up && ip netns exec ce-a ip link set lo up && ip netns exec ce-a ip addr add 10.100.1.1/32 dev lo && ip netns exec ce-a ip route add default via 10.10.1.2 && ip rule add from 10.100.2.1/32 iif eth0 lookup 100 && sysctl -w net.ipv4.conf.veth-pe-cea.forwarding=1 && ip netns exec ce-a iptables -F && ip netns exec ce-a iptables -P INPUT ACCEPT && ip netns exec ce-a iptables -P OUTPUT ACCEPT && ip netns exec ce-a iptables -P FORWARD ACCEPT"
ExecStop=/bin/bash -c "ip netns del ce-a 2>/dev/null; ip link del veth-pe-cea 2>/dev/null; true"

[Install]
WantedBy=multi-user.target
EOF'

# ---------------------------------------------------------------------------
# Station 2 — CE-B namespace (+ iperf3 -s)
# ---------------------------------------------------------------------------
echo "=== Writing station2 deca-ns.service ==="
ssh -T station2 'sudo tee /etc/systemd/system/deca-ns.service > /dev/null << "EOF"
[Unit]
Description=Setup CE-B Network Namespace
After=systemd-networkd.service network-online.target
Wants=network-online.target
Before=frr.service strongswan-starter.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=2
ExecStartPre=/bin/bash -c "ip link del veth-pe-ceb 2>/dev/null; ip link del veth-pe-ce2 2>/dev/null; ip netns del ce-2 2>/dev/null; for i in 1 2 3 4 5; do ip netns del ce-b 2>/dev/null; ip netns list | grep -q \"^ce-b\" || break; sleep 0.5; done; true"
ExecStart=/bin/bash -c "ip netns add ce-b && ip link add veth-pe-ceb type veth peer name veth-ceb-pe && ip link set veth-ceb-pe netns ce-b && ip link set veth-pe-ceb master vrf-mission && ip addr add 10.10.2.2/30 dev veth-pe-ceb && ip link set veth-pe-ceb up && ip netns exec ce-b ip addr add 10.10.2.1/30 dev veth-ceb-pe && ip netns exec ce-b ip link set veth-ceb-pe up && ip netns exec ce-b ip link set lo up && ip netns exec ce-b ip addr add 10.100.2.1/32 dev lo && ip netns exec ce-b ip route add default via 10.10.2.2 && ip rule add to 10.100.2.1/32 lookup 100 && ip rule add to 10.10.2.0/30 lookup 100 && ip netns exec ce-b sysctl -w net.ipv4.conf.veth-ceb-pe.forwarding=1 && ip netns exec ce-b iptables -F && ip netns exec ce-b iptables -P INPUT ACCEPT && ip netns exec ce-b iptables -P FORWARD ACCEPT && ip netns exec ce-b iperf3 -s -D"
ExecStop=/bin/bash -c "ip netns del ce-b 2>/dev/null; ip link del veth-pe-ceb 2>/dev/null; true"

[Install]
WantedBy=multi-user.target
EOF'

# ---------------------------------------------------------------------------
# Ordering drop-ins
# ---------------------------------------------------------------------------
echo "=== FRR / strongSwan Requires=deca-ns ==="
for H in station1 station2; do
  ssh -T "$H" 'sudo mkdir -p /etc/systemd/system/frr.service.d
sudo tee /etc/systemd/system/frr.service.d/override.conf > /dev/null << "EOF"
[Unit]
After=deca-ns.service
Requires=deca-ns.service
EOF
sudo mkdir -p /etc/systemd/system/strongswan-starter.service.d
sudo tee /etc/systemd/system/strongswan-starter.service.d/override.conf > /dev/null << "EOF"
[Unit]
After=deca-ns.service
Requires=deca-ns.service
EOF'
done

# ---------------------------------------------------------------------------
# Watchdog — reset-failed + service heal + VRF CE static safety-net every boot
# ---------------------------------------------------------------------------
echo "=== Writing deca-watchdog.service (all stations) ==="

# PE stations: include VRF static restore (VPN works even when BGP VPNv4 stays NoNeg/0 pfx)
for H in station1 station2; do
  ssh -T "$H" "sudo tee /usr/local/sbin/deca-watchdog.sh > /dev/null" <<'EOF'
#!/bin/bash
set -e
systemctl reset-failed
systemctl is-active --quiet deca-ns.service 2>/dev/null || systemctl restart deca-ns.service 2>/dev/null || true
sleep 2
systemctl is-active --quiet frr || systemctl restart frr
systemctl is-active --quiet strongswan-starter 2>/dev/null || systemctl restart strongswan-starter 2>/dev/null || true
systemctl is-active --quiet telegraf || systemctl restart telegraf
IP=$(ip -4 -br addr show eth0 2>/dev/null | awk '{print $3}' | cut -d/ -f1)
case "$IP" in
  192.168.50.10)
    vtysh -c "configure terminal" -c "vrf vrf-mission" \
      -c "ip route 10.100.2.1/32 192.168.50.20 nexthop-vrf default" \
      -c "ip route 10.10.2.0/30 192.168.50.20 nexthop-vrf default" \
      -c "exit" -c "exit" -c "write" >/dev/null 2>&1 || true
    ;;
  192.168.50.20)
    vtysh -c "configure terminal" -c "vrf vrf-mission" \
      -c "ip route 10.100.1.1/32 192.168.50.10 nexthop-vrf default" \
      -c "ip route 10.10.1.0/30 192.168.50.10 nexthop-vrf default" \
      -c "exit" -c "exit" -c "write" >/dev/null 2>&1 || true
    ;;
esac
EOF
  ssh -T "$H" 'sudo chmod +x /usr/local/sbin/deca-watchdog.sh
sudo tee /etc/systemd/system/deca-watchdog.service > /dev/null << "EOF"
[Unit]
Description=DECA Post-Boot Self-Healing Watchdog
After=frr.service network-online.target deca-ns.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 60
ExecStart=/usr/local/sbin/deca-watchdog.sh

[Install]
WantedBy=multi-user.target
EOF'
done

ssh -T station3 'sudo tee /usr/local/sbin/deca-watchdog.sh > /dev/null << "EOF"
#!/bin/bash
set -e
systemctl reset-failed
systemctl is-active --quiet frr || systemctl restart frr
systemctl is-active --quiet telegraf || systemctl restart telegraf
EOF
sudo chmod +x /usr/local/sbin/deca-watchdog.sh
sudo tee /etc/systemd/system/deca-watchdog.service > /dev/null << "EOF"
[Unit]
Description=DECA Post-Boot Self-Healing Watchdog
After=frr.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 60
ExecStart=/usr/local/sbin/deca-watchdog.sh

[Install]
WantedBy=multi-user.target
EOF'

# ---------------------------------------------------------------------------
# Hostnames (Telegraf host= label)
# ---------------------------------------------------------------------------
echo "=== Hostname fix (station2 historically stuck as ubuntu) ==="
ssh -T station1 'sudo hostnamectl set-hostname station1'
ssh -T station2 'sudo hostnamectl set-hostname station2'
ssh -T station3 'sudo hostnamectl set-hostname station3'
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo systemctl restart telegraf' || true
done

# ---------------------------------------------------------------------------
# daemon-reload + ExecStartPre sanity
# ---------------------------------------------------------------------------
echo "=== daemon-reload + ExecStartPre count ==="
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo systemctl daemon-reload'
done
for H in station1 station2; do
  COUNT=$(ssh -T "$H" 'grep -c ExecStartPre /etc/systemd/system/deca-ns.service')
  echo "  $H ExecStartPre=$COUNT"
  [ "$COUNT" = "1" ] || { echo "FAIL: expected 1 ExecStartPre"; exit 1; }
done

# ---------------------------------------------------------------------------
# Enable
# ---------------------------------------------------------------------------
echo "=== Enable units ==="
ssh -T station1 'sudo systemctl enable frr strongswan-starter chrony telegraf deca-ns.service deca-watchdog.service'
ssh -T station2 'sudo systemctl enable frr strongswan-starter chrony telegraf deca-ns.service deca-watchdog.service'
ssh -T station3 'sudo systemctl enable frr chrony telegraf deca-watchdog.service'

# ---------------------------------------------------------------------------
# Live bring-up
# ---------------------------------------------------------------------------
echo "=== reset-failed + restart chain ==="
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo systemctl reset-failed'
done

ssh -T station1 'sudo systemctl restart deca-ns.service'
sleep 3
ssh -T station1 'sudo systemctl restart frr strongswan-starter'

ssh -T station2 'sudo systemctl restart deca-ns.service'
sleep 3
ssh -T station2 'sudo systemctl restart frr strongswan-starter'
sleep 5

# VRF CE static safety-net (same as watchdog) — do it now so VPN works without waiting 60s
echo "=== VRF underlay safety-net + FRR write ==="
ssh -T station1 'sudo vtysh -c "configure terminal" -c "vrf vrf-mission" \
  -c "ip route 10.100.2.1/32 192.168.50.20 nexthop-vrf default" \
  -c "ip route 10.10.2.0/30 192.168.50.20 nexthop-vrf default" \
  -c "exit" -c "exit" -c "write"'
ssh -T station2 'sudo vtysh -c "configure terminal" -c "vrf vrf-mission" \
  -c "ip route 10.100.1.1/32 192.168.50.10 nexthop-vrf default" \
  -c "ip route 10.10.1.0/30 192.168.50.10 nexthop-vrf default" \
  -c "exit" -c "exit" -c "write"'

echo "=== IPsec (expect 1 ESTABLISHED) ==="
ssh -T station1 'sudo ipsec status' | sed 's/^/  /'

echo "=== VPN ping CE-A → 10.100.2.1 ==="
if ssh -T station1 'sudo ip netns exec ce-a ping -c 3 -W 2 10.100.2.1' | tee /tmp/deca-vpn-ping.txt | grep -q 'bytes from'; then
  echo "PASS: VPN dataplane"
else
  echo "FAIL: VPN ping — inspect ipsec / vrf routes"
  exit 1
fi

# ---------------------------------------------------------------------------
# Laptop Prometheus — ownership must be prometheus:prometheus after any wipe
# ---------------------------------------------------------------------------
echo "=== Laptop Prometheus health ==="
if [ -d /var/lib/prometheus/metrics2 ]; then
  if ! curl -sf --max-time 2 http://localhost:9090/-/ready >/dev/null 2>&1; then
    echo "  Prometheus down — fixing metrics2 ownership and starting"
    sudo chown -R prometheus:prometheus /var/lib/prometheus/metrics2 || true
    sudo chmod 0755 /var/lib/prometheus/metrics2 || true
    sudo systemctl reset-failed prometheus 2>/dev/null || true
    sudo systemctl start prometheus 2>/dev/null || true
    sleep 3
  fi
fi
if curl -sf --max-time 3 http://localhost:9090/-/ready >/dev/null; then
  echo "  Prometheus ready"
  UP=$(curl -sf http://localhost:9090/api/v1/targets | python3 -c 'import sys,json; print(sum(1 for t in json.load(sys.stdin)["data"]["activeTargets"] if t["health"]=="up"))')
  echo "  scrape targets up: $UP"
else
  echo "  WARN: Prometheus still not on :9090 — fix later with:"
  echo "    sudo chown -R prometheus:prometheus /var/lib/prometheus/metrics2"
  echo "    sudo systemctl reset-failed prometheus && sudo systemctl start prometheus"
fi

# ---------------------------------------------------------------------------
# Parity checks
# ---------------------------------------------------------------------------
echo "=== Drop-in / watchdog hash parity ==="
H1=$(ssh -T station1 'sudo md5sum /etc/systemd/system/frr.service.d/override.conf' | awk '{print $1}')
H2=$(ssh -T station2 'sudo md5sum /etc/systemd/system/frr.service.d/override.conf' | awk '{print $1}')
S1=$(ssh -T station1 'sudo md5sum /etc/systemd/system/strongswan-starter.service.d/override.conf' | awk '{print $1}')
S2=$(ssh -T station2 'sudo md5sum /etc/systemd/system/strongswan-starter.service.d/override.conf' | awk '{print $1}')
[ "$H1" = "$H2" ] && echo "PASS: frr override" || { echo "FAIL: frr override"; exit 1; }
[ "$S1" = "$S2" ] && echo "PASS: strongswan override" || { echo "FAIL: strongswan override"; exit 1; }

echo
echo "=== Deploy complete ==="
echo "Verify:  bash ~/deca_diagnostic.sh"
echo "Cold boot: power-cycle Pis, wait 120s (watchdog sleeps 60s), re-run diagnostic."
