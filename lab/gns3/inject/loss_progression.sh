#!/usr/bin/env bash
# GNS3 L4 loss progression — twin of scripts/inject_loss_progression.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

if [[ "${1:-}" == "--clear" ]]; then
  apply_netem_pe1 clear
  patch_state fault_id= loss_gre_pct=0
  echo "cleared loss_progression"
  exit 0
fi

# State→exporter is the GNS3 twin signal path when PE1/CORE containers are down
# (project closed). Never abort before patch_state — that produced loss=0 series.
if ! require_pe1 >/dev/null; then
  echo "WARN: PE1 not running — state-only loss inject (exporter :9275)" >&2
  export DECA_REQUIRE_LIVE=0
  REQUIRE_LIVE=0
fi

# Pi: 24×5s, 0→3.5%
STEPS=${STEPS:-24}
START_PCT=${START_PCT:-0}
END_LOSS=${END_LOSS:-${END_PCT:-3.5}}
STEP_SEC=${STEP_SEC:-5}

patch_state fault_id=loss_progression
for i in $(seq 0 $((STEPS - 1))); do
  pct=$(python3 -c "print(round($START_PCT + ($END_LOSS-$START_PCT)*$i/max($STEPS-1,1), 3))")
  apply_netem_pe1 "loss ${pct}%" || true
  patch_state loss_gre_pct="$pct"
  echo "loss_progression step $((i+1))/$STEPS loss=${pct}% (state patched)"
  sleep "$STEP_SEC"
done
echo "loss_progression done — state at ${END_LOSS}% (clear with --clear)"
