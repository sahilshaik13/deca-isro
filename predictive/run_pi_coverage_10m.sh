#!/usr/bin/env bash
# run_pi_coverage_10m.sh — ~10 min Pi fault-book coverage (PS13 P6 + O2 signals).
#
# One short pass each: L0 quiet, L1 rain, L2 CPU (user%), L3 BGP, L4 loss, L5 util, compound.
# Writes stamp under data/deca/predictive/protocol/ and a coverage_report.json.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
HOST=station1
PROM="${DECA_PROM_URL_PI:-${DECA_PROM_URL:-http://127.0.0.1:9090}}"
STAMP="${1:-pi_coverage_10m_$(date -u +%Y%m%dT%H%M%SZ)}"
OUT="$ROOT/data/deca/predictive/protocol/$STAMP"
mkdir -p "$OUT/logs" "$OUT/series"
export DECA_FABRIC=pi
export DECA_PROM_URL="$PROM"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DECA_PRED_PYTHON="$PY"

LOG="$OUT/coverage.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Pi 10m coverage stamp=$STAMP $(date -Is) ==="

clear_all() {
  for s in cpu_stress bgp_flap rain_fade loss_progression util_congestion; do
    bash "$ROOT/scripts/inject_${s}.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  done
}
clear_all

# Global PIDs (must NOT use command-substitution for background jobs — wait needs real children)
CAP_PID=0
INJ_PID=0

start_capture() {
  local name="$1" secs="$2"
  "$PY" -m predictive.capture_live --fabric pi --prom "$PROM" \
    --out "$OUT/series/${name}.csv" --seconds "$secs" --interval 1 \
    >"$OUT/logs/${name}_capture.log" 2>&1 &
  CAP_PID=$!
}

run_phase() {
  local name="$1" secs="$2"
  shift 2
  echo "=== PHASE $name (${secs}s) @ $(date -Is) ==="
  start_capture "$name" "$secs"
  sleep 3
  if [[ $# -gt 0 ]]; then
    "$@" >"$OUT/logs/${name}_inject.log" 2>&1 &
    INJ_PID=$!
    wait "$INJ_PID" || true
  fi
  wait "$CAP_PID" || true
  clear_all
  sleep 2
}

# Budget ≈ 30+55+50+50+55+55+55 ≈ 350s + clears ≈ 8–10m wall
run_phase L0_quiet 30
run_phase L1_rain 55 \
  bash "$ROOT/scripts/inject_rain_fade.sh" --host "$HOST" --steps 8 --step-sec 5 --start-ms 2 --end-ms 40
run_phase L2_cpu 50 \
  bash "$ROOT/scripts/inject_cpu_stress.sh" --host "$HOST" --seconds 40 --workers 2
run_phase L3_bgp 50 \
  bash "$ROOT/scripts/inject_bgp_flap.sh" --host "$HOST" --cycles 10 --period-sec 4
run_phase L4_loss 55 \
  bash "$ROOT/scripts/inject_loss_progression.sh" --host "$HOST" --steps 8 --step-sec 5 --start-pct 0 --end-pct 3.5
run_phase L5_util 55 \
  bash "$ROOT/scripts/inject_util_congestion.sh" --host "$HOST" --steps 4 --step-sec 10 --start-mbit 5 --end-mbit 35 --parallel 2

echo "=== PHASE COMPOUND (55s) @ $(date -Is) ==="
start_capture COMPOUND 55
sleep 3
bash "$ROOT/scripts/inject_rain_fade.sh" --host "$HOST" --steps 6 --step-sec 5 --start-ms 2 --end-ms 35 \
  >"$OUT/logs/COMPOUND_rain.log" 2>&1 &
RPID=$!
bash "$ROOT/scripts/inject_cpu_stress.sh" --host "$HOST" --seconds 40 --workers 2 \
  >"$OUT/logs/COMPOUND_cpu.log" 2>&1 &
CPID=$!
wait "$RPID" "$CPID" || true
wait "$CAP_PID" || true
clear_all

"$PY" - <<PY
import json, time
from pathlib import Path
import pandas as pd

out = Path("$OUT")
series_dir = out / "series"
checks = []
failures = []

def stats(name, path, rules):
    if not path.exists():
        failures.append(f"{name}: missing series.csv")
        checks.append({"name": name, "rows": 0})
        return
    df = pd.read_csv(path)
    row = {"name": name, "rows": len(df)}
    for col in ("latency_gre_ms", "loss_gre_pct", "util_gre_mbps", "cpu_usage_user", "cpu_usage_system", "bgp_flap_count"):
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce").fillna(0)
            row[f"{col}_max"] = float(s.max())
            row[f"{col}_mean"] = float(s.mean())
    if "bgp_flap_count" in df.columns and len(df):
        s = pd.to_numeric(df["bgp_flap_count"], errors="coerce").fillna(0)
        row["bgp_delta"] = float(s.iloc[-1] - s.iloc[0])
    for metric, vmin in rules:
        val = row.get(metric, 0.0) or 0.0
        if val < vmin:
            failures.append(f"{name}: {metric}={val:.2f} < {vmin}")
    checks.append(row)

l0 = series_dir / "L0_quiet.csv"
l0_user = 0.0
if l0.exists():
    d0 = pd.read_csv(l0)
    if "cpu_usage_user" in d0.columns:
        l0_user = float(pd.to_numeric(d0["cpu_usage_user"], errors="coerce").fillna(0).max())

stats("L0_quiet", series_dir / "L0_quiet.csv", [])
stats("L1_rain", series_dir / "L1_rain.csv", [("latency_gre_ms_max", 25.0)])
stats("L2_cpu", series_dir / "L2_cpu.csv", [("cpu_usage_user_max", max(50.0, l0_user + 15.0))])
stats("L3_bgp", series_dir / "L3_bgp.csv", [("bgp_delta", 5.0)])
stats("L4_loss", series_dir / "L4_loss.csv", [("loss_gre_pct_max", 1.0)])
stats("L5_util", series_dir / "L5_util.csv", [("util_gre_mbps_max", 12.0)])
stats("COMPOUND", series_dir / "COMPOUND.csv", [])
comp = next(c for c in checks if c["name"] == "COMPOUND")
if (comp.get("latency_gre_ms_max", 0) < 15
    and comp.get("cpu_usage_user_max", 0) < 40
    and comp.get("loss_gre_pct_max", 0) < 1
    and comp.get("util_gre_mbps_max", 0) < 10):
    failures.append(f"COMPOUND: no clear overlapping texture {comp}")

ps13 = {
    "PS13-O2.1": {"signal": "util_gre_mbps + latency", "phases": ["L1_rain", "L5_util"], "ok": None},
    "PS13-O2.2": {"signal": "bgp_flap_count delta", "phases": ["L3_bgp"], "ok": None},
    "PS13-O2.3": {"signal": "loss_gre_pct progression", "phases": ["L4_loss"], "ok": None},
    "PS13-O2.4": {"signal": "Q1 ETA heads — infer not run in inject pass", "phases": [], "ok": None},
    "PS13-P6.1": {"signal": "L5 util congestion", "phases": ["L5_util"], "ok": None},
    "PS13-P6.2": {"signal": "L3 BGP flap", "phases": ["L3_bgp"], "ok": None},
    "PS13-P6.3": {"signal": "L1 rain + L4 loss", "phases": ["L1_rain", "L4_loss"], "ok": None},
    "PS13-P6.4": {"signal": "controller policy drift — out of 10m inject book", "phases": [], "ok": False},
    "PS13-Q2-L2": {"signal": "cpu_usage_user (not system)", "phases": ["L2_cpu"], "ok": None},
}
failed_phases = {f.split(":")[0] for f in failures}
for key, meta in ps13.items():
    if meta["ok"] is False:
        continue
    if not meta["phases"]:
        continue
    meta["ok"] = all(ph not in failed_phases for ph in meta["phases"]) and all(
        any(c["name"] == ph and c.get("rows", 0) > 0 for c in checks) for ph in meta["phases"]
    )

report = {
    "stamp": "$STAMP",
    "fabric": "pi",
    "finished_unix": time.time(),
    "ok": not failures,
    "failures": failures,
    "checks": checks,
    "ps13_coverage": ps13,
    "notes": [
        "L2 gate uses cpu_usage_user (stress-ng burns user time).",
        "Inject+telemetry coverage only — not a full Q1/Q2 retrain.",
        "GNS3 smoke may run in parallel on :9091 — Pi uses :9090.",
    ],
}
(out / "coverage_report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"ok": report["ok"], "failures": failures, "n_checks": len(checks)}, indent=2))
if failures:
    print("PI 10m COVERAGE FAILED", flush=True)
    raise SystemExit(1)
print("PI 10m COVERAGE PASSED", flush=True)
PY

echo "=== done $(date -Is) report=$OUT/coverage_report.json ==="
