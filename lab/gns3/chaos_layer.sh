#!/usr/bin/env bash
# Flow 1 Chaos layer — iperf3 + NetEM (+ CPU/BGP/util injects). No TRex.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/inject/_common.sh"
ensure_exporter

MODE="${1:-status}"

case "$MODE" in
  status)
    echo "Chaos tools (Pi twin — no TRex):"
    echo "  iperf3  — TCP/UDP ToS 0x88 TT&C / 0x80 Payload"
    echo "  NetEM   — latency / jitter / loss via lab/gns3/inject/*.sh"
    echo "  stress  — CPU / crypto (cpu_stress.sh)"
    echo "  BGP     — soft-clear flap (bgp_flap.sh)"
    echo
    curl -sf http://127.0.0.1:9275/metrics 2>/dev/null | grep -E 'sdwan_path_latency_ms|gns3_chaos' | head -10 || echo "exporter down — start: python3 lab/gns3/exporters/gns3_path_exporter.py"
    ;;
  baseline)
    patch_state util_gre_mbps=4 ce_util_mbps_gold=5 ce_util_mbps_bronze=2.5 fault_id=
    echo "baseline traffic gauges set (start real iperf on CEs when nodes are up)"
    ;;
  bronze-surge|ce-surge)
    # Mentor CE SLA conflict shape — real inject preferred
    bash "$SCRIPT_DIR/inject/ce_sla_conflict.sh"
    ;;
  netem-demo)
    bash "$SCRIPT_DIR/inject/rain_fade.sh"
    ;;
  *)
    echo "usage: $0 {status|baseline|bronze-surge|netem-demo}"
    exit 1
    ;;
esac
