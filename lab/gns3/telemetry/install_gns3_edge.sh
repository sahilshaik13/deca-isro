#!/usr/bin/env bash
# install_gns3_edge.sh — prepare SNMP / syslog / IPFIX / 1Hz probe agents on GNS3 nodes.
#
# Prefer host-side telegraf-gns3 (compose) for Kafka until L3 is live.
# This script installs in-node agents after "Start all" so future SNMP/syslog
# inputs can be enabled in telegraf.gns3.conf.
#
# Usage (from brain, GNS3 project DECA running):
#   bash lab/gns3/telemetry/install_gns3_edge.sh
#   bash lab/gns3/telemetry/install_gns3_edge.sh --dry-run
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

# GNS3 docker nodes are named like PE1-1, CE-NRSC-1 depending on version.
# Match by substring.
TARGETS=(PE1 PE2 CORE-N CE-NRSC CE-SAC)

echo "=== GNS3 edge telemetry prepare (snmpd / syslog / softflowd stubs) ==="
echo "Repo: $ROOT"
echo "Note: primary 1Hz path is already compose gns3-exporter + telegraf-gns3 → Kafka."
echo

list_containers() {
  docker ps --format '{{.ID}} {{.Names}}' 2>/dev/null || true
}

run_in() {
  local cid="$1"
  shift
  if [[ "$DRY" -eq 1 ]]; then
    echo "DRY docker exec $cid $*"
    return 0
  fi
  docker exec "$cid" sh -c "$*" 2>/dev/null || \
    echo "WARN: exec failed on $cid ($*)"
}

found=0
while read -r cid name; do
  [[ -z "${cid:-}" ]] && continue
  for t in "${TARGETS[@]}"; do
    case "$name" in
      *"$t"*)
        found=1
        echo "--- $name ($cid) ---"
        # Alpine / FRR: best-effort package install (needs outbound once, or cached)
        run_in "$cid" "command -v snmpd >/dev/null 2>&1 || (apk add --no-cache net-snmp net-snmp-tools 2>/dev/null || true)"
        run_in "$cid" "command -v softflowd >/dev/null 2>&1 || (apk add --no-cache softflowd 2>/dev/null || true)"
        run_in "$cid" "mkdir -p /etc/snmp /var/lib/deca-softflowd 2>/dev/null; true"
        run_in "$cid" "grep -q 'deca-lab' /etc/snmp/snmpd.conf 2>/dev/null || echo 'rocommunity deca-lab 127.0.0.1' >> /etc/snmp/snmpd.conf 2>/dev/null || true"
        run_in "$cid" "command -v snmpd >/dev/null && (pkill snmpd 2>/dev/null; snmpd -c /etc/snmp/snmpd.conf) || true"
        # FRR logs → syslog UDP toward host telegraf (5515) when networking allows
        run_in "$cid" "mkdir -p /etc/rsyslog.d 2>/dev/null; echo '*.* @host.docker.internal:5515' > /etc/rsyslog.d/deca-frr.conf 2>/dev/null || true"
        echo "  stub agents attempted (snmpd/softflowd/rsyslog drop-in)"
        ;;
    esac
  done
done < <(list_containers)

if [[ "$found" -eq 0 ]]; then
  echo "No matching GNS3 docker containers found (is DECA started?)."
  echo "Collectors still work via:"
  echo "  - gns3-exporter :9275 (scraped by Prom :9091)"
  echo "  - telegraf-gns3 → Kafka sdwan_telemetry_gns3 → bridge :9276"
  exit 0
fi

echo
echo "Done. When nodes have IPs + snmpd listening, uncomment SNMP/syslog in"
echo "  lab/telemetry-pipeline/telegraf.gns3.conf"
echo "and recreate: docker compose -f lab/telemetry-pipeline/docker-compose.yml up -d telegraf-gns3"
