#!/usr/bin/env bash
# Piggyback live Q1/Q2 infer (dry-run) onto each COMPOUND phase of a variant campaign.
# Supports ≥2 compounds (e.g. rain+cpu and loss+util).
#
#   bash predictive/watch_compound_arbitration.sh \
#     --fabric pi --campaign-log PATH --out-dir PATH
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FABRIC=pi
CAMPAIGN_LOG=""
OUT_DIR=""
INFER_SEC=150
ALLOW_EARLY=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric) FABRIC="$2"; shift 2 ;;
    --campaign-log) CAMPAIGN_LOG="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --infer-sec) INFER_SEC="$2"; shift 2 ;;
    --strict-severity) ALLOW_EARLY=0; shift ;;
    *) echo "unknown $1"; exit 2 ;;
  esac
done
[[ -n "$CAMPAIGN_LOG" && -n "$OUT_DIR" ]] || { echo "need --campaign-log and --out-dir"; exit 2; }
mkdir -p "$OUT_DIR"
STATUS="$OUT_DIR/arbitration_status.txt"
RESULT="$OUT_DIR/arbitration_result.json"

echo "waiting_for_compound $(date -Is)" | tee "$STATUS"

deadline=$(( $(date +%s) + 9000 ))
while [[ ! -f "$CAMPAIGN_LOG" ]]; do
  [[ $(date +%s) -lt $deadline ]] || { echo "TIMEOUT no campaign log" | tee "$STATUS"; exit 1; }
  sleep 5
done

if [[ "$FABRIC" == gns3 ]]; then
  PROM="${DECA_PROM_URL_GNS3:-http://127.0.0.1:9091}"
  HOST=gns3-pe1
else
  PROM="${DECA_PROM_URL:-http://127.0.0.1:9090}"
  HOST=station1
fi
EXTRA=()
[[ "$ALLOW_EARLY" -eq 1 ]] && EXTRA+=(--allow-early-red)
export DECA_FABRIC="$FABRIC"

seen_jobs=0
run_idx=0
declare -a RUN_JSONS=()

while true; do
  n_jobs=$(grep -cE '=== JOB [0-9]+/[0-9]+ compound' "$CAMPAIGN_LOG" 2>/dev/null || true)
  n_jobs=${n_jobs:-0}
  if [[ "$n_jobs" -gt "$seen_jobs" ]]; then
    target=$n_jobs
    # Wait until the Nth compound JOB header exists, then until a start-fault AFTER it
    while true; do
      mapfile -t job_lines < <(grep -nE '=== JOB [0-9]+/[0-9]+ compound' "$CAMPAIGN_LOG" | cut -d: -f1)
      if [[ ${#job_lines[@]} -ge $target ]]; then
        start_line=${job_lines[$((target - 1))]}
        if awk -v s="$start_line" 'NR>s && /start compound fault/ {found=1; exit} END{exit !found}' "$CAMPAIGN_LOG"; then
          break
        fi
      fi
      if grep -q "variant campaign COMPLETE" "$CAMPAIGN_LOG" 2>/dev/null; then
        break 2
      fi
      [[ $(date +%s) -lt $deadline ]] || break 2
      sleep 2
    done
    sleep 5
    run_idx=$((run_idx + 1))
    seen_jobs=$target
    INFER_LOG="$OUT_DIR/infer_compound_${run_idx}.jsonl"
    INFER_STDOUT="$OUT_DIR/infer_compound_${run_idx}.stdout"
    echo "compound_seen#$run_idx launching_infer $(date -Is)" | tee -a "$STATUS"
    set +e
    bash "$ROOT/predictive/launch_infer_q1_q2_cutover.sh" \
      --fabric "$FABRIC" \
      --prom "$PROM" \
      --host "$HOST" \
      --seconds "$INFER_SEC" \
      --cooldown-sec 30 \
      --dry-run \
      --log "$INFER_LOG" \
      "${EXTRA[@]}" \
      >"$INFER_STDOUT" 2>&1
    rc=$?
    set -e
    RUN_JSON="$OUT_DIR/arbitration_run_${run_idx}.json"
    "$ROOT/.venv-predictive/bin/python" - <<PY
import json, pathlib
log = pathlib.Path("$INFER_LOG")
events = []
if log.exists():
    for line in log.read_text().splitlines():
        line=line.strip()
        if not line: continue
        try: events.append(json.loads(line))
        except Exception: pass
with_arb = [e for e in events if e.get("arbitration")]
reds = [e for e in events if e.get("state")=="red"]
alerts = [e for e in events if e.get("alert")]
lat_ok = sum(1 for e in events if e.get("latency_gre_ms") is not None)
compound_hits = [e for e in events if (e.get("arbitration") or {}).get("compound_suspected")
                 or len((e.get("arbitration") or {}).get("firing_tti_heads") or []) > 1]
sample = None
for e in (compound_hits or alerts or reds or [x for x in events if x.get("latency_gre_ms") is not None] or events[-3:]):
    sample = {
        "state": e.get("state"),
        "q2_name": e.get("q2_name"),
        "severity": e.get("severity"),
        "latency_gre_ms": e.get("latency_gre_ms"),
        "urgency_eta_seconds": e.get("urgency_eta_seconds"),
        "arbitration": e.get("arbitration"),
        "has_alert": bool(e.get("alert")),
    }
    if e.get("state") == "red" or (e.get("arbitration") or {}).get("compound_suspected"):
        break
e2e = bool(with_arb) and $rc == 0 and lat_ok > 0 and len(reds) > 0
verdict = {
    "run": $run_idx,
    "fabric": "$FABRIC",
    "infer_rc": $rc,
    "n_events": len(events),
    "n_latency_samples": lat_ok,
    "n_red": len(reds),
    "n_alerts": len(alerts),
    "n_compound_suspected": len(compound_hits),
    "compound_multi_head_seen": bool(compound_hits),
    "ok": e2e,
    "sample": sample,
}
pathlib.Path("$RUN_JSON").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps(verdict, indent=2))
PY
    RUN_JSONS+=("$RUN_JSON")
    continue
  fi

  if grep -q "variant campaign COMPLETE" "$CAMPAIGN_LOG" 2>/dev/null; then
    sleep 3
    n_jobs=$(grep -cE '=== JOB [0-9]+/[0-9]+ compound' "$CAMPAIGN_LOG" 2>/dev/null || true)
    n_jobs=${n_jobs:-0}
    [[ "$n_jobs" -gt "$seen_jobs" ]] && continue
    break
  fi
  [[ $(date +%s) -lt $deadline ]] || break
  sleep 5
done

if [[ ${#RUN_JSONS[@]} -eq 0 ]]; then
  echo "FAILED no compound infer runs $(date -Is)" | tee "$STATUS"
  exit 2
fi

"$ROOT/.venv-predictive/bin/python" - <<PY
import json, pathlib, sys
runs = []
for p in """${RUN_JSONS[*]}""".split():
    runs.append(json.loads(pathlib.Path(p).read_text()))
ok_all = all(r.get("ok") for r in runs)
multi_any = any(r.get("compound_multi_head_seen") for r in runs)
# Prefer a multi-head sample for the summary card
sample = None
for r in runs:
    if r.get("compound_multi_head_seen") and r.get("sample"):
        sample = r["sample"]; break
if sample is None and runs:
    sample = runs[-1].get("sample")
verdict = {
    "fabric": "$FABRIC",
    "n_runs": len(runs),
    "runs": runs,
    "ok": ok_all and multi_any,
    "compound_multi_head_seen": multi_any,
    "wired_arbitration_in_live_loop": True,
    "n_red": sum(r.get("n_red", 0) for r in runs),
    "n_compound_suspected": sum(r.get("n_compound_suspected", 0) for r in runs),
    "n_latency_samples": sum(r.get("n_latency_samples", 0) for r in runs),
    "n_events": sum(r.get("n_events", 0) for r in runs),
    "n_alerts": sum(r.get("n_alerts", 0) for r in runs),
    "sample": sample,
    "note": "ok=every compound window had live lat+red; multi_head on ≥1 run",
}
pathlib.Path("$RESULT").write_text(json.dumps(verdict, indent=2) + "\n")
print(json.dumps({k: verdict[k] for k in ("ok", "n_runs", "compound_multi_head_seen", "n_red")}, indent=2))
status = "PASSED" if verdict["ok"] else "FAILED"
pathlib.Path("$STATUS").write_text(
    f"{status} ok={verdict['ok']} runs={len(runs)} multi={multi_any} $(date -Is)\n"
)
sys.exit(0 if verdict["ok"] else 3)
PY
