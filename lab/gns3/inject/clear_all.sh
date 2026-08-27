#!/usr/bin/env bash
# Clear all GNS3 demo chaos (NetEM + state)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter
apply_netem_pe1 clear
cid="$(find_pe1_container || true)"
[[ -n "$cid" ]] && docker exec "$cid" sh -c 'pkill -f stress || pkill -f dd || true' 2>/dev/null || true
patch_state fault_id= latency_gre_ms=8 latency_eth0_ms=12 jitter_gre_ms=0.5 loss_gre_pct=0 \
  util_gre_mbps=2.5 cpu_usage_system=5 cpu_usage_user=8 bgp_flap_count=0 \
  ce_util_mbps_bronze=2 ce_util_mbps_gold=4
echo "gns3 clear_all done"
