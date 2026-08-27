#!/usr/bin/env bash
# deca-htb-payload-ceil.sh — live HTB payload class (1:15) ceil from tc.
#
# Reads the *actual* configured ceil on the PE WAN (default eth0), not an inject
# sidecar. Same signal util congestion changes via `tc class change`, and the
# same value present at steady state (~34 Mbit on 40 Mbit WAN).
#
# Emits Influx line protocol for Telegraf → Kafka bridge → Prometheus.
set -euo pipefail

IFACE="${DECA_HTB_IFACE:-eth0}"
CLASSID="${DECA_HTB_PAYLOAD_CLASSID:-1:15}"
HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo pe)}"
NOMINAL="${DECA_HTB_PAYLOAD_CEIL_NOMINAL:-34}"

line=$(tc class show dev "$IFACE" classid "$CLASSID" 2>/dev/null | head -1 || true)
ceil_mbps="$NOMINAL"
if [[ -n "$line" ]]; then
  # Prefer Mbit; fall back to Kbit (tc sometimes prints Kbit).
  raw=$(echo "$line" | sed -n 's/.*ceil \([0-9.]*\)Mbit.*/\1/p' | head -1)
  if [[ -n "$raw" ]]; then
    ceil_mbps=$(python3 -c "print(round(float('$raw'), 3))")
  else
    rawk=$(echo "$line" | sed -n 's/.*ceil \([0-9.]*\)Kbit.*/\1/p' | head -1)
    if [[ -n "$rawk" ]]; then
      ceil_mbps=$(python3 -c "print(round(float('$rawk')/1000.0, 3))")
    fi
  fi
fi

printf "htb_payload_ceil_mbps,host=%s,ifName=%s,classid=%s value=%s\n" \
  "$HOST" "$IFACE" "$CLASSID" "$ceil_mbps"
