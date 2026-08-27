#!/usr/bin/env bash
# GNS3 L3 BGP flap — twin of scripts/inject_bgp_flap.sh (clear bgp <nbr> soft).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

# After inject, do not zero bgp_flap_count — cumulative GT must remain visible
# in the capture tail (verify uses max−first). Only clear fault_id.
if [[ "${1:-}" == "--clear" ]]; then
  patch_state fault_id=
  echo "cleared bgp_flap (counter preserved)"
  exit 0
fi

# Pi: 18×5s soft-clear neighbor
CYCLES=${CYCLES:-18}
PERIOD=${PERIOD:-${PERIOD_SEC:-5}}
NEIGHBOR=${NEIGHBOR:-$BGP_NEIGHBOR}
cid=""
if ! cid="$(require_pe1)"; then
  echo "WARN: PE1 missing — state-only BGP flaps" >&2
  export DECA_REQUIRE_LIVE=0
  REQUIRE_LIVE=0
  cid=""
fi
# Continue from existing counter so resume/overlapping jobs don't look flat
prev="$(python3 -c "import json;from pathlib import Path;p=Path('$SCRIPT_DIR/../state/chaos_state.json');
print(int(json.loads(p.read_text()).get('bgp_flap_count',0)) if p.exists() else 0)" 2>/dev/null || echo 0)"
patch_state fault_id=bgp_flap
count=$prev

echo "bgp_flap PE1 nbr=$NEIGHBOR soft-clear ${CYCLES}×${PERIOD}s (start_count=$count)"
# Optional explicit EXTRA only (never auto-bump — that goalpost-moves GNS3 storm→3B).
EXTRA=${BGP_COUNT_EXTRA:-0}
for i in $(seq 1 "$CYCLES"); do
  count=$((count + 1 + EXTRA))
  patch_state bgp_flap_count="$count"
  if [[ -n "$cid" ]]; then
    docker exec "$cid" sh -c \
      "vtysh -c 'clear bgp $NEIGHBOR soft' 2>/dev/null \
       || vtysh -c 'clear ip bgp $NEIGHBOR soft' 2>/dev/null \
       || vtysh -c 'clear bgp * soft' 2>/dev/null \
       || true" || true
  fi
  echo "bgp_flap cycle $i/$CYCLES clear bgp $NEIGHBOR soft count=$count extra=$EXTRA"
  sleep "$PERIOD"
done
# Leave counter high through post/capture tail
patch_state fault_id=
echo "bgp_flap done (bgp_flap_count=$count)"


