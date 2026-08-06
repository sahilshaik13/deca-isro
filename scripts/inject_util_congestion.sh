#!/usr/bin/env bash
# inject_util_congestion.sh — approach HTB payload ceiling with a CONTINUOUS offer.
#
# CAPTURE_CONTRACT (util TTI shape):
#   Default mode = tc-ramp:
#     1) One uninterrupted iperf3 offer on :5006 (HTB 1:15) for the whole window
#     2) Offer bitrate is ≥ OFFER_MULT × end_mbit (default 2×) so measured eth0
#        util tracks the *configured class ceil*, not “how much we chose to send”
#     3) Shape on ce-a veth-cea-pe (pre-IPsec) while mirroring PE 1:15 — eth0
#        util then tracks the configured ceil (post-encap PE filters miss CE flows)
#     4) Lift PE BE 1:20 ceil to parent (40) for the window — encapped flows still
#        land in 1:20 (ceil 24 nominal), which otherwise hard-caps measured util ~24
#     5) Plateau at end_mbit (keep ≤ fabric payload soft ceil ~34 on 40 Mbit WAN —
#        parent HTB is 40 Mbit; ends above that cannot appear in eth0 util)
#     6) Restore CE qdisc + PE 1:15 + PE 1:20 class rates
#
# Why not bitrate-step iperf? Each -b handoff kills the client → near-zero gaps
# that look like oscillation and fail the residency gate (seen in contract smoke).
#
# Usage:
#   bash scripts/inject_util_congestion.sh
#   bash scripts/inject_util_congestion.sh --end-mbit 28 --steps 16 --step-sec 5 --plateau-sec 40
#   bash scripts/inject_util_congestion.sh --offer-mbit 80   # pin offer (skips auto 2×)
#   bash scripts/inject_util_congestion.sh --iperf-steps   # legacy bitrate handoff
#   bash scripts/inject_util_congestion.sh --coarse        # pulsed (debug only)
#   bash scripts/inject_util_congestion.sh --clear
set -euo pipefail

HOST=station1
PEER=station2
NS=ce-a
PEER_NS=ce-b
DST=10.100.2.1
PORT=5006
IFACE=eth0
CLASSID=1:15
STEPS=16
STEP_SEC=5
START_MBIT=5
END_MBIT=34
PARALLEL=4
PLATEAU_SEC=40
# 0 = auto: max(END,START)*OFFER_MULT. Nonzero via --offer-mbit pins explicitly.
OFFER_MBIT=0
OFFER_MULT=2
CLEAR_ONLY=0
MODE=tc   # tc | iperf | coarse
SCHEDULE_OUT="${DECA_UTIL_SCHEDULE_OUT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --peer) PEER="$2"; shift 2 ;;
    --ns) NS="$2"; shift 2 ;;
    --dst) DST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --iface) IFACE="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-mbit) START_MBIT="$2"; shift 2 ;;
    --end-mbit) END_MBIT="$2"; shift 2 ;;
    --parallel) PARALLEL="$2"; shift 2 ;;
    --plateau-sec) PLATEAU_SEC="$2"; shift 2 ;;
    --offer-mbit) OFFER_MBIT="$2"; shift 2 ;;
    --offer-mult) OFFER_MULT="$2"; shift 2 ;;
    --schedule-out) SCHEDULE_OUT="$2"; shift 2 ;;
    --iperf-steps) MODE=iperf; shift ;;
    --coarse) MODE=coarse; STEPS=6; STEP_SEC=20; PLATEAU_SEC=0; shift ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

# Auto offer: enough headroom above the *highest* class ceil we will program.
if [[ "$OFFER_MBIT" -le 0 ]]; then
  _peak=$END_MBIT
  [[ "$START_MBIT" -gt "$_peak" ]] && _peak=$START_MBIT
  OFFER_MBIT=$(( _peak * OFFER_MULT ))
  [[ "$OFFER_MBIT" -lt 16 ]] && OFFER_MBIT=16
fi

run() { ssh -T "$HOST" "sudo bash -s"; }

ensure_peer_servers() {
  ssh -T -o BatchMode=yes -o ConnectTimeout=8 "$PEER" "sudo bash -s" <<EOF || true
set -euo pipefail
ip netns exec $PEER_NS bash -c '
  pkill -x iperf3 2>/dev/null || true
  sleep 1
  iperf3 -s -D -p 5006 || true
  iperf3 -s -D -p 5201 || true
'
EOF
}

stop_clients() {
  run <<'EOF' || true
ip netns exec ce-a pkill -f 'iperf3 -c' 2>/dev/null || true
# Drop ephemeral CE shape left by a killed inject
ip netns exec ce-a tc qdisc del dev veth-cea-pe root 2>/dev/null || true
# Restore PE BE 1:20 if a killed inject left ceil elevated (nominal 5/24)
BE=$(tc class show dev eth0 classid 1:20 | head -1 || true)
if echo "$BE" | grep -qE 'ceil 40[Mm]bit'; then
  tc class change dev eth0 classid 1:20 htb rate 5mbit ceil 24mbit prio 5 2>/dev/null || true
fi
echo cleared
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  echo "Stopping util injectors on $HOST"
  stop_clients
  exit 0
fi

TOTAL=$((STEPS * STEP_SEC + PLATEAU_SEC))
echo "Util inject mode=$MODE :$PORT ×$PARALLEL  ${START_MBIT}→${END_MBIT} Mbit  offer=${OFFER_MBIT}Mbit (≥${OFFER_MULT}×end)  steps=${STEPS}×${STEP_SEC}s plateau=${PLATEAU_SEC}s (~${TOTAL}s) [CAPTURE_CONTRACT]"

ensure_peer_servers
stop_clients >/dev/null

if [[ "$MODE" == "coarse" || "$MODE" == "iperf" ]]; then
  run <<EOF
set -euo pipefail
NS='$NS'; DST='$DST'; PORT=$PORT; PARALLEL=$PARALLEL
STEPS=$STEPS; STEP_SEC=$STEP_SEC; START_MBIT=$START_MBIT; END_MBIT=$END_MBIT
PLATEAU_SEC=$PLATEAU_SEC; MODE='$MODE'; OFFER_MBIT=$OFFER_MBIT
for i in \$(seq 0 \$((STEPS - 1))); do
  mbit=\$(( START_MBIT + (END_MBIT - START_MBIT) * i / (STEPS - 1) ))
  # Offer above step ceil so -b is not the bottleneck (legacy modes).
  offer=\$OFFER_MBIT
  [[ "\$offer" -lt \$((mbit * 2)) ]] && offer=\$((mbit * 2))
  per=\$(( offer / PARALLEL )); [[ "\$per" -lt 1 ]] && per=1
  echo "[\$(date -u +%H:%M:%S)] \$MODE step \$i → ceil=\${mbit}Mbit offer=\${offer}Mbit"
  ip netns exec "\$NS" pkill -f 'iperf3 -c' 2>/dev/null || true
  [[ "\$MODE" == "coarse" ]] && sleep 1
  ip netns exec "\$NS" iperf3 -c "\$DST" -P "\$PARALLEL" -b \${per}M -t \$((STEP_SEC + PLATEAU_SEC + 5)) -p "\$PORT" \
    >/tmp/deca_util_cong.log 2>&1 &
  sleep "\$STEP_SEC"
done
if [[ "\$PLATEAU_SEC" -gt 0 ]]; then
  per=\$(( OFFER_MBIT / PARALLEL )); [[ "\$per" -lt 1 ]] && per=1
  echo "[\$(date -u +%H:%M:%S)] PLATEAU ceil=\${END_MBIT}Mbit offer=\${OFFER_MBIT}Mbit \${PLATEAU_SEC}s"
  ip netns exec "\$NS" pkill -f 'iperf3 -c' 2>/dev/null || true
  ip netns exec "\$NS" iperf3 -c "\$DST" -P "\$PARALLEL" -b \${per}M -t "\$PLATEAU_SEC" -p "\$PORT" \
    >/tmp/deca_util_cong.log 2>&1 &
  sleep "\$PLATEAU_SEC"
fi
ip netns exec "\$NS" pkill -f 'iperf3 -c' 2>/dev/null || true
EOF
  exit 0
fi

# --- Default: tc-ramp (continuous offer, rising shaper) ---
# WHY CE uplink + BE lift, not PE eth0 1:15 alone:
#   ce-a → PE is IPsec/MPLS-encapsulated on eth0, so dport/ToS filters miss and
#   traffic lands in default BE 1:20 (nominal ceil 24). Changing PE 1:15 is a
#   no-op for measured util; leaving 1:20 at 24 hard-caps eth0 ~24 even when CE
#   ceil is higher. Shape on ce-a veth *before* encrypt, and temporarily lift
#   PE 1:20 to parent 40 so CE is the sole rate limit visible on eth0.
run <<EOF
set -euo pipefail
NS='$NS'; DST='$DST'; PORT=$PORT; PARALLEL=$PARALLEL
IFACE='$IFACE'; CLASSID='$CLASSID'
CE_IFACE='veth-cea-pe'
BE_CLASSID='1:20'
STEPS=$STEPS; STEP_SEC=$STEP_SEC; START_MBIT=$START_MBIT; END_MBIT=$END_MBIT
PLATEAU_SEC=$PLATEAU_SEC; OFFER_MBIT=$OFFER_MBIT
TOTAL=$((STEPS * STEP_SEC + PLATEAU_SEC + 10))
per_offer=\$(( OFFER_MBIT / PARALLEL )); [[ "\$per_offer" -lt 1 ]] && per_offer=1

# Snapshot PE 1:15 + BE 1:20 for restore
ORIG=\$(tc class show dev "\$IFACE" classid "\$CLASSID" | head -1 || true)
ORIG_BE=\$(tc class show dev "\$IFACE" classid "\$BE_CLASSID" | head -1 || true)
echo "orig_pe_class: \$ORIG"
echo "orig_pe_be: \$ORIG_BE"
RATE0=\$(echo "\$ORIG" | sed -n 's/.*rate \([0-9.]*[Mm]bit\).*/\1/p' | head -1)
CEIL0=\$(echo "\$ORIG" | sed -n 's/.*ceil \([0-9.]*[Mm]bit\).*/\1/p' | head -1)
BE_RATE0=\$(echo "\$ORIG_BE" | sed -n 's/.*rate \([0-9.]*[Mm]bit\).*/\1/p' | head -1)
BE_CEIL0=\$(echo "\$ORIG_BE" | sed -n 's/.*ceil \([0-9.]*[Mm]bit\).*/\1/p' | head -1)
[[ -z "\$RATE0" ]] && RATE0=28mbit
[[ -z "\$CEIL0" ]] && CEIL0=34mbit
[[ -z "\$BE_RATE0" ]] && BE_RATE0=5mbit
[[ -z "\$BE_CEIL0" ]] && BE_CEIL0=24mbit

# Lift BE once for the whole window (encapped util traffic lands here)
tc class change dev "\$IFACE" classid "\$BE_CLASSID" htb rate "\$BE_RATE0" ceil 40mbit prio 5 2>/dev/null || true
echo "[\$(date -u +%H:%M:%S)] lifted PE \$BE_CLASSID ceil→40mbit (was \$BE_CEIL0) so CE shape can show on eth0"

set_ceil() {
  local mbit="\$1"
  local rate=\$(( mbit * 8 / 10 )); [[ "\$rate" -lt 1 ]] && rate=1
  # Recreate CE HTB each step — mid-flight class replace fails on this kernel.
  ip netns exec "\$NS" tc qdisc del dev "\$CE_IFACE" root 2>/dev/null || true
  ip netns exec "\$NS" tc qdisc add dev "\$CE_IFACE" root handle 1: htb default 15
  ip netns exec "\$NS" tc class add dev "\$CE_IFACE" parent 1: classid 1:1 htb rate 40mbit ceil 40mbit
  ip netns exec "\$NS" tc class add dev "\$CE_IFACE" parent 1:1 classid 1:15 htb rate "\${rate}mbit" ceil "\${mbit}mbit" prio 2
  # Mirror on PE payload class (audit / twin; encapped flows still miss PE 1:15)
  tc class change dev "\$IFACE" classid "\$CLASSID" htb rate "\${rate}mbit" ceil "\${mbit}mbit" prio 2 2>/dev/null || true
}

restore() {
  ip netns exec "\$NS" tc qdisc del dev "\$CE_IFACE" root 2>/dev/null || true
  tc class change dev "\$IFACE" classid "\$CLASSID" htb rate "\$RATE0" ceil "\$CEIL0" prio 2 2>/dev/null || true
  tc class change dev "\$IFACE" classid "\$BE_CLASSID" htb rate "\$BE_RATE0" ceil "\$BE_CEIL0" prio 5 2>/dev/null || true
  ip netns exec "\$NS" pkill -f 'iperf3 -c' 2>/dev/null || true
  echo "[\$(date -u +%H:%M:%S)] restored CE \$CE_IFACE + PE \$CLASSID=\$RATE0/\$CEIL0 + PE \$BE_CLASSID=\$BE_RATE0/\$BE_CEIL0"
}
trap restore EXIT

: > /tmp/deca_util_ceil_schedule.jsonl
echo "[\$(date -u +%H:%M:%S)] start continuous offer \${OFFER_MBIT}Mbit (≥2× end=\${END_MBIT}) for \${TOTAL}s (shape on CE \$CE_IFACE)"
ip netns exec "\$NS" iperf3 -c "\$DST" -P "\$PARALLEL" -b \${per_offer}M -t "\$TOTAL" -p "\$PORT" \
  >/tmp/deca_util_cong.log 2>&1 &
# Note: no --tos needed — CE HTB default 15 catches all CE egress during inject.
sleep 2

for i in \$(seq 0 \$((STEPS - 1))); do
  mbit=\$(( START_MBIT + (END_MBIT - START_MBIT) * i / (STEPS - 1) ))
  now=\$(date +%s)
  echo "[\$(date -u +%H:%M:%S)] tc-ramp step \$i/\$STEPS CE+PE ceil=\${mbit}Mbit offer=\${OFFER_MBIT}Mbit"
  set_ceil "\$mbit"
  printf '{"ts_unix":%s,"htb_payload_ceil_mbps":%s,"phase":"ramp","step":%s,"end_mbit":%s,"offer_mbit":%s,"shape":"ce_veth","be_lifted":true}\n' \
    "\$now" "\$mbit" "\$i" "\$END_MBIT" "\$OFFER_MBIT" >> /tmp/deca_util_ceil_schedule.jsonl
  sleep "\$STEP_SEC"
done

if [[ "\$PLATEAU_SEC" -gt 0 ]]; then
  now=\$(date +%s)
  echo "[\$(date -u +%H:%M:%S)] PLATEAU ceil=\${END_MBIT}Mbit offer=\${OFFER_MBIT}Mbit for \${PLATEAU_SEC}s"
  set_ceil "\$END_MBIT"
  printf '{"ts_unix":%s,"htb_payload_ceil_mbps":%s,"phase":"plateau","step":-1,"end_mbit":%s,"offer_mbit":%s,"shape":"ce_veth","be_lifted":true}\n' \
    "\$now" "\$END_MBIT" "\$END_MBIT" "\$OFFER_MBIT" >> /tmp/deca_util_ceil_schedule.jsonl
  sleep "\$PLATEAU_SEC"
fi

echo "[\$(date -u +%H:%M:%S)] tc-ramp complete"
tail -8 /tmp/deca_util_cong.log 2>/dev/null || true
EOF

# Pull schedule sidecar to brain (CAPTURE_CONTRACT util labeling)
if [[ -n "$SCHEDULE_OUT" ]]; then
  mkdir -p "$(dirname "$SCHEDULE_OUT")"
  scp -q "${HOST}:/tmp/deca_util_ceil_schedule.jsonl" "$SCHEDULE_OUT" \
    && echo "wrote schedule $SCHEDULE_OUT" \
    || echo "WARN: could not scp util ceil schedule from $HOST"
fi

echo "[$(date -u +%H:%M:%S)] inject finished"
