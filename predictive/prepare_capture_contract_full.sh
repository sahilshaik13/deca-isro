#!/usr/bin/env bash
# prepare_capture_contract_full.sh — freeze the trimmed CAPTURE_CONTRACT full plan
# and print the exact launch command. Does NOT start capture unless --go.
#
# Usage:
#   bash predictive/prepare_capture_contract_full.sh              # prepare only
#   bash predictive/prepare_capture_contract_full.sh --fabric pi  # default
#   bash predictive/prepare_capture_contract_full.sh --go         # LAUNCH (only when user says go)
#   bash predictive/prepare_capture_contract_full.sh --go --resume
#
# Locked trim (~9.25 h/fabric): L1/L4×4 · L2/L3 short inject · L5×8+plateau≥40 ·
# L6×4 · COMPOUND×8 · chaos 7200s. See docs/CAPTURE_CONTRACT.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
FABRIC=pi
SEED=42
STAMP=""
DO_GO=0
RESUME=0
SKIP_PREFLIGHT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric) FABRIC="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --go) DO_GO=1; shift ;;
    --resume) RESUME=1; shift ;;
    --skip-preflight) SKIP_PREFLIGHT=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

[[ "$FABRIC" == pi || "$FABRIC" == gns3 ]] || { echo "fabric pi|gns3"; exit 2; }

if [[ -z "$STAMP" ]]; then
  STAMP="full_variants_${FABRIC}_contract_$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [[ "$FABRIC" == pi ]]; then
  OUT_ROOT="$ROOT/data/deca/predictive/protocol/$STAMP"
  PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
  HOST=station1
else
  OUT_ROOT="$ROOT/data/deca/predictive/protocol_gns3/$STAMP"
  PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
  HOST=gns3-pe1
fi

PREP="$OUT_ROOT/_prep"
mkdir -p "$PREP" "$OUT_ROOT/logs"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"

echo "=== CAPTURE_CONTRACT full PREPARE fabric=$FABRIC stamp=$STAMP $(date -Is) ==="

# --- 1) Accuracy-contract plan (same builder run_variant_campaign uses) ---
PLAN="$PREP/plan.json"
"$PY" -m predictive.variant_recipes --mode full --seed "$SEED" --out "$PLAN"
EST_H="$("$PY" -c "import json;print(json.load(open('$PLAN'))['est_hours'])")"
N_JOBS="$("$PY" -c "import json;print(json.load(open('$PLAN'))['n_jobs'])")"
"$PY" -c "import json;d=json.load(open('$PLAN')); assert d['accuracy_contract']['best_honest_q1_q2_path']; assert d['accuracy_contract']['campaign_trim']['l4_x4_requires_loss_stride1']"

# --- 2) Preflight (refuses launch if fail; prepare still writes packet) ---
PREFLIGHT_OK=1
preflight() {
  echo "--- preflight ---"
  if [[ "$FABRIC" == pi ]]; then
    curl -sf -m 5 "$PROM/-/ready" >/dev/null || { echo "FAIL: Prom not ready at $PROM"; return 1; }
    echo "OK Prom $PROM"
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" 'hostname' >/dev/null \
      || { echo "FAIL: cannot SSH $HOST"; return 1; }
    echo "OK SSH $HOST"
    # refuse if another variant/q2 capture looks live
    if pgrep -af 'run_variant_campaign\.sh|run_q2_campaign\.sh' | grep -v "$$" | grep -qv grep; then
      echo "WARN: another variant/q2 campaign process may be running — check before --go"
    fi
  else
    curl -sf -m 5 "$PROM/-/ready" >/dev/null || { echo "FAIL: GNS3 Prom not ready at $PROM"; return 1; }
    docker ps --format '{{.Names}}' | grep -qE 'GNS3\.PE1\.|PE1' \
      || { echo "FAIL: GNS3 PE1 not running"; return 1; }
    echo "OK GNS3 Prom + PE1"
  fi
  for s in inject_cpu_stress inject_bgp_flap inject_rain_fade inject_loss_progression \
           inject_util_congestion inject_ce_sla_conflict; do
    [[ -x "$ROOT/scripts/${s}.sh" ]] || { echo "FAIL: missing $s"; return 1; }
  done
  echo "OK inject scripts"
  [[ -x "$ROOT/predictive/run_variant_campaign.sh" ]] || { echo "FAIL: run_variant_campaign.sh"; return 1; }
  echo "OK run_variant_campaign.sh"
  return 0
}

if [[ "$SKIP_PREFLIGHT" -eq 0 ]]; then
  preflight || PREFLIGHT_OK=0
else
  echo "--- preflight skipped ---"
fi

# --- 3) Launch packet (human + machine) ---
LAUNCH_CMD=(bash "$ROOT/predictive/run_variant_campaign.sh"
  --fabric "$FABRIC" --mode full --seed "$SEED" --stamp "$STAMP")
[[ "$RESUME" -eq 1 ]] && LAUNCH_CMD+=(--resume)

cat >"$PREP/LAUNCH_PACKET.json" <<EOF
{
  "prepared_ist": "$(date -Is)",
  "fabric": "$FABRIC",
  "stamp": "$STAMP",
  "out_root": "$OUT_ROOT",
  "prom": "$PROM",
  "host": "$HOST",
  "seed": $SEED,
  "n_jobs": $N_JOBS,
  "est_hours": $EST_H,
  "preflight_ok": $([[ "$PREFLIGHT_OK" -eq 1 ]] && echo true || echo false),
  "do_not_auto_start": true,
  "launch_requires": "--go on prepare_capture_contract_full.sh OR explicit run_variant_campaign.sh",
  "launch_cmd": "${LAUNCH_CMD[*]}",
  "post_run": "bash predictive/post_capture_contract_full.sh --fabric $FABRIC --stamp $STAMP",
  "priority_after": ["verify_L6_CE_SLA", "BGP_multiscale_features", "Q1_latency_densify", "multi_label_presence", "rekey_injector", "O4_depth"],
  "cite_board_untouched": "0.884/0.823/0.992 remain until this stamp is scored under promote bar"
}
EOF

cat >"$PREP/GO.sh" <<EOF
#!/usr/bin/env bash
# Generated — only run when operator confirms go.
set -euo pipefail
cd "$ROOT"
exec ${LAUNCH_CMD[*]}
EOF
chmod +x "$PREP/GO.sh"

cat >"$PREP/README.txt" <<EOF
CAPTURE_CONTRACT full campaign — PREPARED, not started.
stamp=$STAMP  fabric=$FABRIC  est_hours=$EST_H  n_jobs=$N_JOBS
preflight_ok=$PREFLIGHT_OK

To launch (only when told):
  bash predictive/prepare_capture_contract_full.sh --fabric $FABRIC --stamp $STAMP --go
  # or: bash $PREP/GO.sh

After COMPLETE:
  bash predictive/post_capture_contract_full.sh --fabric $FABRIC --stamp $STAMP
EOF

echo
echo "=== PREPARED (not started) ==="
echo "  stamp:     $STAMP"
echo "  out:       $OUT_ROOT"
echo "  plan:      $PLAN"
echo "  packet:    $PREP/LAUNCH_PACKET.json"
echo "  est_hours: $EST_H  n_jobs=$N_JOBS"
echo "  preflight: $([[ "$PREFLIGHT_OK" -eq 1 ]] && echo OK || echo FAIL)"
echo
echo "  Launch when you say go:"
echo "    bash predictive/prepare_capture_contract_full.sh --fabric $FABRIC --stamp $STAMP --go"
echo

if [[ "$DO_GO" -eq 0 ]]; then
  echo "Stopped after prepare (no --go)."
  exit 0
fi

if [[ "$PREFLIGHT_OK" -ne 1 && "$SKIP_PREFLIGHT" -eq 0 ]]; then
  echo "REFUSE --go: preflight failed. Fix lab or pass --skip-preflight (not recommended)."
  exit 3
fi

echo "=== LAUNCHING CAPTURE_CONTRACT full fabric=$FABRIC stamp=$STAMP $(date -Is) ==="
exec bash "$PREP/GO.sh"
