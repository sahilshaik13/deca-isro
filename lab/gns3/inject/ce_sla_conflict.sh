#!/usr/bin/env bash
# GNS3 CE SLA conflict — Bronze surge vs Gold TT&C via real iperf3 (Pi twin).
# Mentor: name rogue vs victim; Bronze must not starve Gold.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

stop_iperf() {
  docker ps --format '{{.Names}}' | grep -E '^gns3-ce-sla-' | xargs -r docker rm -f >/dev/null 2>&1 || true
}

if [[ "${1:-}" == "--clear" ]]; then
  stop_iperf
  patch_state fault_id= ce_util_mbps_bronze=2 util_gre_mbps=2.5 ce_util_mbps_gold=4
  echo "cleared ce_sla_conflict"
  exit 0
fi

STEPS=${STEPS:-4}
STEP_SEC=${STEP_SEC:-15}
START_MBIT=${START_MBIT:-3}
END_MBIT=${END_MBIT:-20}
VICTIM_MBIT=${VICTIM_MBIT:-1}

IPA=$(cname IPERF-A || true)
IPB=$(cname IPERF-B || true)
MAU=$(cname CE-Mauritius || true)
NRSC=$(cname CE-NRSC || true)

# Prefer CE-Mauritius → SAC path; fall back to IPERF-A/B mesh
SRC="${MAU:-$IPA}"
DST_PEER="${IPB}"
if [[ -z "$SRC" || -z "$DST_PEER" ]]; then
  if [[ "$REQUIRE_LIVE" == "1" ]]; then
    echo "ERROR: need CE-Mauritius or IPERF-A/B for CE SLA conflict" >&2
    exit 1
  fi
  echo "WARN: nodes missing — gauge ramp only" >&2
fi

patch_state fault_id=ce_sla_conflict
stop_iperf

if [[ -n "$DST_PEER" ]] && docker image inspect networkstatic/iperf3 >/dev/null 2>&1; then
  docker run -d --rm --name gns3-ce-sla-srv --network "container:$DST_PEER" networkstatic/iperf3 -s >/dev/null 2>&1 || true
fi

# Light Gold TT&C probe (victim) if NRSC/IPERF-A available
VICTIM_SRC="${NRSC:-$IPA}"
if [[ -n "$VICTIM_SRC" ]] && docker ps --format '{{.Names}}' | grep -q '^gns3-ce-sla-srv$'; then
  hold=$((STEPS * STEP_SEC + 10))
  docker run -d --rm --name gns3-ce-sla-gold --network "container:$VICTIM_SRC" \
    networkstatic/iperf3 -u -b "${VICTIM_MBIT}M" --tos 0x88 -c 10.10.6.10 -t "$hold" \
    >/dev/null 2>&1 || true
fi

for i in $(seq 0 $((STEPS - 1))); do
  mbit=$(python3 -c "print(round($START_MBIT + ($END_MBIT-$START_MBIT)*$i/max($STEPS-1,1), 2))")
  patch_state ce_util_mbps_bronze="$mbit" util_gre_mbps="$(python3 -c "print(round($mbit*0.9+2,1))")" ce_util_mbps_gold="$VICTIM_MBIT"
  echo "ce_sla_conflict rogue Bronze ${mbit}Mbit ToS=0x80 · victim Gold TT&C ${VICTIM_MBIT}Mbit ToS=0x88"
  if [[ -n "$SRC" ]] && docker ps --format '{{.Names}}' | grep -q '^gns3-ce-sla-srv$'; then
    docker rm -f gns3-ce-sla-rogue >/dev/null 2>&1 || true
    docker run -d --rm --name gns3-ce-sla-rogue --network "container:$SRC" \
      networkstatic/iperf3 -u -b "${mbit}M" --tos 0x80 -c 10.10.6.10 -t "$STEP_SEC" \
      >/dev/null 2>&1 || true
  fi
  sleep "$STEP_SEC"
done

echo "ce_sla_conflict hold high briefly"
sleep 5
stop_iperf
patch_state fault_id= ce_util_mbps_bronze=2 util_gre_mbps=2.5 ce_util_mbps_gold=4
echo "ce_sla_conflict done"
