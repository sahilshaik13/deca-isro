#!/usr/bin/env bash
# run_variant_campaign.sh — diverse recipes (smoke gate → full) for Pi or GNS3.
#
#   bash predictive/run_variant_campaign.sh --fabric pi --mode smoke
#   bash predictive/run_variant_campaign.sh --fabric pi --mode full --stamp STAMP
#   bash predictive/run_variant_campaign.sh --fabric gns3 --mode smoke
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
FABRIC=pi
MODE=smoke
SEED=42
STAMP=""
RESUME=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric) FABRIC="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --resume) RESUME=1; shift ;;
    *) echo "unknown $1"; exit 2 ;;
  esac
done

[[ "$FABRIC" == pi || "$FABRIC" == gns3 ]] || { echo "fabric pi|gns3"; exit 2; }
[[ "$MODE" == smoke || "$MODE" == full || "$MODE" == quick ]] || { echo "mode smoke|full|quick"; exit 2; }

if [[ -z "$STAMP" ]]; then
  STAMP="${MODE}_variants_${FABRIC}_$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [[ "$FABRIC" == pi ]]; then
  OUT_ROOT="$ROOT/data/deca/predictive/protocol/$STAMP"
  PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
  HOST=station1
  Q2="$ROOT/predictive/run_q2_campaign.sh"
  export DECA_FABRIC=pi
else
  OUT_ROOT="$ROOT/data/deca/predictive/protocol_gns3/$STAMP"
  PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
  HOST=gns3-pe1
  Q2="$ROOT/predictive/run_q2_campaign_gns3.sh"
  export DECA_FABRIC=gns3
  # Refuse if PE1 down
  docker ps --format '{{.Names}}' | grep -qE 'GNS3\.PE1\.|PE1' \
    || { echo "ERROR: GNS3 PE1 not running — refuse variant campaign"; exit 3; }
fi

mkdir -p "$OUT_ROOT/recipes" "$OUT_ROOT/logs"
PLAN="$OUT_ROOT/plan.json"
LOG="$OUT_ROOT/campaign.log"
export DECA_PRED_PYTHON="$PY"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PROM_URL="$PROM"

exec > >(tee -a "$LOG") 2>&1
echo "=== variant campaign fabric=$FABRIC mode=$MODE stamp=$STAMP $(date -Is) ==="

"$PY" -m predictive.variant_recipes --mode "$MODE" --seed "$SEED" --out "$PLAN"
echo "plan: $PLAN"

# Preflight clears
if [[ "$FABRIC" == pi ]]; then
  for s in cpu_stress bgp_flap rain_fade loss_progression util_congestion; do
    bash "$ROOT/scripts/inject_${s}.sh" --clear --host station1 >/dev/null 2>&1 || true
  done
  bash "$ROOT/scripts/inject_ce_sla_conflict.sh" --clear --host station1 >/dev/null 2>&1 || true
  bash "$ROOT/scripts/run_capture_traffic.sh" --clear --host station1 >/dev/null 2>&1 || true
else
  bash "$ROOT/lab/gns3/inject/clear_all.sh" >/dev/null 2>&1 || true
  bash "$ROOT/lab/gns3/inject/capture_traffic.sh" --clear >/dev/null 2>&1 || true
fi

n_jobs="$("$PY" -c "import json;print(json.load(open('$PLAN'))['n_jobs'])")"
# Fail fast if accuracy contract missing
"$PY" -c "import json;d=json.load(open('$PLAN')); assert d.get('accuracy_contract',{}).get('best_honest_q1_q2_path'), d"

for ji in $(seq 0 $((n_jobs - 1))); do
  job_type="$("$PY" -c "import json;print(json.load(open('$PLAN'))['jobs'][$ji]['job'])")"
  recipe_path="$OUT_ROOT/recipes/job_$(printf '%03d' "$ji").json"
  "$PY" -c "import json; json.dump(json.load(open('$PLAN'))['jobs'][$ji]['recipe'], open('$recipe_path','w'), indent=2)"

  if [[ "$job_type" == labeled || "$job_type" == ce_sla ]]; then
    lab="$("$PY" -c "import json;print(json.load(open('$recipe_path'))['label'])")"
    name="$("$PY" -c "import json;print(json.load(open('$recipe_path'))['name'])")"
    vidx="$("$PY" -c "import json;print(json.load(open('$recipe_path')).get('variant_idx',0))")"
    dest="$OUT_ROOT/L${lab}_${name}/iter_$(printf '%02d' $((vidx + 1)))"
    mkdir -p "$dest"
    if [[ "$RESUME" -eq 1 && -f "$dest/label.json" ]]; then
      echo "--- skip $dest (exists) ---"
      continue
    fi
    echo "=== JOB $ji/$n_jobs labeled L$lab $name v=$vidx → $dest ==="
    if [[ "$lab" -eq 0 ]]; then
      secs="$("$PY" -c "import json;print(json.load(open('$recipe_path'))['seconds'])")"
      DECA_PRED_OUT="$dest" bash "$Q2" --label 0 --seconds "$secs" --prom "$PROM" \
        --recipe-json "$recipe_path" --stamp "${STAMP}_j${ji}"
    else
      DECA_PRED_OUT="$dest" bash "$Q2" --label "$lab" --prom "$PROM" \
        --recipe-json "$recipe_path" --stamp "${STAMP}_j${ji}"
    fi
  elif [[ "$job_type" == compound ]]; then
    vidx="$("$PY" -c "import json;print(json.load(open('$recipe_path')).get('variant_idx',0))")"
    dest="$OUT_ROOT/COMPOUND/iter_$(printf '%02d' $((vidx + 1)))"
    mkdir -p "$dest"
    if [[ "$RESUME" -eq 1 && -f "$dest/label.json" ]]; then
      echo "--- skip $dest ---"
      continue
    fi
    echo "=== JOB $ji/$n_jobs compound v=$vidx → $dest ==="
    DECA_FABRIC="$FABRIC" bash "$ROOT/predictive/run_compound_capture.sh" \
      --recipe-json "$recipe_path" --out "$dest" --host "$HOST" --prom "$PROM"
  elif [[ "$job_type" == chaos_holdout ]]; then
    dest="$OUT_ROOT/chaos_holdout"
    mkdir -p "$dest"
    if [[ "$RESUME" -eq 1 && -f "$dest/label.json" ]]; then
      echo "--- skip chaos holdout ---"
      continue
    fi
    secs="$("$PY" -c "import json;print(json.load(open('$recipe_path'))['seconds'])")"
    echo "=== JOB $ji/$n_jobs chaos holdout ${secs}s → $dest ==="
    if [[ "$FABRIC" == pi ]]; then
      bash "$ROOT/predictive/run_chaos_campaign.sh" \
        --out "$dest" --seconds "$secs" --host station1 --prom "$PROM" --stamp "${STAMP}_holdout"
    else
      bash "$ROOT/predictive/run_chaos_campaign_gns3.sh" \
        --out "$dest" --seconds "$secs" --prom "$PROM" --stamp "${STAMP}_holdout"
    fi
    echo '{"train": false, "name": "chaos_holdout", "variant": true}' >"$dest/label.json"
  fi
done

echo "=== variant campaign COMPLETE fabric=$FABRIC mode=$MODE stamp=$STAMP $(date -Is) ==="
echo "$STAMP" >"$OUT_ROOT/ACTIVE_DONE"
[[ "$FABRIC" == pi ]] && echo "$STAMP" >"$ROOT/data/deca/predictive/protocol/ACTIVE_VARIANT_STAMP.json" \
  || echo "$STAMP" >"$ROOT/data/deca/predictive/protocol_gns3/ACTIVE_VARIANT_STAMP.json"
