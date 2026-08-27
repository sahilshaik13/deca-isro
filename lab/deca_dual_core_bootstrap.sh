#!/usr/bin/env bash
# Bootstrap dual P-router namespaces on station3 (CORE-NORTH / CORE-SOUTH).
# Idempotent: safe to re-run. Does NOT yet install FRR daemons inside netns —
# that is a follow-on step after VLAN/veth PE attachments exist.
#
# Usage:
#   ./lab/deca_dual_core_bootstrap.sh           # ssh station3
#   DECA_DUAL_CORE_LOCAL=1 ./lab/deca_dual_core_bootstrap.sh  # run locally on station3
set -euo pipefail

REMOTE_HOST="${DECA_CORE_HOST:-station3}"

remote() {
  if [[ "${DECA_DUAL_CORE_LOCAL:-0}" == "1" ]]; then
    sudo bash -c "$*"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=10 -T "$REMOTE_HOST" "sudo bash -c $(printf '%q' "$*")"
  fi
}

echo "=== Dual-core namespaces on ${REMOTE_HOST} ==="

remote '
set -euo pipefail
# Namespaces
ip netns add core-north 2>/dev/null || true
ip netns add core-south 2>/dev/null || true

# Inter-core backbone veth (recreate if missing)
if ! ip netns exec core-north ip link show veth-core-n >/dev/null 2>&1; then
  ip link del veth-core-n 2>/dev/null || true
  ip link del veth-core-s 2>/dev/null || true
  ip link add veth-core-n type veth peer name veth-core-s
  ip link set veth-core-n netns core-north
  ip link set veth-core-s netns core-south
fi

# Loopbacks (P router IDs)
ip netns exec core-north bash -c "
  ip link set lo up
  ip addr replace 10.1.3.1/32 dev lo
  ip link set veth-core-n up
  ip addr replace 10.3.0.1/30 dev veth-core-n
"
ip netns exec core-south bash -c "
  ip link set lo up
  ip addr replace 10.1.3.2/32 dev lo
  ip link set veth-core-s up
  ip addr replace 10.3.0.2/30 dev veth-core-s
"

echo "--- netns ---"
ip netns list | grep -E "core-north|core-south" || true
echo "--- CORE-NORTH ---"
ip netns exec core-north ip -br addr
echo "--- CORE-SOUTH ---"
ip netns exec core-south ip -br addr
'

echo "=== Dual-core netns ready ==="
echo "Next: attach PE1/PE2 via VLAN or veth to both namespaces; run FRR in each netns."
