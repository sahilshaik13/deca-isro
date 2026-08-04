#!/usr/bin/env bash
# run_protocol_campaign_gns3.sh — GNS3 protocol corpus (pilot or full).
#
# Writes to data/deca/predictive/protocol_gns3/<STAMP>/ only.
# Never touches Pi ACTIVE_STAMP.json / :9090 / scripts/inject_*.sh.
#
# Usage:
#   bash predictive/run_protocol_campaign_gns3.sh              # pilot
#   bash predictive/run_protocol_campaign_gns3.sh --full
#   bash predictive/run_protocol_campaign_gns3.sh --only 0,1
#   bash predictive/run_protocol_campaign_gns3.sh --skip-chaos
#   bash predictive/run_protocol_campaign_gns3.sh --pilot --stamp STAMP --resume
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export DECA_FABRIC=gns3
PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
MODE=pilot
ONLY=""
SKIP_CHAOS=0
RESUME=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
INJ="$ROOT/lab/gns3/inject"
PROTO_ROOT="$ROOT/data/deca/predictive/protocol_gns3"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) MODE=full; shift ;;
    --pilot) MODE=pilot; shift ;;
    --medium) MODE=medium; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    --skip-chaos) SKIP_CHAOS=1; shift ;;
    --resume) RESUME=1; shift ;;
    --host) shift 2 ;;
    --prom) PROM="$2"; shift 2 ;;
    --stamp) STAMP="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

OUT_ROOT="$PROTO_ROOT/$STAMP"
mkdir -p "$OUT_ROOT" "$PROTO_ROOT"
MANIFEST="$OUT_ROOT/manifest.jsonl"
DEBUG_LOG="$OUT_ROOT/campaign_debug.log"
if [[ "$RESUME" -eq 0 ]]; then
  : >"$MANIFEST"
  : >"$DEBUG_LOG"
else
  touch "$MANIFEST"
  echo "" >>"$DEBUG_LOG"
  echo "===== RESUME $(date -u +%Y-%m-%dT%H:%M:%SZ) pid=$$ =====" >>"$DEBUG_LOG"
fi

dbg() {
  # Always visible in campaign log + durable debug file
  local msg="[DEBUG $(date -u +%Y-%m-%dT%H:%M:%SZ) pid=$$] $*"
  echo "$msg"
  echo "$msg" >>"$DEBUG_LOG" 2>/dev/null || true
}

on_err() {
  local rc=$?
  dbg "ERR trap rc=$rc line=${BASH_LINENO[0]:-?} cmd=${BASH_COMMAND:-?} pwd=$PWD"
  dbg "ERR trap callstack: ${FUNCNAME[*]:-}"
  return 0
}

on_exit() {
  local rc=$?
  dbg "EXIT trap rc=$rc line=${BASH_LINENO[0]:-?} last_cmd=${BASH_COMMAND:-?}"
  # do not clear injectors here — may race; leave state for post-mortem
  return 0
}

trap on_err ERR
trap on_exit EXIT

# Durations: full ≈ Pi multi-day; medium ≈ transfer stamp (~2–3h); pilot ≈ smoke
if [[ "$MODE" == full ]]; then
  L0_SEC=$((24 * 3600))
  L1_ITERS=10; L1_INJECT=$((2 * 3600)); L1_BASE=60; L1_POST=60
  L2_ITERS=10; L2_INJECT=$((1 * 3600)); L2_BASE=30; L2_POST=30
  L3_ITERS=10; L3_INJECT=$((1 * 3600)); L3_BASE=30; L3_POST=30
  L4_ITERS=8; L4_INJECT=600; L4_BASE=60; L4_POST=60
  L5_ITERS=8; L5_INJECT=600; L5_BASE=60; L5_POST=60
  CHAOS_SEC=$((12 * 3600))
elif [[ "$MODE" == medium ]]; then
  # Honest transfer corpus without multi-day wall clock
  L0_SEC=600
  L1_ITERS=4; L1_INJECT=300; L1_BASE=20; L1_POST=20
  L2_ITERS=4; L2_INJECT=180; L2_BASE=15; L2_POST=15
  L3_ITERS=4; L3_INJECT=180; L3_BASE=15; L3_POST=15
  L4_ITERS=4; L4_INJECT=300; L4_BASE=20; L4_POST=20
  L5_ITERS=4; L5_INJECT=300; L5_BASE=20; L5_POST=20
  CHAOS_SEC=1800
else
  L0_SEC=180
  L1_ITERS=2; L1_INJECT=120; L1_BASE=20; L1_POST=20
  L2_ITERS=2; L2_INJECT=90;  L2_BASE=15; L2_POST=15
  L3_ITERS=2; L3_INJECT=90;  L3_BASE=15; L3_POST=15
  L4_ITERS=2; L4_INJECT=120; L4_BASE=20; L4_POST=20
  L5_ITERS=2; L5_INJECT=120; L5_BASE=20; L5_POST=20
  CHAOS_SEC=240
fi

want() {
  local lab="$1"
  [[ -z "$ONLY" ]] && return 0
  [[ ",$ONLY," == *",$lab,"* ]]
}

# Lightweight PE1 HTB restore (campaign clear path). Full fabric HTB is slow and
# previously correlated with orchestrator death after L1 — keep it optional.
restore_pe1_htb() {
  local pe1
  pe1=$(docker ps --format '{{.Names}}' | grep -F 'GNS3.PE1.' | head -1 || true)
  if [[ -z "$pe1" ]]; then
    dbg "restore_pe1_htb: PE1 container missing — skip"
    return 0
  fi
  dbg "restore_pe1_htb: start on $pe1"
  # timeout so a wedged docker exec cannot hang the campaign forever
  if timeout 30 docker exec "$pe1" sh -c '
    set +e
    IF=eth0
    ip link set $IF up 2>/dev/null
    tc qdisc del dev $IF root 2>/dev/null
    tc qdisc add dev $IF root handle 1: htb default 20
    tc class add dev $IF parent 1: classid 1:1 htb rate 100mbit ceil 100mbit
    tc class add dev $IF parent 1:1 classid 1:10 htb rate 10mbit ceil 100mbit prio 0
    tc class add dev $IF parent 1:1 classid 1:15 htb rate 70mbit ceil 85mbit prio 1
    tc class add dev $IF parent 1:1 classid 1:20 htb rate 5mbit ceil 40mbit prio 2
    tc qdisc add dev $IF parent 1:10 handle 10: sfq
    tc qdisc add dev $IF parent 1:15 handle 15: sfq
    tc qdisc add dev $IF parent 1:20 handle 20: sfq
    tc filter add dev $IF protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
    tc filter add dev $IF protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
    exit 0
  ' >>"$DEBUG_LOG" 2>&1; then
    dbg "restore_pe1_htb: ok"
  else
    dbg "restore_pe1_htb: FAILED rc=$? (ignored — campaign continues)"
  fi
  return 0
}

clear_all() {
  # NEVER let cleanup kill the orchestrator (set -e safe)
  dbg "clear_all: begin"
  set +e
  dbg "clear_all: inject/clear_all.sh"
  timeout 60 bash "$INJ/clear_all.sh" >>"$DEBUG_LOG" 2>&1
  dbg "clear_all: clear_all.sh rc=$?"
  dbg "clear_all: util_congestion --clear"
  timeout 30 bash "$INJ/util_congestion.sh" --clear >>"$DEBUG_LOG" 2>&1
  dbg "clear_all: util_congestion rc=$?"
  restore_pe1_htb
  # Optional full-fabric HTB (off by default during campaign loops)
  if [[ "${DECA_GNS3_FULL_HTB_EACH_LABEL:-0}" == "1" ]]; then
    dbg "clear_all: full apply_sla_htb (DECA_GNS3_FULL_HTB_EACH_LABEL=1)"
    timeout 120 env BEST_EFFORT=1 bash "$ROOT/lab/gns3/apply_sla_htb.sh" >>"$DEBUG_LOG" 2>&1
    dbg "clear_all: apply_sla_htb rc=$?"
  fi
  set -e
  dbg "clear_all: end"
  return 0
}

append_manifest() {
  dbg "append_manifest: writing 1 line"
  echo "$1" >>"$MANIFEST"
  dbg "append_manifest: ok (manifest_lines=$(wc -l <"$MANIFEST"))"
}

dbg "=== GNS3 Protocol campaign mode=$MODE stamp=$STAMP resume=$RESUME ==="
dbg "out=$OUT_ROOT prom=$PROM debug_log=$DEBUG_LOG"
echo "=== GNS3 Protocol campaign mode=$MODE stamp=$STAMP ==="
echo "out=$OUT_ROOT prom=$PROM"
echo "debug: $DEBUG_LOG"
clear_all

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"
export DECA_PROM_URL_GNS3="$PROM"
export DECA_CAPTURE_PAUSE_FILE="$OUT_ROOT/CAPTURE_PAUSE"

# ACTIVE stamp for GNS3 only — never overwrite Pi ACTIVE_STAMP.json
python3 - <<PY
import json, time
from pathlib import Path
p = Path("$PROTO_ROOT/ACTIVE_STAMP_GNS3.json")
p.write_text(json.dumps({
  "active_stamp": "$STAMP",
  "fabric": "gns3",
  "mode": "$MODE",
  "prom": "$PROM",
  "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "path": "$OUT_ROOT",
  "resume": bool($RESUME),
}, indent=2) + "\n")
print("wrote", p)
PY

cat >"$OUT_ROOT/campaign_schema.json" <<EOF
{
  "stamp": "$STAMP",
  "fabric": "gns3",
  "mode": "$MODE",
  "schema_version": 2,
  "prom": "$PROM",
  "series_columns_extra": ["util_gre_mbps", "ipsec_rekey_events_1h", "ipsec_rekey_anomaly", "path_asymmetry"],
  "labels": {
    "0": "normal",
    "1": "rain_fade",
    "2": "cpu_stress",
    "3": "bgp_flap",
    "4": "loss_progression",
    "5": "util_congestion"
  },
  "notes": "GNS3 sim corpus — separate from Pi protocol/. Do not mash into Pi Q2 train set."
}
EOF

run_labeled() {
  local label="$1" iter="$2" name="$3"
  local baseline="$4" inject="$5" post="$6" seconds_only="${7:-0}"
  local dest="$OUT_ROOT/L${label}_${name}/iter_$(printf '%02d' "$iter")"
  local rc=0
  mkdir -p "$dest"
  dbg "run_labeled: enter label=$label iter=$iter name=$name dest=$dest"
  if [[ -f "$dest/label.json" ]]; then
    local rows=0
    if [[ -f "$dest/series.csv" ]]; then
      rows=$(($(wc -l < "$dest/series.csv") - 1))
    fi
    echo "--- label=$label iter=$iter SKIP (label.json exists, series_rows=$rows) ---"
    dbg "run_labeled: SKIP label=$label iter=$iter rows=$rows"
    return 0
  fi
  local started ended
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "--- label=$label iter=$iter → $dest ---"
  dbg "run_labeled: starting q2 label=$label iter=$iter at $started"
  set +e
  if [[ "$label" -eq 0 ]]; then
    DECA_PRED_OUT="$dest" bash "$ROOT/predictive/run_q2_campaign_gns3.sh" \
      --label 0 --seconds "$seconds_only" --prom "$PROM" \
      --stamp "${STAMP}_L0_i${iter}"
    rc=$?
  else
    DECA_PRED_OUT="$dest" bash "$ROOT/predictive/run_q2_campaign_gns3.sh" \
      --label "$label" --baseline-sec "$baseline" --inject-sec "$inject" \
      --post-sec "$post" --prom "$PROM" \
      --stamp "${STAMP}_L${label}_i${iter}"
    rc=$?
  fi
  set -e
  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  dbg "run_labeled: q2 finished label=$label iter=$iter rc=$rc ended=$ended label.json=$([ -f "$dest/label.json" ] && echo yes || echo no)"
  if [[ "$rc" -ne 0 ]]; then
    dbg "run_labeled: WARNING q2 rc=$rc — still clearing + manifest if label.json present"
  fi
  clear_all
  if [[ -f "$dest/label.json" ]]; then
    append_manifest "$(cat <<EOF
{"label":$label,"name":"$name","iteration":$iter,"path":"$dest","started":"$started","ended":"$ended","baseline_sec":$baseline,"inject_sec":$inject,"post_sec":$post,"mode":"$MODE","prom":"$PROM","fabric":"gns3","host":"gns3-pe1","q2_rc":$rc}
EOF
)"
  else
    dbg "run_labeled: NO label.json — not appending manifest (label=$label iter=$iter)"
  fi
  dbg "run_labeled: leave label=$label iter=$iter"
  # Do not abort the whole campaign on a single label failure
  return 0
}

if want 0; then
  run_labeled 0 1 normal 0 0 0 "$L0_SEC"
fi
if want 1; then
  for i in $(seq 1 "$L1_ITERS"); do
    run_labeled 1 "$i" rain_fade "$L1_BASE" "$L1_INJECT" "$L1_POST"
  done
fi
if want 2; then
  for i in $(seq 1 "$L2_ITERS"); do
    run_labeled 2 "$i" cpu_stress "$L2_BASE" "$L2_INJECT" "$L2_POST"
  done
fi
if want 3; then
  for i in $(seq 1 "$L3_ITERS"); do
    run_labeled 3 "$i" bgp_flap "$L3_BASE" "$L3_INJECT" "$L3_POST"
  done
fi
if want 4; then
  for i in $(seq 1 "$L4_ITERS"); do
    run_labeled 4 "$i" loss_progression "$L4_BASE" "$L4_INJECT" "$L4_POST"
  done
fi
if want 5; then
  for i in $(seq 1 "$L5_ITERS"); do
    run_labeled 5 "$i" util_congestion "$L5_BASE" "$L5_INJECT" "$L5_POST"
  done
fi

if [[ "$SKIP_CHAOS" -eq 0 ]]; then
  if [[ -f "$OUT_ROOT/chaos/label.json" ]]; then
    dbg "chaos: SKIP (label.json exists)"
    echo "=== GNS3 chaos SKIP (already done) ==="
  else
    echo "=== GNS3 chaos validation (${CHAOS_SEC}s) ==="
    dbg "chaos: start seconds=$CHAOS_SEC"
    set +e
    bash "$ROOT/predictive/run_chaos_campaign_gns3.sh" \
      --out "$OUT_ROOT/chaos" --seconds "$CHAOS_SEC" --prom "$PROM" \
      --stamp "$STAMP"
    dbg "chaos: finished rc=$?"
    set -e
    append_manifest "{\"label\":\"chaos\",\"path\":\"$OUT_ROOT/chaos\",\"seconds\":$CHAOS_SEC,\"mode\":\"$MODE\",\"train\":false,\"fabric\":\"gns3\"}"
  fi
fi

cat >"$OUT_ROOT/protocol_summary.json" <<EOF
{
  "stamp": "$STAMP",
  "fabric": "gns3",
  "mode": "$MODE",
  "out": "$OUT_ROOT",
  "manifest": "$MANIFEST",
  "schema_version": 2,
  "prom": "$PROM",
  "debug_log": "$DEBUG_LOG"
}
EOF

dbg "GNS3 Protocol complete successfully"
# disable EXIT noise on clean finish
trap - ERR EXIT
echo
echo "GNS3 Protocol complete: $OUT_ROOT"
echo "  ACTIVE: $PROTO_ROOT/ACTIVE_STAMP_GNS3.json"
echo "  debug:  $DEBUG_LOG"
echo "  Next: python -m predictive.build_protocol_dataset --protocol-dir $OUT_ROOT"
