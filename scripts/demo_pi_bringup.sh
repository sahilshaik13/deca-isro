#!/usr/bin/env bash
# Pi-only ultimate-demo bring-up (leave GNS3 alone).
# Wires: fabric=pi · frozen Q1/Q2+BGP infer · Ollama Q3 · frontend · controller check.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API="${DECA_API_URL:-http://127.0.0.1:8000}"
export PATH="$HOME/.local/bin:${PATH:-}"
export LD_LIBRARY_PATH="$HOME/.local/lib/ollama:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$ROOT"

Q1_MODEL=data/deca/predictive/protocol_models/lstm_q1_unified/q1_tti_lstm.keras
Q1_SCALER=data/deca/predictive/protocol_models/lstm_q1_unified/q1_scaler.npz
Q2_MODEL=data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib
BGP_SPEC=data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/bgp_3a3b_locked.joblib
INFER_LOG=/tmp/infer_q1_q2_live_demo.log
FE_LOG=/tmp/deca-frontend-dev.log
OLLAMA_LOG=/tmp/ollama_serve.log

ok()  { printf 'PASS  %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; FAIL=1; }
FAIL=0

need_file() {
  [[ -f "$1" ]] && ok "model $1" || bad "missing $1"
}

echo "== DECA Pi demo bring-up =="

need_file "$Q1_MODEL"
need_file "$Q1_SCALER"
need_file "$Q2_MODEL"
need_file "$BGP_SPEC"

# Ollama (Q3 Phi-3 + nomic embed)
if ! curl -sf -m 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  nohup ollama serve >"$OLLAMA_LOG" 2>&1 &
  for _ in $(seq 1 20); do
    sleep 1
    curl -sf -m 2 http://127.0.0.1:11434/api/tags >/dev/null && break
  done
fi
if curl -sf -m 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  ok "Ollama :11434"
else
  bad "Ollama :11434"
fi

# API + controller + Prom
curl -sf -m 3 "$API/api/v1/faults/status" >/dev/null && ok "API :8000" || bad "API :8000"
curl -sf -m 3 http://127.0.0.1:9280/metrics >/dev/null && ok "Controller :9280" || bad "Controller :9280"
curl -sf -m 3 http://127.0.0.1:9090/-/ready >/dev/null && ok "Prom Pi :9090" || bad "Prom Pi :9090"

# Force Pi fabric
curl -sf -m 10 -X POST "$API/api/v1/fabric" \
  -H 'Content-Type: application/json' \
  -d '{"active":"pi","set_by":"demo_pi_bringup"}' >/dev/null
FAB=$(curl -sf -m 5 "$API/api/v1/fabric" | python3 -c "import sys,json; print(json.load(sys.stdin).get('active',''))")
[[ "$FAB" == "pi" ]] && ok "Fabric=pi" || bad "Fabric=$FAB (want pi)"

# Frontend
if ! curl -sf -m 2 http://127.0.0.1:3000 >/dev/null; then
  (cd "$ROOT/deca-frontend" && nohup npm run dev >"$FE_LOG" 2>&1 &)
  for _ in $(seq 1 40); do
    sleep 1
    curl -sf -m 2 http://127.0.0.1:3000 >/dev/null && break
  done
fi
curl -sf -m 3 http://127.0.0.1:3000 >/dev/null && ok "Frontend :3000" || bad "Frontend :3000"

# Live infer (frozen cite stack) — replace stale process if needed
if ! pgrep -f '\.venv-predictive/bin/python -m predictive.infer_q1_q2_live' >/dev/null; then
  nohup .venv-predictive/bin/python -m predictive.infer_q1_q2_live \
    --q1-model "$Q1_MODEL" \
    --q1-scaler "$Q1_SCALER" \
    --q2-model "$Q2_MODEL" \
    --bgp-specialist "$BGP_SPEC" \
    --fabric pi --orch "$API" --seconds 0 --interval 2 \
    >"$INFER_LOG" 2>&1 &
  sleep 6
fi
if pgrep -f '\.venv-predictive/bin/python -m predictive.infer_q1_q2_live' >/dev/null; then
  ok "Live infer (frozen d2 + BGP @0.85)"
else
  bad "Live infer not running (see $INFER_LOG)"
fi

if ssh -o BatchMode=yes -o ConnectTimeout=5 station1 true 2>/dev/null; then
  ok "SSH station1"
else
  bad "SSH station1"
fi

CAT=$(curl -sf -m 5 "$API/api/v1/faults/status" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('catalog') or []))")
[[ "$CAT" -ge 5 ]] && ok "Fault buttons catalog ($CAT)" || bad "Fault catalog=$CAT"

echo
echo "Dashboard: http://127.0.0.1:3000"
echo "Jury click: Fabric=Pi → Simple fault → Decide → Approve"
echo "Logs: infer=$INFER_LOG  frontend=$FE_LOG  ollama=$OLLAMA_LOG"
echo "Cite stack only — do not swap unpromoted util-clean/τ for demo."
[[ "$FAIL" -eq 0 ]] && echo "READY" || { echo "NOT READY"; exit 1; }
