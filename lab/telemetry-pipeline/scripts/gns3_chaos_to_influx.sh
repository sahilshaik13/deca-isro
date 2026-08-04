#!/usr/bin/env bash
# Emit Influx lines from GNS3 chaos_state.json for telegraf-gns3 → Kafka.
# Pure bash (telegraf image has no python). Same metric names as Pi probes.
set -euo pipefail
STATE="${DECA_GNS3_CHAOS_STATE:-/state/chaos_state.json}"
HOST="${DECA_GNS3_HOST_TAG:-gns3-pe1}"
ts="$(date +%s)000000000"

json_num() {
  local key="$1" default="$2"
  if [[ ! -f "$STATE" ]]; then
    echo "$default"
    return
  fi
  # Match "key": 1.23 or "key":1
  local v
  v="$(grep -oE "\"${key}\"[[:space:]]*:[[:space:]]*-?[0-9]+([.][0-9]+)?" "$STATE" 2>/dev/null | head -1 | grep -oE -- '-?[0-9]+([.][0-9]+)?$' || true)"
  if [[ -n "${v:-}" ]]; then
    echo "$v"
  else
    echo "$default"
  fi
}

lat_gre="$(json_num latency_gre_ms 8.0)"
lat_eth0="$(json_num latency_eth0_ms 12.0)"
jit="$(json_num jitter_gre_ms 0.5)"
loss="$(json_num loss_gre_pct 0.0)"
util="$(json_num util_gre_mbps 2.5)"
cpu_s="$(json_num cpu_usage_system 5.0)"
cpu_u="$(json_num cpu_usage_user 8.0)"
mem="$(json_num mem_used_percent 35.0)"
bgp="$(json_num bgp_flap_count 0.0)"

tags="host=${HOST},fabric=gns3,src=edge"
echo "sdwan_path_latency_ms,${tags},path=gre value=${lat_gre} ${ts}"
echo "sdwan_path_latency_ms,${tags},path=eth0 value=${lat_eth0} ${ts}"
echo "sdwan_path_jitter_ms,host=${HOST},fabric=gns3,path=gre value=${jit} ${ts}"
echo "sdwan_path_loss_pct,${tags},path=gre value=${loss} ${ts}"
echo "sdwan_path_util_mbps,host=${HOST},fabric=gns3,path=gre value=${util} ${ts}"
echo "cpu_usage_system,host=${HOST},fabric=gns3 value=${cpu_s} ${ts}"
echo "cpu_usage_user,host=${HOST},fabric=gns3 value=${cpu_u} ${ts}"
echo "mem_used_percent,host=${HOST},fabric=gns3 value=${mem} ${ts}"
echo "bgp_flap_count,host=${HOST},fabric=gns3 value=${bgp} ${ts}"
