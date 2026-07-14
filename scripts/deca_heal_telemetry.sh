#!/bin/bash
# Quick heal for failed [7/8] VPN ping + [8/8] 0/3 Telegraf after partial boot.
# Run on the laptop (lab USB eth up).
set -euo pipefail

echo "=== DECA heal: VPN dataplane + Telegraf scrape ==="

# --- Laptop side: Prometheus must be up ---
if ! curl -sf --max-time 2 http://localhost:9090/-/ready >/dev/null; then
  echo "WARN: Prometheus not ready on :9090 — start it before expecting 3/3 scrapes"
else
  echo "OK: Prometheus ready"
fi

# --- Stations: telegraf + namespaces + ipsec ---
for H in station1 station2; do
  echo "--- $H ---"
  ssh -T "$H" 'sudo systemctl reset-failed
    sudo systemctl is-active --quiet deca-ns.service || sudo systemctl restart deca-ns.service
    sleep 2
    sudo systemctl is-active --quiet frr || sudo systemctl restart frr
    sudo systemctl is-active --quiet strongswan-starter || sudo systemctl restart strongswan-starter
    sudo systemctl is-active --quiet telegraf || sudo systemctl restart telegraf
    echo "  deca-ns=$(systemctl is-active deca-ns.service 2>/dev/null || echo n/a) frr=$(systemctl is-active frr) ipsec=$(systemctl is-active strongswan-starter) telegraf=$(systemctl is-active telegraf)"
    ip netns list 2>/dev/null | head -5 || true'
done

echo "--- station3 (no deca-ns / ipsec) ---"
ssh -T station3 'sudo systemctl reset-failed
  sudo systemctl is-active --quiet frr || sudo systemctl restart frr
  sudo systemctl is-active --quiet telegraf || sudo systemctl restart telegraf
  echo "  frr=$(systemctl is-active frr) telegraf=$(systemctl is-active telegraf)"'

sleep 3

echo "=== IPsec (want 1 ESTABLISHED) ==="
ssh -T station1 'sudo ipsec status' | sed 's/^/  /'

echo "=== CE namespaces present? ==="
ssh -T station1 'ip netns list'
ssh -T station2 'ip netns list'

echo "=== [7/8] VPN ping ce-a → 10.100.2.1 ==="
if ssh -T station1 'sudo ip netns exec ce-a ping -c 3 -W 2 10.100.2.1'; then
  echo "PASS: VPN dataplane"
else
  echo "FAIL: VPN ping"
  echo "  Debug hints:"
  echo "    ssh station1 'sudo ip netns exec ce-a ip a; sudo ip netns exec ce-a ip r'"
  echo "    ssh station2 'sudo ip netns exec ce-b ip a'"
  echo "    ssh station1 'sudo ipsec statusall | head -40'"
fi

echo "=== Direct Telegraf :9273 from laptop ==="
UP=0
for IP in 10 20 30; do
  if curl -sf --max-time 3 "http://192.168.50.$IP:9273/metrics" >/dev/null; then
    echo "  192.168.50.$IP:9273 UP"
    UP=$((UP + 1))
  else
    echo "  192.168.50.$IP:9273 DOWN"
    ssh -T "station$((IP / 10))" 'systemctl is-active telegraf; sudo ss -ltnp | grep 9273 || true' 2>/dev/null || true
  fi
done
echo "  Direct reachability: $UP / 3"

echo "=== Prometheus target health ==="
if curl -sf --max-time 3 http://localhost:9090/api/v1/targets >/tmp/prom_targets.json; then
  python3 - <<'PY'
import json
d=json.load(open("/tmp/prom_targets.json"))
active=d.get("data",{}).get("activeTargets",[])
print(f"  targets listed: {len(active)}")
for t in active:
    print(f"  {t.get('labels',{}).get('instance','?')} job={t.get('labels',{}).get('job','?')} health={t.get('health')} lastError={t.get('lastError','')[:80]}")
up=sum(1 for t in active if t.get("health")=="up")
print(f"  health up: {up}")
PY
else
  echo "  cannot query Prometheus /api/v1/targets"
fi

echo "=== Done — re-run: bash ~/deca_diagnostic.sh ==="
