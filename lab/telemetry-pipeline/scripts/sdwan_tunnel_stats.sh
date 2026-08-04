#!/usr/bin/env bash
# Edge continuous underlay probe for Telegraf inputs.exec (Influx line protocol).
#
# Runs ON the PE (station1 / station2) — not on the brain.
# Probes gre-te-core and eth0 toward the peer PE; emits:
#   sdwan_path_latency_ms{path=gre|eth0}
#   sdwan_path_loss_pct{path=gre|eth0}
#
# Tuned for 1s Telegraf interval. Default -c 25 @ 30ms ≈ 0.75s burst so
# 8% vs 15%+ netem produce distinct Prom peaks (fractional % packet loss).
# Air-gapped: local ICMP only (no cloud).
set -euo pipefail

HOST_TAG="$(hostname -s 2>/dev/null || hostname | cut -d. -f1)"
COUNT="${DECA_PROBE_COUNT:-25}"
INTERVAL="${DECA_PROBE_INTERVAL:-0.03}"
WAIT="${DECA_PROBE_WAIT:-1}"

# Peer / via defaults (override via env on the Pi if needed)
case "$HOST_TAG" in
  station1)
    GRE_DEV="${DECA_GRE_DEV:-gre-te-core}"
    GRE_TARGET="${DECA_GRE_TARGET:-10.50.1.2}"          # CORE / GRE far end
    ETH_DEV="${DECA_ETH_DEV:-eth0}"
    ETH_TARGET="${DECA_ETH_TARGET:-192.168.50.20}"     # PE2
    ;;
  station2)
    GRE_DEV="${DECA_GRE_DEV:-gre-te-core}"
    GRE_TARGET="${DECA_GRE_TARGET:-10.50.2.2}"          # CORE / GRE far end
    ETH_DEV="${DECA_ETH_DEV:-eth0}"
    ETH_TARGET="${DECA_ETH_TARGET:-192.168.50.10}"     # PE1
    ;;
  *)
    GRE_DEV="${DECA_GRE_DEV:-gre-te-core}"
    GRE_TARGET="${DECA_GRE_TARGET:-10.50.1.2}"
    ETH_DEV="${DECA_ETH_DEV:-eth0}"
    ETH_TARGET="${DECA_ETH_TARGET:-192.168.50.20}"
    ;;
esac

parse_ping() {
  # stdin: ping output → prints "lat_ms loss_pct" (lat empty if no RTT)
  # Prefer fractional loss (e.g. 6.66667) so L4 end_pct variants are distinguishable.
  local text lat loss tx rx
  text="$(cat)"
  lat="$(printf '%s\n' "$text" | sed -n 's/.*= *\([0-9.]*\)\/\([0-9.]*\)\/.*/\2/p' | head -1)"
  if [[ -z "$lat" ]]; then
    lat="$(printf '%s\n' "$text" | awk -F'[=/]' '/rtt|round-trip/ {print $6; exit}')"
  fi
  loss="$(printf '%s\n' "$text" | sed -n 's/.*, \([0-9][0-9]*\.[0-9]*\)% packet loss.*/\1/p' | head -1)"
  if [[ -z "$loss" ]]; then
    loss="$(printf '%s\n' "$text" | sed -n 's/.*, \([0-9][0-9]*\)% packet loss.*/\1/p' | head -1)"
  fi
  # Fallback: derive from transmitted/received counts (always fractional-capable)
  if [[ -z "$loss" ]]; then
    tx="$(printf '%s\n' "$text" | sed -n 's/^\([0-9][0-9]*\) packets transmitted.*/\1/p' | head -1)"
    rx="$(printf '%s\n' "$text" | sed -n 's/.*, \([0-9][0-9]*\) received.*/\1/p' | head -1)"
    if [[ -n "${tx:-}" && -n "${rx:-}" && "$tx" -gt 0 ]]; then
      loss="$(awk -v t="$tx" -v r="$rx" 'BEGIN{printf "%.3f", (t-r)*100.0/t}')"
    fi
  fi
  [[ -z "$loss" ]] && loss="100"
  if [[ -z "$lat" ]]; then
    printf ' %s\n' "$loss"
  else
    printf '%s %s\n' "$lat" "$loss"
  fi
}

probe_one() {
  local path="$1" dev="$2" target="$3"
  local out lat loss
  LAST_LAT="0"
  if ! ip link show "$dev" &>/dev/null; then
    printf 'sdwan_path_latency_ms,host=%s,path=%s,src=edge value=0\n' "$HOST_TAG" "$path"
    printf 'sdwan_path_loss_pct,host=%s,path=%s,src=edge value=100\n' "$HOST_TAG" "$path"
    return
  fi
  out="$(ping -c "$COUNT" -i "$INTERVAL" -W "$WAIT" -I "$dev" "$target" 2>&1 || true)"
  read -r lat loss <<<"$(printf '%s\n' "$out" | parse_ping)"
  if [[ -n "${lat:-}" ]]; then
    LAST_LAT="$lat"
    printf 'sdwan_path_latency_ms,host=%s,path=%s,src=edge value=%s\n' "$HOST_TAG" "$path" "$lat"
  else
    # no RTT — still emit loss; omit latency or use 0 with loss=100
    printf 'sdwan_path_latency_ms,host=%s,path=%s,src=edge value=0\n' "$HOST_TAG" "$path"
  fi
  printf 'sdwan_path_loss_pct,host=%s,path=%s,src=edge value=%s\n' "$HOST_TAG" "$path" "${loss:-100}"
}

probe_one gre "$GRE_DEV" "$GRE_TARGET"
gre_lat="${LAST_LAT:-0}"
probe_one eth0 "$ETH_DEV" "$ETH_TARGET"
eth_lat="${LAST_LAT:-0}"
# PS13-O2.2: named path asymmetry for Prom (abs GRE−eth0 RTT)
asym=$(awk -v g="$gre_lat" -v e="$eth_lat" 'BEGIN{d=g-e; if(d<0)d=-d; printf "%.3f", d}')
printf 'path_asymmetry_ms,host=%s,src=edge value=%s\n' "$HOST_TAG" "$asym"
printf 'path_asymmetry,host=%s,src=edge value=%s\n' "$HOST_TAG" "$asym"
