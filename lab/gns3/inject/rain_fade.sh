#!/usr/bin/env bash
# GNS3 L1 rain fade — twin of scripts/inject_rain_fade.sh (NetEM delay on underlay).
# Defaults = Pi canonical; override STEPS/STEP_SEC for short NOC demos.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

if [[ "${1:-}" == "--clear" ]]; then
  apply_netem_pe1 clear
  patch_state fault_id= latency_gre_ms=8 jitter_gre_ms=0.5
  echo "cleared rain_fade"
  exit 0
fi

if ! require_pe1 >/dev/null; then
  echo "WARN: PE1 not running — state-only rain inject (exporter :9275)" >&2
  export DECA_REQUIRE_LIVE=0
  REQUIRE_LIVE=0
fi

# Pi: 24×5s, 5→100ms, jitter 5ms
STEPS=${STEPS:-24}
START_MS=${START_MS:-5}
END_MS=${END_MS:-100}
STEP_SEC=${STEP_SEC:-5}
JITTER_MS=${JITTER_MS:-5}

patch_state fault_id=rain_fade
for i in $(seq 0 $((STEPS - 1))); do
  ms=$(python3 -c "print(round($START_MS + ($END_MS-$START_MS)*$i/max($STEPS-1,1), 1))")
  apply_netem_pe1 "delay ${ms}ms ${JITTER_MS}ms distribution normal" || true
  patch_state latency_gre_ms="$ms" jitter_gre_ms="$JITTER_MS"
  echo "rain_fade step $((i+1))/$STEPS delay=${ms}ms±${JITTER_MS}ms (state patched)"
  sleep "$STEP_SEC"
done
echo "rain_fade done — state at ${END_MS}ms (clear with --clear)"
