#!/usr/bin/env bash
# start_protocol_watchdog.sh — resolve ACTIVE_STAMP then run watch_protocol_capture.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTIVE="$ROOT/data/deca/predictive/protocol/ACTIVE_STAMP.json"
STAMP="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["active_stamp"])' "$ACTIVE")"
export STAMP
export INTERVAL="${INTERVAL:-30}"
export DECA_PRED_PYTHON="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
export DECA_PROM_URL="${DECA_PROM_URL:-http://127.0.0.1:9090}"
exec bash "$ROOT/predictive/watch_protocol_capture.sh"
