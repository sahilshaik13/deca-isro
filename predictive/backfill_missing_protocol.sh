#!/usr/bin/env bash
# backfill_missing_protocol.sh — fill gaps in ACTIVE Pi protocol stamp without
# fighting the live campaign.
#
# Gaps this covers:
#   • L3_bgp_flap/iter_01 series.csv (clobbered by a bad resume; q2_windows kept)
#   • any L4/L5 q2_windows.csv missing after q2_windows.py label 4/5 fix
#
# Usage:
#   bash predictive/backfill_missing_protocol.sh           # wait + backfill
#   bash predictive/backfill_missing_protocol.sh --nowait  # fail if busy
#   bash predictive/backfill_missing_protocol.sh --windows-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${DECA_PRED_PY:-${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}}"
export DECA_PRED_PYTHON="$PY"
export DECA_FABRIC=pi
ACTIVE_JSON="$ROOT/data/deca/predictive/protocol/ACTIVE_STAMP.json"
HOST="${HOST:-station1}"
PROM="${PROM:-http://127.0.0.1:9090}"
NOWAIT=0
WINDOWS_ONLY=0

for a in "$@"; do
  case "$a" in
    --nowait) NOWAIT=1 ;;
    --windows-only) WINDOWS_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  esac
done

STAMP="$(python3 -c "import json;print(json.load(open('$ACTIVE_JSON'))['active_stamp'])")"
BASE="$ROOT/data/deca/predictive/protocol/$STAMP"
[[ -d "$BASE" ]] || { echo "missing stamp dir $BASE"; exit 2; }

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "=== backfill stamp=$STAMP ==="

rebuild_windows() {
  local series="$1" label="$2"
  local dir
  dir=$(dirname "$series")
  [[ -f "$series" ]] || return 0
  local rows
  rows=$(wc -l <"$series")
  [[ "$rows" -ge 100 ]] || { echo "SKIP short $series rows=$rows"; return 0; }
  echo "q2_windows label=$label → $dir"
  "$PY" -m predictive.q2_windows --capture "$series" --label "$label" --out-dir "$dir" --preprocess
}

# Always safe: rebuild missing L4/L5 windows from existing series
for s in "$BASE"/L4_loss_progression/iter_*/series.csv; do
  [[ -f "${s%/*}/q2_windows.csv" ]] && continue
  rebuild_windows "$s" 4
done
for s in "$BASE"/L5_util_congestion/iter_*/series.csv; do
  rows=$(wc -l <"$s")
  [[ "$rows" -ge 700 ]] || continue
  [[ -f "${s%/*}/q2_windows.csv" ]] && continue
  rebuild_windows "$s" 5
done

if [[ "$WINDOWS_ONLY" -eq 1 ]]; then
  echo "windows-only done"
  exit 0
fi

L3_01="$BASE/L3_bgp_flap/iter_01"
need_l3=0
if [[ ! -f "$L3_01/series.csv" ]] || [[ "$(wc -l <"$L3_01/series.csv" 2>/dev/null || echo 0)" -lt 3000 ]]; then
  need_l3=1
fi

if [[ "$need_l3" -eq 0 ]]; then
  echo "L3 iter_01 series already present — nothing to inject"
  exit 0
fi

lab_busy() {
  pgrep -f 'inject_(util_congestion|bgp_flap|rain_fade|cpu_stress|loss_progression)\.sh' >/dev/null 2>&1 \
    || pgrep -f 'run_q2_campaign\.sh' >/dev/null 2>&1 \
    || pgrep -f 'run_protocol_campaign\.sh' >/dev/null 2>&1 \
    || pgrep -f 'run_chaos_campaign\.sh' >/dev/null 2>&1 \
    || pgrep -f 'resume_active_protocol\.sh' >/dev/null 2>&1
}

echo "L3 iter_01 needs series backfill (~1h BGP inject on $HOST)"
if lab_busy; then
  if [[ "$NOWAIT" -eq 1 ]]; then
    echo "lab busy — refuse (--nowait). Re-run after L5/chaos finishes."
    exit 3
  fi
  echo "waiting for live campaign/injectors to finish…"
  while lab_busy; do
    sleep 60
    echo "  still busy $(date -Is)"
  done
fi

# Preserve prior q2 artifacts; archive clobber leftovers
ARCHIVE="$L3_01/backfill_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ARCHIVE"
for f in series.csv SERIES_CLOBBERED.json series.csv.clobbered_* capture.log inject.log clear.log; do
  [[ -e "$L3_01"/$f ]] && mv "$L3_01"/$f "$ARCHIVE/" || true
done
# Keep label.json / q2_windows as provenance; will overwrite after recapture
cp -a "$L3_01/q2_windows.csv" "$ARCHIVE/q2_windows.csv.prev" 2>/dev/null || true
cp -a "$L3_01/label.json" "$ARCHIVE/label.json.prev" 2>/dev/null || true

echo "=== recapture L3 BGP iter_01 into $L3_01 ==="
DECA_PRED_OUT="$L3_01" DECA_PRED_PYTHON="$PY" bash "$ROOT/predictive/run_q2_campaign.sh" \
  --label 3 \
  --baseline-sec 60 \
  --inject-sec 3600 \
  --post-sec 60 \
  --host "$HOST" \
  --prom "$PROM" \
  --stamp "${STAMP}_L3_i1_backfill"

rows=$(wc -l <"$L3_01/series.csv")
echo "backfill complete series_rows=$((rows - 1))"
[[ "$rows" -ge 3000 ]] || { echo "WARN: short series ($rows lines)"; exit 4; }
echo "OK $L3_01/series.csv + q2_windows.csv"
