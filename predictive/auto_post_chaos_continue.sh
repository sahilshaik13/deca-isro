#!/usr/bin/env bash
# auto_post_chaos_continue.sh — after Pi chaos + L3 backfill, redo invalid L5.
#
# Safe to leave running: waits for chaos/label.json, then for L3 iter_01 series,
# then archives flat-util L5 and re-runs --only 5 --skip-chaos.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
STAMP="${1:-20260729T202832Z}"
BASE="$ROOT/data/deca/predictive/protocol/$STAMP"
LOG="$BASE/auto_post_chaos_continue.log"
HOST="${HOST:-station1}"
PROM="${PROM:-http://127.0.0.1:9090}"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"

exec >>"$LOG" 2>&1
echo "=== auto_post_chaos_continue start $(date -Is) stamp=$STAMP ==="

lab_busy() {
  pgrep -f 'inject_(util_congestion|bgp_flap|rain_fade|cpu_stress|loss_progression)\.sh' >/dev/null 2>&1 \
    || pgrep -f 'run_q2_campaign\.sh' >/dev/null 2>&1 \
    || pgrep -f 'run_protocol_campaign\.sh' >/dev/null 2>&1 \
    || pgrep -f 'run_chaos_campaign\.sh' >/dev/null 2>&1 \
    || pgrep -f 'resume_active_protocol\.sh' >/dev/null 2>&1 \
    || pgrep -f 'backfill_missing_protocol\.sh' >/dev/null 2>&1
}

echo "waiting for chaos/label.json…"
while [[ ! -f "$BASE/chaos/label.json" ]]; do
  rows=0
  [[ -f "$BASE/chaos/series.csv" ]] && rows=$(($(wc -l <"$BASE/chaos/series.csv") - 1))
  echo "  chaos pending rows=$rows $(date -Is)"
  sleep 120
done
echo "chaos complete $(date -Is)"

echo "waiting for L3 iter_01 series (>=3000 rows) + idle lab…"
L3="$BASE/L3_bgp_flap/iter_01/series.csv"
while true; do
  rows=0
  [[ -f "$L3" ]] && rows=$(($(wc -l <"$L3") - 1))
  if [[ "$rows" -ge 3000 ]] && ! lab_busy; then
    echo "L3 backfill ready rows=$rows lab idle $(date -Is)"
    break
  fi
  busy=no
  lab_busy && busy=yes || true
  echo "  L3 rows=$rows busy=$busy $(date -Is)"
  sleep 60
done

# Smoke util path before committing ~1.6h L5
echo "=== util smoke (60s) ==="
export DECA_FABRIC=pi
bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
bash "$ROOT/scripts/inject_util_congestion.sh" \
  --host "$HOST" --steps 2 --step-sec 15 --start-mbit 22 --end-mbit 36 --parallel 2 \
  >"$BASE/L5_util_smoke.log" 2>&1 || true
sleep 2
UTIL="$("$PY" - <<'PY'
import os
os.environ["DECA_FABRIC"] = "pi"
from predictive.prom_export import sample_bundle
u = sample_bundle("http://127.0.0.1:9090").get("util_gre_mbps")
print(u if u is not None else "nan")
PY
)"
bash "$ROOT/scripts/inject_util_congestion.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
echo "smoke util_gre_mbps=$UTIL"
python3 - <<PY
u = float("$UTIL") if "$UTIL" not in ("nan", "") else -1.0
if u < 15.0:
    raise SystemExit(f"REFUSE L5 redo: util smoke too low ({u})")
print(f"util smoke OK ({u:.2f} Mbps)")
PY

# Archive invalid L5 so --resume will re-capture
ARCH="$BASE/L5_util_congestion/INVALID_ARCHIVE_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ARCH"
echo "archiving flat-util L5 → $ARCH"
for it in "$BASE"/L5_util_congestion/iter_*; do
  [[ -d "$it" ]] || continue
  name=$(basename "$it")
  mkdir -p "$ARCH/$name"
  for f in series.csv q2_windows.csv q2_meta.json windows_summary.json label.json inject.log capture.log; do
    [[ -e "$it/$f" ]] && mv "$it/$f" "$ARCH/$name/" || true
  done
  # leave INVALID_UTIL.md pointer
  echo "archived to $ARCH/$name — awaiting redo $(date -Is)" >"$it/REDO_PENDING.txt"
done
[[ -f "$BASE/L5_util_congestion/INVALID_UTIL.md" ]] && cp -a "$BASE/L5_util_congestion/INVALID_UTIL.md" "$ARCH/" || true

echo "=== L5 redo (8× full util) $(date -Is) ==="
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_FABRIC=pi
bash "$ROOT/predictive/run_protocol_campaign.sh" \
  --full --stamp "$STAMP" --only 5 --skip-chaos --resume \
  --host "$HOST" --prom "$PROM"

# Verify util rose in new series
echo "=== post-L5 util check ==="
"$PY" - <<PY
import csv
from pathlib import Path
root = Path("$BASE/L5_util_congestion")
bad = []
for it in sorted(root.glob("iter_*")):
    s = it / "series.csv"
    if not s.exists():
        bad.append(f"{it.name}: NO_SERIES")
        continue
    rows = list(csv.DictReader(s.open()))
    util = [float(r["util_gre_mbps"]) for r in rows if r.get("util_gre_mbps") not in (None, "")]
    umax = max(util) if util else 0.0
    ok = umax >= 15.0
    print(f"{it.name}: rows={len(rows)} util_max={umax:.3f} {'OK' if ok else 'FAIL'}")
    if not ok:
        bad.append(f"{it.name}: util_max={umax:.3f}")
    # clear pending marker on success
    pending = it / "REDO_PENDING.txt"
    if ok and pending.exists():
        pending.unlink()
if bad:
    raise SystemExit("L5 redo incomplete/invalid: " + "; ".join(bad))
print("L5 redo OK")
PY

# L0 util contamination note + clean filter artifact (non-destructive)
echo "=== L0 util-clean filter artifact ==="
"$PY" - <<'PY'
import csv
from pathlib import Path
root = Path("/home/brain/deca-isro/data/deca/predictive/protocol/20260729T202832Z/L0_normal/iter_01")
src = root / "series.csv"
out = root / "series_util_quiet.csv"
note = root / "UTIL_CONTAMINATION.md"
rows = list(csv.DictReader(src.open()))
cols = list(rows[0].keys()) if rows else []
quiet = [r for r in rows if float(r.get("util_gre_mbps") or 0) < 5.0]
with out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(quiet)
note.write_text(
    "# L0 util contamination\n\n"
    f"Full series: {len(rows)} rows; util p50 was ~36 Mbps (run_traffic during L0).\n"
    f"Quiet filter util_gre_mbps < 5: {len(quiet)} rows → `{out.name}`.\n"
    "Prefer quiet series (or re-capture) when training util-aware models; "
    "keep full series for latency/loss baselines if needed.\n"
)
print(f"wrote {out} quiet_rows={len(quiet)}/{len(rows)}")
PY

echo "=== auto_post_chaos_continue DONE $(date -Is) ==="
echo "Chaining auto_full_ml_pipeline (GNS3 medium + train/eval)…"
bash "$ROOT/predictive/auto_full_ml_pipeline.sh" "$STAMP"
echo "=== chained pipeline finished $(date -Is) ==="
