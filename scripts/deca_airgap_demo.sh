#!/usr/bin/env bash
# DECA air-gap demo harness — jury-facing proof of zero WAN egress.
#
# Design (rootless, no sudo):
#   1) Host netns: confirm lab Prometheus is up AND WAN currently works.
#   2) Enter unshare -r -n (empty netns, loopback only): WAN probes FAIL;
#      local GGUF copilot (disk + CPU only) still produces a complete alert.
#   3) Host netns again: Prometheus still ready (lab never depended on WAN).
#
# This is stronger than "we didn't call the internet" — the process literally
# has no route to it — while staying honest that host Prom lives in the host
# netns (unreachable from inside the empty netns by design).
#
# Usage:
#   bash scripts/deca_airgap_demo.sh
#
# Env:
#   DECA_AIRGAP_HOLD_SEC      hold inside netns for observation (default 6)
#   DECA_AIRGAP_LLM_TIMEOUT   LLM probe budget seconds (default 45)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${ROOT}/.venv/bin/python"
HOLD="${DECA_AIRGAP_HOLD_SEC:-6}"
LLM_TO="${DECA_AIRGAP_LLM_TIMEOUT:-45}"

if ! unshare -r -n true 2>/dev/null; then
  echo "ERROR: unshare -r -n failed (need unprivileged user namespaces)."
  exit 1
fi

echo "=============================================================="
echo " DECA AIR-GAP DEMO"
echo "=============================================================="

echo
echo "[0] Host pre-check: Prometheus + WAN baseline"
if ! curl -sS --connect-timeout 3 --max-time 5 http://127.0.0.1:9090/-/ready | grep -qi ready; then
  echo "  FAIL: Prometheus not ready on 127.0.0.1:9090"
  exit 3
fi
echo "  OK: Prometheus ready (host netns)"

WAN_BASELINE=0
if curl -sS --connect-timeout 3 --max-time 5 https://1.1.1.1/ >/dev/null 2>&1; then
  WAN_BASELINE=1
  echo "  OK: WAN reachable on host (baseline before cut)"
else
  echo "  NOTE: WAN already unreachable on host — netns cut still demonstrated below"
fi

echo
echo "[1] Cutting process WAN via unshare -r -n (loopback-only netns)…"

# Inner script runs with NO WAN / NO host LAN — only a private lo.
unshare -r -n env ROOT="$ROOT" PY="$PY" HOLD="$HOLD" LLM_TO="$LLM_TO" bash <<'INNER'
set -euo pipefail
cd "$ROOT"
ip link set lo up

echo
echo "[2] Inside netns — WAN must FAIL"
if curl -sS --connect-timeout 2 --max-time 4 https://1.1.1.1/ >/dev/null 2>&1; then
  echo "  FAIL: WAN still reachable inside netns"
  exit 2
fi
echo "  OK: 1.1.1.1 blocked"

if curl -sS --connect-timeout 2 --max-time 4 https://example.com/ >/dev/null 2>&1; then
  echo "  FAIL: example.com reachable inside netns"
  exit 2
fi
echo "  OK: example.com blocked"

echo
echo "[3] Inside netns — local copilot (--skip-llm) must PASS"
ALERT=$("$PY" scripts/deca_copilot_bridge.py --once --class policy_drift --host station1 \
  --confidence 0.8 --eta 2.5 --skip-llm)
echo "$ALERT" | "$PY" -c '
import sys, json
raw = sys.stdin.read(); i = raw.find("{"); a = json.loads(raw[i:])
assert a.get("predicted_issue") == "policy_drift"
assert a.get("recommended_actions")
assert a.get("confidence_score") == 0.8
print("  OK: structured alert path=", a.get("generation_path"),
      "actions=", len(a["recommended_actions"]))
'

echo
echo "[4] Inside netns — LLM/GGUF path (complete alert required; fallback OK)"
set +e
ALERT2=$("$PY" scripts/deca_copilot_bridge.py --once --class congestion_breach --host station1 \
  --confidence 0.9 --eta 3.0 --llm-timeout "$LLM_TO" 2>/tmp/deca_airgap_llm.log)
set -e
echo "$ALERT2" | "$PY" -c '
import sys, json
raw = sys.stdin.read().strip()
i = raw.find("{")
assert i >= 0, raw[:200]
a = json.loads(raw[i:])
for k in ("predicted_issue", "confidence_score", "root_cause", "affected_scope", "recommended_actions"):
    assert a.get(k) not in (None, "", []), k
print("  OK: alert complete path=", a.get("generation_path"),
      "fallback=", a.get("fallback_reason"))
'

echo
echo "Holding air-gap ${HOLD}s for jury observation…"
sleep "$HOLD"
echo "  (leaving netns)"
INNER

echo
echo "[5] Host post-check: Prometheus still ready after air-gap process exited"
if ! curl -sS --connect-timeout 3 --max-time 5 http://127.0.0.1:9090/-/ready | grep -qi ready; then
  echo "  FAIL: Prometheus not ready after demo"
  exit 3
fi
echo "  OK: Prometheus still ready (lab-local; never needed WAN)"

if [[ "$WAN_BASELINE" -eq 1 ]]; then
  if curl -sS --connect-timeout 3 --max-time 5 https://1.1.1.1/ >/dev/null 2>&1; then
    echo "  OK: host WAN restored/unaffected (cut was process-scoped)"
  else
    echo "  NOTE: host WAN still down — unrelated to this process-scoped cut"
  fi
fi

echo
echo "=============================================================="
echo " AIR-GAP DEMO PASS"
echo "=============================================================="
