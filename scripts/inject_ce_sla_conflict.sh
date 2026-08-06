#!/usr/bin/env bash
# inject_ce_sla_conflict.sh — Bronze CE burst vs Gold TT&C (ISRO mentor CE↔CE SLA conflict).
#
# Story: Mauritius (Bronze / 90%) surges Payload util while NRSC (Gold / 99.9%) keeps
# a light TT&C probe. Shared PE1 HTB/WAN pressure → Decide names rogue vs victim.
#
# CAPTURE_CONTRACT (L6 shape):
#   Default = continuous plateau:
#     1) Victim TT&C probe for the whole window
#     2) One uninterrupted rogue iperf3 on :5006 (HTB 1:15) at rogue_mbit
#     3) No kill/restart dead air (same failure mode as old pulsed L5)
#   --coarse = legacy stepped bitrate handoff (debug only — not for long campaign)
#
# Usage:
#   bash scripts/inject_ce_sla_conflict.sh
#   bash scripts/inject_ce_sla_conflict.sh --rogue-mbit 20 --hold-sec 90
#   bash scripts/inject_ce_sla_conflict.sh --coarse --steps 5 --step-sec 18
#   bash scripts/inject_ce_sla_conflict.sh --clear
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
HOLD_SEC=0                  # 0 → STEPS*STEP_SEC in continuous mode
VICTIM_MBIT=1
CLEAR_ONLY=0
FORCE_CLEAR=0
MODE=continuous             # continuous | coarse

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --rogue-ns) ROGUE_NS="$2"; shift 2 ;;
    --victim-ns) VICTIM_NS="$2"; shift 2 ;;
    --rogue-mbit|--end-mbit) ROGUE_END="$2"; shift 2 ;;
    --start-mbit) ROGUE_START="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --hold-sec) HOLD_SEC="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    --force-clear) FORCE_CLEAR=1; shift ;;
    --coarse) MODE=coarse; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
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

if [[ "$HOLD_SEC" -le 0 ]]; then
  HOLD_SEC=$((STEPS * STEP_SEC))
fi

echo "CE SLA conflict mode=$MODE rogue=$ROGUE_NS →${ROGUE_END}Mbit :5006; victim=$VICTIM_NS TT&C ${VICTIM_MBIT}M hold=${HOLD_SEC}s [CAPTURE_CONTRACT]"

if [[ "$MODE" == "coarse" ]]; then
  # Legacy pulsed ramp (debug) — kill/restart each step → high→idle drops
  run <<EOF
set -euo pipefail
ROGUE_NS='$ROGUE_NS'; VICTIM_NS='$VICTIM_NS'; DST='$DST_SAC'
ROGUE_TOS=$ROGUE_TOS; VICTIM_TOS=$VICTIM_TOS
STEPS=$STEPS; STEP_SEC=$STEP_SEC; START_MBIT=$ROGUE_START; END_MBIT=$ROGUE_END
VICTIM_MBIT=$VICTIM_MBIT; ROGUE_PORT=5006; VICTIM_PORT=5201
ssh -o BatchMode=yes -o ConnectTimeout=5 192.168.50.20 \
  'sudo bash -c "ip netns exec ce-b iperf3 -s -D -p 5006 2>/dev/null || true; ip netns exec ce-b iperf3 -s -D -p 5201 2>/dev/null || true"' \
  2>/dev/null || true
echo \$\$ > /tmp/deca_ce_sla_conflict.pid
TOTAL=\$(( STEPS * STEP_SEC + 5 ))
ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
ip netns exec "\$VICTIM_NS" iperf3 -c "\$DST" -u -b "\${VICTIM_MBIT}M" -t "\$TOTAL" --tos "\$VICTIM_TOS" -p "\$VICTIM_PORT" \
  >/tmp/deca_ce_sla_victim.log 2>&1 &
for i in \$(seq 0 \$((STEPS - 1))); do
  if [[ "\$STEPS" -eq 1 ]]; then mbit=\$END_MBIT
  else mbit=\$(( START_MBIT + (END_MBIT - START_MBIT) * i / (STEPS - 1) )); fi
  echo "[\$(date -u +%H:%M:%S)] COARSE rogue step \$i/\$STEPS \${mbit}Mbit"
  ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
  sleep 1
  ip netns exec "\$ROGUE_NS" iperf3 -c "\$DST" -P 2 -b "\${mbit}M" -t "\$STEP_SEC" -p "\$ROGUE_PORT" \
    >/tmp/deca_ce_sla_rogue.log 2>&1 &
  sleep "\$STEP_SEC"
done
ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
rm -f /tmp/deca_ce_sla_conflict.pid
echo "[\$(date -u +%H:%M:%S)] CE SLA coarse complete"
EOF
  exit 0
fi

# --- Default: continuous plateau (no kill/restart gaps) ---
run <<EOF
set -euo pipefail
ROGUE_NS='$ROGUE_NS'; VICTIM_NS='$VICTIM_NS'; DST='$DST_SAC'
ROGUE_TOS=$ROGUE_TOS; VICTIM_TOS=$VICTIM_TOS
HOLD_SEC=$HOLD_SEC; END_MBIT=$ROGUE_END; VICTIM_MBIT=$VICTIM_MBIT
ROGUE_PORT=5006; VICTIM_PORT=5201
TOTAL=\$(( HOLD_SEC + 8 ))

ssh -o BatchMode=yes -o ConnectTimeout=5 192.168.50.20 \
  'sudo bash -c "ip netns exec ce-b iperf3 -s -D -p 5006 2>/dev/null || true; ip netns exec ce-b iperf3 -s -D -p 5201 2>/dev/null || true"' \
  2>/dev/null || true

cleanup() {
  ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
  ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
  rm -f /tmp/deca_ce_sla_conflict.pid
  echo "[\$(date -u +%H:%M:%S)] CE SLA continuous cleared"
}
trap cleanup EXIT INT TERM

echo \$\$ > /tmp/deca_ce_sla_conflict.pid
: > /tmp/deca_ce_sla_schedule.jsonl
now=\$(date +%s)
printf '{"ts_unix":%s,"phase":"plateau","rogue_mbit":%s,"hold_sec":%s}\n' \
  "\$now" "\$END_MBIT" "\$HOLD_SEC" >> /tmp/deca_ce_sla_schedule.jsonl

ip netns exec "\$VICTIM_NS" pkill -f 'iperf3.*--tos' 2>/dev/null || true
ip netns exec "\$ROGUE_NS" pkill -f iperf3 2>/dev/null || true
sleep 1

echo "[\$(date -u +%H:%M:%S)] start victim TT&C \${VICTIM_MBIT}M + rogue plateau \${END_MBIT}Mbit for \${HOLD_SEC}s"
ip netns exec "\$VICTIM_NS" iperf3 -c "\$DST" -u -b "\${VICTIM_MBIT}M" -t "\$TOTAL" --tos "\$VICTIM_TOS" -p "\$VICTIM_PORT" \
  >/tmp/deca_ce_sla_victim.log 2>&1 &
# Continuous rogue — single offer, no mid-hold restart
ip netns exec "\$ROGUE_NS" iperf3 -c "\$DST" -P 2 -b "\${END_MBIT}M" -t "\$TOTAL" -p "\$ROGUE_PORT" \
  >/tmp/deca_ce_sla_rogue.log 2>&1 &
sleep "\$HOLD_SEC"
echo "[\$(date -u +%H:%M:%S)] CE SLA continuous plateau complete"
tail -5 /tmp/deca_ce_sla_rogue.log 2>/dev/null || true
EOF

echo "[$(date -u +%H:%M:%S)] inject finished"
