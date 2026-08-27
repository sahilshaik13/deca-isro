#!/usr/bin/env bash
# After L4×8 land in manifest and no L4 capture is active, pause that fabric's
# efficiency pack, replace weak L3 with BEST-band captures, resume for L1+.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

FABRIC="${1:?usage: $0 pi|gns3}"
if [[ "$FABRIC" == pi ]]; then
  STAMP=eff_pack_pi_20260804T092105Z
  OUT="$ROOT/data/deca/predictive/protocol/$STAMP"
  PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
  Q2="$ROOT/predictive/run_q2_campaign.sh"
  # Must pin fabric — ambient DECA_FABRIC=gns3 (NOC / sibling redo) rewrites
  # PromQL to gns3-pe1 labels on :9090 → capture waits forever on empty series.
  export DECA_FABRIC=pi
  unset DECA_REQUIRE_LIVE || true
else
  STAMP=eff_pack_gns3_20260804T094436Z
  OUT="$ROOT/data/deca/predictive/protocol_gns3/$STAMP"
  PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
  Q2="$ROOT/predictive/run_q2_campaign_gns3.sh"
  export DECA_REQUIRE_LIVE=0
  export DECA_FABRIC=gns3
fi

LOG="$OUT/logs/best_redo.log"
mkdir -p "$OUT/logs"
exec >>"$LOG" 2>&1
echo "=== best_redo start fabric=$FABRIC $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

l4_count() {
  local n
  n=$(grep -c '"id":"L4_' "$OUT/manifest.jsonl" 2>/dev/null || true)
  echo "${n:-0}"
}

l4_capture_active() {
  ps -eo args | grep -v grep | grep -F "$OUT/L4_loss_progression" | grep -q capture_live
}

pack_pids() {
  if [[ "$FABRIC" == gns3 ]]; then
    pgrep -f "run_efficiency_pack.sh --fabric gns3 --stamp $STAMP" || true
  else
    pgrep -f "run_efficiency_pack.sh --fabric pi --stamp $STAMP" || true
  fi
}

ensure_gns3_up() {
  [[ "$FABRIC" == gns3 ]] || return 0
  local PROJ=78f1223e-f45b-4f61-b131-8e103a8eaebb
  curl -sf -m5 -X POST "http://127.0.0.1:3080/v2/projects/$PROJ/open" >/dev/null || true
  docker ps --format '{{.Names}}' | grep -qE 'GNS3\.PE1\.' && return 0
  echo "starting GNS3 PE/CORE…"
  "$PY" - <<'PY' || true
import json, urllib.request
PROJ="78f1223e-f45b-4f61-b131-8e103a8eaebb"
base=f"http://127.0.0.1:3080/v2/projects/{PROJ}"
try:
    urllib.request.urlopen(urllib.request.Request(base+"/open", method="POST", data=b""), timeout=30)
except Exception:
    pass
nodes=json.load(urllib.request.urlopen(base+"/nodes"))
for n in nodes:
    if n["name"].startswith(("PE","CORE","CE-","IPERF")):
        try:
            urllib.request.urlopen(urllib.request.Request(base+f"/nodes/{n['node_id']}/start", method="POST", data=b""), timeout=60)
        except Exception:
            pass
PY
  sleep 5
}

grade_ok() {
  "$PY" - "$1" "$2" <<'PY'
import sys
from pathlib import Path
import pandas as pd
from predictive.preprocess import align_1hz, ema_smooth
from predictive.severity_label import stamp_series, _bgp_rate_smooth
p=Path(sys.argv[1]); kind=sys.argv[2]
df=ema_smooth(align_1hz(pd.read_csv(p)), span=5)
st=stamp_series(df, 3)
a=float((st["severity"]=="3A").mean()); b=float((st["severity"]=="3B").mean())
delta=float(df["bgp_flap_count"].iloc[-1]-df["bgp_flap_count"].iloc[0])
rate=float(_bgp_rate_smooth(df["bgp_flap_count"]).mean())
print(f"n={len(df)} delta={delta:.0f} rate={rate:.3f} 3A={a:.2f} 3B={b:.2f}")
if kind=="storm":
    sys.exit(0 if (b>=0.40 and delta>=100) else 1)
sys.exit(0 if (a>=0.55 and b<0.25 and delta>=50) else 1)
PY
}

run_one_l3() {
  local id="$1" recipe="$2" dest="$3" kind="$4"
  echo "--- REDO $id ($kind) ---"
  rm -rf "$dest"
  mkdir -p "$dest"
  ensure_gns3_up
  DECA_PRED_OUT="$dest" bash "$Q2" --label 3 --prom "$PROM" --recipe-json "$recipe" \
    --stamp "${STAMP}_BEST_${id}" >"$OUT/logs/best_${id}.log" 2>&1
  if grade_ok "$dest/series.csv" "$kind"; then
    echo "PASS $id"
    grep -v "\"id\":\"${id}\"" "$OUT/manifest.jsonl" >"$OUT/manifest.jsonl.tmp" || true
    mv "$OUT/manifest.jsonl.tmp" "$OUT/manifest.jsonl"
    printf '{"id":"%s","path":"%s","ts":"%s","best_redo":true}\n' \
      "$id" "$dest" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$OUT/manifest.jsonl"
    return 0
  fi
  echo "FAIL $id (band not met) — keeping capture for audit; not promoted as BEST"
  # Additive hard storms: still index in manifest with honest flag so they are not lost,
  # but tagged so merge can treat as attempt-not-guarantee.
  if [[ "$id" == *storm_hard* ]]; then
    grep -v "\"id\":\"${id}\"" "$OUT/manifest.jsonl" >"$OUT/manifest.jsonl.tmp" || true
    mv "$OUT/manifest.jsonl.tmp" "$OUT/manifest.jsonl"
    printf '{"id":"%s","path":"%s","ts":"%s","best_redo":false,"additive_hard_attempt":true,"band_met":false}\n' \
      "$id" "$dest" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$OUT/manifest.jsonl"
  fi
  return 1
}

echo "Waiting for L4×8 + idle L4 capture…"
while true; do
  ensure_gns3_up
  c=$(l4_count); c=${c//[^0-9]/}
  active=0; l4_capture_active && active=1 || true
  echo "$(date -u +%H:%M:%SZ) L4_done=$c l4_capture_active=$active"
  if [[ "${c:-0}" -ge 8 && "$active" -eq 0 ]]; then
    # also wait if q2 campaign still on an l4 recipe for this stamp
    if ps -eo args | grep -v grep | grep -F "$STAMP" | grep -E 'l4_mild|l4_deep' | grep -q .; then
      sleep 20; continue
    fi
    break
  fi
  sleep 45
done

echo "Pausing pack for BEST L3 redo"
for pid in $(pack_pids); do
  echo "TERM $pid"; kill -TERM "$pid" 2>/dev/null || true
done
sleep 4
for pid in $(pack_pids); do
  kill -KILL "$pid" 2>/dev/null || true
done
# kill orphan L1+ campaigns if any started
if [[ "$FABRIC" == gns3 ]]; then
  pkill -f "run_q2_campaign_gns3.sh.*${STAMP}" 2>/dev/null || true
  bash "$ROOT/lab/gns3/inject/clear_all.sh" >/dev/null 2>&1 || true
else
  pkill -f "run_q2_campaign.sh.*${STAMP}" 2>/dev/null || true
  for s in cpu_stress bgp_flap rain_fade loss_progression util_congestion; do
    bash "$ROOT/scripts/inject_${s}.sh" --clear --host station1 >/dev/null 2>&1 || true
  done
fi
sleep 2

R="$OUT/recipes_best_redo"
if [[ "$FABRIC" == gns3 ]]; then
  # HONESTY: do NOT replace soft storm→3A twin captures (selection bias / goalpost move).
  # Keep originals; ADD period=3 hard attempts under l3_storm_hard_* (may still land 3A — disclose).
  echo "Keeping original GNS3 l3_storm_* (soft twin texture) — no replace"
  mkdir -p "$OUT/L3_bgp_flap"
  echo "Original soft storms retained as transfer-honest corpus" >"$OUT/L3_bgp_flap/HONEST_SOFT_STORM_KEPT.md"
  for i in 1 2 3 4; do
    # additive path + new manifest id — never rm original l3_storm_i
    run_one_l3 "L3_l3_storm_hard_${i}" "$R/l3_storm_hard_${i}.json"       "$OUT/L3_bgp_flap/l3_storm_hard_${i}" storm || \
      echo "NOTE: hard storm $i did not hit 3B — kept attempt; originals untouched"
  done
  # mild: only replace if currently weak; archive first
  for i in 6 8; do
    src="$OUT/L3_bgp_flap/l3_mild_${i}"
    if [[ -d "$src" ]]; then
      mkdir -p "$OUT/L3_bgp_flap/_pre_best_mild"
      rm -rf "$OUT/L3_bgp_flap/_pre_best_mild/l3_mild_${i}"
      cp -a "$src" "$OUT/L3_bgp_flap/_pre_best_mild/l3_mild_${i}"
    fi
    run_one_l3 "L3_l3_mild_${i}" "$R/l3_mild_${i}.json" "$src" mild || true
  done
else
  # Pi storm_3 was counter-discontinuity corruption (not honest soft texture) — redo in place OK
  src="$OUT/L3_bgp_flap/l3_storm_3"
  mkdir -p "$OUT/L3_bgp_flap/_pre_best_storm"
  if [[ -d "$src" ]]; then
    rm -rf "$OUT/L3_bgp_flap/_pre_best_storm/l3_storm_3"
    cp -a "$src" "$OUT/L3_bgp_flap/_pre_best_storm/l3_storm_3"
  fi
  run_one_l3 "L3_l3_storm_3" "$R/l3_storm_3.json" "$src" storm || true
fi

echo "Resume pack → L1 + COMPOUND + chaos"
if [[ "$FABRIC" == gns3 ]]; then
  setsid env DECA_REQUIRE_LIVE=0 DECA_FABRIC=gns3 nohup bash "$ROOT/predictive/run_efficiency_pack.sh" \
    --fabric gns3 --stamp "$STAMP" --resume >>"$OUT/logs/pack_after_best.log" 2>&1 < /dev/null &
else
  setsid env DECA_FABRIC=pi nohup bash "$ROOT/predictive/run_efficiency_pack.sh" \
    --fabric pi --stamp "$STAMP" --resume >>"$OUT/logs/pack_after_best.log" 2>&1 < /dev/null &
fi
echo "resumed pid=$!"
echo "=== best_redo done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
