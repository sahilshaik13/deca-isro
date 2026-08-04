#!/usr/bin/env bash
# inject_bgp_flap.sh — Route-flap / underlay instability profile (Q2 label 3).
#
# Default mode: repeated `clear bgp <nbr> soft` — matches lab Prom metric
# bgp_flap_count (routeRefreshSent+Recv; see lab/deca-deploy.sh Tier 5b).
#
# Optional --link-bounce: briefly DOWN/UP gre-te-core each cycle (harder
# underlay hit; always restores UP on exit).
#
# Usage:
#   bash scripts/inject_bgp_flap.sh
#   bash scripts/inject_bgp_flap.sh --cycles 18 --period-sec 5
#   bash scripts/inject_bgp_flap.sh --link-bounce --cycles 12
#   bash scripts/inject_bgp_flap.sh --clear
set -euo pipefail

HOST=station1
NEIGHBOR=10.1.3.1
DEV=gre-te-core
CYCLES=18
PERIOD_SEC=5
DOWN_SEC=2
LINK_BOUNCE=0
CLEAR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --neighbor) NEIGHBOR="$2"; shift 2 ;;
    --dev) DEV="$2"; shift 2 ;;
    --cycles) CYCLES="$2"; shift 2 ;;
    --period-sec) PERIOD_SEC="$2"; shift 2 ;;
    --down-sec) DOWN_SEC="$2"; shift 2 ;;
    --link-bounce) LINK_BOUNCE=1; shift ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s" -- "$@"; }

ensure_up() {
  run <<EOF
ip link set $DEV up 2>/dev/null || true
ip -br link show $DEV || true
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  echo "Restoring $HOST $DEV UP (no flap loop)"
  ensure_up
  exit 0
fi

TOTAL=$((CYCLES * PERIOD_SEC))
MODE="soft-clear"
[[ "$LINK_BOUNCE" -eq 1 ]] && MODE="link-bounce+$MODE"
echo "BGP flap on $HOST nbr=$NEIGHBOR: ${CYCLES}×${PERIOD_SEC}s (~${TOTAL}s) mode=$MODE"
ensure_up >/dev/null 2>&1 || true

run <<EOF
set -euo pipefail
NEIGHBOR='$NEIGHBOR'
DEV='$DEV'
CYCLES=$CYCLES
PERIOD_SEC=$PERIOD_SEC
DOWN_SEC=$DOWN_SEC
LINK_BOUNCE=$LINK_BOUNCE

restore() {
  ip link set "\$DEV" up 2>/dev/null || true
  echo "[\$(date -u +%H:%M:%S)] restored \$DEV UP"
}
trap restore EXIT INT TERM

for i in \$(seq 1 "\$CYCLES"); do
  echo "[\$(date -u +%H:%M:%S)] flap \$i/\$CYCLES clear bgp \$NEIGHBOR soft"
  vtysh -c "clear bgp \$NEIGHBOR soft" >/dev/null
  if [[ "\$LINK_BOUNCE" -eq 1 ]]; then
    echo "[\$(date -u +%H:%M:%S)] link bounce \$DEV down \${DOWN_SEC}s"
    ip link set "\$DEV" down
    sleep "\$DOWN_SEC"
    ip link set "\$DEV" up
  fi
  rem=\$PERIOD_SEC
  if [[ "\$LINK_BOUNCE" -eq 1 ]]; then
    rem=\$(( PERIOD_SEC - DOWN_SEC ))
  fi
  [[ \$rem -lt 1 ]] && rem=1
  sleep "\$rem"
done
echo "[\$(date -u +%H:%M:%S)] flap campaign complete"
ip -br link show "\$DEV" || true
EOF

echo "Done. Ensure UP with: $0 --clear --host $HOST"
