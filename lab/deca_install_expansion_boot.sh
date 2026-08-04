#!/usr/bin/env bash
# Install expansion boot units + heal scripts onto all three stations so cold
# power-on restores Mauritius / GRE TE / HTB / VRF-up / Phase-D exporters.
# Run from the laptop on the lab LAN. Does NOT touch models/fault_classifier/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' 2>/dev/null \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
for H in station1 station2 station3; do need "$H"; done

echo "=== Install /usr/local/bin/deca-expansion-boot.sh + systemd unit ==="
for H in station1 station2 station3; do
  scp -q "$ROOT/lab/deca-expansion-boot.sh" "$H:/tmp/deca-expansion-boot.sh"
  ssh -T "$H" 'sudo bash -s' <<'EOF'
set -euo pipefail
install -m 0755 /tmp/deca-expansion-boot.sh /usr/local/bin/deca-expansion-boot.sh
tee /etc/systemd/system/deca-expansion-boot.service >/dev/null <<'UNIT'
[Unit]
Description=DECA network-expansion boot restore (VRF, GRE TE, HTB, Mauritius)
After=network-online.target frr.service
Wants=network-online.target
# After CE namespaces on PE stations when present
After=deca-ns.service deca-ns-mauritius.service deca-vrf-up.service
Wants=deca-vrf-up.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/deca-expansion-boot.sh
# Second pass after FRR/IPsec finish coming up
ExecStartPost=/bin/bash -c 'sleep 20; /usr/local/bin/deca-expansion-boot.sh || true'
SuccessExitStatus=0

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable deca-expansion-boot.service
EOF
  echo "  $H: expansion-boot unit enabled"
done

# Phase D exporters (idempotent install, no IPsec bounce)
if [[ -x "$ROOT/lab/deca_expand_phase_d.sh" ]]; then
  echo "=== Ensuring Phase D exporters installed ==="
  SKIP_SMOKE=1 bash "$ROOT/lab/deca_expand_phase_d.sh" || echo "WARN: phase D install had issues — continuing"
fi

# Mauritius units must exist + be enabled on station1
echo "=== Ensuring Mauritius + VRF-up units ==="
if ! ssh -T station1 'systemctl list-unit-files | grep -q deca-ns-mauritius'; then
  echo "Installing Mauritius via phase A..."
  bash "$ROOT/lab/deca_expand_phase_a.sh" || true
fi
ssh -T station1 'sudo systemctl enable --now deca-vrf-up.service deca-ns-mauritius.service deca-mauritius-bgp.service deca-expansion-boot.service'
ssh -T station2 'sudo systemctl enable --now deca-vrf-up.service deca-expansion-boot.service'
ssh -T station3 'sudo systemctl enable --now deca-expansion-boot.service'

# Patch watchdog to heal expansion after base services
echo "=== Updating deca-watchdog.service (heal expansion on every boot) ==="
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo bash -s' <<'EOF'
set -euo pipefail
tee /etc/systemd/system/deca-watchdog.service >/dev/null <<'UNIT'
[Unit]
Description=DECA Post-Boot Self-Healing Watchdog
After=frr.service network-online.target deca-expansion-boot.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 60
ExecStart=/bin/bash -c "systemctl reset-failed; systemctl is-active --quiet deca-ns.service 2>/dev/null || systemctl restart deca-ns.service 2>/dev/null; systemctl start deca-vrf-up.service 2>/dev/null; systemctl start deca-ns-mauritius.service 2>/dev/null; systemctl start deca-mauritius-bgp.service 2>/dev/null; sleep 2; systemctl is-active --quiet frr || systemctl restart frr; systemctl is-active --quiet strongswan-starter 2>/dev/null || systemctl restart strongswan-starter 2>/dev/null; systemctl is-active --quiet telegraf || systemctl restart telegraf; /usr/local/bin/deca-expansion-boot.sh 2>/dev/null || true; mkdir -p /run/deca; date -u +%Y-%m-%dT%H:%M:%SZ > /run/deca/station-ready"

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable deca-watchdog.service
EOF
done

echo "=== Run expansion boot once now ==="
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo /usr/local/bin/deca-expansion-boot.sh' || true
done

echo
echo "=== Expansion boot install complete ==="
echo "Cold boot order: network → deca-ns → mauritius → expansion-boot → frr/ipsec → watchdog(+60s heal)"
echo "Ready latch: /run/deca/station-ready (brain campaign pauses until ping+:9273+Prom OK)"
echo "Proof: power-cycle Pis, wait ≥120s, then: check stations"
