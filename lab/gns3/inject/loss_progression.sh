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

require_pe1 >/dev/null

# Pi: 24×5s, 0→3.5%
STEPS=${STEPS:-24}
START_PCT=${START_PCT:-0}
END_LOSS=${END_LOSS:-${END_PCT:-3.5}}
STEP_SEC=${STEP_SEC:-5}

patch_state fault_id=loss_progression
for i in $(seq 0 $((STEPS - 1))); do
  pct=$(python3 -c "print(round($START_PCT + ($END_LOSS-$START_PCT)*$i/max($STEPS-1,1), 3))")
  apply_netem_pe1 "loss ${pct}%"
  patch_state loss_gre_pct="$pct"
  echo "loss_progression step $((i+1))/$STEPS loss=${pct}%"
  sleep "$STEP_SEC"
done
echo "loss_progression done — netem left at ${END_LOSS}% (clear with --clear)"
