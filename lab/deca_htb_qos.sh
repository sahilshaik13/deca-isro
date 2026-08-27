#!/usr/bin/env bash
# deca_htb_qos.sh — PS13 aerospace QoS on a WAN interface (default eth0).
#
# Wire marks (DECA PS13 convention — not IETF PHB ToS names):
#   TT&C   ToS 0x88 (136) → HTB 1:10 LLQ / strict priority
#   Payload ToS 0x80 (128) → HTB 1:15 ~70% of link + RED early-drop ~85%
#   Admin/BE default       → HTB 1:20 scavenger
#
# Also matches legacy EF 0xb8 into 1:10 and AF41 0x88 was TT&C under PS13;
# port fallbacks :5004→1:10, :5006→1:15 for iperf class flows.
#
# Usage (on a PE, as root):
#   IF=eth0 RATE=40mbit bash lab/deca_htb_qos.sh
#   FORCE=1 IF=eth0 bash lab/deca_htb_qos.sh   # replace even if HTB present
#
# Idempotent unless FORCE=1. Does not touch models/.
set -euo pipefail

IF="${IF:-eth0}"
RATE="${RATE:-40mbit}"
FORCE="${FORCE:-0}"

# Parse numeric mbit for payload share math (default 40)
RATE_NUM="${RATE%mbit}"
RATE_NUM="${RATE_NUM%Mbit}"
RATE_NUM="${RATE_NUM%M}"
if ! [[ "$RATE_NUM" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  RATE_NUM=40
fi

# TT&C: small guaranteed, high prio, full ceil (LLQ behavior under HTB prio)
TTC_RATE="2mbit"
TTC_CEIL="${RATE}"

# Payload: 70% of link capacity reserved; ceil capped near 85% for early pressure
PAY_RATE="$(awk -v r="$RATE_NUM" 'BEGIN{printf "%.0fmbit", r*0.70}')"
PAY_CEIL="$(awk -v r="$RATE_NUM" 'BEGIN{printf "%.0fmbit", r*0.85}')"

# Scavenger leftover
BE_RATE="5mbit"
BE_CEIL="$(awk -v r="$RATE_NUM" 'BEGIN{printf "%.0fmbit", r*0.60}')"

if [[ "$FORCE" != "1" ]] && tc qdisc show dev "$IF" 2>/dev/null | grep -q 'qdisc htb 1:'; then
  # Upgrade in place if PS13 Payload mark (0x80 → 1:15) filter missing
  if tc filter show dev "$IF" 2>/dev/null | grep -q 'tos 80'; then
    echo "[deca_htb_qos] $IF already has PS13 HTB (0x80 filter present) — skip"
    exit 0
  fi
  echo "[deca_htb_qos] $IF has HTB but not PS13 filters — replacing"
  FORCE=1
fi

tc qdisc del dev "$IF" root 2>/dev/null || true
tc qdisc add dev "$IF" root handle 1: htb default 20
tc class add dev "$IF" parent 1: classid 1:1 htb rate "$RATE" ceil "$RATE"
tc class add dev "$IF" parent 1:1 classid 1:10 htb rate "$TTC_RATE" ceil "$TTC_CEIL" prio 1
tc class add dev "$IF" parent 1:1 classid 1:15 htb rate "$PAY_RATE" ceil "$PAY_CEIL" prio 2
tc class add dev "$IF" parent 1:1 classid 1:20 htb rate "$BE_RATE" ceil "$BE_CEIL" prio 5

# LLQ leaf — low latency fairness among TT&C microflows
tc qdisc add dev "$IF" parent 1:10 handle 10: sfq perturb 10

# WRED-style early drop on Payload (Linux RED). avpkt≈1000; min/max near 85% fill.
# limit/min/max are byte thresholds for the RED qdisc queue.
tc qdisc add dev "$IF" parent 1:15 handle 15: red \
  limit 500000 min 350000 max 425000 avpkt 1000 burst 40 probability 0.2 ecn 2>/dev/null \
  || tc qdisc add dev "$IF" parent 1:15 handle 15: sfq perturb 10

tc qdisc add dev "$IF" parent 1:20 handle 20: sfq perturb 10

# u32 TOS match uses the ToS octet; mask 0xfc keeps DSCP bits
# PS13 primary:
tc filter add dev "$IF" protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
tc filter add dev "$IF" protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
# Legacy EF still maps to TT&C LLQ (older generators)
tc filter add dev "$IF" protocol ip parent 1:0 prio 3 u32 match ip tos 0xb8 0xfc flowid 1:10
# Port fallbacks (iperf class ports)
tc filter add dev "$IF" protocol ip parent 1:0 prio 4 u32 match ip dport 5004 0xffff flowid 1:10
tc filter add dev "$IF" protocol ip parent 1:0 prio 5 u32 match ip dport 5006 0xffff flowid 1:15

echo "[deca_htb_qos] installed on $IF parent=$RATE TT&C=1:10@$TTC_RATE Payload=1:15@$PAY_RATE(ceil $PAY_CEIL≈85%) BE=1:20"
tc class show dev "$IF" | head -20
