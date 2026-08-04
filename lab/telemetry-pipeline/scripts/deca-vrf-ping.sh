#!/usr/bin/env bash
# Emit Influx ping stats via VRF (mission CE prefixes are not in default table).
# Usage: deca-vrf-ping.sh <target> [vrf]
# Example: deca-vrf-ping.sh 10.100.3.1 vrf-mission
set -euo pipefail

TARGET="${1:?target IP required}"
VRF="${2:-vrf-mission}"
COUNT="${PING_COUNT:-3}"
TIMEOUT="${PING_WAIT:-2}"
TAG_HOST="${HOSTNAME:-$(hostname -s)}"

if [[ "$(id -u)" -eq 0 ]]; then
  out=$(ip vrf exec "$VRF" ping -n -c "$COUNT" -W "$TIMEOUT" "$TARGET" 2>/dev/null || true)
else
  out=$(sudo -n ip vrf exec "$VRF" ping -n -c "$COUNT" -W "$TIMEOUT" "$TARGET" 2>/dev/null || true)
fi

# packet loss percent
loss=$(printf '%s\n' "$out" | awk -F',' '/packet loss/ {
  for (i=1;i<=NF;i++) if ($i ~ /packet loss/) { gsub(/[^0-9.]/,"",$i); print $i; exit }
}')
loss=${loss:-100}

# rtt min/avg/max
avg=$(printf '%s\n' "$out" | awk -F'=' '/rtt|round-trip/ {
  split($2,a,"/"); gsub(/ /,"",a[2]); print a[2]; exit
}')
avg=${avg:-0}

# reachable?
ok=0
recv=$(printf '%s\n' "$out" | awk '/packets transmitted/ {
  for (i=1;i<=NF;i++) if ($(i)=="received," || $(i)=="received") { print $(i-1); exit }
}')
[[ "${recv:-0}" =~ ^[0-9]+$ ]] && (( recv > 0 )) && ok=1

safe_target=${TARGET//./_}
printf "vrf_ping_avg_ms,host=%s,target=%s,vrf=%s value=%s\n" \
  "$TAG_HOST" "$TARGET" "$VRF" "$avg"
printf "vrf_ping_loss_pct,host=%s,target=%s,vrf=%s value=%s\n" \
  "$TAG_HOST" "$TARGET" "$VRF" "$loss"
printf "vrf_ping_up,host=%s,target=%s,vrf=%s value=%s\n" \
  "$TAG_HOST" "$TARGET" "$VRF" "$ok"
