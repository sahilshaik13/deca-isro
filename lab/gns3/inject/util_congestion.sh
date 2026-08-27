#!/usr/bin/env bash
# GNS3 L5 util congestion — twin of scripts/inject_util_congestion.sh.
# Ramp UDP ToS 0x80 through HTB 1:15 (real iperf3; gauges overlay).
# CAPTURE_CONTRACT: write util_ceil_schedule.jsonl (--schedule-out) for Q1 labels.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

SCHEDULE_OUT=""
PLATEAU_SEC="${PLATEAU_SEC:-40}"

# Parse optional flags before --clear / env-driven mode
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --clear) ARGS+=("$1"); shift ;;
    --schedule-out) SCHEDULE_OUT="$2"; shift 2 ;;
    --plateau-sec) PLATEAU_SEC="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-mbit) START_MBIT="$2"; shift 2 ;;
    --end-mbit) END_MBIT="$2"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

if [[ "${1:-}" == "--clear" ]]; then
  patch_state fault_id= util_gre_mbps=2.5 ce_util_mbps_bronze=2.0 ce_util_mbps_gold=4.0
  docker ps --format '{{.Names}}' | grep -E '^gns3-util-' | xargs -r docker rm -f >/dev/null 2>&1 || true
  echo "cleared util_congestion"
  exit 0
fi

# Defaults (overridden by env from run_q2_campaign_gns3 or flags above)
STEPS=${STEPS:-6}
STEP_SEC=${STEP_SEC:-20}
START_MBIT=${START_MBIT:-5}
END_MBIT=${END_MBIT:-30}
TOS=${TOS:-128}
[[ "$PLATEAU_SEC" -lt 40 ]] && PLATEAU_SEC=40

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

SCHED_TMP=$(mktemp)
: >"$SCHED_TMP"
# Live mirror so SIGTERM (compound kill after inject window) still leaves a usable schedule.
if [[ -n "$SCHEDULE_OUT" ]]; then
  mkdir -p "$(dirname "$SCHEDULE_OUT")"
  : >"$SCHEDULE_OUT"
fi
append_sched() {
  local ceil="$1" phase="$2" step="$3"
  local now line
  now=$(date +%s)
  line=$(printf '{"ts_unix":%s,"htb_payload_ceil_mbps":%s,"phase":"%s","step":%s,"end_mbit":%s}' \
    "$now" "$ceil" "$phase" "$step" "$END_MBIT")
  printf '%s\n' "$line" >>"$SCHED_TMP"
  [[ -n "$SCHEDULE_OUT" ]] && printf '%s\n' "$line" >>"$SCHEDULE_OUT"
}
flush_sched() {
  if [[ -n "${SCHEDULE_OUT:-}" && -f "${SCHED_TMP:-}" ]]; then
    mkdir -p "$(dirname "$SCHEDULE_OUT")"
    cp "$SCHED_TMP" "$SCHEDULE_OUT" 2>/dev/null || true
  fi
}
_util_cleanup() {
  flush_sched
  docker ps --format '{{.Names}}' | grep -E '^gns3-util-' | xargs -r docker rm -f >/dev/null 2>&1 || true
  patch_state fault_id= util_gre_mbps=2.5 ce_util_mbps_bronze=2.0 ce_util_mbps_gold=4.0 >/dev/null 2>&1 || true
  rm -f "${SCHED_TMP:-}"
}
trap '_util_cleanup' EXIT INT TERM

if [[ -n "$IPA" && -n "$IPB" ]] && docker image inspect networkstatic/iperf3 >/dev/null 2>&1; then
  docker rm -f gns3-util-srv gns3-util-cli >/dev/null 2>&1 || true
  docker run -d --rm --name gns3-util-srv --network "container:$IPB" \
    networkstatic/iperf3 -s -p 5201 >/dev/null 2>&1 || true
fi

# Fit ramp+plateau inside ~STEPS×STEP_SEC budget when caller sized STEPS from inject_sec.
RAMP_STEPS="$STEPS"
RAMP_SEC="$STEP_SEC"
if (( STEPS * STEP_SEC > PLATEAU_SEC + STEP_SEC )); then
  # reserve plateau from the inject window
  BUDGET=$((STEPS * STEP_SEC))
  RAMP_BUDGET=$((BUDGET - PLATEAU_SEC))
  [[ "$RAMP_BUDGET" -lt "$STEP_SEC" ]] && RAMP_BUDGET=$STEP_SEC
  RAMP_STEPS=$((RAMP_BUDGET / STEP_SEC))
  [[ "$RAMP_STEPS" -lt 4 ]] && RAMP_STEPS=4
fi

# Offer ≥2× end_mbit so bitrate is not the bottleneck (Pi twin discipline).
# Gauge / schedule still track *configured* ceil; iperf pushes harder so HTB shapes.
OFFER_MULT="${OFFER_MULT:-2}"
OFFER_MBIT=$(python3 -c "print(max(16, int(round($END_MBIT * $OFFER_MULT))))")
echo "util_congestion HTB 1:15 ToS=$TOS: ${START_MBIT}→${END_MBIT} Mbit offer=${OFFER_MBIT}Mbit (≥${OFFER_MULT}×) ramp=${RAMP_STEPS}×${RAMP_SEC}s plateau=${PLATEAU_SEC}s"
for i in $(seq 0 $((RAMP_STEPS - 1))); do
  mbit=$(python3 -c "print(round($START_MBIT + ($END_MBIT-$START_MBIT)*$i/max($RAMP_STEPS-1,1), 2))")
  bronze=$(python3 -c "print(round(min($mbit * 0.85, 40), 2))")
  gold=$(python3 -c "print(round(min($mbit * 0.35, 15), 2))")
  patch_state util_gre_mbps="$mbit" ce_util_mbps_bronze="$bronze" ce_util_mbps_gold="$gold" \
    htb_payload_ceil_mbps="$mbit"
  append_sched "$mbit" ramp "$i"
  echo "util_congestion step $((i+1))/$RAMP_STEPS ceil=${mbit}Mbit offer=${OFFER_MBIT}Mbit ToS=$TOS :5201"
  if [[ -n "$IPA" ]] && docker ps --format '{{.Names}}' | grep -q '^gns3-util-srv$'; then
    docker rm -f gns3-util-cli >/dev/null 2>&1 || true
    docker run -d --rm --name gns3-util-cli --network "container:$IPA" \
      networkstatic/iperf3 -u -b "${OFFER_MBIT}M" --tos "$TOS" -p 5201 -c 10.10.6.10 -t "$RAMP_SEC" \
      >/dev/null 2>&1 || true
  elif [[ "$REQUIRE_LIVE" == "1" && -n "$IPA" ]]; then
    echo "ERROR: util server missing — refuse gauge-only" >&2
    rm -f "$SCHED_TMP"
    exit 1
  fi
  sleep "$RAMP_SEC"
done

# Plateau at end_mbit (CAPTURE_CONTRACT residency)
patch_state util_gre_mbps="$END_MBIT" htb_payload_ceil_mbps="$END_MBIT"
append_sched "$END_MBIT" plateau -1
echo "util_congestion PLATEAU ceil=${END_MBIT}Mbit offer=${OFFER_MBIT}Mbit for ${PLATEAU_SEC}s"
if [[ -n "$IPA" ]] && docker ps --format '{{.Names}}' | grep -q '^gns3-util-srv$'; then
  docker rm -f gns3-util-cli >/dev/null 2>&1 || true
  docker run -d --rm --name gns3-util-cli --network "container:$IPA" \
    networkstatic/iperf3 -u -b "${OFFER_MBIT}M" --tos "$TOS" -p 5201 -c 10.10.6.10 -t "$PLATEAU_SEC" \
    >/dev/null 2>&1 || true
fi
sleep "$PLATEAU_SEC"

# Normal completion — trap EXIT will flush schedule + clear gauges/containers
if [[ -n "$SCHEDULE_OUT" ]]; then
  flush_sched
  echo "wrote schedule $SCHEDULE_OUT ($(wc -l <"$SCHEDULE_OUT") lines)"
fi
echo "util_congestion done"
