#!/usr/bin/env python3
"""Generate diverse fault recipes for variant campaigns (smoke / full).

Contract (plan fails to build if violated):
  1. No clone recipes — every labeled iter has a unique primary-knob tuple.
  2. Full traffic × fault matrix — every fault label × every traffic profile.
  3. CE SLA conflict track included (PS13-P6.4).
  4. Compound patterns + chaos holdout (never train).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# Background traffic during fault capture (L0 = idle only).
# L5 util inject owns the path → force idle so util GT stays clean.
TRAFFIC_PROFILES = ("idle", "ttc_light", "payload_medium", "mixed")
FAULT_TRAFFIC = ("ttc_light", "payload_medium", "mixed", "idle")  # rotate; includes idle cell

# Primary knob grids — indexed (never random-collision) for uniqueness.
#
# CAPTURE_CONTRACT campaign trim (2026-08-05) — locked:
#   Trim: L2/L3 inject wall-clock (fast-onset); L1/L4 variant *count* (already strong).
#   Keep: L5/L6 plateau length, COMPOUND×8, chaos_holdout 7200s, per-class window floor.
L1_ENDS = [30, 55, 90, 110]  # 4 variants (was 8) — still covers FAULT_TRAFFIC
L1_INJECT = [600, 900, 1200, 1500]  # keep inject length for latency/jitter TTI density
L2_WORKERS = [1, 2, 3, 0, 1, 2, 3, 0]
L2_INJECT = [120, 150, 180, 240, 135, 165, 210, 270]  # unique × traffic; was 300–900
L3_PERIOD = [3, 5, 8, 12, 4, 6, 10, 7]
L3_INJECT = [120, 150, 180, 240, 135, 165, 210, 270]  # unique; was 300–900
# Keep ≥5%: edge ping is -c 15; still need headroom above SLA (2%) for texture.
L4_ENDS = [5.0, 8.0, 12.0, 18.0]  # 4 variants (was 8)
L4_INJECT = [300, 480, 600, 480]  # keep length — loss TTI window floor lesson (n=41 was too thin)
# Keep ends ≤ fabric payload soft ceil (~34 on 40 Mbit WAN parent). Ends above
# parent cannot appear in eth0 util even with offer≫ceil — measured Mbps then
# tracks offer/WAN, not the programmed class ceil (util 5A/5B info gap).
L5_ENDS = [12, 16, 20, 24, 28, 30, 32, 34]
L5_INJECT = [300, 300, 480, 480, 600, 600, 480, 300]
L5_PLATEAU = [40, 45, 40, 45, 50, 40, 45, 40]  # do not trim — residency shape fix
CE_ROGUE = [12, 16, 20, 24]
# Full-plan variant counts per label (L0 separate)
FULL_N_VARIANTS = {1: 4, 2: 8, 3: 8, 4: 4, 5: 8}


def _pick(rng: random.Random, choices: list):
    return rng.choice(choices)


def primary_key(recipe: dict) -> tuple:
    """Identity used to forbid clone iters."""
    name = recipe.get("name") or recipe.get("kind")
    if name == "normal":
        return ("normal", recipe.get("seconds"), recipe.get("traffic_profile", "idle"))
    if name == "rain_fade":
        return (
            "rain_fade",
            recipe.get("end_ms"),
            recipe.get("inject_sec"),
            recipe.get("start_ms"),
            recipe.get("step_sec"),
            recipe.get("jitter_ms"),
            recipe.get("traffic_profile"),
        )
    if name == "cpu_stress":
        return ("cpu_stress", recipe.get("workers"), recipe.get("inject_sec"), recipe.get("traffic_profile"))
    if name == "bgp_flap":
        return (
            "bgp_flap",
            recipe.get("period_sec"),
            recipe.get("inject_sec"),
            recipe.get("link_bounce"),
            recipe.get("traffic_profile"),
        )
    if name == "loss_progression":
        return (
            "loss_progression",
            recipe.get("end_pct"),
            recipe.get("inject_sec"),
            recipe.get("step_sec"),
            recipe.get("traffic_profile"),
        )
    if name == "util_congestion":
        return (
            "util_congestion",
            recipe.get("end_mbit"),
            recipe.get("inject_sec"),
            recipe.get("parallel"),
            recipe.get("start_mbit"),
            recipe.get("traffic_profile"),
        )
    if name == "ce_sla_conflict":
        return (
            "ce_sla_conflict",
            recipe.get("rogue_mbit"),
            recipe.get("inject_sec"),
            recipe.get("traffic_profile"),
        )
    if recipe.get("kind") == "compound":
        return ("compound", tuple(recipe.get("faults") or []), recipe.get("total_sec"), recipe.get("traffic_profile"))
    if recipe.get("kind") == "chaos_holdout":
        return ("chaos_holdout", recipe.get("seconds"))
    return (name, json.dumps(recipe, sort_keys=True))


def recipe_for(label: int, variant_idx: int, *, mode: str, seed: int) -> dict:
    """Return inject knobs for one labeled capture (unique by variant_idx)."""
    rng = random.Random(seed * 1009 + label * 97 + variant_idx * 13)
    traffic = FAULT_TRAFFIC[variant_idx % len(FAULT_TRAFFIC)]
    base = {
        "label": label,
        "variant_idx": variant_idx,
        "mode": mode,
        "seed": seed * 1009 + label * 97 + variant_idx * 13,
        "traffic_profile": traffic,
    }

    if mode == "quick":
        if label == 0:
            return {**base, "name": "normal", "seconds": 20, "traffic_profile": "idle"}
        if label == 4:
            # Wider ends + longer peak so Pi fractional probes separate variants.
            end_pct = 8.0 if variant_idx % 2 == 0 else 20.0
            inject = 70 if variant_idx % 2 == 0 else 90
            return {
                **base,
                "name": "loss_progression",
                "baseline_sec": 5,
                "inject_sec": inject,
                "post_sec": 15,
                "start_pct": 0.0,
                "end_pct": end_pct,
                "step_sec": 5,
                "traffic_profile": "ttc_light" if variant_idx % 2 == 0 else "mixed",
            }
        raise ValueError(f"quick mode only supports labels 0 and 4, got {label}")

    if mode == "smoke":
        if label == 0:
            return {**base, "name": "normal", "seconds": 45, "traffic_profile": "idle"}
        if label == 1:
            end_ms = 30 if variant_idx % 2 == 0 else 60
            inject = 90 if variant_idx % 2 == 0 else 120
            return {
                **base,
                "name": "rain_fade",
                "baseline_sec": 10,
                "inject_sec": inject,
                "post_sec": 10,
                "start_ms": 2,
                "end_ms": end_ms,
                "step_sec": 5,
                "jitter_ms": 5,
                "traffic_profile": "ttc_light" if variant_idx % 2 == 0 else "payload_medium",
            }
        if label == 2:
            workers = 2 if variant_idx % 2 == 0 else 0
            return {
                **base,
                "name": "cpu_stress",
                "baseline_sec": 10,
                "inject_sec": 60 if variant_idx % 2 == 0 else 90,
                "post_sec": 10,
                "workers": workers,
                "traffic_profile": "mixed" if variant_idx % 2 == 0 else "ttc_light",
            }
        if label == 3:
            period = 3 if variant_idx % 2 == 0 else 8
            inject = 60 if variant_idx % 2 == 0 else 90
            return {
                **base,
                "name": "bgp_flap",
                "baseline_sec": 10,
                "inject_sec": inject,
                "post_sec": 10,
                "period_sec": period,
                "cycles": max(6, inject // period),
                "link_bounce": False,
                "traffic_profile": "payload_medium" if variant_idx % 2 == 0 else "idle",
            }
        if label == 4:
            # Smoke: wide end_pct spread so Pi probes (now -c 15) show clear variance.
            end_pct = 8.0 if variant_idx % 2 == 0 else 15.0
            inject = 100 if variant_idx % 2 == 0 else 140
            return {
                **base,
                "name": "loss_progression",
                "baseline_sec": 10,
                "inject_sec": inject,
                "post_sec": 15,
                "start_pct": 0.0,
                "end_pct": end_pct,
                "step_sec": 5,
                "traffic_profile": "ttc_light" if variant_idx % 2 == 0 else "mixed",
            }
        if label == 5:
            # Util inject owns traffic — keep profile idle
            end_mbit = 18 if variant_idx % 2 == 0 else 30
            inject = 90 if variant_idx % 2 == 0 else 120
            return {
                **base,
                "name": "util_congestion",
                "baseline_sec": 10,
                "inject_sec": inject,
                "post_sec": 10,
                "start_mbit": 5,
                "end_mbit": end_mbit,
                "parallel": 2,
                "step_sec": 15,
                "traffic_profile": "idle",
            }
        raise ValueError(label)

    # --- full: index into grids (no RNG collision) ---
    i = variant_idx
    if label == 0:
        return {**base, "name": "normal", "seconds": 600, "traffic_profile": "idle"}
    if label == 1:
        return {
            **base,
            "name": "rain_fade",
            "baseline_sec": 20 + (i % 3) * 20,
            "inject_sec": L1_INJECT[i % len(L1_INJECT)],
            "post_sec": 20 + (i % 2) * 20,
            "start_ms": [1, 2, 5, 8][i % 4],
            "end_ms": L1_ENDS[i % len(L1_ENDS)],
            "step_sec": [3, 5, 8, 5][i % 4],
            "jitter_ms": [2, 5, 10, 5][i % 4],
            "traffic_profile": FAULT_TRAFFIC[i % len(FAULT_TRAFFIC)],
        }
    if label == 2:
        return {
            **base,
            "name": "cpu_stress",
            "baseline_sec": 15 if i % 2 == 0 else 30,
            "inject_sec": L2_INJECT[i % len(L2_INJECT)],
            "post_sec": 20,
            "workers": L2_WORKERS[i % len(L2_WORKERS)],
            "traffic_profile": FAULT_TRAFFIC[i % len(FAULT_TRAFFIC)],
        }
    if label == 3:
        period = L3_PERIOD[i % len(L3_PERIOD)]
        inject = L3_INJECT[i % len(L3_INJECT)]
        return {
            **base,
            "name": "bgp_flap",
            "baseline_sec": 20,
            "inject_sec": inject,
            "post_sec": 20,
            "period_sec": period,
            "cycles": max(8, inject // period),
            "link_bounce": bool(i % 4 == 3),
            "traffic_profile": FAULT_TRAFFIC[i % len(FAULT_TRAFFIC)],
        }
    if label == 4:
        return {
            **base,
            "name": "loss_progression",
            "baseline_sec": 20,
            "inject_sec": L4_INJECT[i % len(L4_INJECT)],
            "post_sec": 20,
            "start_pct": 0.0 if i % 2 == 0 else 0.2,
            "end_pct": L4_ENDS[i % len(L4_ENDS)],
            "step_sec": [4, 5, 8, 5][i % 4],
            "traffic_profile": FAULT_TRAFFIC[i % len(FAULT_TRAFFIC)],
        }
    if label == 5:
        return {
            **base,
            "name": "util_congestion",
            "baseline_sec": 20,
            "inject_sec": L5_INJECT[i % len(L5_INJECT)],
            "post_sec": 20,
            "start_mbit": [2, 5, 8, 12][i % 4],
            "end_mbit": L5_ENDS[i % len(L5_ENDS)],
            "parallel": [1, 2, 3, 2][i % 4],
            "step_sec": [12, 15, 20, 15][i % 4],
            "plateau_sec": L5_PLATEAU[i % len(L5_PLATEAU)],
            "traffic_profile": "idle",  # util inject owns the path
        }
    raise ValueError(label)


def ce_sla_recipe(variant_idx: int, *, mode: str, seed: int) -> dict:
    rng = random.Random(seed * 23 + variant_idx * 41)
    if mode == "smoke":
        return {
            "label": 6,
            "name": "ce_sla_conflict",
            "kind": "ce_sla",
            "variant_idx": variant_idx,
            "mode": mode,
            "baseline_sec": 10,
            "inject_sec": 90,
            "post_sec": 10,
            "rogue_mbit": 20,
            "start_mbit": 5,
            "traffic_profile": "idle",  # inject owns bronze/gold flows
            "seed": seed * 23 + variant_idx * 41,
        }
    return {
        "label": 6,
        "name": "ce_sla_conflict",
        "kind": "ce_sla",
        "variant_idx": variant_idx,
        "mode": mode,
        "baseline_sec": 20,
        "inject_sec": _pick(rng, [300, 420, 600]),
        "post_sec": 20,
        "rogue_mbit": CE_ROGUE[variant_idx % len(CE_ROGUE)],
        "start_mbit": _pick(rng, [2, 3, 4]),
        "traffic_profile": "idle",
        "seed": seed * 23 + variant_idx * 41,
    }


def compound_recipe(variant_idx: int, *, mode: str, seed: int) -> dict:
    rng = random.Random(seed * 17 + variant_idx * 31)
    if mode == "quick":
        total = 75
        baseline = 5
    elif mode == "smoke":
        total = 180
        baseline = 10
    else:
        total = _pick(rng, [900, 1200, 1500])
        baseline = 20
    patterns = [
        ["rain_fade", "cpu_stress"],
        ["rain_fade", "bgp_flap"],
        ["loss_progression", "util_congestion"],
        ["cpu_stress", "util_congestion"],
        ["rain_fade", "loss_progression"],
        ["bgp_flap", "loss_progression"],
        ["rain_fade", "cpu_stress", "util_congestion"],
        ["loss_progression", "bgp_flap"],
    ]
    faults = patterns[variant_idx % len(patterns)]
    return {
        "kind": "compound",
        "variant_idx": variant_idx,
        "mode": mode,
        "total_sec": total,
        "baseline_sec": baseline,
        "faults": faults,
        "rain_end_ms": 40 if mode == "quick" else _pick(rng, [35, 50, 70]),
        "loss_end_pct": 10.0 if mode == "quick" else _pick(rng, [2.0, 3.5, 5.0]),
        "util_end_mbit": 28 if mode == "quick" else _pick(rng, [16, 24, 32]),
        "cpu_workers": 1 if mode == "quick" else _pick(rng, [1, 2, 0]),
        "bgp_period_sec": _pick(rng, [4, 5, 8]),
        "traffic_profile": "ttc_light" if mode == "quick" else FAULT_TRAFFIC[variant_idx % len(FAULT_TRAFFIC)],
    }


def assert_plan_coverage(jobs: list[dict], *, mode: str) -> dict:
    """Hard fail if plan is incomplete — this is the accuracy contract."""
    failures: list[str] = []
    keys: list[tuple] = []
    labeled = [j for j in jobs if j["job"] == "labeled"]
    by_lab: dict[int, list[dict]] = {}
    for j in labeled:
        r = j["recipe"]
        lab = int(r["label"])
        by_lab.setdefault(lab, []).append(r)
        keys.append(primary_key(r))

    if len(keys) != len(set(keys)):
        # find dupes
        seen = set()
        for k in keys:
            if k in seen:
                failures.append(f"duplicate recipe key: {k}")
            seen.add(k)

    if mode == "quick":
        if len(by_lab.get(4, [])) < 2:
            failures.append("quick needs ≥2 L4 loss variants")
        compounds = [j for j in jobs if j["job"] == "compound"]
        if len(compounds) < 2:
            failures.append(f"quick needs ≥2 compounds, got {len(compounds)}")
        pairs = {tuple((j["recipe"].get("faults") or [])) for j in compounds}
        if len(pairs) < 2:
            failures.append(f"quick compounds must use ≥2 distinct fault pairs, got {pairs}")
        if not any("loss_progression" in (j["recipe"].get("faults") or []) for j in compounds):
            failures.append("quick needs ≥1 compound that includes loss_progression")
        report = {
            "ok": not failures,
            "failures": failures,
            "n_jobs": len(jobs),
            "n_labeled": len(labeled),
            "n_compound": len(compounds),
            "focus": ["L4", "COMPOUND"],
        }
        if failures:
            raise SystemExit(
                "PLAN COVERAGE FAILED (accuracy contract):\n  - " + "\n  - ".join(failures)
            )
        return report

    if mode == "util_clean":
        # Redo-only: L0 util NaN fix + L5 schedule/plateau + util-bearing compounds.
        if len(by_lab.get(0, [])) < 1:
            failures.append("util_clean needs ≥1 L0 baseline")
        if len(by_lab.get(5, [])) != FULL_N_VARIANTS[5]:
            failures.append(
                f"util_clean needs L5×{FULL_N_VARIANTS[5]}, got {len(by_lab.get(5, []))}"
            )
        if by_lab.get(5):
            bad = [r["variant_idx"] for r in by_lab[5] if r.get("traffic_profile") != "idle"]
            if bad:
                failures.append(f"L5 must use traffic_profile=idle; bad v={bad}")
            short_plat = [
                r["variant_idx"]
                for r in by_lab[5]
                if int(r.get("plateau_sec") or 0) < 40
            ]
            if short_plat:
                failures.append(f"L5 plateau_sec must be ≥40; bad v={short_plat}")
        compounds = [j for j in jobs if j["job"] == "compound"]
        util_compounds = [
            j for j in compounds if "util_congestion" in (j["recipe"].get("faults") or [])
        ]
        if len(util_compounds) < 3:
            failures.append(
                f"util_clean needs ≥3 util-bearing compounds, got {len(util_compounds)}"
            )
        report = {
            "ok": not failures,
            "failures": failures,
            "n_jobs": len(jobs),
            "n_labeled": len(labeled),
            "n_compound": len(compounds),
            "n_util_compound": len(util_compounds),
            "focus": ["L0", "L5", "COMPOUND_util"],
            "note": (
                "supersedes backfilled util_ceil_schedule / L0 util NaN fill on the "
                "contract stamp for util Q1 / util features"
            ),
        }
        if failures:
            raise SystemExit(
                "PLAN COVERAGE FAILED (accuracy contract):\n  - " + "\n  - ".join(failures)
            )
        return report

    # traffic × fault matrix (labels 1–4); L5 idle-only by design (util owns path)
    for lab in (1, 2, 3, 4):
        profiles = {r.get("traffic_profile") for r in by_lab.get(lab, [])}
        if mode == "full":
            missing = set(FAULT_TRAFFIC) - profiles
            if missing:
                failures.append(f"L{lab} missing traffic profiles: {sorted(missing)}")
        else:
            if len(profiles) < 2:
                failures.append(f"L{lab} smoke needs ≥2 traffic profiles, got {sorted(profiles)}")
    if by_lab.get(5):
        bad = [r["variant_idx"] for r in by_lab[5] if r.get("traffic_profile") != "idle"]
        if bad:
            failures.append(f"L5 must use traffic_profile=idle (util owns path); bad v={bad}")
        short_plat = [
            r["variant_idx"]
            for r in by_lab[5]
            if int(r.get("plateau_sec") or 0) < 40
        ]
        if mode == "full" and short_plat:
            failures.append(
                f"L5 plateau_sec must be ≥40 (CAPTURE_CONTRACT residency); bad v={short_plat}"
            )

    if mode == "full":
        for lab, need in FULL_N_VARIANTS.items():
            got = len(by_lab.get(lab, []))
            if got != need:
                failures.append(f"L{lab} full needs {need} variants, got {got}")

    ce = [j for j in jobs if j["job"] == "ce_sla"]
    if mode == "smoke" and len(ce) < 1:
        failures.append("smoke needs ≥1 CE SLA conflict capture (PS13-P6.4)")
    if mode == "full" and len(ce) < 4:
        failures.append(f"full needs ≥4 CE SLA variants, got {len(ce)}")

    compounds = [j for j in jobs if j["job"] == "compound"]
    if mode == "smoke" and len(compounds) < 2:
        failures.append(f"smoke needs ≥2 compounds (diversify fault pairs), got {len(compounds)}")
    if mode == "full" and len(compounds) < 8:
        failures.append(f"full needs 8 compounds, got {len(compounds)}")
    if mode == "smoke" and compounds:
        pairs = {tuple((j["recipe"].get("faults") or [])) for j in compounds}
        if len(pairs) < 2:
            failures.append(f"smoke compounds must use ≥2 distinct fault pairs, got {pairs}")
        # At least one compound must include loss (L4-family texture under overlap)
        if not any("loss_progression" in (j["recipe"].get("faults") or []) for j in compounds):
            failures.append("smoke needs ≥1 compound that includes loss_progression")

    if mode == "full" and not any(j["job"] == "chaos_holdout" for j in jobs):
        failures.append("full needs chaos_holdout (never train)")

    # uniqueness per label on primary fault knobs (ignore traffic for L2 workers check)
    for lab, rs in by_lab.items():
        if lab == 0:
            continue
        lab_keys = [primary_key(r) for r in rs]
        if len(lab_keys) != len(set(lab_keys)):
            failures.append(f"L{lab} has clone recipes among {len(rs)} variants")

    report = {
        "ok": not failures,
        "failures": failures,
        "n_jobs": len(jobs),
        "n_labeled": len(labeled),
        "n_ce_sla": len(ce),
        "n_compound": len(compounds),
        "traffic_fault_matrix": {
            str(lab): sorted({r.get("traffic_profile") for r in rs})
            for lab, rs in sorted(by_lab.items())
        },
    }
    if failures:
        raise SystemExit(
            "PLAN COVERAGE FAILED (accuracy contract):\n  - " + "\n  - ".join(failures)
        )
    return report


def quick_plan(seed: int = 42) -> list[dict]:
    """~8–10 min wall: L0 + L4×2 (8%/15%) + 2 compounds (rain+cpu, loss+util)."""
    jobs: list[dict] = [
        {"job": "labeled", "recipe": recipe_for(0, 0, mode="quick", seed=seed)},
        {"job": "labeled", "recipe": recipe_for(4, 0, mode="quick", seed=seed)},
        {"job": "labeled", "recipe": recipe_for(4, 1, mode="quick", seed=seed)},
        {"job": "compound", "recipe": compound_recipe(0, mode="quick", seed=seed)},
        {"job": "compound", "recipe": compound_recipe(2, mode="quick", seed=seed)},
    ]
    return jobs


def smoke_plan(seed: int = 42) -> list[dict]:
    """~35 min: 2 variants/fault × traffic + CE SLA + 2 compounds (rain+cpu, loss+util)."""
    jobs: list[dict] = []
    jobs.append({"job": "labeled", "recipe": recipe_for(0, 0, mode="smoke", seed=seed)})
    for lab in (1, 2, 3, 4, 5):
        for v in (0, 1):
            jobs.append({"job": "labeled", "recipe": recipe_for(lab, v, mode="smoke", seed=seed)})
    jobs.append({"job": "ce_sla", "recipe": ce_sla_recipe(0, mode="smoke", seed=seed)})
    # v0 = rain+cpu (L1×L2); v2 = loss+util (L4×L5) — both needed for high compound confidence
    jobs.append({"job": "compound", "recipe": compound_recipe(0, mode="smoke", seed=seed)})
    jobs.append({"job": "compound", "recipe": compound_recipe(2, mode="smoke", seed=seed)})
    return jobs


def full_plan(seed: int = 42) -> list[dict]:
    """Contract-trimmed full hunt: short L2/L3, fewer L1/L4, keep L5/L6/COMPOUND/chaos."""
    jobs: list[dict] = []
    jobs.append({"job": "labeled", "recipe": recipe_for(0, 0, mode="full", seed=seed)})
    for lab in (1, 2, 3, 4, 5):
        n = FULL_N_VARIANTS[lab]
        for v in range(n):
            jobs.append({"job": "labeled", "recipe": recipe_for(lab, v, mode="full", seed=seed)})
    for v in range(4):
        jobs.append({"job": "ce_sla", "recipe": ce_sla_recipe(v, mode="full", seed=seed)})
    for v in range(8):
        jobs.append({"job": "compound", "recipe": compound_recipe(v, mode="full", seed=seed)})
    jobs.append(
        {
            "job": "chaos_holdout",
            "recipe": {
                "kind": "chaos_holdout",
                "mode": "full",
                "seconds": 7200,
                "note": "never train on this capture — do not trim sealed exam",
                "traffic_profiles_cycled": list(FAULT_TRAFFIC),
            },
        }
    )
    return jobs


# Full-plan compound variant_idx values that include util_congestion (seed=42 patterns).
UTIL_CLEAN_COMPOUND_VARIANTS = (2, 3, 6)


def util_clean_plan(seed: int = 42) -> list[dict]:
    """Clean redo for corrupt util path: L0 + L5×8 (plateau+schedule) + util compounds.

    Use after a contract stamp that had GNS3 L0 util NaNs and/or missing
    ``util_ceil_schedule.jsonl`` / no plateau. Same inject knobs as full (seed-locked).
    """
    jobs: list[dict] = []
    jobs.append({"job": "labeled", "recipe": recipe_for(0, 0, mode="util_clean", seed=seed)})
    for v in range(FULL_N_VARIANTS[5]):
        jobs.append({"job": "labeled", "recipe": recipe_for(5, v, mode="util_clean", seed=seed)})
    for v in UTIL_CLEAN_COMPOUND_VARIANTS:
        # compound_recipe totals follow full (non-smoke/quick) branch
        jobs.append({"job": "compound", "recipe": compound_recipe(v, mode="util_clean", seed=seed)})
    return jobs


def estimate_seconds(plan: list[dict]) -> int:
    est = 0
    for j in plan:
        r = j["recipe"]
        if j["job"] in ("labeled", "ce_sla"):
            if r.get("label") == 0:
                est += int(r.get("seconds", 60))
            else:
                est += int(r.get("baseline_sec", 0)) + int(r.get("inject_sec", 0)) + int(r.get("post_sec", 0))
                # L5 tc-ramp adds plateau after step ramp (CAPTURE_CONTRACT)
                if r.get("name") == "util_congestion":
                    est += int(r.get("plateau_sec") or 40)
        elif j["job"] == "compound":
            est += int(r["total_sec"])
        elif j["job"] == "chaos_holdout":
            est += int(r["seconds"])
    return est


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode",
        choices=("smoke", "full", "quick", "util_clean"),
        required=True,
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True, help="write plan JSON")
    args = ap.parse_args()
    if args.mode == "smoke":
        plan = smoke_plan(args.seed)
    elif args.mode == "quick":
        plan = quick_plan(args.seed)
    elif args.mode == "util_clean":
        plan = util_clean_plan(args.seed)
    else:
        plan = full_plan(args.seed)
    coverage = assert_plan_coverage(plan, mode=args.mode)
    est = estimate_seconds(plan)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": args.mode,
        "seed": args.seed,
        "n_jobs": len(plan),
        "est_seconds": est,
        "est_hours": round(est / 3600, 2),
        "accuracy_contract": {
            "unique_recipes": True,
            "traffic_x_fault_matrix": args.mode != "util_clean",
            "ce_sla_track": args.mode in ("smoke", "full"),
            "compound_train": True,
            "chaos_holdout_never_train": args.mode == "full",
            "group_holdout_retrain": True,
            "best_honest_q1_q2_path": True,
            "util_clean_redo": args.mode == "util_clean",
            "campaign_trim": {
                "l2_l3_short_inject": True,
                "l1_l4_fewer_variants": True,
                "keep_l5_l6_plateau": True,
                "keep_compound_x8": True,
                "keep_chaos_7200": True,
                "full_n_variants": FULL_N_VARIANTS,
                "post_run_window_floor_check": (
                    "python -m predictive.check_q1_window_floors --protocol-dir <stamp> "
                    "(loss/jitter stride=1 densify; soft≥100 hard≥50 — n=41 thin-class lesson)"
                ),
                "l4_x4_requires_loss_stride1": True,
                "util_clean_scope": (
                    "L0 + L5×8 + util compounds (v2/v3/v6) — prefer over backfilled "
                    "schedules/NaN fills from the contract stamp"
                )
                if args.mode == "util_clean"
                else None,
            },
            "coverage": coverage,
        },
        "jobs": plan,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "wrote": str(out),
                "n_jobs": len(plan),
                "est_seconds": est,
                "est_hours": round(est / 3600, 2),
                "accuracy_contract_ok": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
