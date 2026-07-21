#!/bin/bash
# DECA plug-and-play deploy — clean CE namespaces + ordering + post-boot watchdog.
# Run from the laptop on the lab LAN (USB eth 192.168.50.1).
# Fixes: stale systemd failed-state blocking strongSwan; corrupted dual ExecStartPre;
#        missing Before=strongswan; no boot-time reset-failed heal.
set -euo pipefail

echo "=== DECA plug-and-play deploy (clean rewrite) ==="

need_host() {
  local h=$1
  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$h" 'true' 2>/dev/null; then
    echo "FAIL: cannot SSH to $h (is USB lab NIC up? 192.168.50.0/24?)"
    exit 1
  fi
}

for H in station1 station2 station3; do
  need_host "$H"
done

# ---------------------------------------------------------------------------
# Station 1 — CE-A namespace (full clean rewrite, never sed-patch)
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
# Station 2 — CE-B namespace (+ iperf3 -s -D)
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
# Ordering drop-ins: FRR + strongSwan require namespaces
# ---------------------------------------------------------------------------
echo "=== Writing FRR / strongSwan Requires=deca-ns drop-ins ==="
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
# Watchdog: clear stale failed-state every boot, then heal FRR/IPsec/Telegraf
# ---------------------------------------------------------------------------
echo "=== Writing deca-watchdog.service on all stations ==="
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo tee /etc/systemd/system/deca-watchdog.service > /dev/null << "EOF"
[Unit]
Description=DECA Post-Boot Self-Healing Watchdog
After=frr.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 60
ExecStart=/bin/bash -c "systemctl reset-failed; systemctl is-active --quiet deca-ns.service 2>/dev/null || systemctl restart deca-ns.service 2>/dev/null; sleep 2; systemctl is-active --quiet frr || systemctl restart frr; systemctl is-active --quiet strongswan-starter 2>/dev/null || systemctl restart strongswan-starter 2>/dev/null; systemctl is-active --quiet telegraf || systemctl restart telegraf"

[Install]
WantedBy=multi-user.target
EOF'
done

# ---------------------------------------------------------------------------
# daemon-reload + verify exactly one ExecStartPre on PE stations
# ---------------------------------------------------------------------------
echo "=== daemon-reload + ExecStartPre sanity ==="
for H in station1 station2; do
  COUNT=$(ssh -T "$H" 'sudo systemctl daemon-reload; grep -c ExecStartPre /etc/systemd/system/deca-ns.service')
  echo "  $H ExecStartPre count = $COUNT"
  if [ "$COUNT" != "1" ]; then
    echo "FAIL: $H deca-ns.service must have exactly 1 ExecStartPre (got $COUNT)"
    ssh -T "$H" 'cat /etc/systemd/system/deca-ns.service'
    exit 1
  fi
done
ssh -T station3 'sudo systemctl daemon-reload'

# ---------------------------------------------------------------------------
# Tier 5 — vrf_route_count exporter + Telegraf inputs.exec (station1/station2)
# docs/TIER5_VRF_ROUTE_COUNT.md — FRR ADMIN route count, orthogonal to traffic
# features so a PE1 tunnel/congestion fault can't drown a PE2 VRF leak.
# ---------------------------------------------------------------------------
echo "=== Writing deca-vrf-route-count exporter + Telegraf fragment (station1/2) ==="
for H in station1 station2; do
  ssh -T "$H" 'sudo tee /etc/sudoers.d/90-telegraf-vtysh > /dev/null << "EOF"
_telegraf ALL=(root) NOPASSWD: /usr/bin/vtysh -c show ip route vrf vrf-admin summary, /usr/bin/vtysh -c show ip route vrf vrf-mission summary
EOF
sudo chmod 0440 /etc/sudoers.d/90-telegraf-vtysh
sudo visudo -cf /etc/sudoers.d/90-telegraf-vtysh'
  ssh -T "$H" 'sudo tee /usr/local/bin/deca-vrf-route-count.sh > /dev/null << "EOF"
#!/usr/bin/env bash
# FRR per-VRF route counts for Telegraf inputs.exec (Influx line protocol).
set -euo pipefail

count_routes() {
  local vrf="$1"
  # BGP table, not RIB/FIB -- imported VPNv4 prefixes never resolve nexthops
  # across the VRF boundary in this lab topology, so they never install into
  # the RIB even when the leak is live (verified 2026-07-20). The BGP table
  # reacts immediately and is the real fault fingerprint.
  sudo vtysh -c "show bgp vrf ${vrf} ipv4 unicast" 2>/dev/null \
    | awk "/^Displayed/ { print \$2; exit } /^No BGP prefixes/ { print 0; exit }"
}

emit() {
  local vrf="$1" val
  val="$(count_routes "${vrf}")"
  val="${val:-0}"
  printf "vrf_route_count,vrf=%s value=%s\n" "${vrf}" "${val}"
}

emit vrf-admin
emit vrf-mission
EOF
sudo chmod 0755 /usr/local/bin/deca-vrf-route-count.sh
sudo mkdir -p /etc/telegraf/telegraf.d
sudo tee /etc/telegraf/telegraf.d/deca-vrf-route-count.conf > /dev/null << "EOF"
[[inputs.exec]]
  commands = ["/usr/local/bin/deca-vrf-route-count.sh"]
  timeout = "4s"
  interval = "5s"
  data_format = "influx"
  name_override = "vrf_route_count"
EOF
sudo systemctl restart telegraf'
done

echo "=== Verifying vrf_route_count_value on Telegraf :9273 (station1/2) ==="
# Telegraf suffixes the exec field name ("value") onto name_override, so the
# real Prometheus series is vrf_route_count_value, not vrf_route_count.
for H in station1 station2; do
  if ssh -T "$H" 'curl -s localhost:9273/metrics' | grep -q '^vrf_route_count_value'; then
    echo "PASS: $H exposing vrf_route_count_value"
  else
    echo "WARN: $H missing vrf_route_count_value on :9273 — check vtysh perms (sudoers user must match \`systemctl show telegraf -p User\`) / telegraf logs"
  fi
done

# ---------------------------------------------------------------------------
# Tier 5b — bgp_flap_count exporter + Telegraf inputs.exec (station1 only)
# docs/DECA_ROI_TIERS.md Tier 5 — diagnosed 2026-07-21: bgp_route_flap's only
# prior signal was a fabricated stamp_bgp_update_pulse() scalar with no live
# scrape (anomaly gate p(anom)=0.52 vs 0.74-0.86 for every other fault).
# `clear bgp <nbr> soft` (the injector's actual command) is a route-refresh,
# not a session reset, so connectionsDropped never moves; routeRefreshSent/
# Recv from `show bgp neighbor 10.1.3.1 json` does (verified live). Separate
# sudoers drop-in (91-, not 90-) so re-running the Tier 5 block above can't
# clobber this rule via its own overwriting `tee`.
# ---------------------------------------------------------------------------
echo "=== Writing deca-bgp-flap-count exporter + Telegraf fragment (station1) ==="
ssh -T station1 'sudo tee /etc/sudoers.d/91-telegraf-bgp-flap > /dev/null << "EOF"
_telegraf ALL=(root) NOPASSWD: /usr/bin/vtysh -c show bgp neighbor 10.1.3.1 json
EOF
sudo chmod 0440 /etc/sudoers.d/91-telegraf-bgp-flap
sudo visudo -cf /etc/sudoers.d/91-telegraf-bgp-flap'
ssh -T station1 'sudo tee /usr/local/bin/deca-bgp-flap-count.sh > /dev/null << "EOF"
#!/usr/bin/env bash
# Live FRR BGP route-refresh churn counter for Telegraf inputs.exec (Influx line protocol).
set -euo pipefail

NEIGHBOR="${1:-10.1.3.1}"

count_refresh() {
  local neighbor="$1"
  # clear bgp soft is a route-refresh, not a session reset -- connectionsDropped
  # never moves (verified 2026-07-21), routeRefreshSent/Recv does. No jq on the
  # Pis; parse with python3 (present).
  sudo vtysh -c "show bgp neighbor ${neighbor} json" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(0)
    sys.exit(0)
n = d.get(sys.argv[1], {})
ms = n.get(\"messageStats\", {})
print(int(ms.get(\"routeRefreshSent\", 0)) + int(ms.get(\"routeRefreshRecv\", 0)))
" "${neighbor}"
}

emit() {
  local neighbor="$1" val
  val="$(count_refresh "${neighbor}")"
  val="${val:-0}"
  printf "bgp_flap_count,neighbor=%s value=%s\n" "${neighbor}" "${val}"
}

emit "${NEIGHBOR}"
EOF
sudo chmod 0755 /usr/local/bin/deca-bgp-flap-count.sh
sudo mkdir -p /etc/telegraf/telegraf.d
sudo tee /etc/telegraf/telegraf.d/deca-bgp-flap-count.conf > /dev/null << "EOF"
[[inputs.exec]]
  commands = ["/usr/local/bin/deca-bgp-flap-count.sh"]
  timeout = "4s"
  interval = "5s"
  data_format = "influx"
  name_override = "bgp_flap_count"
EOF
sudo systemctl restart telegraf'

echo "=== Verifying bgp_flap_count_value on Telegraf :9273 (station1) ==="
if ssh -T station1 'curl -s localhost:9273/metrics' | grep -q '^bgp_flap_count_value'; then
  echo "PASS: station1 exposing bgp_flap_count_value"
else
  echo "WARN: station1 missing bgp_flap_count_value on :9273 — check vtysh perms (sudoers user must match \`systemctl show telegraf -p User\`) / telegraf logs"
fi

# ---------------------------------------------------------------------------
# Enable units
# ---------------------------------------------------------------------------
echo "=== Enabling units ==="
ssh -T station1 'sudo systemctl enable frr strongswan-starter chrony telegraf deca-ns.service deca-watchdog.service'
ssh -T station2 'sudo systemctl enable frr strongswan-starter chrony telegraf deca-ns.service deca-watchdog.service'
ssh -T station3 'sudo systemctl enable frr chrony telegraf deca-watchdog.service'

# ---------------------------------------------------------------------------
# Clear poisoned failed-state + bring chain up now (no reboot required)
# ---------------------------------------------------------------------------
echo "=== reset-failed + restart namespace → IPsec chain ==="
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo systemctl reset-failed'
done

ssh -T station1 'sudo systemctl restart deca-ns.service'
sleep 3
ssh -T station1 'sudo systemctl restart strongswan-starter'

ssh -T station2 'sudo systemctl restart deca-ns.service'
sleep 3
ssh -T station2 'sudo systemctl restart strongswan-starter'
sleep 5

echo "=== IPsec status (expect exactly ONE ESTABLISHED SA) ==="
ssh -T station1 'sudo ipsec status'

SA_LINES=$(ssh -T station1 'sudo ipsec status' | grep -c 'ESTABLISHED' || true)
if [ "${SA_LINES}" -lt 1 ]; then
  echo "FAIL: no ESTABLISHED SA — inspect journalctl -u strongswan-starter / deca-ns"
  exit 1
fi
if [ "${SA_LINES}" -gt 2 ]; then
  # allow one connection + one child SA wording; warn if clearly duplicated peers
  echo "WARN: multiple ESTABLISHED lines ($SA_LINES) — check for duplicate SAs"
fi

# ---------------------------------------------------------------------------
# VPN dataplane smoke (CE-A → CE-B)
# ---------------------------------------------------------------------------
echo "=== VPN ping CE-A → 10.100.2.1 ==="
if ssh -T station1 'sudo ip netns exec ce-a ping -c 2 -W 2 10.100.2.1' | grep -q 'bytes from'; then
  echo "PASS: VPN dataplane OK"
else
  echo "WARN: VPN ping failed — namespaces up but route/SA may still be converging; re-check after 30s"
fi

# ---------------------------------------------------------------------------
# Hash parity on drop-ins
# ---------------------------------------------------------------------------
echo "=== Drop-in hash parity ==="
H1=$(ssh -T station1 'sudo md5sum /etc/systemd/system/frr.service.d/override.conf' | awk '{print $1}')
H2=$(ssh -T station2 'sudo md5sum /etc/systemd/system/frr.service.d/override.conf' | awk '{print $1}')
S1=$(ssh -T station1 'sudo md5sum /etc/systemd/system/strongswan-starter.service.d/override.conf' | awk '{print $1}')
S2=$(ssh -T station2 'sudo md5sum /etc/systemd/system/strongswan-starter.service.d/override.conf' | awk '{print $1}')
W1=$(ssh -T station1 'sudo md5sum /etc/systemd/system/deca-watchdog.service' | awk '{print $1}')
W2=$(ssh -T station2 'sudo md5sum /etc/systemd/system/deca-watchdog.service' | awk '{print $1}')
W3=$(ssh -T station3 'sudo md5sum /etc/systemd/system/deca-watchdog.service' | awk '{print $1}')

[ "$H1" = "$H2" ] && echo "PASS: frr override identical" || { echo "FAIL: frr override mismatch"; exit 1; }
[ "$S1" = "$S2" ] && echo "PASS: strongswan override identical" || { echo "FAIL: strongswan override mismatch"; exit 1; }
[ "$W1" = "$W2" ] && [ "$W2" = "$W3" ] && echo "PASS: watchdog identical on all 3" || { echo "FAIL: watchdog mismatch"; exit 1; }

echo "=== Enablement ==="
ssh -T station1 'sudo systemctl is-enabled deca-ns.service frr strongswan-starter chrony telegraf deca-watchdog.service'
ssh -T station2 'sudo systemctl is-enabled deca-ns.service frr strongswan-starter chrony telegraf deca-watchdog.service'
ssh -T station3 'sudo systemctl is-enabled frr chrony telegraf deca-watchdog.service'

echo
echo "=== Deployment complete ==="
echo "Next (proof): cold power-cycle all 3 Pis, wait 120s, then:"
echo "  ./check_stations.sh"
echo "  # or: bash ~/deca_diagnostic.sh"
echo "If stage 6/7 fail: ssh station1 'sudo journalctl -u deca-watchdog --no-pager | tail -20'"
