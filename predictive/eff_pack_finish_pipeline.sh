#!/usr/bin/env bash
# eff_pack_finish_pipeline.sh — wait for packs → fill weak slots → merge → train → score once.
# Idempotent. Safe to re-invoke. Does NOT mash GNS3 into Pi train.
# Compound multi-label architecture is OUT OF SCOPE (after scores).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

PI_STAMP=eff_pack_pi_20260804T092105Z
GNS_STAMP=eff_pack_gns3_20260804T094436Z
PI_OUT="$ROOT/data/deca/predictive/protocol/$PI_STAMP"
GNS_OUT="$ROOT/data/deca/predictive/protocol_gns3/$GNS_STAMP"
FV="$ROOT/data/deca/predictive/protocol/full_variants_pi_20260803T175816Z"
MODELS="$ROOT/data/deca/predictive/protocol_models"
STATE="$PI_OUT/FINISH_STATE.json"
STATUS="$PI_OUT/FINISH_STATUS.md"
LOG="$PI_OUT/logs/finish_pipeline.log"
mkdir -p "$PI_OUT/logs" "$GNS_OUT/logs"
exec >>"$LOG" 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

write_status() {
  local phase="$1" detail="${2:-}"
  cat >"$STATUS" <<EOF
# Efficiency pack finish — live status

**Updated:** $(date -u +%Y-%m-%dT%H:%M:%SZ) / $(TZ=Asia/Kolkata date +'%Y-%m-%d %H:%M:%S %Z')  
**Phase:** \`$phase\`  
**Detail:** $detail

| Gate | Status |
| --- | --- |
| Pi pack (L1+COMPOUND+chaos) | $( [[ -s $PI_OUT/chaos_holdout/series.csv ]] && echo DONE || echo running ) |
| GNS3 pack | $( [[ -s $GNS_OUT/chaos_holdout/series.csv ]] && echo DONE || echo running ) |
| Quarantine out of L* | yes |
| Fill BEST crumbs | see phase |
| Merge + Q2 train | see phase |
| chaos_final once + PROMOTE_BAR | see phase |

Compound multi-label = **after** this scorecard — not in this pipeline.
EOF
  "$PY" - <<PY
import json
from pathlib import Path
Path("$STATE").write_text(json.dumps({
  "phase": "$phase",
  "detail": """$detail""",
  "ts_utc": __import__("datetime").datetime.utcnow().isoformat()+"Z",
}, indent=2) + "\n")
PY
}

pack_done() {
  local out="$1"
  [[ -s "$out/chaos_holdout/series.csv" ]] || return 1
  local n
  n=$(wc -l <"$out/chaos_holdout/series.csv" | tr -d ' ')
  # chaos is ~5400s → need full capture (not just 5000 early)
  [[ "${n:-0}" -ge 5300 ]] || return 1
  # and capture_live for this chaos must not still be writing
  if pgrep -f "capture_live.*${out}/chaos_holdout" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

packs_alive() {
  pgrep -f "run_efficiency_pack.sh --fabric" >/dev/null 2>&1 \
    || pgrep -f "redo_eff_pack_best.sh" >/dev/null 2>&1 \
    || pgrep -f "capture_live --fabric" >/dev/null 2>&1
}

# ---------- phase: wait ----------
wait_packs() {
  write_status WAITING_PACKS "Pi and/or GNS3 still capturing"
  if pack_done "$PI_OUT" && pack_done "$GNS_OUT"; then
    log "both packs DONE"
    return 0
  fi
  log "waiting — pi_done=$(pack_done "$PI_OUT" && echo 1 || echo 0) gns_done=$(pack_done "$GNS_OUT" && echo 1 || echo 0) alive=$(packs_alive && echo 1 || echo 0)"
  # If a pack died early, watchdog should resume; we only report
  return 1
}

# ---------- grade helpers ----------
grade_l3() {
  local series="$1" kind="$2" # storm|mild
  "$PY" - "$series" "$kind" <<'PY'
import sys
from pathlib import Path
import pandas as pd
from predictive.preprocess import align_1hz, ema_smooth
from predictive.severity_label import stamp_series, _bgp_rate_smooth
p=Path(sys.argv[1]); kind=sys.argv[2]
if not p.exists() or p.stat().st_size < 100:
    print("MISSING"); sys.exit(2)
df=ema_smooth(align_1hz(pd.read_csv(p)), span=5)
st=stamp_series(df, 3)
a=float((st["severity"]=="3A").mean()); b=float((st["severity"]=="3B").mean())
delta=float(df["bgp_flap_count"].iloc[-1]-df["bgp_flap_count"].iloc[0])
# reject counter discontinuities
jumps=(df["bgp_flap_count"].diff().abs() > 1000).sum()
rate=float(_bgp_rate_smooth(df["bgp_flap_count"]).mean())
print(f"n={len(df)} delta={delta:.0f} rate={rate:.3f} 3A={a:.2f} 3B={b:.2f} big_jumps={int(jumps)}")
if jumps >= 2:
    sys.exit(3)
if kind=="storm":
    sys.exit(0 if (b>=0.40 and delta>=100) else 1)
sys.exit(0 if (a>=0.55 and b<0.25 and delta>=50) else 1)
PY
}

grade_l4() {
  local series="$1" deep="$2" # 0 mild 1 deep
  "$PY" - "$series" "$deep" <<'PY'
import sys
from pathlib import Path
import pandas as pd
from predictive.preprocess import align_1hz, ema_smooth
p=Path(sys.argv[1]); deep=int(sys.argv[2])
df=ema_smooth(align_1hz(pd.read_csv(p)), span=5)
loss=df["loss_gre_pct"].astype(float)
mx=float(loss.max()); n=len(df)
jumps=int((df["bgp_flap_count"].diff().abs() > 1000).sum()) if "bgp_flap_count" in df else 0
print(f"n={n} loss_max={mx:.2f} bgp_jumps={jumps}")
if n < 500: sys.exit(2)
if jumps >= 2: sys.exit(3)
need = 5.0 if deep else 0.8
sys.exit(0 if mx >= need else 1)
PY
}

grade_l1() {
  local series="$1"
  "$PY" - "$series" <<'PY'
import sys
from pathlib import Path
import pandas as pd
from predictive.preprocess import align_1hz, ema_smooth
p=Path(sys.argv[1])
df=ema_smooth(align_1hz(pd.read_csv(p)), span=5)
lat=df["latency_gre_ms"].astype(float)
span=float(lat.max()-lat.min()); n=len(df)
print(f"n={n} lat_span={span:.2f} max={float(lat.max()):.2f}")
sys.exit(0 if (n>=500 and span>=8.0) else 1)
PY
}

redo_pi_l3() {
  local id="$1" recipe="$2" dest="$3" kind="$4"
  log "FILL redo $id ($kind)"
  mkdir -p "$(dirname "$dest")"
  # archive current if present
  if [[ -d "$dest" ]]; then
    mkdir -p "$PI_OUT/_quarantine_do_not_train/replaced_weak"
    rm -rf "$PI_OUT/_quarantine_do_not_train/replaced_weak/$(basename "$dest")"
    mv "$dest" "$PI_OUT/_quarantine_do_not_train/replaced_weak/$(basename "$dest")"
  fi
  mkdir -p "$dest"
  export DECA_FABRIC=pi
  DECA_PRED_OUT="$dest" bash "$ROOT/predictive/run_q2_campaign.sh" \
    --label 3 --prom http://127.0.0.1:9090 --recipe-json "$recipe" \
    --stamp "${PI_STAMP}_FILL_${id}" >"$PI_OUT/logs/fill_${id}.log" 2>&1
  if grade_l3 "$dest/series.csv" "$kind"; then
    log "FILL PASS $id"
    grep -v "\"id\":\"${id}\"" "$PI_OUT/manifest.jsonl" >"$PI_OUT/manifest.jsonl.tmp" || true
    mv "$PI_OUT/manifest.jsonl.tmp" "$PI_OUT/manifest.jsonl"
    printf '{"id":"%s","path":"%s","ts":"%s","best_fill":true}\n' \
      "$id" "$dest" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$PI_OUT/manifest.jsonl"
    return 0
  fi
  log "FILL FAIL $id — kept attempt"
  return 1
}

fill_best() {
  write_status FILL_BEST "grading + replacing weak Pi slots (GNS3 soft storms kept honest)"
  local fail=0

  # Pi L3 storms
  for i in 1 2 3 4; do
    local s="$PI_OUT/L3_bgp_flap/l3_storm_$i/series.csv"
    if ! grade_l3 "$s" storm; then
      local rc=$?
      log "Pi l3_storm_$i grade fail rc=$rc — refill"
      # use recipes_best_redo if present else recipes
      local r="$PI_OUT/recipes_best_redo/l3_storm_$i.json"
      [[ -f "$r" ]] || r="$PI_OUT/recipes/l3_storm_$i.json"
      [[ -f "$r" ]] || r="$PI_OUT/recipes_best_redo/l3_storm_3.json"
      redo_pi_l3 "L3_l3_storm_$i" "$r" "$PI_OUT/L3_bgp_flap/l3_storm_$i" storm || fail=$((fail+1))
    else
      log "Pi l3_storm_$i BEST ok"
    fi
  done
  for i in 5 6 7 8; do
    local s="$PI_OUT/L3_bgp_flap/l3_mild_$i/series.csv"
    if ! grade_l3 "$s" mild; then
      log "Pi l3_mild_$i weak — refill"
      local r="$PI_OUT/recipes/l3_mild_$i.json"
      [[ -f "$r" ]] || continue
      redo_pi_l3 "L3_l3_mild_$i" "$r" "$PI_OUT/L3_bgp_flap/l3_mild_$i" mild || fail=$((fail+1))
    else
      log "Pi l3_mild_$i BEST ok"
    fi
  done

  # Pi L4
  for nm in l4_mild_1 l4_mild_2 l4_mild_3 l4_mild_4; do
    if ! grade_l4 "$PI_OUT/L4_loss_progression/$nm/series.csv" 0; then
      log "WARN Pi $nm weak/corrupt grade — flag (refill separately if needed)"
      mkdir -p "$PI_OUT/_quarantine_do_not_train/weak_l4_flags"
      echo "weak $(date -u -Iseconds)" >"$PI_OUT/_quarantine_do_not_train/weak_l4_flags/$nm.flag"
      fail=$((fail+1))
    else
      log "Pi $nm L4 ok"
    fi
  done
  for nm in l4_deep_5 l4_deep_6 l4_deep_7 l4_deep_8; do
    if ! grade_l4 "$PI_OUT/L4_loss_progression/$nm/series.csv" 1; then
      log "WARN Pi $nm weak"
      mkdir -p "$PI_OUT/_quarantine_do_not_train/weak_l4_flags"
      echo "weak $(date -u -Iseconds)" >"$PI_OUT/_quarantine_do_not_train/weak_l4_flags/$nm.flag"
      fail=$((fail+1))
    else
      log "Pi $nm L4 ok"
    fi
  done

  # Pi L1
  for i in 1 2 3; do
    local s="$PI_OUT/L1_rain_fade/l1_$i/series.csv"
    [[ -f "$s" ]] || { log "Pi l1_$i missing (pack may still be writing)"; return 1; }
    if ! grade_l1 "$s"; then
      log "WARN Pi l1_$i weak rain span"
      fail=$((fail+1))
    else
      log "Pi l1_$i ok"
    fi
  done

  # GNS3: soft storms NEVER replaced (honesty). Milds: flag only if weak.
  for i in 1 2 3 4; do
    log "GNS3 soft l3_storm_$i retained (honesty) — $(grade_l3 "$GNS_OUT/L3_bgp_flap/l3_storm_$i/series.csv" storm >/dev/null 2>&1 && echo would_pass_storm || echo expected_3A_twin)"
  done
  for i in 5 6 7 8; do
    if ! grade_l3 "$GNS_OUT/L3_bgp_flap/l3_mild_$i/series.csv" mild; then
      log "GNS3 mild_$i still weak — disclose; soft twin texture OK for transfer"
    else
      log "GNS3 mild_$i ok"
    fi
  done

  echo "$fail" >"$PI_OUT/logs/fill_best_fail_count.txt"
  write_status FILL_BEST_DONE "grade complete fail_flags=$fail (L3 hard fails trigger refill; L4/L1 flagged)"
  return 0
}

# ---------- merge + train ----------
merge_train() {
  write_status MERGE_TRAIN "building merged dataset + Q2 candidate"
  local MERGE_STAMP="merged_pi_eff_$(date -u +%Y%m%dT%H%M%SZ)"
  local MERGE="$ROOT/data/deca/predictive/protocol/$MERGE_STAMP"
  mkdir -p "$MERGE/dataset" "$MERGE/logs"
  echo "$MERGE_STAMP" >"$PI_OUT/ACTIVE_MERGE_STAMP.txt"

  # Build pack-only windows (skips _quarantine)
  log "build_protocol_dataset pack"
  "$PY" -m predictive.build_protocol_dataset --protocol-dir "$PI_OUT" --balance \
    >"$MERGE/logs/build_pack.log" 2>&1

  # Concat FV + pack windows (keep good + add pack). Prefer FV existing dataset.
  log "merge windows FV + pack"
  "$PY" - <<PY
import pandas as pd
from pathlib import Path
fv = Path("$FV/dataset/q2_windows.csv")
pk = Path("$PI_OUT/dataset/q2_windows.csv")
out = Path("$MERGE/dataset/q2_windows.csv")
assert fv.exists() and pk.exists(), (fv, pk)
a = pd.read_csv(fv)
b = pd.read_csv(pk)
b["source_capture"] = b.get("source_capture", "eff_pack").astype(str)
if "source_capture" not in a.columns:
    a["source_capture"] = "full_variants"
# tag pack rows
b["source_capture"] = "eff_pack/" + b["source_capture"].astype(str)
m = pd.concat([a, b], ignore_index=True)
out.parent.mkdir(parents=True, exist_ok=True)
m.to_csv(out, index=False)
Path("$MERGE/dataset/merge_meta.json").write_text(
    __import__("json").dumps({
        "fv_rows": len(a), "pack_rows": len(b), "merged_rows": len(m),
        "fv": str(fv), "pack": str(pk),
        "policy": "keep good full_variants + add eff_pack (quarantine excluded)",
    }, indent=2) + "\n"
)
print(f"merged {len(a)}+{len(b)}={len(m)} → {out}")
PY

  # Copy scaler from pack or FV
  cp -a "$PI_OUT/dataset/preprocess_scaler.npz" "$MERGE/dataset/" 2>/dev/null \
    || cp -a "$FV/dataset/preprocess_scaler.npz" "$MERGE/dataset/"

  local CAND="$MODELS/_candidates/${MERGE_STAMP}_q2_sev"
  mkdir -p "$CAND"
  log "train Q2 severity candidate → $CAND"
  # Match promoted-ish hyperparams family (d2_e100_l6_mcw3 style)
  "$PY" -m predictive.train_q2_xgb --severity \
    --data "$MERGE/dataset/q2_windows.csv" \
    --out-dir "$CAND" \
    --test-size 0.2 --seed 42 \
    --group-col source_capture --group-split \
    --holdout-must-contain L4 --holdout-must-contain COMPOUND \
    --max-depth 2 --n-estimators 100 --min-child-weight 3 \
    >"$MERGE/logs/train_q2.log" 2>&1

  echo "$CAND" >"$PI_OUT/ACTIVE_CANDIDATE.txt"
  echo "$MERGE" >"$PI_OUT/ACTIVE_MERGE_DIR.txt"
  write_status TRAINED "candidate=$CAND merge=$MERGE_STAMP"
}

# ---------- score once ----------
score_promote() {
  write_status SCORE "chaos_final once + PROMOTE_BAR"
  local CAND MERGE
  CAND=$(cat "$PI_OUT/ACTIVE_CANDIDATE.txt")
  MERGE=$(cat "$PI_OUT/ACTIVE_MERGE_DIR.txt")
  local MODEL="$CAND/q2_severity.joblib"
  [[ -f "$MODEL" ]] || MODEL="$CAND/model.joblib"
  [[ -f "$MODEL" ]] || { log "ERROR: no joblib in $CAND"; return 1; }
  local CHAOS="$FV/chaos_holdout"
  local OUTJ="$MERGE/logs/chaos_final_oneshot.json"
  local DEVJ="$MERGE/logs/chaos_dev_check.json"

  # light chaos_dev check (allowed) then FINAL once
  log "chaos_dev check (t_rel<3600) model=$MODEL"
  "$PY" -m predictive.eval_chaos \
    --chaos-dir "$CHAOS" \
    --q2-model "$MODEL" \
    --t-rel-max 3600 \
    --out-json "$DEVJ" >"$MERGE/logs/eval_chaos_dev.log" 2>&1 || true

  log "chaos_final ONCE (t_rel>=3600)"
  "$PY" -m predictive.eval_chaos \
    --chaos-dir "$CHAOS" \
    --q2-model "$MODEL" \
    --t-rel-min 3600 \
    --out-json "$OUTJ" >"$MERGE/logs/eval_chaos_final.log" 2>&1

  # GNS3 transfer
  local GNS_WIN=""
  for d in \
    "$ROOT/data/deca/predictive/protocol_gns3/full_variants_gns3_20260803T175816Z/dataset/q2_windows.csv" \
    "$GNS_OUT/dataset/q2_windows.csv"; do
    [[ -f "$d" ]] && GNS_WIN="$d" && break
  done
  if [[ -n "$GNS_WIN" ]]; then
    log "GNS3 transfer eval windows=$GNS_WIN"
    "$PY" - <<PY >"$MERGE/logs/gns3_transfer.json"
import json, joblib, pandas as pd, numpy as np
from pathlib import Path
from sklearn.metrics import accuracy_score
model=joblib.load(Path("$CAND")/"model.joblib")
meta=json.loads((Path("$CAND")/"meta.json").read_text()) if (Path("$CAND")/"meta.json").exists() else {}
# fall back: train_metrics features
feat=meta.get("features") or json.loads((Path("$CAND")/"train_metrics.json").read_text()).get("features")
df=pd.read_csv("$GNS_WIN")
# severity
ycol="severity" if "severity" in df.columns else "severity_id"
X=df[feat].astype(float)
y=df[ycol]
# map if needed
pred=model.predict(X)
# if model predicts ids
acc=float(accuracy_score(y if y.dtype!=object else y, pred)) if False else None
# Better: use same path as existing transfer scripts if present
tm=json.loads((Path("$CAND")/"train_metrics.json").read_text())
features=tm.get("feature_names") or tm.get("features")
if features is None:
    # infer from model
    features=list(X.columns)[: model.n_features_in_]
X=df.reindex(columns=features).astype(float).fillna(0)
from predictive.severity_label import SEVERITY_TO_ID
if ycol=="severity":
    y_id=y.map(SEVERITY_TO_ID)
else:
    y_id=y.astype(int)
pred=model.predict(X)
acc=float((pred==y_id.to_numpy()).mean())
print(json.dumps({"gns3_transfer_acc": acc, "n": int(len(df)), "windows": "$GNS_WIN"}, indent=2))
PY
  else
    # build gns3 pack dataset for transfer
    log "build GNS3 pack dataset for transfer"
    "$PY" -m predictive.build_protocol_dataset --protocol-dir "$GNS_OUT" --balance \
      >"$MERGE/logs/build_gns3.log" 2>&1 || true
  fi

  # Holdout from train_metrics
  log "write PROMOTE_SCORECARD"
  "$PY" - <<PY
import json
from pathlib import Path
cand=Path("$CAND")
merge=Path("$MERGE")
bar=json.loads(Path("$PI_OUT/PROMOTE_BAR.json").read_text())
tm=json.loads((cand/"train_metrics.json").read_text())
final=json.loads(Path("$OUTJ").read_text())
dev=json.loads(Path("$DEVJ").read_text()) if Path("$DEVJ").exists() else {}
xfer={"gns3_transfer_acc": None}
xp=merge/"logs"/"gns3_transfer.json"
if xp.exists():
    try: xfer=json.loads(xp.read_text())
    except Exception: pass

def phase_acc(ev, root):
    # best-effort from eval_chaos json structure
    phases=ev.get("phases") or ev.get("phase_exact") or {}
    if isinstance(phases, dict) and root in phases:
        v=phases[root]
        return float(v.get("exact", v) if isinstance(v, dict) else v)
    # alternate
    for k,v in (ev.get("by_root") or {}).items():
        if str(k) in (str(root), f"root_{root}"):
            return float(v.get("exact_acc", v.get("acc", 0)))
    return None

holdout=float(tm.get("accuracy") or tm.get("holdout_accuracy") or 0)
chaos_final=float(final.get("q2_severity_exact_acc") or final.get("severity_exact_acc") or final.get("exact_acc") or 0)
bgp_exact=phase_acc(final, 3) or phase_acc(final, "3") or final.get("bgp_exact_acc")
bgp_family=final.get("bgp_family_acc") or final.get("root_3_recall")
loss_ph=phase_acc(final, 4) or final.get("loss_phase_exact")
util_ph=phase_acc(final, 5) or final.get("util_phase_exact")
gns3=xfer.get("gns3_transfer_acc")

# Pull from nested eval if present
if bgp_exact is None and "q2" in final:
    q2=final["q2"]
    chaos_final=float(q2.get("severity_exact_acc", chaos_final))
    bgp_exact=q2.get("bgp_exact") or bgp_exact
    bgp_family=q2.get("bgp_family") or bgp_family

req=bar.get("require") or bar
# PROMOTE_BAR.json shape may vary — use md numbers as defaults
need={
  "bgp_exact": 0.70,
  "bgp_family": 0.84,
  "holdout": 0.870,
  "chaos_final": 0.800,
  "loss_phase": 0.950,
  "util_phase": 0.950,
  "gns3_transfer": 0.620,
}
checks={
  "holdout": holdout,
  "chaos_final": chaos_final,
  "bgp_exact": bgp_exact,
  "bgp_family": bgp_family,
  "loss_phase": loss_ph,
  "util_phase": util_ph,
  "gns3_transfer": gns3,
}
promote=True
reasons=[]
for k,floor in need.items():
    v=checks.get(k)
    if v is None:
        promote=False; reasons.append(f"{k}=MISSING")
        continue
    if float(v) < floor:
        promote=False; reasons.append(f"{k}={v:.4f}<{floor}")

scorecard={
  "candidate": str(cand),
  "merge": str(merge),
  "metrics": checks,
  "floors": need,
  "promote": promote,
  "reasons": reasons,
  "chaos_final_raw_keys": list(final.keys())[:40],
  "train_accuracy": holdout,
  "decision": "PROMOTE" if promote else "NO_PROMOTE_keep_d2_e100_l6_mcw3",
}
(merge/"PROMOTE_SCORECARD.json").write_text(json.dumps(scorecard, indent=2)+"\n")
(Path("$PI_OUT")/"PROMOTE_SCORECARD.json").write_text(json.dumps(scorecard, indent=2)+"\n")
print(json.dumps(scorecard, indent=2))
PY

  write_status SCORED "see PROMOTE_SCORECARD.json"
}

# ---------- main state machine ----------
main() {
  log "=== finish pipeline tick ==="
  if [[ -f "$PI_OUT/PROMOTE_SCORECARD.json" ]] && grep -q '"decision"' "$PI_OUT/PROMOTE_SCORECARD.json"; then
    write_status DONE "scorecard already written — idle"
    log "already scored — exit 0"
    return 0
  fi

  if ! wait_packs; then
    return 2
  fi

  if [[ ! -f "$PI_OUT/logs/fill_best_done.flag" ]]; then
    fill_best
    touch "$PI_OUT/logs/fill_best_done.flag"
  fi

  if [[ ! -f "$PI_OUT/ACTIVE_CANDIDATE.txt" ]]; then
    merge_train
  fi

  if [[ ! -f "$PI_OUT/PROMOTE_SCORECARD.json" ]]; then
    score_promote
  fi

  write_status DONE "pipeline complete"
  log "=== finish pipeline COMPLETE ==="
  return 0
}

main "$@"
