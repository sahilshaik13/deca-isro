#!/usr/bin/env bash
# queue_util_clean_after_contract.sh — start util_clean when contract stamps finish.
# Invoked by prepare_util_clean_redo.sh --queue-after-contract (or run directly).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SEED=42
FABRICS_CSV=gns3
STAMPS_CSV=""
PI_CONTRACT=full_variants_pi_contract_20260805T042130Z
GNS3_CONTRACT=full_variants_gns3_contract_20260805T070955Z
POLL_SEC=60

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabrics) FABRICS_CSV="$2"; shift 2 ;;
    --stamps) STAMPS_CSV="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --pi-contract) PI_CONTRACT="$2"; shift 2 ;;
    --gns3-contract) GNS3_CONTRACT="$2"; shift 2 ;;
    --poll-sec) POLL_SEC="$2"; shift 2 ;;
    *) echo "unknown $1"; exit 2 ;;
  esac
done

IFS=',' read -ra FABRICS <<<"$FABRICS_CSV"
IFS=',' read -ra STAMPS <<<"$STAMPS_CSV"
[[ "${#FABRICS[@]}" -eq "${#STAMPS[@]}" && "${#STAMPS[@]}" -gt 0 ]] \
  || { echo "need matching --fabrics and --stamps CSV"; exit 2; }

done_path() {
  local stamp="$1"
  if [[ -f "$ROOT/data/deca/predictive/protocol/$stamp/ACTIVE_DONE" ]]; then
    echo "$ROOT/data/deca/predictive/protocol/$stamp/ACTIVE_DONE"
  elif [[ -f "$ROOT/data/deca/predictive/protocol_gns3/$stamp/ACTIVE_DONE" ]]; then
    echo "$ROOT/data/deca/predictive/protocol_gns3/$stamp/ACTIVE_DONE"
  else
    echo ""
  fi
}

echo "=== util_clean queue $(date -Is) waiting on contract stamps ==="
echo "  pi=$PI_CONTRACT  gns3=$GNS3_CONTRACT  poll=${POLL_SEC}s"

# Wait until BOTH contract campaigns are done (or absent/never started).
# If a contract stamp has no campaign process AND no ACTIVE_DONE but has many
# labels, still wait for ACTIVE_DONE to avoid racing a live run.
while true; do
  pi_done=0
  gns_done=0
  [[ -f "$ROOT/data/deca/predictive/protocol/$PI_CONTRACT/ACTIVE_DONE" ]] && pi_done=1
  [[ -f "$ROOT/data/deca/predictive/protocol_gns3/$GNS3_CONTRACT/ACTIVE_DONE" ]] && gns_done=1

  pi_live=0
  gns_live=0
  pgrep -af "run_variant_campaign.sh --fabric pi" | grep -q "$PI_CONTRACT" && pi_live=1 || true
  pgrep -af "run_variant_campaign.sh --fabric gns3" | grep -q "$GNS3_CONTRACT" && gns_live=1 || true

  echo "$(date -Is) pi_done=$pi_done pi_live=$pi_live gns_done=$gns_done gns_live=$gns_live"

  if [[ "$pi_done" -eq 1 && "$gns_done" -eq 1 && "$pi_live" -eq 0 && "$gns_live" -eq 0 ]]; then
    break
  fi
  # If only launching for one fabric, only wait on that fabric's contract
  if [[ "${#FABRICS[@]}" -eq 1 ]]; then
    only="${FABRICS[0]}"
    if [[ "$only" == gns3 && "$gns_done" -eq 1 && "$gns_live" -eq 0 ]]; then
      break
    fi
    if [[ "$only" == pi && "$pi_done" -eq 1 && "$pi_live" -eq 0 ]]; then
      break
    fi
  fi
  sleep "$POLL_SEC"
done

echo "=== contracts done — launching util_clean $(date -Is) ==="
# Clear leftover injects before clean redo
bash "$ROOT/lab/gns3/inject/clear_all.sh" >/dev/null 2>&1 || true
bash "$ROOT/lab/gns3/inject/util_congestion.sh" --clear >/dev/null 2>&1 || true
for s in cpu_stress bgp_flap rain_fade loss_progression util_congestion; do
  bash "$ROOT/scripts/inject_${s}.sh" --clear --host station1 >/dev/null 2>&1 || true
done

for i in "${!FABRICS[@]}"; do
  fab="${FABRICS[$i]}"
  stamp="${STAMPS[$i]}"
  if [[ -n "$(done_path "$stamp")" ]]; then
    echo "skip $stamp — already ACTIVE_DONE"
    continue
  fi
  if [[ "$fab" == pi ]]; then
    log="$ROOT/data/deca/predictive/protocol/$stamp/logs/launch_nohup.log"
  else
    log="$ROOT/data/deca/predictive/protocol_gns3/$stamp/logs/launch_nohup.log"
  fi
  mkdir -p "$(dirname "$log")"
  echo "LAUNCH fabric=$fab stamp=$stamp"
  nohup bash "$ROOT/predictive/run_variant_campaign.sh" \
    --fabric "$fab" --mode util_clean --seed "$SEED" --stamp "$stamp" \
    >>"$log" 2>&1 &
  echo "  pid=$! log=$log"
  sleep 8
done
echo "=== util_clean queue complete $(date -Is) ==="
