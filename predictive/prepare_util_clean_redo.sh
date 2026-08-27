#!/usr/bin/env bash
# prepare_util_clean_redo.sh — clean L0/L5/util-compound redo (~2.4 h/fabric).
#
# Replaces corrupted contract-stamp util path data:
#   • GNS3 L0 early util_gre_mbps NaNs (Prom path=eth0 vs gre)
#   • GNS3 L5 missing util_ceil_schedule.jsonl / no plateau
#   • util-bearing compounds finalized after parent death / backfilled schedule
#
# Prefer this stamp over backfilled sidecars for util Q1 / util features.
#
# Usage:
#   bash predictive/prepare_util_clean_redo.sh                 # prepare GNS3 (default)
#   bash predictive/prepare_util_clean_redo.sh --fabric pi
#   bash predictive/prepare_util_clean_redo.sh --fabric both
#   bash predictive/prepare_util_clean_redo.sh --go            # LAUNCH now (refuse if busy)
#   bash predictive/prepare_util_clean_redo.sh --queue-after-contract
#       # wait for current contract stamps ACTIVE_DONE, then launch
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
FABRIC=gns3
SEED=42
STAMP=""
DO_GO=0
QUEUE_AFTER=0
RESUME=0

PI_CONTRACT="${DECA_PI_CONTRACT_STAMP:-full_variants_pi_contract_20260805T042130Z}"
GNS3_CONTRACT="${DECA_GNS3_CONTRACT_STAMP:-full_variants_gns3_contract_20260805T070955Z}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric) FABRIC="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --go) DO_GO=1; shift ;;
    --queue-after-contract) QUEUE_AFTER=1; shift ;;
    --resume) RESUME=1; shift ;;
    --pi-contract) PI_CONTRACT="$2"; shift 2 ;;
    --gns3-contract) GNS3_CONTRACT="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

[[ "$FABRIC" == pi || "$FABRIC" == gns3 || "$FABRIC" == both ]] || {
  echo "fabric pi|gns3|both"; exit 2
}

prepare_one() {
  local fab="$1"
  local stamp="$2"
  local out_root prom host
  if [[ "$fab" == pi ]]; then
    out_root="$ROOT/data/deca/predictive/protocol/$stamp"
    prom="${DECA_PROM_URL:-http://127.0.0.1:9090}"
    host=station1
  else
    out_root="$ROOT/data/deca/predictive/protocol_gns3/$stamp"
    prom="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
    host=gns3-pe1
  fi
  local prep="$out_root/_prep"
  mkdir -p "$prep" "$out_root/logs"
  local plan="$prep/plan.json"
  "$PY" -m predictive.variant_recipes --mode util_clean --seed "$SEED" --out "$plan"
  local est_h n_jobs
  est_h="$("$PY" -c "import json;print(json.load(open('$plan'))['est_hours'])")"
  n_jobs="$("$PY" -c "import json;print(json.load(open('$plan'))['n_jobs'])")"

  cat >"$prep/LAUNCH_PACKET.json" <<EOF
{
  "prepared_ist": "$(date -Is)",
  "fabric": "$fab",
  "stamp": "$stamp",
  "mode": "util_clean",
  "out_root": "$out_root",
  "prom": "$prom",
  "host": "$host",
  "seed": $SEED,
  "n_jobs": $n_jobs,
  "est_hours": $est_h,
  "supersedes_corrupt_on": {
    "pi_contract": "$PI_CONTRACT",
    "gns3_contract": "$GNS3_CONTRACT",
    "scope": ["L0_normal", "L5_util_congestion", "COMPOUND util v2/v3/v6"]
  },
  "reason": "clean redo — L0 util NaNs + L5 schedule/plateau + util compounds",
  "do_not_auto_start": true,
  "launch": "bash $ROOT/predictive/run_variant_campaign.sh --fabric $fab --mode util_clean --seed $SEED --stamp $stamp"
}
EOF

  cat >"$prep/README.md" <<EOF
# util_clean redo — \`$stamp\`

Fabric: **$fab** · ~**${est_h} h** · **$n_jobs** jobs · seed=$SEED

## Scope
- L0 baseline (clean \`util_gre_mbps\`)
- L5×8 with live \`util_ceil_schedule.jsonl\` + plateau ≥40s
- COMPOUND variants with util: v2 (loss+util), v3 (cpu+util), v6 (rain+cpu+util)

## Prefer over
Backfilled schedules / NaN fills on contract stamps:
- \`$PI_CONTRACT\`
- \`$GNS3_CONTRACT\`

## Launch
\`\`\`bash
bash predictive/run_variant_campaign.sh --fabric $fab --mode util_clean --seed $SEED --stamp $stamp
\`\`\`
EOF

  echo "PREPARED fabric=$fab stamp=$stamp est_hours=$est_h n_jobs=$n_jobs → $out_root"
  echo "  packet: $prep/LAUNCH_PACKET.json"
}

STAMPS=()
FABRICS=()
if [[ "$FABRIC" == both ]]; then
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  [[ -n "$STAMP" ]] && ts="$STAMP"
  FABRICS=(gns3 pi)
  STAMPS=("util_clean_gns3_${ts}" "util_clean_pi_${ts}")
elif [[ -z "$STAMP" ]]; then
  FABRICS=("$FABRIC")
  STAMPS=("util_clean_${FABRIC}_$(date -u +%Y%m%dT%H%M%SZ)")
else
  FABRICS=("$FABRIC")
  STAMPS=("$STAMP")
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"

echo "=== util_clean PREPARE fabric=$FABRIC $(date -Is) ==="
for i in "${!FABRICS[@]}"; do
  prepare_one "${FABRICS[$i]}" "${STAMPS[$i]}"
done

busy_check() {
  if pgrep -af 'run_variant_campaign\.sh' | grep -v grep | grep -qv "$$"; then
    echo "BUSY: variant campaign already running — refuse --go (use --queue-after-contract)"
    pgrep -af 'run_variant_campaign\.sh' | grep -v grep | head -5
    return 1
  fi
  return 0
}

launch_one() {
  local fab="$1" stamp="$2"
  local log
  if [[ "$fab" == pi ]]; then
    log="$ROOT/data/deca/predictive/protocol/$stamp/logs/launch_nohup.log"
  else
    log="$ROOT/data/deca/predictive/protocol_gns3/$stamp/logs/launch_nohup.log"
  fi
  mkdir -p "$(dirname "$log")"
  local cmd=(bash "$ROOT/predictive/run_variant_campaign.sh"
    --fabric "$fab" --mode util_clean --seed "$SEED" --stamp "$stamp")
  [[ "$RESUME" -eq 1 ]] && cmd+=(--resume)
  echo "LAUNCH ${cmd[*]}"
  nohup "${cmd[@]}" >>"$log" 2>&1 &
  echo "  pid=$! log=$log"
}

if [[ "$QUEUE_AFTER" -eq 1 ]]; then
  echo "=== queue: wait for contract ACTIVE_DONE then launch util_clean ==="
  nohup bash "$ROOT/predictive/queue_util_clean_after_contract.sh" \
    --fabrics "$(IFS=,; echo "${FABRICS[*]}")" \
    --stamps "$(IFS=,; echo "${STAMPS[*]}")" \
    --seed "$SEED" \
    --pi-contract "$PI_CONTRACT" \
    --gns3-contract "$GNS3_CONTRACT" \
    >>"$ROOT/data/deca/predictive/protocol_gns3/_queue_util_clean.log" 2>&1 &
  echo "queued waiter pid=$!  log=data/deca/predictive/protocol_gns3/_queue_util_clean.log"
  echo "Prepared stamps: ${STAMPS[*]}"
  exit 0
fi

if [[ "$DO_GO" -eq 1 ]]; then
  busy_check
  for i in "${!FABRICS[@]}"; do
    launch_one "${FABRICS[$i]}" "${STAMPS[$i]}"
    # stagger dual-fabric slightly
    [[ "${#FABRICS[@]}" -gt 1 ]] && sleep 5
  done
else
  echo
  echo "Prepared only (not launched). When ready:"
  echo "  bash predictive/prepare_util_clean_redo.sh --fabric $FABRIC --go"
  echo "  # or wait for current contract campaigns:"
  echo "  bash predictive/prepare_util_clean_redo.sh --fabric $FABRIC --queue-after-contract"
fi
