#!/usr/bin/env bash
# wait_then_full_ml.sh — chain to full ML pipeline after auto_post DONE.
# Kept as a file so cmdline does not false-positive lab_busy pgrep patterns.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="${1:-20260729T202832Z}"
BASE="$ROOT/data/deca/predictive/protocol/$STAMP"
LOG="$BASE/auto_post_chaos_continue.log"
CHAIN="$BASE/chain_full_ml.log"
mkdir -p "$BASE"
echo "clean chain waiter start $(date -Is)" | tee -a "$CHAIN"
while ! grep -q "auto_post_chaos_continue DONE" "$LOG" 2>/dev/null; do
  echo "waiting auto_post DONE… $(date -Is)" | tee -a "$CHAIN"
  sleep 120
done
echo "detected auto_post DONE $(date -Is)" | tee -a "$CHAIN"
if [[ -f "$BASE/RESULTS_FOR_RETURN.md" ]]; then
  echo "RESULTS already present — skip" | tee -a "$CHAIN"
  exit 0
fi
if pgrep -f 'predictive/auto_full_ml_pipeline.sh' >/dev/null; then
  echo "full pipeline already running — skip" | tee -a "$CHAIN"
  exit 0
fi
echo "starting auto_full_ml_pipeline $(date -Is)" | tee -a "$CHAIN"
bash "$ROOT/predictive/auto_full_ml_pipeline.sh" "$STAMP" >>"$CHAIN" 2>&1
echo "chain finished $(date -Is)" | tee -a "$CHAIN"
