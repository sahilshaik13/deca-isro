#!/usr/bin/env bash
# LAN ping → Influx (avoids Telegraf inputs.ping stderr-as-error noise).
# Usage: deca-lan-ping.sh <target>
set -euo pipefail
TARGET="${1:?target}"
COUNT="${PING_COUNT:-3}"
TIMEOUT="${PING_WAIT:-2}"
TAG_HOST="${HOSTNAME:-$(hostname -s)}"

out=$(ping -n -c "$COUNT" -W "$TIMEOUT" "$TARGET" 2>/dev/null || true)
loss=$(printf '%s\n' "$out" | awk -F',' '/packet loss/ {
  for (i=1;i<=NF;i++) if ($i ~ /packet loss/) { gsub(/[^0-9.]/,"",$i); print $i; exit }
}')
loss=${loss:-100}
avg=$(printf '%s\n' "$out" | awk -F'=' '/rtt|round-trip/ {
  split($2,a,"/"); gsub(/ /,"",a[2]); print a[2]; exit
}')
avg=${avg:-0}
ok=0
recv=$(printf '%s\n' "$out" | awk '/packets transmitted/ {print $4; exit}')
recv=${recv:-0}
recv=${recv%,}
[[ "$recv" =~ ^[0-9]+$ ]] && (( recv > 0 )) && ok=1 || true

printf "lan_ping_avg_ms,host=%s,target=%s value=%s\n" "$TAG_HOST" "$TARGET" "$avg"
printf "lan_ping_loss_pct,host=%s,target=%s value=%s\n" "$TAG_HOST" "$TARGET" "$loss"
printf "lan_ping_up,host=%s,target=%s value=%s\n" "$TAG_HOST" "$TARGET" "$ok"
exit 0
