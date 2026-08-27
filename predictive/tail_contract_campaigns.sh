#!/usr/bin/env bash
# Unified live tail for Pi + GNS3 CAPTURE_CONTRACT full campaigns.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PI_STAMP="${1:-$(cat /tmp/deca_pi_contract_stamp.txt 2>/dev/null || true)}"
GNS_STAMP="${2:-$(cat /tmp/deca_gns3_contract_stamp.txt 2>/dev/null || true)}"
PI_STAMP="${PI_STAMP:-full_variants_pi_contract_20260805T042130Z}"
[[ -n "${GNS_STAMP:-}" ]] || { echo "need GNS stamp (arg2 or /tmp/deca_gns3_contract_stamp.txt)"; exit 2; }
PI_LOG="$ROOT/data/deca/predictive/protocol/${PI_STAMP}/campaign.log"
GNS_LOG="$ROOT/data/deca/predictive/protocol_gns3/${GNS_STAMP}/campaign.log"
mkdir -p "$(dirname "$PI_LOG")" "$(dirname "$GNS_LOG")"
touch "$PI_LOG" "$GNS_LOG"
echo "PI  $PI_LOG"
echo "GNS $GNS_LOG"
echo "--- Ctrl-C to stop tail (campaigns keep running) ---"
exec tail -F "$PI_LOG" "$GNS_LOG"
