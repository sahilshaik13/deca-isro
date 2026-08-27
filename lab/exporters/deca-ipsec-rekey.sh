#!/usr/bin/env bash
# IPsec SA age + rekey event counters for Telegraf (PS13-O2.3 groundwork).
# Emits Influx lines scraped via edge :9273.
set -euo pipefail
out=$(sudo ipsec statusall 2>/dev/null || sudo ipsec status 2>/dev/null || true)
age=0
if echo "$out" | grep -q 'ESTABLISHED'; then
  line=$(echo "$out" | grep ESTABLISHED | head -1)
  if echo "$line" | grep -qoE '[0-9]+ seconds ago'; then
    age=$(echo "$line" | grep -oE '[0-9]+ seconds ago' | awk '{print $1}')
  elif echo "$line" | grep -qoE '[0-9]+ minutes ago'; then
    age=$(echo "$line" | grep -oE '[0-9]+ minutes ago' | awk '{print $1*60}')
  elif echo "$line" | grep -qoE '[0-9]+ hours ago'; then
    age=$(echo "$line" | grep -oE '[0-9]+ hours ago' | awk '{print $1*3600}')
  fi
fi
nsa=$(echo "$out" | grep -c 'INSTALLED, TUNNEL' || true)

# Rekey / CHILD_SA establish events in last hour (charon syslog)
rekey_1h=0
if command -v journalctl >/dev/null 2>&1; then
  rekey_1h=$(journalctl --since "1 hour ago" 2>/dev/null \
    | grep -ciE 'rekey|CHILD_SA.*(established|install)|IKE_SA.*(rekey|reauthentic)' || true)
fi
if [[ "${rekey_1h}" -eq 0 ]] && [[ -r /var/log/syslog ]]; then
  # best-effort fallback: count matching lines with today's date prefix is weak;
  # still useful when journal is empty
  rekey_1h=$(grep -ciE 'rekey|CHILD_SA.*established' /var/log/syslog 2>/dev/null | head -1 || true)
  rekey_1h=${rekey_1h:-0}
fi

# Simple on-box anomaly flag (rate threshold; brain may refine)
anom=0
if [[ "${rekey_1h}" -ge 3 ]]; then
  anom=1
fi

printf "ipsec_sa_age_s value=%s\n" "${age:-0}"
printf "ipsec_child_sa_count value=%s\n" "${nsa:-0}"
printf "ipsec_rekey_events_1h value=%s\n" "${rekey_1h:-0}"
printf "ipsec_rekey_events_total value=%s\n" "${rekey_1h:-0}"
printf "ipsec_rekey_anomaly value=%s\n" "${anom}"
