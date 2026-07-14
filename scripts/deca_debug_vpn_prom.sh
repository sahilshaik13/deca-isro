#!/bin/bash
# Diagnose + attempt fix for:
#   A) Prometheus scrape health=down lastError=out of bounds (while :9273 curls OK)
#   B) CE-A→CE-B ping 100% loss despite IPsec ESTABLISHED / BGP NoNeg
set -euo pipefail

echo "=== A) Clock skew (common cause of Prometheus 'out of bounds') ==="
echo -n "  laptop UTC: "; date -u
for H in station1 station2 station3; do
  echo -n "  $H UTC: "
  ssh -T "$H" 'date -u' 2>/dev/null || echo 'ssh fail'
done

echo
echo "=== A) Do Telegraf metrics carry explicit timestamps? ==="
# Prometheus exposition with trailing timestamp → uses that time; stale/skew ⇒ out of bounds
sample=$(curl -sf --max-time 3 http://192.168.50.10:9273/metrics | grep -E '^[a-zA-Z_:]' | grep -E ' [0-9eE+.-]+ [0-9]{10,}$' | head -3 || true)
if [ -n "$sample" ]; then
  echo "  YES — explicit timestamps present (suspect for out-of-bounds):"
  echo "$sample" | sed 's/^/    /'
else
  echo "  No explicit timestamps in first lines (Prometheus will stamp scrape time)"
  curl -sf --max-time 3 http://192.168.50.10:9273/metrics | grep -E '^net_bytes' | head -3 | sed 's/^/    /'
fi

echo
echo "=== A) Telegraf prometheus_client config snippets ==="
for H in station1 station2 station3; do
  echo "  --- $H ---"
  ssh -T "$H" 'grep -RIn "prometheus_client\|metric_version\|export_timestamp\|timestamps" /etc/telegraf/ 2>/dev/null | head -20' || true
done

echo
echo "=== A) Soft fix attempts for scrape ==="
# 1) Restart telegraf (clear stale metric buffers)
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo systemctl restart telegraf'
done
sleep 3

# 2) If Prometheus supports it, reload; else remind restart
if curl -sf -X POST --max-time 2 http://localhost:9090/-/reload >/dev/null 2>&1; then
  echo "  Prometheus reload OK"
else
  echo "  WARN: POST /-/reload failed — restart Prometheus after telegraf restart:"
  echo "    sudo systemctl restart prometheus   # or however you start it"
fi

sleep 5
echo "  target health after telegraf restart:"
curl -sf http://localhost:9090/api/v1/targets | python3 -c '
import sys,json
for t in json.load(sys.stdin).get("data",{}).get("activeTargets",[]):
    print("   ", t["labels"].get("instance"), t["health"], t.get("lastError","")[:100])
'

echo
echo "=== B) BGP (VPN needs VPNv4; NoNeg ⇒ dataplane dead) ==="
ssh -T station1 'sudo vtysh -c "show bgp summary" 2>/dev/null | head -40'
ssh -T station1 'sudo vtysh -c "show bgp ipv4 vpn summary" 2>/dev/null | head -30'
ssh -T station1 'sudo vtysh -c "show ip route vrf vrf-mission" 2>/dev/null | head -30'

echo
echo "=== B) Soft-clear BGP + bounce VRF paths ==="
ssh -T station1 'sudo vtysh -c "clear bgp * soft"'
ssh -T station3 'sudo vtysh -c "clear bgp * soft"' 2>/dev/null || true
sleep 5
ssh -T station1 'sudo vtysh -c "show bgp summary" 2>/dev/null | grep -E "10\.1\.|Neighbor|State"'

echo
echo "=== B) CE route + policy routing ==="
ssh -T station1 'echo "ce-a:"; sudo ip netns exec ce-a ip r; echo "rules:"; ip rule | head -20; echo "table 100:"; ip route show table 100 2>/dev/null | head -15'
ssh -T station2 'echo "ce-b:"; sudo ip netns exec ce-b ip r; ip rule | head -10; ip route show table 100 2>/dev/null | head -15'

echo
echo "=== B) VPN ping retry ==="
if ssh -T station1 'sudo ip netns exec ce-a ping -c 3 -W 2 10.100.2.1'; then
  echo "PASS: VPN dataplane"
else
  echo "FAIL still — recreate namespaces (keeps IPsec):"
  ssh -T station1 'sudo systemctl restart deca-ns.service'
  ssh -T station2 'sudo systemctl restart deca-ns.service'
  sleep 3
  ssh -T station1 'sudo systemctl restart strongswan-starter'
  ssh -T station2 'sudo systemctl restart strongswan-starter'
  sleep 5
  ssh -T station1 'sudo vtysh -c "clear bgp * soft"'
  sleep 3
  ssh -T station1 'sudo ip netns exec ce-a ping -c 3 -W 2 10.100.2.1' || echo "FAIL after ns bounce"
fi

echo
echo "=== Done. If Prometheus still out-of-bounds, paste laptop+station date -u and one metrics line with timestamp ==="
