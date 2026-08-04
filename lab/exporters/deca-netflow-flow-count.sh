#!/usr/bin/env bash
# Real softflowd IPFIX/NetFlow summary for Prometheus (Tier-5 pattern).
# Primary metrics from softflowctl dump-flows / statistics.
# netflow_proxy_flow_count remains the cheap conntrack fallback.
#
# Safe under Telegraf inputs.exec: pipefail + `head` must not SIGPIPE (exit 141).
set -euo pipefail

softflowctl_cmd() {
  if [[ "$(id -u)" -eq 0 ]]; then
    softflowctl "$@"
  else
    sudo -n softflowctl "$@"
  fi
}

CTL="${SOFTFLOWD_CTL:-/var/run/softflowd.ctl}"
DUMP_DIR="${SOFTFLOWD_DUMP_DIR:-/var/lib/deca-softflowd}"
mkdir -p "$DUMP_DIR" 2>/dev/null || true
chmod 1777 "$DUMP_DIR" 2>/dev/null || true

flows=0
bytes=0
pkts=0
top=0
voice_bytes=0
video_bytes=0
bulk_bytes=0
ipfix_datagrams=0

# Extract first regex match without SIGPIPE from `head` under pipefail.
first_re() {
  local s="$1" re="$2"
  [[ "$s" =~ $re ]] && printf '%s\n' "${BASH_REMATCH[1]}" || true
}

if [[ -S "$CTL" ]] && command -v softflowctl >/dev/null 2>&1; then
  set +e
  stats=$(softflowctl_cmd -c "$CTL" statistics 2>/dev/null)
  if [[ -n "$stats" ]]; then
    af=$(printf '%s\n' "$stats" | awk -F: '/Number of active flows/ {gsub(/ /,"",$2); print $2; exit}')
    [[ -n "${af:-}" ]] && flows=$af
    mx=$(printf '%s\n' "$stats" | awk '/Flow bytes:/ {print $4; exit}')
    [[ -n "${mx:-}" ]] && top=$mx
  fi

  # Cap dump-flows — large tables overrun Telegraf timeouts (SIGTERM / 141).
  if [[ "$(id -u)" -eq 0 ]]; then
    dump=$(timeout 2s softflowctl -c "$CTL" dump-flows 2>/dev/null)
  else
    dump=$(timeout 2s sudo -n softflowctl -c "$CTL" dump-flows 2>/dev/null)
  fi
  dump_file="$DUMP_DIR/last_dump_flows.txt"
  if ! printf '%s\n' "${dump:-}" >"$dump_file" 2>/dev/null; then
    dump_file="/tmp/deca-softflowd-last_dump_flows.$UID.txt"
    printf '%s\n' "${dump:-}" >"$dump_file" 2>/dev/null || true
  fi
  if [[ -n "${dump:-}" ]]; then
    while IFS= read -r line; do
      [[ "$line" == ACTIVE* ]] || continue
      o1=$(first_re "$line" 'octets>:([0-9]+)')
      o2=$(first_re "$line" 'octets<:([0-9]+)')
      p1=$(first_re "$line" 'packets>:([0-9]+)')
      p2=$(first_re "$line" 'packets<:([0-9]+)')
      o1=${o1:-0}; o2=${o2:-0}; p1=${p1:-0}; p2=${p2:-0}
      ob=$((o1 + o2))
      pb=$((p1 + p2))
      bytes=$((bytes + ob))
      pkts=$((pkts + pb))
      if (( ob > top )); then top=$ob; fi
      if [[ "$line" == *']:5004 '* ]]; then voice_bytes=$((voice_bytes + ob)); fi
      if [[ "$line" == *']:5006 '* ]]; then video_bytes=$((video_bytes + ob)); fi
      if [[ "$line" == *']:5201 '* ]]; then bulk_bytes=$((bulk_bytes + ob)); fi
    done <<<"$dump"
    ac=$(printf '%s\n' "$dump" | grep -c '^ACTIVE')
    if [[ "${ac:-0}" -gt 0 ]]; then flows=$ac; fi
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

printf "netflow_flow_count value=%s\n" "${flows:-0}"
printf "netflow_bytes_total value=%s\n" "${bytes:-0}"
printf "netflow_packets_total value=%s\n" "${pkts:-0}"
printf "netflow_top_talker_bytes value=%s\n" "${top:-0}"
printf "netflow_voice_bytes value=%s\n" "${voice_bytes:-0}"
printf "netflow_video_bytes value=%s\n" "${video_bytes:-0}"
printf "netflow_bulk_bytes value=%s\n" "${bulk_bytes:-0}"
printf "netflow_ipfix_datagrams value=%s\n" "${ipfix_datagrams:-0}"
printf "netflow_proxy_flow_count value=%s\n" "${proxy:-0}"
exit 0
