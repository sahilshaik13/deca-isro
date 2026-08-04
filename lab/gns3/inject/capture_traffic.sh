#!/usr/bin/env bash
# GNS3 twin of scripts/run_capture_traffic.sh — light background util overlay + optional iperf.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

PROFILE=${PROFILE:-idle}
DUR=${DUR:-${SECONDS_RUN:-60}}
CLEAR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --seconds|--duration) DUR="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

stop_iperf() {
  docker ps --format '{{.Names}}' | grep -E '^gns3-cap-traffic' | xargs -r docker rm -f >/dev/null 2>&1 || true
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  stop_iperf
  # only reset traffic gauges if we own the fault id
  cur="$(python3 -c "import json;from pathlib import Path;p=Path('$SCRIPT_DIR/../state/chaos_state.json');
print(json.loads(p.read_text()).get('fault_id','') if p.exists() else '')" 2>/dev/null || true)"
  if [[ -z "$cur" || "$cur" == "capture_traffic" ]]; then
    patch_state fault_id= util_gre_mbps=2.5 ce_util_mbps_bronze=2 ce_util_mbps_gold=4
  fi
  echo "cleared capture traffic"
  exit 0
fi

case "$PROFILE" in
  idle)
    stop_iperf
    echo "traffic profile=idle"
    exit 0
    ;;
  ttc_light)
    UTIL=4; GOLD=3; BRONZE=2
    ;;
  payload_medium)
    UTIL=10; GOLD=4; BRONZE=8
    ;;
  mixed)
    UTIL=8; GOLD=3; BRONZE=6
    ;;
  *) echo "bad profile $PROFILE"; exit 2 ;;
esac

patch_state fault_id=capture_traffic util_gre_mbps="$UTIL" ce_util_mbps_gold="$GOLD" ce_util_mbps_bronze="$BRONZE"
echo "gns3 traffic profile=$PROFILE util=$UTIL for ${DUR}s"
sleep "$DUR"
stop_iperf
patch_state fault_id= util_gre_mbps=2.5 ce_util_mbps_bronze=2 ce_util_mbps_gold=4
echo "gns3 traffic profile done"
