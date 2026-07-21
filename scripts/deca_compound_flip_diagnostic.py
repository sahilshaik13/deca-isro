#!/usr/bin/env python3
"""At hit-leg confirm time: what did the miss leg score?

Distinguishes operator/threshold suppression vs feature drowning for compound blinds.
Uses declarations.jsonl + Prometheus replay (when retention allows).

Usage:
    python scripts/deca_compound_flip_diagnostic.py
    python scripts/deca_compound_flip_diagnostic.py --run blind_compound_tunnel_recheck_20260720_0154_40m
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from _paths import RPI_NET_DIR
from deca_live_common import FAULT_HOST, fetch_telemetry_long, load_bgp_pulses, read_jsonl
from deca_live_operator import build_host_features, load_suite
from deca_school_exam_train import predict_weighted_multiclass_with_confidence

COMPOUND_RUNS = [
    "blind_compound_bgp_route_flap_20260719_1239_40m",
    "blind_compound_congestion_breach_20260719_1256_40m",
    "blind_compound_tunnel_degradation_20260719_1317_40m",
    "blind_compound_bgp_recheck_20260719_1516_40m",
    "blind_compound_tunnel_recheck_20260719_2012_40m",
    "blind_compound_tunnel_recheck_20260720_0154_40m",
    "blind_compound_bgp_recheck_20260720_0213_40m",
]


def run_dir(run_id: str) -> Path:
    for base in (RPI_NET_DIR / "blind-tests", RPI_NET_DIR / "live"):
        p = base / run_id
        if (p / "ground_truth.sealed.jsonl").is_file():
            return p
    raise FileNotFoundError(run_id)


def parse_ts(s: str) -> datetime:
    return pd.Timestamp(s).to_pydatetime().astimezone(timezone.utc)


def per_class_scores(suite, X_row) -> dict[str, float]:
    gate, full_clf = suite.gate, suite.full_clf
    p_anom = float(gate.predict_proba(X_row)[:, 1][0])
    p_full = full_clf.predict_proba(X_row)[0]
    full_classes = list(full_clf.classes_)
    if p_anom < suite.gate_thr:
        return {suite.classes[suite.healthy_idx]: 1.0 - p_anom}
    out = {}
    for j, cid in enumerate(full_classes):
        cls = suite.classes[int(cid)]
        thr = max(suite.class_thr.get(int(cid), 1.0), 1e-6)
        out[cls] = float(p_full[j] / thr)
    return out


def replay_scores_at(run_id: str, host: str, at: datetime, lookback_min: float = 45.0) -> dict | None:
    start = at - timedelta(minutes=lookback_min)
    end = at + timedelta(seconds=30)
    raw = fetch_telemetry_long(start, end)
    if raw.empty:
        return None
    bgp = load_bgp_pulses(run_id, start, end)
    hosts = build_host_features(raw, bgp)
    if host not in hosts or hosts[host].empty:
        return None
    suite = load_suite()
    g = hosts[host]
    # nearest frame at or before `at`
    idx = g.index[g.index <= pd.Timestamp(at)]
    if len(idx) == 0:
        row = g.iloc[[0]]
    else:
        row = g.loc[[idx[-1]]]
    scores = per_class_scores(suite, row.reindex(columns=suite.features))
    winner = max(scores, key=scores.get)
    raw_pred, conf = predict_weighted_multiclass_with_confidence(
        suite.gate, suite.full_clf, row.reindex(columns=suite.features),
        healthy_idx=suite.healthy_idx, gate_thr=suite.gate_thr, class_thr=suite.class_thr,
    )
    return {
        "frame_ts": str(row.index[-1]),
        "winner": suite.classes[int(raw_pred[0])],
        "winner_conf": float(conf[0]),
        "scores": scores,
    }


def miss_host_declarations_at(decls: list[dict], host: str, at: datetime, window_s: int = 45) -> list[dict]:
    out = []
    for d in decls:
        if d.get("host") != host:
            continue
        ts = parse_ts(d["ts"])
        if abs((ts - at).total_seconds()) <= window_s:
            out.append(d)
    return out


def analyze_run(run_id: str, suite) -> list[dict]:
    base = run_dir(run_id)
    gt = [e for e in read_jsonl(base / "ground_truth.sealed.jsonl") if not e.get("is_near_miss")]
    decls = read_jsonl(base / "declarations.jsonl")
    sc_path = base / "scorecard.json"
    scored = json.loads(sc_path.read_text()) if sc_path.is_file() else {"events": []}
    det_by_id = {e["event_id"]: e.get("detected") for e in scored.get("events", [])}

    by_group: dict[str, list[dict]] = {}
    for ev in gt:
        if ev.get("fault_type") == "near_miss":
            continue
        cg = ev.get("compound_group") or ev["event_id"]
        by_group.setdefault(cg, []).append(ev)

    rows = []
    for cg, legs in by_group.items():
        if len(legs) < 2:
            continue
        confirms = []
        for leg in legs:
            host = leg["host"]
            ft = leg["fault_type"]
            fs, bt = parse_ts(leg["fault_start"]), parse_ts(leg["breach_time"])
            hits = [
                d for d in decls
                if d.get("event") == "confirmed_raise"
                and d.get("host") == host
                and d.get("confirmed") == ft
                and fs <= parse_ts(d["ts"]) <= bt + timedelta(minutes=5)
            ]
            confirms.append((leg, hits[0] if hits else None))

        hit_leg, hit_decl = next(((l, d) for l, d in confirms if d), (None, None))
        miss_leg, _ = next(((l, d) for l, d in confirms if l is not hit_leg), (None, None))
        if not hit_leg or not miss_leg:
            continue

        hit_ts = parse_ts(hit_decl["ts"])
        miss_ft = miss_leg["fault_type"]
        miss_host = miss_leg["host"]

        # Declarations on miss host during overlap window
        fs0 = min(parse_ts(l["fault_start"]) for l in legs)
        bt1 = max(parse_ts(l["breach_time"]) for l in legs)
        miss_decls = [
            d for d in decls
            if d.get("host") == miss_host
            and fs0 <= parse_ts(d["ts"]) <= bt1 + timedelta(minutes=2)
        ]
        ever_adv_miss = [
            d for d in miss_decls
            if d.get("advisory") == miss_ft or d.get("confirmed") == miss_ft
        ]
        ever_conf_miss = [d for d in miss_decls if d.get("confirmed") == miss_ft]

        near = miss_host_declarations_at(decls, miss_host, hit_ts)
        replay = replay_scores_at(run_id, miss_host, hit_ts)

        miss_score = None
        winner_at_hit = None
        if replay:
            miss_score = replay["scores"].get(miss_ft)
            winner_at_hit = replay["winner"]

        rows.append({
            "run_id": run_id,
            "compound_group": cg,
            "hit": f"{hit_leg['fault_type']}@{hit_leg['host']}",
            "miss": f"{miss_ft}@{miss_host}",
            "hit_confirm_ts": hit_decl["ts"],
            "miss_detected": det_by_id.get(miss_leg["event_id"]),
            "miss_ever_advisory_or_confirm": len(ever_adv_miss) > 0,
            "miss_ever_confirmed": len(ever_conf_miss) > 0,
            "miss_adv_conf_events": len(ever_adv_miss),
            "at_hit_miss_host_advisory": near[0].get("advisory") if near else None,
            "at_hit_miss_host_confirmed": near[0].get("confirmed") if near else None,
            "at_hit_miss_host_confidence": near[0].get("confidence") if near else None,
            "replay_winner": winner_at_hit,
            "replay_miss_score": round(miss_score, 3) if miss_score is not None else None,
            "replay_top3": sorted(
                ((k, round(v, 3)) for k, v in (replay or {}).get("scores", {}).items()),
                key=lambda x: -x[1],
            )[:3] if replay else None,
            "prometheus_ok": replay is not None,
        })
    return rows


def verdict(row: dict) -> str:
    ms = row.get("replay_miss_score")
    if ms is not None:
        if ms >= 0.35:
            return "SUPPRESSED_SIGNAL — miss class scored materially but lost argmax"
        if ms >= 0.15:
            return "WEAK_SIGNAL — some miss-class score, not enough to compete"
        return "DROWNED — miss class near noise at hit-confirm instant"
    if row.get("miss_ever_advisory_or_confirm"):
        return "DECL_ONLY — miss class appeared in feed but no Prom replay"
    return "ABSENT — miss class never surfaced in declarations"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", default=None)
    args = parser.parse_args()
    runs = args.run or COMPOUND_RUNS
    suite = load_suite()

    all_rows = []
    for rid in runs:
        try:
            all_rows.extend(analyze_run(rid, suite))
        except FileNotFoundError:
            print(f"SKIP {rid}: not found")

    print("\n=== COMPOUND FLIP DIAGNOSTIC — miss leg at hit-leg confirm ===\n")
    for r in all_rows:
        print(f"{r['run_id']}")
        print(f"  compound: {r['compound_group']}")
        print(f"  HIT  {r['hit']} @ {r['hit_confirm_ts']}")
        print(f"  MISS {r['miss']} detected={r['miss_detected']}")
        print(f"  miss ever advisory/confirm in window: {r['miss_ever_advisory_or_confirm']} "
              f"(n={r['miss_adv_conf_events']}) confirmed={r['miss_ever_confirmed']}")
        print(f"  at hit instant on miss host: adv={r['at_hit_miss_host_advisory']} "
              f"conf={r['at_hit_miss_host_confirmed']} operator_conf={r['at_hit_miss_host_confidence']}")
        if r["prometheus_ok"]:
            print(f"  replay winner={r['replay_winner']} miss_score={r['replay_miss_score']} top3={r['replay_top3']}")
        else:
            print("  replay: Prometheus window unavailable")
        print(f"  → {verdict(r)}\n")

    n = len(all_rows)
    if n:
        drowned = sum(1 for r in all_rows if "DROWNED" in verdict(r) or "ABSENT" in verdict(r))
        suppressed = sum(1 for r in all_rows if "SUPPRESSED" in verdict(r) or "WEAK" in verdict(r))
        print(f"SUMMARY: {n} compound pairs | drowned/absent={drowned} | weak/suppressed={suppressed}")


if __name__ == "__main__":
    main()
