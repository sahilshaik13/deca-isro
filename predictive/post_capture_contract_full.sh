#!/usr/bin/env bash
# post_capture_contract_full.sh — after CAPTURE_CONTRACT full campaign COMPLETE.
# Window floors → build dataset → train Q2 candidates → chaos_dev select →
# chaos_final oneshot → write verdict. Does not promote automatically.
#
#   bash predictive/post_capture_contract_full.sh --fabric pi --stamp STAMP
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
FABRIC=pi
STAMP=""
SKIP_TRAIN=0
CHAOS_DEV_MAX=3600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric) FABRIC="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    --skip-train) SKIP_TRAIN=1; shift ;;
    --chaos-dev-max) CHAOS_DEV_MAX="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

[[ -n "$STAMP" ]] || { echo "need --stamp"; exit 2; }
[[ "$FABRIC" == pi || "$FABRIC" == gns3 ]] || { echo "fabric pi|gns3"; exit 2; }

if [[ "$FABRIC" == pi ]]; then
  OUT_ROOT="$ROOT/data/deca/predictive/protocol/$STAMP"
else
  OUT_ROOT="$ROOT/data/deca/predictive/protocol_gns3/$STAMP"
fi

[[ -d "$OUT_ROOT" ]] || { echo "missing $OUT_ROOT"; exit 2; }
[[ -f "$OUT_ROOT/ACTIVE_DONE" ]] || {
  echo "WARN: no ACTIVE_DONE — campaign may still be running. Continue in 3s…"
  sleep 3
}

LOG="$OUT_ROOT/logs/post_capture_contract.log"
TRAIN_ROOT="$OUT_ROOT/train_logs/contract_full"
mkdir -p "$OUT_ROOT/logs" "$TRAIN_ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"
export DECA_FABRIC="$FABRIC"

exec > >(tee -a "$LOG") 2>&1
echo "=== post CAPTURE_CONTRACT fabric=$FABRIC stamp=$STAMP $(date -Is) ==="

# 1) Mandatory Q1 window floors
echo "=== check_q1_window_floors ==="
"$PY" -m predictive.check_q1_window_floors \
  --protocol-dir "$OUT_ROOT" \
  --out "$OUT_ROOT/Q1_WINDOW_FLOORS.json"

# 2) Build balanced dataset (new stamp — does not touch frozen cite matrix)
echo "=== build_protocol_dataset ==="
BUILD_ARGS=(--protocol-dir "$OUT_ROOT" --balance --fabric "$FABRIC")
if [[ "$FABRIC" == gns3 ]]; then
  BUILD_ARGS+=(--fit-gns3-severity-bands --dataset-subdir dataset_sev_bands_gns3)
fi
"$PY" -m predictive.build_protocol_dataset "${BUILD_ARGS[@]}"

DS="$OUT_ROOT/dataset"
[[ "$FABRIC" == gns3 && -d "$OUT_ROOT/dataset_sev_bands_gns3" ]] \
  && DS="$OUT_ROOT/dataset_sev_bands_gns3"
Q2="$DS/q2_windows.csv"
[[ -f "$Q2" ]] || { echo "missing $Q2"; exit 2; }

if [[ "$SKIP_TRAIN" -eq 1 ]]; then
  echo "skip-train: dataset ready at $DS"
  exit 0
fi

CHAOS="$OUT_ROOT/chaos_holdout"
[[ -d "$CHAOS" ]] || { echo "missing chaos_holdout at $CHAOS"; exit 2; }

BANDS_ARGS=()
BANDS=""
if [[ "$FABRIC" == gns3 ]]; then
  BANDS="$(find "$OUT_ROOT" -name 'severity_bands_gns3.json' | head -1 || true)"
  [[ -n "$BANDS" ]] && BANDS_ARGS=(--severity-bands-json "$BANDS")
fi

# 3) Train candidates (group holdout) — BGP-fix discipline later on chaos_dev
train_one() {
  local name="$1" md="$2" ne="$3" rl="$4" mcw="$5"
  local out="$TRAIN_ROOT/$name"
  mkdir -p "$out"
  echo "--- train $name d=$md e=$ne l=$rl mcw=$mcw ---"
  "$PY" -m predictive.train_q2_xgb --severity --group-split \
    --data "$Q2" --out-dir "$out" \
    --max-depth "$md" --n-estimators "$ne" --reg-lambda "$rl" \
    --min-child-weight "$mcw" \
    --holdout-must-contain L4_ \
    --holdout-must-contain 'COMPOUND/' \
    --test-size 0.25 --seed 42
}

echo "=== train candidates ==="
train_one cand_d2_e100_l6_mcw3 2 100 6 3
train_one cand_d3_e120_l4 3 120 4 2
train_one cand_d2_e80_l8 2 80 8 2

# 4) chaos_dev (t_rel < 3600) select → chaos_final (t_rel ≥ 3600) oneshot
echo "=== chaos_dev select + chaos_final oneshot ==="
for cand in cand_d2_e100_l6_mcw3 cand_d3_e120_l4 cand_d2_e80_l8; do
  m="$TRAIN_ROOT/$cand/q2_severity.joblib"
  [[ -f "$m" ]] || continue
  "$PY" -m predictive.eval_chaos \
    --chaos-dir "$CHAOS" --q2-model "$m" \
    --t-rel-max "$CHAOS_DEV_MAX" \
    --out-json "$TRAIN_ROOT/$cand/chaos_dev.json" \
    ${BANDS_ARGS[@]+"${BANDS_ARGS[@]}"}
done

"$PY" - <<PY
import json
from pathlib import Path
import subprocess

train_root = Path("$TRAIN_ROOT")
out_root = Path("$OUT_ROOT")
chaos = Path("$CHAOS")
py = "$PY"
fabric = "$FABRIC"
dev_max = float("$CHAOS_DEV_MAX")

results = []
for p in sorted(train_root.glob("cand_*/chaos_dev.json")):
    d = json.loads(p.read_text())
    tm = p.parent / "train_metrics.json"
    hold = json.loads(tm.read_text()).get("accuracy") if tm.exists() else None
    results.append({
        "name": p.parent.name,
        "model": str(p.parent / "q2_severity.joblib"),
        "chaos_dev": d.get("accuracy"),
        "holdout": hold,
    })

if not results:
    raise SystemExit("no chaos_dev scores")

results.sort(
    key=lambda r: (
        r["chaos_dev"] if r["chaos_dev"] is not None else -1,
        r["holdout"] if r["holdout"] is not None else -1,
    ),
    reverse=True,
)
selected = results[0]
print("selected", selected["name"], "chaos_dev", selected["chaos_dev"])

cmd = [
    py, "-m", "predictive.eval_chaos",
    "--chaos-dir", str(chaos),
    "--q2-model", selected["model"],
    "--t-rel-min", str(dev_max),
    "--out-json", str(train_root / "SELECTED_chaos_final_oneshot.json"),
]
if fabric == "gns3":
    bands_file = list(out_root.glob("**/severity_bands_gns3.json"))
    if bands_file:
        cmd += ["--severity-bands-json", str(bands_file[0])]
subprocess.check_call(cmd)
final = json.loads((train_root / "SELECTED_chaos_final_oneshot.json").read_text())

verdict = {
    "stamp": "$STAMP",
    "fabric": fabric,
    "selected": selected["name"],
    "selection_rule": f"chaos_dev (t_rel<{dev_max:g}) primary → holdout tiebreak",
    "candidates": results,
    "chaos_final_ONESHOT": final.get("accuracy"),
    "chaos_final_path": str(train_root / "SELECTED_chaos_final_oneshot.json"),
    "note": "Do not promote without beating frozen d2 promote bar. Cite 0.884 is frozen-artifact.",
    "next_priority": [
        "verify_L6_CE_SLA",
        "BGP_multiscale_features",
        "Q1_latency_densify_check",
        "multi_label_presence",
        "rekey_injector",
        "O4_depth",
    ],
}
(train_root / "CONTRACT_FULL_VERDICT.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict, indent=2))
PY

echo "=== post CAPTURE_CONTRACT DONE $(date -Is) ==="
echo "  verdict: $TRAIN_ROOT/CONTRACT_FULL_VERDICT.json"
echo "  Promote only if sealed chaos_final clears bar — do not overwrite cite board casually."
