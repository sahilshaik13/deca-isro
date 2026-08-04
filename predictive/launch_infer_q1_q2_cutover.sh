#!/usr/bin/env bash
# launch_infer_q1_q2_cutover.sh — Phase-7 live gate with real loss/jitter/util TTI.
# Air-gapped; no WAN. Models under data/deca/predictive/protocol_models/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv-predictive/bin/python"
export PYTHONPATH="${ROOT}"
PM="${ROOT}/data/deca/predictive/protocol_models"

exec "$PY" -m predictive.infer_q1_q2_live \
  --q1-model "${PM}/lstm_q1/q1_tti_lstm.keras" \
  --q1-scaler "${PM}/lstm_q1/q1_scaler.npz" \
  --q2-model "${PM}/xgb_q2_sev/q2_severity.joblib" \
  --q1-loss-model "${PM}/lstm_q1_loss/q1_loss_tti_lstm.keras" \
  --q1-loss-scaler "${PM}/lstm_q1_loss/q1_loss_scaler.npz" \
  --q1-jitter-model "${PM}/lstm_q1_jitter/q1_jitter_tti_lstm.keras" \
  --q1-jitter-scaler "${PM}/lstm_q1_jitter/q1_jitter_scaler.npz" \
  --q1-util-model "${PM}/lstm_q1_util/q1_util_tti_lstm.keras" \
  --q1-util-scaler "${PM}/lstm_q1_util/q1_util_scaler.npz" \
  "$@"
