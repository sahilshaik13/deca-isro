"""Verify variant smoke captures have real, *diverse* texture.

Exit 0 only if gates pass — required before launching full campaign.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def series_stats(path: Path) -> dict:
    df = pd.read_csv(path)
    out = {"rows": len(df), "path": str(path)}
    for col, key in [
        ("latency_gre_ms", "lat"),
        ("loss_gre_pct", "loss"),
        ("util_gre_mbps", "util"),
        # stress-ng / crypto burn lands in *user* time; system alone looks ambient.
        ("cpu_usage_user", "cpu"),
        ("cpu_usage_system", "cpu_sys"),
        ("bgp_flap_count", "bgp"),
        ("path_asymmetry", "asym"),
    ]:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").fillna(0)
        out[f"{key}_max"] = float(s.max())
        out[f"{key}_p95"] = float(s.quantile(0.95))
        out[f"{key}_mean"] = float(s.mean())
    if "bgp_flap_count" in df.columns:
        s = pd.to_numeric(df["bgp_flap_count"], errors="coerce").fillna(0)
        # Prefer peak rise (clear_all may zero the gauge at capture end)
        if len(s):
            out["bgp_delta"] = float(max(0.0, float(s.max() - s.iloc[0])))
        else:
            out["bgp_delta"] = 0.0
    return out


def load_recipe(iter_dir: Path) -> dict:
    for name in ("label.json", "recipe.json"):
        p = iter_dir / name
        if p.exists():
            meta = json.loads(p.read_text())
            return meta.get("recipe", meta)
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp-dir", required=True)
    ap.add_argument("--report", default="")
    ap.add_argument(
        "--focus",
        default="",
        choices=("", "quick"),
        help="quick: only gate L4 + COMPOUND (10m focused smoke)",
    )
    args = ap.parse_args()
    root = Path(args.stamp_dir)
    failures: list[str] = []
    checks: list[dict] = []
    focus_quick = args.focus == "quick"

    # L0 ambient baseline (for relative L2 gate — busy hosts can sit >50% user idle)
    l0_cpu_p95 = 0.0
    l0_dirs = sorted((root / "L0_normal").glob("iter_*"))
    if l0_dirs:
        s0 = l0_dirs[0] / "series.csv"
        if s0.exists():
            st0 = series_stats(s0)
            checks.append({**st0, "folder": "L0_normal", "iter": l0_dirs[0].name})
            l0_cpu_p95 = float(st0.get("cpu_p95", st0.get("cpu_max", 0.0)) or 0.0)

    # Per-label primary gate + diversity across variants
    expectations = {
        "L1_rain_fade": ("lat_max", 20.0, "end_ms"),
        "L2_cpu_stress": ("cpu_max", 50.0, "workers"),  # floor; raised vs L0 below
        "L3_bgp_flap": ("bgp_delta", 5.0, "period_sec"),
        "L4_loss_progression": ("loss_max", 1.0, "end_pct"),
        "L5_util_congestion": ("util_max", 12.0, "end_mbit"),
    }
    if focus_quick:
        expectations = {"L4_loss_progression": expectations["L4_loss_progression"]}

    for folder, (metric, min_val, recipe_key) in expectations.items():
        dirs = sorted((root / folder).glob("iter_*"))
        if len(dirs) < 2:
            failures.append(f"{folder}: need ≥2 variant iters, found {len(dirs)}")
            continue
        vals = []
        recipe_ends = []
        # L2: require clear lift over ambient (busy Pi can idle ~55% user)
        l2_min = min_val
        if folder == "L2_cpu_stress":
            l2_min = max(min_val, l0_cpu_p95 + 15.0, 70.0)
        for d in dirs:
            s = d / "series.csv"
            if not s.exists():
                failures.append(f"{d}: missing series.csv")
                continue
            st = series_stats(s)
            st["folder"] = folder
            st["iter"] = d.name
            recipe = load_recipe(d)
            st["recipe"] = {
                k: recipe.get(k)
                for k in (recipe_key, "variant_idx", "inject_sec")
                if k in recipe or True
            }
            checks.append(st)
            primary = st.get(metric, 0.0)
            vals.append(primary)
            need = l2_min if folder == "L2_cpu_stress" else min_val
            if primary < need:
                extra = f"; L0 cpu_p95={l0_cpu_p95:.1f}" if folder == "L2_cpu_stress" else ""
                failures.append(
                    f"{d}: {metric}={primary:.2f} < {need:.2f} (flat/failed inject{extra})"
                )
            if recipe_key in recipe:
                recipe_ends.append(
                    float(recipe[recipe_key]) if recipe[recipe_key] is not None else -1
                )

        # Diversity: recipe endpoints must differ OR measured peaks must differ >10%
        if len(set(round(v, 1) for v in recipe_ends if v >= 0)) < 2:
            if max(vals) - min(vals) < 0.05 * max(max(vals), 1e-6) and max(vals) > 0:
                if len(set(recipe_ends)) < 2:
                    failures.append(
                        f"{folder}: variants look identical "
                        f"(recipe {recipe_key}={recipe_ends}, {metric}={vals})"
                    )
        # L4: require measured loss diversity when recipe ends differ (Pi probe quantization)
        if folder == "L4_loss_progression" and len(vals) >= 2:
            ends = [v for v in recipe_ends if v >= 0]
            if len(set(round(x, 1) for x in ends)) >= 2:
                spread = abs(vals[0] - vals[1])
                rel = spread / max(max(vals), 1e-6)
                if spread < 2.0 and rel < 0.15:
                    failures.append(
                        f"L4_loss_progression: loss peaks not diverse enough "
                        f"(loss_max={vals}, recipe end_pct={ends}; "
                        f"need Δ≥2pp or ≥15% relative — check probe -c / netem)"
                    )

    # Compound present + windows for train path (smoke: ≥2 diversified pairs)
    comp = sorted((root / "COMPOUND").glob("iter_*/series.csv"))
    if not comp:
        failures.append("COMPOUND: missing compound smoke capture")
    else:
        if len(comp) < 2:
            failures.append(f"COMPOUND: need ≥2 iters for smoke diversity, found {len(comp)}")
        saw_loss_compound = False
        fault_pairs: set[tuple] = set()
        for series in comp:
            st = series_stats(series)
            checks.append({**st, "folder": "COMPOUND", "iter": series.parent.name})
            if (
                st.get("lat_max", 0) < 15
                and st.get("loss_max", 0) < 1
                and st.get("util_max", 0) < 10
                and st.get("cpu_max", 0) < 50
            ):
                failures.append(f"COMPOUND {series.parent.name}: no clear fault texture {st}")
            # Prefer multi-signal compound (at least 2 families moving)
            hot = sum(
                [
                    st.get("lat_max", 0) >= 15,
                    st.get("loss_max", 0) >= 1,
                    st.get("util_max", 0) >= 10,
                    st.get("cpu_max", 0) >= 50,
                ]
            )
            if hot < 2:
                failures.append(
                    f"COMPOUND {series.parent.name}: need ≥2 stress families elevated "
                    f"(lat/loss/util/cpu), got hot={hot} {st}"
                )
            if st.get("loss_max", 0) >= 1:
                saw_loss_compound = True
            qw = series.parent / "q2_windows.csv"
            if not qw.exists():
                failures.append(
                    f"{series.parent}: missing q2_windows.csv (compound must be train-ingestible)"
                )
            else:
                n_win = max(0, sum(1 for _ in open(qw)) - 1)
                if n_win < 3:
                    failures.append(f"{qw}: need ≥3 Q2 windows, got {n_win}")
            recipe = load_recipe(series.parent)
            fault_pairs.add(tuple(recipe.get("faults") or []))
        if len(comp) >= 2 and len(fault_pairs) < 2:
            failures.append(f"COMPOUND: fault pairs not diverse {fault_pairs}")
        if len(comp) >= 2 and not saw_loss_compound:
            failures.append("COMPOUND: need ≥1 iter with loss_max≥1 (L4-family under overlap)")

    # CE SLA (PS13-P6.4) — skipped in quick focus
    if not focus_quick:
        ce_dirs = sorted((root / "L6_ce_sla_conflict").glob("iter_*"))
        if not ce_dirs:
            failures.append("L6_ce_sla_conflict: missing CE SLA smoke capture (PS13-P6.4)")
        else:
            s = ce_dirs[0] / "series.csv"
            if not s.exists():
                failures.append(f"{ce_dirs[0]}: missing series.csv")
            else:
                st = series_stats(s)
                checks.append({**st, "folder": "L6_ce_sla_conflict", "iter": ce_dirs[0].name})
                if st.get("util_max", 0) < 8:
                    failures.append(
                        f"{ce_dirs[0]}: util_max={st.get('util_max', 0):.1f} < 8 (CE SLA flat)"
                    )

    # Traffic × fault: recipes must declare ≥2 profiles on L1–L4
    traffic_by_folder: dict[str, set[str]] = {}
    for folder in expectations:
        for d in sorted((root / folder).glob("iter_*")):
            recipe = load_recipe(d)
            tp = recipe.get("traffic_profile")
            if tp:
                traffic_by_folder.setdefault(folder, set()).add(str(tp))
    traffic_folders = (
        ("L4_loss_progression",)
        if focus_quick
        else ("L1_rain_fade", "L2_cpu_stress", "L3_bgp_flap", "L4_loss_progression")
    )
    for folder in traffic_folders:
        profiles = traffic_by_folder.get(folder, set())
        if len(profiles) < 2:
            failures.append(
                f"{folder}: need ≥2 traffic_profile values in recipes, got {sorted(profiles)}"
            )

    # Plan accuracy contract if present
    plan_path = root / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        ac = plan.get("accuracy_contract") or {}
        if not ac.get("best_honest_q1_q2_path"):
            failures.append("plan.json missing accuracy_contract.best_honest_q1_q2_path")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from predictive.variant_recipes import primary_key  # noqa: WPS433

            keys = []
            for j in plan.get("jobs", []):
                if j.get("job") in ("labeled", "ce_sla"):
                    keys.append(primary_key(j["recipe"]))
            if len(keys) != len(set(keys)):
                failures.append("plan.json has duplicate recipe keys (clone iters)")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"plan uniqueness check failed: {exc}")

    report = {
        "stamp_dir": str(root),
        "ok": not failures,
        "failures": failures,
        "n_checks": len(checks),
        "checks": checks,
        "l0_cpu_p95": l0_cpu_p95,
        "l2_cpu_min_required": max(50.0, l0_cpu_p95 + 15.0, 70.0),
        "traffic_profiles_seen": {k: sorted(v) for k, v in traffic_by_folder.items()},
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ("ok", "failures", "n_checks", "l2_cpu_min_required")},
            indent=2,
        )
    )
    if failures:
        print("SMOKE GATE FAILED", file=sys.stderr)
        for f in failures:
            print(" -", f, file=sys.stderr)
        raise SystemExit(1)
    print("SMOKE GATE PASSED")


if __name__ == "__main__":
    main()
