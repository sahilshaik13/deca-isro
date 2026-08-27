#!/usr/bin/env bash
# run_capture_contract_smoke.sh — Lane A smoke: L1–L6 + one COMPOUND under CAPTURE_CONTRACT.
#
# ~15–20 min wall. Writes series + docs/CAPTURE_CONTRACT_SMOKE.md with ALL rows
# for human validation (primary-signal trajectories, not just gate numbers).
#
# Usage:
#   bash predictive/run_capture_contract_smoke.sh
#   bash predictive/run_capture_contract_smoke.sh contract_smoke_20260805T…
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${DECA_PRED_PYTHON:-$ROOT/.venv-predictive/bin/python}"
HOST=station1
PROM="${DECA_PROM_URL_PI:-${DECA_PROM_URL:-http://127.0.0.1:9090}}"
STAMP="${1:-contract_smoke_$(date -u +%Y%m%dT%H%M%SZ)}"
OUT="$ROOT/data/deca/predictive/protocol/$STAMP"
MD="$ROOT/docs/CAPTURE_CONTRACT_SMOKE.md"
mkdir -p "$OUT/logs" "$OUT/series"
export DECA_FABRIC=pi
export DECA_PROM_URL="$PROM"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

LOG="$OUT/smoke.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== CAPTURE_CONTRACT smoke stamp=$STAMP $(date -Is) ==="

clear_all() {
  for s in rain_fade loss_progression util_congestion cpu_stress bgp_flap ce_sla_conflict; do
    bash "$ROOT/scripts/inject_${s}.sh" --clear --host "$HOST" >/dev/null 2>&1 || true
  done
}
clear_all

CAP_PID=0
run_phase() {
  local name="$1" secs="$2"
  shift 2
  echo "=== PHASE $name (${secs}s) @ $(date -Is) ==="
  "$PY" -m predictive.capture_live --fabric pi --prom "$PROM" \
    --out "$OUT/series/${name}.csv" --seconds "$secs" --interval 1 \
    >"$OUT/logs/${name}_capture.log" 2>&1 &
  CAP_PID=$!
  sleep 3
  if [[ $# -gt 0 ]]; then
    "$@" >"$OUT/logs/${name}_inject.log" 2>&1 &
    local INJ=$!
    wait "$INJ" || true
  fi
  wait "$CAP_PID" || true
  clear_all
  sleep 2
}

# L1: rain → latency + jitter (≥5 ms SLA)
run_phase L1_rain 80 \
  bash "$ROOT/scripts/inject_rain_fade.sh" --host "$HOST" \
    --steps 12 --step-sec 5 --start-ms 2 --end-ms 45 --jitter-ms 5

# L2: CPU plateau — primary = cpu_usage_user
run_phase L2_cpu 75 \
  bash "$ROOT/scripts/inject_cpu_stress.sh" --host "$HOST" --seconds 60 --workers 4

# L3: BGP soft-clear rate — primary = bgp_flap_count delta
run_phase L3_bgp 75 \
  bash "$ROOT/scripts/inject_bgp_flap.sh" --host "$HOST" \
    --cycles 12 --period-sec 5 \
    --schedule-out "$OUT/series/L3_bgp_flap_schedule.jsonl"

# L4: loss progression past Payload 2%
run_phase L4_loss 80 \
  bash "$ROOT/scripts/inject_loss_progression.sh" --host "$HOST" \
    --steps 12 --step-sec 5 --start-pct 0 --end-pct 4.0

# L5: tc-ramp util + schedule sidecar
run_phase L5_util 180 \
  bash "$ROOT/scripts/inject_util_congestion.sh" --host "$HOST" \
    --steps 16 --step-sec 5 --start-mbit 5 --end-mbit 34 --parallel 2 --plateau-sec 40 \
    --schedule-out "$OUT/series/L5_util_ceil_schedule.jsonl"

# L6: CE SLA continuous rogue plateau (not pulsed)
run_phase L6_ce 100 \
  bash "$ROOT/scripts/inject_ce_sla_conflict.sh" --host "$HOST" --force-clear \
    --rogue-mbit 20 --hold-sec 80

# COMPOUND: rain + CPU — both primary signals must move
run_phase COMPOUND_rain_cpu 100 \
  bash -c "
    bash \"$ROOT/scripts/inject_rain_fade.sh\" --host \"$HOST\" \
      --steps 12 --step-sec 5 --start-ms 2 --end-ms 40 --jitter-ms 5 &
    bash \"$ROOT/scripts/inject_cpu_stress.sh\" --host \"$HOST\" --seconds 70 --workers 4 &
    wait
  "

echo "=== ROW-AUDIT + markdown @ $(date -Is) ==="
"$PY" - "$OUT" "$MD" "$STAMP" <<'PY'
"""Row-audit contract smoke + write docs/CAPTURE_CONTRACT_SMOKE.md with ALL rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from predictive.fabric_baseline import fabric_util_ceiling_mbps

out = Path(sys.argv[1])
md_path = Path(sys.argv[2])
stamp = sys.argv[3]
ceil = fabric_util_ceiling_mbps("pi")
series_dir = out / "series"

phases = [
    ("L1_rain", "latency / jitter (rain fade)"),
    ("L2_cpu", "CPU plateau — cpu_usage_user"),
    ("L3_bgp", "BGP soft-clear rate — bgp_flap_count Δ"),
    ("L4_loss", "loss progression"),
    ("L5_util", "util tc-ramp → HTB ceil"),
    ("L6_ce", "CE SLA continuous rogue plateau"),
    ("COMPOUND_rain_cpu", "overlap: rain + CPU (both legs)"),
]

def gap_seconds(df: pd.DataFrame) -> int:
    ts = df["ts_unix"].astype(int).to_numpy()
    if len(ts) < 2:
        return 0
    return int(np.clip(np.diff(ts) - 1, 0, None).sum())

def longest_run(vals: np.ndarray, thr: float) -> int:
    run = best = 0
    for v in vals:
        if v >= thr:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best

def high_to_idle_drops(vals: np.ndarray, thr: float) -> int:
    return sum(
        1 for i in range(1, len(vals)) if vals[i - 1] >= thr and vals[i] < 1.0
    )

gates = []
failures = []
phase_dfs: dict[str, pd.DataFrame] = {}

for name, _desc in phases:
    p = series_dir / f"{name}.csv"
    if not p.exists():
        failures.append(f"{name}: missing series.csv")
        continue
    raw = pd.read_csv(p)
    phase_dfs[name] = raw
    gaps = gap_seconds(raw)
    gap_log = p.with_suffix(".gaps.jsonl")
    logged_gaps = sum(1 for _ in gap_log.open() if _.strip()) if gap_log.exists() else 0

    gre = pd.to_numeric(raw.get("latency_gre_ms"), errors="coerce")
    eth = pd.to_numeric(raw.get("latency_eth0_ms"), errors="coerce")
    asym = pd.to_numeric(raw.get("path_asymmetry"), errors="coerce")
    inst = (gre - eth).abs()
    asym_err = (inst - asym).abs()
    asym_med = float(asym_err.median()) if len(asym_err) else float("nan")
    asym_p95 = float(asym_err.quantile(0.95)) if len(asym_err) else float("nan")
    frac_bad = float((asym_err > 1.0).mean()) if len(asym_err) else 1.0

    util = pd.to_numeric(raw.get("util_gre_mbps"), errors="coerce").fillna(0)
    jit = pd.to_numeric(raw.get("jitter_gre_ms"), errors="coerce").fillna(0)
    loss = pd.to_numeric(raw.get("loss_gre_pct"), errors="coerce").fillna(0)
    lat = gre.fillna(0)
    cpu_u = pd.to_numeric(raw.get("cpu_usage_user"), errors="coerce").fillna(0)
    cpu_s = pd.to_numeric(raw.get("cpu_usage_system"), errors="coerce").fillna(0)
    bgp = pd.to_numeric(raw.get("bgp_flap_count"), errors="coerce").fillna(0)
    bgp_delta = float(bgp.iloc[-1] - bgp.iloc[0]) if len(bgp) else 0.0

    row = {
        "phase": name,
        "rows": len(raw),
        "gap_seconds": gaps,
        "gap_log_events": logged_gaps,
        "asym_err_median_ms": round(asym_med, 4),
        "asym_err_p95_ms": round(asym_p95, 4),
        "asym_frac_err_gt_1ms": round(frac_bad, 4),
        "lat_max": round(float(lat.max()), 3),
        "jit_max": round(float(jit.max()), 3),
        "loss_max": round(float(loss.max()), 3),
        "util_max": round(float(util.max()), 3),
        "cpu_user_max": round(float(cpu_u.max()), 3),
        "cpu_user_mean": round(float(cpu_u.mean()), 3),
        "cpu_sys_max": round(float(cpu_s.max()), 3),
        "bgp_delta": round(bgp_delta, 1),
    }
    gates.append(row)

    if frac_bad > 0.05 or asym_med > 0.5:
        failures.append(
            f"{name}: asymmetry not tracking instant diff "
            f"(median_err={asym_med:.3f} frac>1ms={frac_bad:.3f})"
        )

    if name == "L1_rain":
        if float(lat.max()) < 20:
            failures.append(f"{name}: latency_max={lat.max():.2f} < 20 (weak rain)")
        if float(jit.max()) < 4.5:
            failures.append(f"{name}: jitter_max={jit.max():.2f} < 4.5 (need ≥~5ms SLA)")

    if name == "L2_cpu":
        thr = 25.0
        res = longest_run(cpu_u.to_numpy(dtype=float), thr)
        row["cpu_user_residency_s"] = res
        row["cpu_user_thr"] = thr
        if float(cpu_u.max()) < 35:
            failures.append(
                f"{name}: cpu_usage_user max={cpu_u.max():.1f} < 35 (flat / wrong metric)"
            )
        if res < 20:
            failures.append(
                f"{name}: cpu_usage_user residency(≥{thr:.0f})={res}s < 20 "
                "(need sustained plateau, not a spike)"
            )
        # user must dominate the story vs system-only
        if float(cpu_u.max()) < 20 and float(cpu_s.max()) >= 40:
            failures.append(
                f"{name}: system-only rise (user={cpu_u.max():.1f} sys={cpu_s.max():.1f}) "
                "— L2 primary is cpu_usage_user"
            )

    if name == "L3_bgp":
        pos = int((bgp.diff().fillna(0) > 0).sum())
        row["bgp_positive_delta_rows"] = pos
        sched = series_dir / "L3_bgp_flap_schedule.jsonl"
        sched_n = 0
        if sched.exists():
            sched_n = sum(1 for line in sched.open() if line.strip())
        row["bgp_schedule_events"] = sched_n
        if bgp_delta < 8:
            failures.append(
                f"{name}: bgp_flap_count Δ={bgp_delta:.0f} < 8 "
                "(soft-clear not moving Prom counter)"
            )
        if pos < 4:
            failures.append(
                f"{name}: only {pos} rows with positive Δ "
                "(flap rate not visible at 1 Hz)"
            )
        if not sched.exists() or sched_n < 6:
            failures.append(
                f"{name}: flap schedule missing/thin ({sched_n} events) — need --schedule-out"
            )

    if name == "L4_loss" and float(loss.max()) < 1.0:
        failures.append(f"{name}: loss_max={loss.max():.2f} < 1")

    if name in ("L5_util", "L6_ce"):
        pay_ceil = 0.85 * ceil
        thr = 0.40 * pay_ceil if name == "L6_ce" else 0.55 * pay_ceil
        # L6 rogue=20 → expect util near ~15–25, not full payload ceil
        if name == "L6_ce":
            thr = 8.0
        uvals = util.to_numpy(dtype=float)
        best = longest_run(uvals, thr)
        drops = high_to_idle_drops(uvals, thr)
        row["near_ceil_run_s"] = best
        row["near_ceil_thr"] = round(thr, 2)
        row["high_to_idle_drops"] = drops
        if float(util.max()) < (8 if name == "L6_ce" else 12):
            failures.append(f"{name}: util_max={util.max():.2f} too flat")
        if float(util.max()) > 1.25 * ceil:
            failures.append(
                f"{name}: util_max={util.max():.2f} ≫ ceil={ceil:.0f} "
                "(CAPTURE_CONTRACT smoke fail)"
            )
        min_res = 15 if name == "L5_util" else 25
        if best < min_res:
            failures.append(
                f"{name}: residency(≥{thr:.1f})={best}s < {min_res} "
                "(need continuous plateau, not pulsed)"
            )
        if drops >= 5:
            failures.append(
                f"{name}: high→idle drops={drops} ≥5 (still pulsing between steps)"
            )

    if name == "L5_util":
        sched = series_dir / "L5_util_ceil_schedule.jsonl"
        if not sched.exists():
            failures.append(f"{name}: missing util_ceil_schedule.jsonl")
        else:
            from predictive.preprocess import align_1hz, ema_smooth
            from predictive.util_schedule import (
                attach_ceil_schedule,
                build_util_windows_contract,
                load_ceil_schedule,
            )

            cleaned = ema_smooth(align_1hz(raw), span=5)
            w_g, meta_g = build_util_windows_contract(cleaned, sched, win=30, stride=5)
            gated_n = int((w_g["label_usable"] == True).sum()) if not w_g.empty else 0  # noqa: E712
            end_mbit = float(meta_g.get("util_end_mbit") or 34)
            sch = load_ceil_schedule(sched)
            en = attach_ceil_schedule(cleaned, sch)
            ceil_by = en.set_index("ts_unix")["htb_payload_ceil_mbps"].astype(float)
            gate = 0.70 * end_mbit
            early_confound = 0
            breach_sched = meta_g.get("util_breach_ts")
            for start in range(0, len(cleaned) - 30 + 1, 5):
                end_ts = int(cleaned["ts_unix"].iloc[start + 29])
                if breach_sched is not None and end_ts > int(breach_sched):
                    continue
                try:
                    c = float(
                        ceil_by.reindex(ceil_by.index.union([end_ts]))
                        .sort_index()
                        .ffill()
                        .loc[end_ts]
                    )
                except Exception:
                    c = 0.0
                u_last = float(cleaned["util_gre_mbps"].iloc[start + 29])
                if c < gate and u_last >= 0.55 * end_mbit:
                    early_confound += 1
            row["util_gated_usable"] = gated_n
            row["util_early_eth0_confound_windows"] = early_confound
            row["util_schedule_breach_ts"] = breach_sched
            row["util_confound_note"] = (
                f"{early_confound} early eth0-confound windows excluded; "
                f"{gated_n} schedule-gated usable"
            )
            if gated_n < 1:
                failures.append(f"{name}: schedule-gated usable windows={gated_n}")

    if name == "COMPOUND_rain_cpu":
        # Both legs must be visible — interaction must not drown either
        if float(lat.max()) < 15:
            failures.append(
                f"{name}: rain leg weak latency_max={lat.max():.2f} < 15"
            )
        if float(cpu_u.max()) < 30:
            failures.append(
                f"{name}: CPU leg weak cpu_usage_user max={cpu_u.max():.1f} < 30"
            )
        cpu_res = longest_run(cpu_u.to_numpy(dtype=float), 25.0)
        row["cpu_user_residency_s"] = cpu_res
        if cpu_res < 15:
            failures.append(
                f"{name}: CPU residency under overlap={cpu_res}s < 15 "
                "(drowned or not sustained)"
            )

# ---- markdown ----
lines: list[str] = []
lines.append("# Capture-contract smoke — validation data")
lines.append("")
lines.append(f"**Stamp:** `{stamp}`  ")
lines.append(f"**Path:** `data/deca/predictive/protocol/{stamp}/`  ")
lines.append(f"**Contract:** [`CAPTURE_CONTRACT.md`](./CAPTURE_CONTRACT.md)  ")
lines.append(f"**Fabric ceil (HTB):** {ceil:.0f} Mbit  ")
lines.append(f"**Verdict:** {'**PASS**' if not failures else '**FAIL**'}")
lines.append("")
lines.append(
    "Covers **L1–L6 + COMPOUND** primary-signal row audit "
    "(not only L1/L4/L5)."
)
lines.append("")
if failures:
    lines.append("## Failures")
    lines.append("")
    for f in failures:
        lines.append(f"- {f}")
    lines.append("")

lines.append("## Gate summary")
lines.append("")
lines.append(
    "| phase | rows | gap_s | asym_err_med | frac>1ms | lat_max | jit_max | "
    "loss_max | util_max | cpu_user_max | bgp_Δ | residency / notes |"
)
lines.append(
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
)
for g in gates:
    notes = []
    if "cpu_user_residency_s" in g:
        notes.append(f"cpu_res={g['cpu_user_residency_s']}s")
    if "near_ceil_run_s" in g:
        notes.append(f"util_res={g['near_ceil_run_s']}s drops={g.get('high_to_idle_drops', '?')}")
    if "util_gated_usable" in g:
        notes.append(f"gated={g['util_gated_usable']} confound={g.get('util_early_eth0_confound_windows', '?')}")
    if "bgp_schedule_events" in g:
        notes.append(f"flap_sched={g['bgp_schedule_events']}")
    lines.append(
        f"| {g['phase']} | {g['rows']} | {g['gap_seconds']} | "
        f"{g['asym_err_median_ms']} | {g['asym_frac_err_gt_1ms']} | "
        f"{g['lat_max']} | {g['jit_max']} | {g['loss_max']} | {g['util_max']} | "
        f"{g['cpu_user_max']} | {g['bgp_delta']} | {'; '.join(notes) or '—'} |"
    )
lines.append("")
lines.append("### What to check visually")
lines.append("")
lines.append("1. **Asymmetry:** `path_asymmetry` ≈ `|gre − eth0|` every row.")
lines.append("2. **Gaps:** `gap_s` small; see `series/*.gaps.jsonl`.")
lines.append("3. **L2:** `cpu_usage_user` sustained plateau (not system-only).")
lines.append("4. **L3:** `bgp_flap_count` steps up across flap cycles.")
lines.append("5. **L5/L6:** util residency without high→idle pulsing; L5 not ≫ ceil.")
lines.append("6. **COMPOUND:** rain latency **and** CPU user both elevated under overlap.")
lines.append("")

base_cols = [
    "ts_unix",
    "latency_gre_ms",
    "latency_eth0_ms",
    "path_asymmetry",
    "asym_instant",
    "asym_err",
    "jitter_gre_ms",
    "loss_gre_pct",
    "util_gre_mbps",
]
extra_by_phase = {
    "L2_cpu": ["cpu_usage_user", "cpu_usage_system"],
    "L3_bgp": ["bgp_flap_count"],
    "L6_ce": ["cpu_usage_user"],
    "COMPOUND_rain_cpu": ["cpu_usage_user", "cpu_usage_system"],
}

for name, desc in phases:
    raw = phase_dfs.get(name)
    lines.append(f"## {name} — {desc}")
    lines.append("")
    if raw is None:
        lines.append("_missing_")
        lines.append("")
        continue
    df = raw.copy()
    gre = pd.to_numeric(df["latency_gre_ms"], errors="coerce")
    eth = pd.to_numeric(df["latency_eth0_ms"], errors="coerce")
    asym = pd.to_numeric(df["path_asymmetry"], errors="coerce")
    df["asym_instant"] = (gre - eth).abs()
    df["asym_err"] = (df["asym_instant"] - asym).abs()
    for c in df.columns:
        if c == "ts_unix":
            df[c] = df[c].astype(int)
        elif pd.api.types.is_numeric_dtype(df[c]):
            df[c] = pd.to_numeric(df[c], errors="coerce").round(4)

    cols_show = base_cols + extra_by_phase.get(name, [])
    present = [c for c in cols_show if c in df.columns]
    lines.append(
        f"**Rows:** {len(df)} · **CSV:** `data/deca/predictive/protocol/{stamp}/series/{name}.csv`"
    )
    lines.append("")
    lines.append("| " + " | ".join(present) + " |")
    lines.append("| " + " | ".join(["---:" for _ in present]) + " |")
    for _, r in df[present].iterrows():
        cells = []
        for c in present:
            v = r[c]
            if c == "ts_unix":
                cells.append(str(int(v)))
            elif pd.isna(v):
                cells.append("")
            else:
                cells.append(
                    f"{float(v):.4f}".rstrip("0").rstrip(".")
                    if isinstance(v, (float, np.floating))
                    else str(v)
                )
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

lines.append("## Post-`align_1hz` note")
lines.append("")
lines.append(
    "Train/eval always run `align_1hz` before windows (CAPTURE_CONTRACT A). "
    "Tables above are **raw** capture rows (includes any residual gaps)."
)
lines.append("")

report = {
    "stamp": stamp,
    "ceil_mbps": ceil,
    "ok": len(failures) == 0,
    "failures": failures,
    "gates": gates,
    "out": str(out),
    "markdown": str(md_path),
}
(out / "SMOKE_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
md_path.write_text("\n".join(lines) + "\n")
print(json.dumps(report, indent=2))
if failures:
    sys.exit(1)
PY

echo "=== done markdown=$MD ==="
