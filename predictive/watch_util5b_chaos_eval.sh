#!/usr/bin/env bash
# Wait for fresh util5b chaos_holdout (7200s), then chaos_dev select → oneshot final.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
STAMP="${1:-full_variants_pi_contract_20260805T042130Z}"
OUT="$ROOT/data/deca/predictive/protocol/$STAMP"
CHAOS="$OUT/chaos_holdout"
TRAIN="$OUT/train_logs/contract_util5b_schedule"
LOG="$OUT/logs/util5b_chaos_eval.log"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$OUT/logs"

exec > >(tee -a "$LOG") 2>&1
echo "=== watch util5b chaos eval $(date -Is) ==="

# Wait until capture finished: label.json present + series ~7200 + chaos proc gone
for i in $(seq 1 180); do
  n=0
  [[ -f "$CHAOS/series.csv" ]] && n=$(wc -l <"$CHAOS/series.csv" | tr -d ' ')
  alive=0
  pgrep -f "run_chaos_campaign.sh.*${STAMP}/chaos_holdout" >/dev/null 2>&1 && alive=1
  pgrep -f "capture_live.*${STAMP}/chaos_holdout" >/dev/null 2>&1 && alive=1
  echo "$(date -Is) rows=$n alive=$alive label=$([[ -f $CHAOS/label.json ]] && echo yes || echo no)"
  if [[ -f "$CHAOS/label.json" && "$n" -ge 7000 && "$alive" -eq 0 ]]; then
    break
  fi
  sleep 60
done

[[ -f "$CHAOS/label.json" ]] || { echo "chaos did not finish"; exit 1; }
[[ -f "$CHAOS/util_ceil_schedule.jsonl" ]] || { echo "missing util schedule"; exit 1; }

# Sanity: util phase must contain some 5B under schedule labeling
"$PY" - <<PY
from pathlib import Path
import json
from collections import Counter
import pandas as pd
from predictive.preprocess import align_1hz, ema_smooth
from predictive.util_schedule import attach_ceil_schedule, load_ceil_schedule
from predictive.severity_label import label_rows
from predictive.eval_chaos import schedule_root_at

chaos = Path("$CHAOS")
df = ema_smooth(align_1hz(pd.read_csv(chaos / "series.csv")), span=5)
t0 = int(df["ts_unix"].iloc[0])
df["t_rel"] = df["ts_unix"].astype(int) - t0
df = attach_ceil_schedule(df, load_ceil_schedule(chaos / "util_ceil_schedule.jsonl"))
sch = json.loads((chaos / "chaos_schedule.json").read_text())
roots = [schedule_root_at(float(t), sch) for t in df["t_rel"]]
sev = label_rows(df, 5)
mask = [r == 5 for r in roots]
c = Counter(sev[mask])
print("chaos util-phase severity", dict(c))
if c.get("5B", 0) < 30:
    raise SystemExit(f"insufficient 5B in util phase: {dict(c)}")
PY

CHAOS_DEV_MAX=3600
for cand in cand_d2_e100_l6_mcw3 cand_d3_e120_l4 cand_d2_e80_l8; do
  m="$TRAIN/$cand/q2_severity.joblib"
  [[ -f "$m" ]] || continue
  "$PY" -m predictive.eval_chaos \
    --chaos-dir "$CHAOS" --q2-model "$m" \
    --t-rel-max "$CHAOS_DEV_MAX" \
    --out-json "$TRAIN/$cand/chaos_dev.json"
done

"$PY" - <<PY
import json
import subprocess
from pathlib import Path

train_root = Path("$TRAIN")
chaos = Path("$CHAOS")
py = "$PY"
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
        "util_phase_exact_dev": d.get("util_phase_exact"),
    })
results.sort(
    key=lambda r: (
        r["chaos_dev"] if r["chaos_dev"] is not None else -1,
        r["holdout"] if r["holdout"] is not None else -1,
    ),
    reverse=True,
)
selected = results[0]
print("selected", selected)

cmd = [
    py, "-m", "predictive.eval_chaos",
    "--chaos-dir", str(chaos),
    "--q2-model", selected["model"],
    "--t-rel-min", str(dev_max),
    "--out-json", str(train_root / "SELECTED_chaos_final_oneshot.json"),
]
subprocess.check_call(cmd)
final = json.loads((train_root / "SELECTED_chaos_final_oneshot.json").read_text())

# Frozen d2 on same fresh chaos (reference, not selection)
frozen = Path("$ROOT/data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib")
subprocess.check_call([
    py, "-m", "predictive.eval_chaos",
    "--chaos-dir", str(chaos),
    "--q2-model", str(frozen),
    "--t-rel-min", str(dev_max),
    "--out-json", str(train_root / "FROZEN_d2_chaos_final_on_fresh.json"),
])
frozen_final = json.loads((train_root / "FROZEN_d2_chaos_final_on_fresh.json").read_text())

verdict = {
    "stamp": "$STAMP",
    "fabric": "pi",
    "train_dir": str(train_root),
    "selected": selected["name"],
    "selection_rule": f"chaos_dev (t_rel<{dev_max:g}) primary → holdout tiebreak",
    "candidates": results,
    "chaos_final_ONESHOT": final.get("accuracy"),
    "chaos_final_phases": {
        "loss": final.get("loss_phase_exact"),
        "util": final.get("util_phase_exact"),
        "bgp": final.get("bgp_exact"),
        "phase_n": final.get("phase_n"),
    },
    "frozen_d2_on_fresh_chaos_final": {
        "accuracy": frozen_final.get("accuracy"),
        "util": frozen_final.get("util_phase_exact"),
        "loss": frozen_final.get("loss_phase_exact"),
        "bgp": frozen_final.get("bgp_exact"),
    },
    "promote": "NO_PROMOTE unless clears frozen cite bar 0.815; board stays locked",
    "label_fix": "schedule-sourced 5A/5B (UTIL5B_SCHEDULE_RECEIPT.json)",
}
(train_root / "CONTRACT_UTIL5B_VERDICT.json").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict, indent=2))
PY

echo "=== util5b chaos eval DONE $(date -Is) ==="
