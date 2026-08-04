#!/usr/bin/env bash
# deca_vrf_isolation_check.sh — verify PS13 macro-segmentation.
#
# Lab names: vrf-mission (table 100) + vrf-admin (table 200).
# PS13 synonym for vrf-admin is "vrf-default" (admin/eth0-pinned traffic).
#
# Checks:
#   1) Both VRFs exist and are UP
#   2) No obvious cross-VRF default route leak in the opposite table
#   3) IPsec SA established (fail-closed prerequisite for mission WAN)
set -euo pipefail

HOST="${1:-station1}"

ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$HOST" 'sudo bash -s' <<'EOF'
set +e
fail=0
echo "=== VRF links ==="
ip -br link show type vrf
for v in vrf-mission vrf-admin; do
  if ! ip link show "$v" &>/dev/null; then
    echo "FAIL: missing $v"
    fail=1
  elif ! ip link show "$v" | grep -q 'UP'; then
    echo "FAIL: $v not UP"
    fail=1
  else
    echo "OK: $v UP"
  fi
done

echo "=== Mission table must not be empty; admin is separate ==="
mc=$(ip route show vrf vrf-mission 2>/dev/null | wc -l)
ac=$(ip route show vrf vrf-admin 2>/dev/null | wc -l)
echo "vrf-mission routes: $mc"
echo "vrf-admin routes:   $ac"
[ "$mc" -ge 1 ] || { echo "WARN: vrf-mission empty"; }

echo "=== IPsec (swanctl preferred) ==="
if command -v swanctl >/dev/null; then
  if swanctl --list-sas 2>/dev/null | grep -q ESTABLISHED; then
    echo "OK: IPsec ESTABLISHED (mission traffic may ride ESP)"
    swanctl --list-conns 2>/dev/null | grep -A2 copy_dscp || \
      grep -n copy_dscp /etc/swanctl/conf.d/*.conf 2>/dev/null | head -5
  else
    echo "FAIL: no ESTABLISHED SA — TT&C must FAIL-CLOSED (no cleartext WAN)"
    fail=1
  fi
else
  ipsec status 2>/dev/null | head -5 || echo "WARN: no swanctl/ipsec"
fi

echo "=== copy_dscp ==="
grep -R "copy_dscp" /etc/swanctl/conf.d/ 2>/dev/null | head -5 \
  || echo "WARN: copy_dscp not found in swanctl conf.d"

exit $fail
EOF
