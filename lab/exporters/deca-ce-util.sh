#!/usr/bin/env bash
# deca-ce-util.sh — per-CE util (Mbps) from PE veth counters (Influx line protocol).
set -euo pipefail

STATE_DIR="${DECA_CE_UTIL_STATE:-/tmp/deca_ce_util}"
mkdir -p "$STATE_DIR"
HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo pe)}"
NOW=$(date +%s)

# CE → PE attachment veth (present only on the owning PE)
declare -A IFACE=(
  [ce-a]=veth-pe-cea
  [ce-mauritius]=veth-pe-cem
  [ce-b]=veth-pe-ceb
  [ce-mcf]=veth-pe-cemcf
)

for ce in ce-a ce-mauritius ce-b ce-mcf; do
  ifn="${IFACE[$ce]}"
  [[ -d "/sys/class/net/$ifn" ]] || continue
  rx=$(cat "/sys/class/net/$ifn/statistics/rx_bytes" 2>/dev/null || echo 0)
  tx=$(cat "/sys/class/net/$ifn/statistics/tx_bytes" 2>/dev/null || echo 0)
  total=$((rx + tx))
  sf="$STATE_DIR/${ce}.state"
  mbps=0
  if [[ -f "$sf" ]]; then
    read -r prev_t prev_b <"$sf" || true
    if [[ -n "${prev_t:-}" && -n "${prev_b:-}" && "$NOW" -gt "$prev_t" ]]; then
      dt=$((NOW - prev_t))
      db=$((total - prev_b))
      if [[ "$dt" -gt 0 && "$db" -ge 0 ]]; then
        mbps=$(python3 -c "print(round(($db)*8.0/($dt)/1e6, 3))")
      fi
    fi
  fi
  echo "$NOW $total" >"$sf"
  echo "ce_util_mbps,ce=${ce},host=${HOST},ifName=${ifn} value=${mbps}"
done
