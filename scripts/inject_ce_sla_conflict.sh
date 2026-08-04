#!/usr/bin/env bash
# inject_ce_sla_conflict.sh — Bronze CE burst vs Gold TT&C (ISRO mentor CE↔CE SLA conflict).
#
# Story: Mauritius (Bronze / 90%) surges Payload util while NRSC (Gold / 99.9%) keeps
# a light TT&C probe. Shared PE1 HTB/WAN pressure → Decide names rogue vs victim.
#
# Does NOT clear the protocol campaign's BGP inject unless you pass --force-clear.
# Prefer running when campaign is idle or on a free window.
#
# Usage:
#   bash scripts/inject_ce_sla_conflict.sh
#   bash scripts/inject_ce_sla_conflict.sh --clear
#   bash scripts/inject_ce_sla_conflict.sh --rogue-mbit 20 --hold-sec 90
set -euo pipefail

HOST=station1
ROGUE_NS=ce-mauritius
VICTIM_NS=ce-a
DST_SAC=10.100.2.1          # SAC lo via mission path
ROGUE_TOS=128               # 0x80 — competes in HTB 1:15 (non-critical bulk)
VICTIM_TOS=136              # 0x88 TT&C
ROGUE_START=2
ROGUE_END=20
STEPS=5
STEP_SEC=18
VICTIM_MBIT=1
CLEAR_ONLY=0
FORCE_CLEAR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --rogue-ns) ROGUE_NS="$2"; shift 2 ;;
    --victim-ns) VICTIM_NS="$2"; shift 2 ;;
    --rogue-mbit|--end-mbit) ROGUE_END="$2"; shift 2 ;;
    --start-mbit) ROGUE_START="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --hold-sec) STEP_SEC="$2"; STEPS=1; ROGUE_START="$ROGUE_END"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    --force-clear) FORCE_CLEAR=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s"; }

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  echo "Clearing CE SLA conflict injectors on $HOST"
  run <<EOF
pkill -f 'deca_ce_sla_' 2>/dev/null || true
ip netns exec ce-mauritius pkill -f iperf3 2>/dev/null || true
ip netns exec ce-a pkill -f 'iperf3.*--tos 136' 2>/dev/null || true
ip netns exec ce-a pkill -f 'iperf3.*--tos 0x88' 2>/dev/null || true
echo cleared
EOF
  exit 0
fi

if pgrep -f 'inject_bgp_flap.sh|inject_cpu_stress.sh|inject_rain_fade.sh' >/dev/null 2>&1; then
  if [[ "$FORCE_CLEAR" -ne 1 ]]; then
    echo "WARN: another inject/campaign fault appears active on brain."
    echo "      Refusing to stack CE conflict (pass --force-clear to override)."
    exit 3
  fi
fi

echo "CE SLA conflict: rogue=$ROGUE_NS ${ROGUE_START}→${ROGUE_END} Mbit via HTB TCP :5006; victim=$VICTIM_NS TT&C ${VICTIM_MBIT}M"
run <<EOF
set -euo pipefail
ROGUE_NS='$ROGUE_NS'
VICTIM_NS='$VICTIM_NS'
DST='$DST_SAC'
ROGUE_TOS=$ROGUE_TOS
VICTIM_TOS=$VICTIM_TOS
STEPS=$STEPS
STEP_SEC=$STEP_SEC
START_MBIT=$ROGUE_START
END_MBIT=$ROGUE_END
VICTIM_MBIT=$VICTIM_MBIT
# Payload path must hit HTB 1:15 (dport 5006) so util_gre_mbps / max(gre|eth0) moves
ROGUE_PORT=5006
VICTIM_PORT=5201

# Far-end servers on SAC (ce-b)
ssh -o BatchMode=yes -o ConnectTimeout=5 192.168.50.20 \
  'sudo bash -c "ip netns exec ce-b iperf3 -s -D -p 5006 2>/dev/null || true; ip netns exec ce-b iperf3 -s -D -p 5201 2>/dev/null || true"' \
  2>/dev/null || true

echo \$\$ > /tmp/deca_ce_sla_conflict.pid

# Light Gold TT&C probe (background)
ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
TOTAL=\$(( STEPS * STEP_SEC + 5 ))
ip netns exec "\$VICTIM_NS" iperf3 -c "\$DST" -u -b "\${VICTIM_MBIT}M" -t "\$TOTAL" --tos "\$VICTIM_TOS" -p "\$VICTIM_PORT" \
  >/tmp/deca_ce_sla_victim.log 2>&1 &

for i in \$(seq 0 \$((STEPS - 1))); do
  if [[ "\$STEPS" -eq 1 ]]; then
    mbit=\$END_MBIT
  else
    mbit=\$(( START_MBIT + (END_MBIT - START_MBIT) * i / (STEPS - 1) ))
  fi
  echo "[\$(date -u +%H:%M:%S)] rogue step \$i/\$STEPS hold \${mbit}Mbit TCP :\$ROGUE_PORT (\${STEP_SEC}s)"
  ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
  sleep 1
  # TCP :5006 → HTB 1:15 (same as L5 util) so Prom util_gre_mbps rises
  ip netns exec "\$ROGUE_NS" iperf3 -c "\$DST" -P 2 -b "\${mbit}M" -t "\$STEP_SEC" -p "\$ROGUE_PORT" \
    >/tmp/deca_ce_sla_rogue.log 2>&1 &
  sleep "\$STEP_SEC"
done

ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
rm -f /tmp/deca_ce_sla_conflict.pid
echo "[\$(date -u +%H:%M:%S)] CE SLA conflict ramp complete"
EOF
