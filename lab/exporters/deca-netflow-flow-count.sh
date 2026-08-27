#!/usr/bin/env bash
# Fast softflowd summary for Telegraf (venue-safe).
# Prefer softflowctl statistics — avoid O(n) bash parse of dump-flows (was melting Pi CPU).
set -euo pipefail

CACHE=/var/tmp/deca-netflow.last
LOCK=/var/tmp/deca-netflow.lock
# _telegraf cannot write /run/lock — keep lock+cache under /var/tmp
exec 9>"$LOCK"
if ! flock -n 9; then
  if [[ -r "$CACHE" ]]; then
    cat "$CACHE"
  else
    printf 'netflow_flow_count value=0\n'
    printf 'netflow_bytes_total value=0\n'
    printf 'netflow_packets_total value=0\n'
    printf 'netflow_top_talker_bytes value=0\n'
    printf 'netflow_voice_bytes value=0\n'
    printf 'netflow_video_bytes value=0\n'
    printf 'netflow_bulk_bytes value=0\n'
    printf 'netflow_ipfix_datagrams value=0\n'
    printf 'netflow_proxy_flow_count value=0\n'
  fi
  exit 0
fi

softflowctl_cmd() {
  if [[ "$(id -u)" -eq 0 ]]; then
    softflowctl "$@"
  else
    sudo -n softflowctl "$@"
  fi
}

CTL="${SOFTFLOWD_CTL:-/var/run/softflowd.ctl}"
DUMP_DIR="${SOFTFLOWD_DUMP_DIR:-/var/lib/deca-softflowd}"

flows=0
bytes=0
pkts=0
top=0
voice_bytes=0
video_bytes=0
bulk_bytes=0
ipfix_datagrams=0

if [[ -S "$CTL" ]] && command -v softflowctl >/dev/null 2>&1; then
  set +e
  # Note: timeout cannot invoke bash functions — call softflowctl directly.
  if [[ "$(id -u)" -eq 0 ]]; then
    stats=$(timeout 2s softflowctl -c "$CTL" statistics 2>/dev/null)
  else
    stats=$(timeout 2s sudo -n softflowctl -c "$CTL" statistics 2>/dev/null)
  fi
  if [[ -n "${stats:-}" ]]; then
    af=$(printf '%s\n' "$stats" | awk -F: '/Number of active flows/ {gsub(/ /,"",$2); print $2; exit}')
    [[ -n "${af:-}" ]] && flows=$af
    # "Flow bytes: min X avg Y max Z" — fields after label
    mx=$(printf '%s\n' "$stats" | awk '/Flow bytes:/ {print $5; exit}')
    [[ -n "${mx:-}" && "$mx" != "average" ]] || mx=$(printf '%s\n' "$stats" | awk '/Flow bytes:/ {print $4; exit}')
    [[ -n "${mx:-}" ]] && top=$mx
    # Packets processed ≈ cumulative; use as packets_total proxy
    tp=$(printf '%s\n' "$stats" | awk -F: '/Packets processed/ {gsub(/ /,"",$2); print $2; exit}')
    [[ -n "${tp:-}" ]] && pkts=$tp
  fi
  set -e
fi

if [[ -r "$DUMP_DIR/datagram_count" ]]; then
  ipfix_datagrams=$(tr -d '[:space:]' <"$DUMP_DIR/datagram_count" || echo 0)
fi

proxy=0
if command -v conntrack >/dev/null 2>&1; then
  proxy=$(conntrack -C 2>/dev/null || echo 0)
elif [[ -r /proc/net/nf_conntrack ]]; then
  proxy=$(wc -l </proc/net/nf_conntrack | tr -d ' ')
else
  proxy=$(ss -tan state established 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
fi

{
  printf "netflow_flow_count value=%s\n" "${flows:-0}"
  printf "netflow_bytes_total value=%s\n" "${bytes:-0}"
  printf "netflow_packets_total value=%s\n" "${pkts:-0}"
  printf "netflow_top_talker_bytes value=%s\n" "${top:-0}"
  printf "netflow_voice_bytes value=%s\n" "${voice_bytes:-0}"
  printf "netflow_video_bytes value=%s\n" "${video_bytes:-0}"
  printf "netflow_bulk_bytes value=%s\n" "${bulk_bytes:-0}"
  printf "netflow_ipfix_datagrams value=%s\n" "${ipfix_datagrams:-0}"
  printf "netflow_proxy_flow_count value=%s\n" "${proxy:-0}"
} | tee "$CACHE"
exit 0
