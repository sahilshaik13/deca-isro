#!/usr/bin/env bash
# GNS3 L5 util congestion — twin of scripts/inject_util_congestion.sh.
# Ramp UDP ToS 0x80 through HTB 1:15 (real iperf3; gauges overlay only).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

if [[ "${1:-}" == "--clear" ]]; then
  patch_state fault_id= util_gre_mbps=2.5 ce_util_mbps_bronze=2.0 ce_util_mbps_gold=4.0
  docker ps --format '{{.Names}}' | grep -E '^gns3-util-' | xargs -r docker rm -f >/dev/null 2>&1 || true
  echo "cleared util_congestion"
  exit 0
fi

# Pi: 6×20s, 5→30 Mbit, ToS 0x80 → :5201
STEPS=${STEPS:-6}
STEP_SEC=${STEP_SEC:-20}
START_MBIT=${START_MBIT:-5}
END_MBIT=${END_MBIT:-30}
TOS=${TOS:-128}

IPA=$(cname IPERF-A || true)
IPB=$(cname IPERF-B || true)
if [[ -z "$IPA" || -z "$IPB" ]]; then
  if [[ "$REQUIRE_LIVE" == "1" ]]; then
    echo "ERROR: need IPERF-A/B for L5 util (DECA_REQUIRE_LIVE=1)" >&2
    exit 1
  fi
  echo "WARN: IPERF-A/B missing — gauge ramp only" >&2
fi

if [[ -n "$IPA" && -n "$IPB" ]]; then
  if ! docker image inspect networkstatic/iperf3 >/dev/null 2>&1; then
    if [[ "$REQUIRE_LIVE" == "1" ]]; then
      echo "ERROR: networkstatic/iperf3 required (Pi twin)" >&2
      docker pull networkstatic/iperf3 || exit 1
    fi
  fi
fi

patch_state fault_id=util_congestion

if [[ -n "$IPA" && -n "$IPB" ]] && docker image inspect networkstatic/iperf3 >/dev/null 2>&1; then
  docker rm -f gns3-util-srv gns3-util-cli >/dev/null 2>&1 || true
  # Pi far-end listens on 5201 for util ramp
  docker run -d --rm --name gns3-util-srv --network "container:$IPB" \
    networkstatic/iperf3 -s -p 5201 >/dev/null 2>&1 || true
fi

echo "util_congestion HTB 1:15 ToS=$TOS: ${START_MBIT}→${END_MBIT} Mbit over $((STEPS * STEP_SEC))s"
for i in $(seq 0 $((STEPS - 1))); do
  mbit=$(python3 -c "print(round($START_MBIT + ($END_MBIT-$START_MBIT)*$i/max($STEPS-1,1), 2))")
  bronze=$(python3 -c "print(round(min($mbit * 0.85, 40), 2))")
  gold=$(python3 -c "print(round(min($mbit * 0.35, 15), 2))")
  patch_state util_gre_mbps="$mbit" ce_util_mbps_bronze="$bronze" ce_util_mbps_gold="$gold"
  echo "util_congestion step $((i+1))/$STEPS util=${mbit}Mbit ToS=$TOS :5201 (HTB 1:15)"
  if [[ -n "$IPA" ]] && docker ps --format '{{.Names}}' | grep -q '^gns3-util-srv$'; then
    docker rm -f gns3-util-cli >/dev/null 2>&1 || true
    docker run -d --rm --name gns3-util-cli --network "container:$IPA" \
      networkstatic/iperf3 -u -b "${mbit}M" --tos "$TOS" -p 5201 -c 10.10.6.10 -t "$STEP_SEC" \
      >/dev/null 2>&1 || true
  elif [[ "$REQUIRE_LIVE" == "1" && -n "$IPA" ]]; then
    echo "ERROR: util server missing — refuse gauge-only" >&2
    exit 1
  fi
  sleep "$STEP_SEC"
done

docker ps --format '{{.Names}}' | grep -E '^gns3-util-' | xargs -r docker rm -f >/dev/null 2>&1 || true
patch_state fault_id= util_gre_mbps=2.5 ce_util_mbps_bronze=2.0 ce_util_mbps_gold=4.0
echo "util_congestion done"
