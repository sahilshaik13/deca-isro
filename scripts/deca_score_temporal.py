#!/usr/bin/env python3
"""Score the live fault classifier on a chronological network stream + loom.

Random exam papers are not time series. This script walks network rows in time
order, runs the promoted gate+head, applies sticky hysteresis (Temporal Loom),
writes ``models/temporal_persist_score.json``, and **patches** the promoted
artifacts with loom knobs + measured boost metrics.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score, recall_score

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_inference import (
    DEFAULT_ADVISORY_ENTER_K,
    DEFAULT_ADVISORY_EXIT_K,
    DEFAULT_EXIT_K,
    DEFAULT_ENTER_K,
    apply_advisory,
    apply_loom,
    build_topology_agreement_mask,
    load_lstm_bundle,
    load_topology_graph,
    loom_config_from_bundle,
    predict_ttb_stream,
    summarize_advisory_lead,
    summarize_branch_agreement,
    summarize_persistence,
    train_secondary_branch,
    write_loom_into_promoted,
)
from deca_school_exam_train import (
    RARE,
    feature_columns,
    predict_weighted_multiclass,
    predict_weighted_multiclass_with_confidence,
)
from rebuild_unified import UNIFIED_LABELS, to_unified_label


def main() -> int:
    p = argparse.ArgumentParser(description="Temporal score + loom hysteresis")
    p.add_argument("--enter-k", type=int, default=None, help="Override global enter_k fallback (default: promoted loom)")
    p.add_argument("--exit-k", type=int, default=None, help="Override global exit_k fallback (default: promoted loom)")
    p.add_argument(
        "--enter-k-by-class",
        type=str,
        default=None,
        help='JSON dict override merged onto per-class enter_k, e.g. \'{"bgp_route_flap":1}\'',
    )
    p.add_argument(
        "--exit-k-by-class",
        type=str,
        default=None,
        help='JSON dict override merged onto per-class exit_k, e.g. \'{"bgp_route_flap":3}\'',
    )
    p.add_argument(
        "--no-per-class",
        action="store_true",
        help="Disable per-class hysteresis; use the single global enter_k/exit_k for every fault",
    )
    p.add_argument(
        "--advisory-enter-k",
        type=int,
        default=None,
        help=f"Override advisory tier enter_k (default: promoted loom, {DEFAULT_ADVISORY_ENTER_K})",
    )
    p.add_argument(
        "--advisory-exit-k",
        type=int,
        default=None,
        help=f"Override advisory tier exit_k (default: promoted loom, {DEFAULT_ADVISORY_EXIT_K})",
    )
    p.add_argument(
        "--no-advisory",
        action="store_true",
        help="Skip scoring/writing the advisory tier",
    )
    p.add_argument(
        "--ttb-gate",
        action="store_true",
        help="Bind confirmed-tier entry to a falling LSTM time-to-breach trend (needs models/lstm/)",
    )
    p.add_argument(
        "--no-ttb-gate",
        action="store_true",
        help="Force-disable the ttb gate even if the promoted loom has it enabled",
    )
    p.add_argument(
        "--ttb-gate-tolerance",
        type=int,
        default=None,
        help="Allowed upticks in the TTB window before the gate blocks entry (default: promoted loom, 0)",
    )
    p.add_argument(
        "--soft-streak",
        action="store_true",
        help="Use cumulative frame confidence for entry instead of a hard consecutive-frame count",
    )
    p.add_argument(
        "--no-soft-streak",
        action="store_true",
        help="Force-disable soft streak even if the promoted loom has it enabled",
    )
    p.add_argument(
        "--branch-agreement",
        action="store_true",
        help="Require a secondary head (default wm) to agree on the full streak before entry",
    )
    p.add_argument(
        "--no-branch-agreement",
        action="store_true",
        help="Force-disable branch agreement even if the promoted loom has it enabled",
    )
    p.add_argument(
        "--branch-family",
        type=str,
        default=None,
        help="Secondary head family for branch agreement (default: promoted loom, wm)",
    )
    p.add_argument(
        "--topology-gate",
        action="store_true",
        help="Require topology neighbors to echo the same fault at this timestamp",
    )
    p.add_argument(
        "--no-topology-gate",
        action="store_true",
        help="Force-disable topology gate even if the promoted loom has it enabled",
    )
    p.add_argument(
        "--topology-min-neighbors",
        type=int,
        default=None,
        help="How many neighbor nodes must agree (default: promoted loom, 1)",
    )
    p.add_argument("--tail-frac", type=float, default=0.25, help="Score last fraction of network timeline")
    p.add_argument(
        "--no-write-promoted",
        action="store_true",
        help="Do not patch decision_thresholds.json / pickles with loom metrics",
    )
    args = p.parse_args()

    df = pd.read_parquet(PROCESSED_DIR / "deca_unified_dataset.parquet")
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    feats = feature_columns(df)

    net = df[df["source"] == "network"].copy()
    cut = net.index[int(len(net) * (1.0 - args.tail_frac))]
    te = net.loc[net.index >= cut]
    print(f"Network rows={len(net):,}  temporal test tail={len(te):,}  from {cut}")

    y_raw = te["unified_label"].astype(str)
    le_classes = [c for c in UNIFIED_LABELS if c in set(df["unified_label"].astype(str))]
    le_classes += sorted(set(y_raw) - set(le_classes))
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = y_raw.map(class_to_idx).astype(int).values
    X = te[feats]

    bundle = joblib.load(MODELS_DIR / "fault_classifier" / "fault_classifier_xgb.pkl")
    healthy_idx = int(bundle["healthy_idx"])
    loom = loom_config_from_bundle(bundle)
    if args.enter_k is not None:
        loom["enter_k"] = int(args.enter_k)
    if args.exit_k is not None:
        loom["exit_k"] = int(args.exit_k)
    loom.setdefault("enter_k", DEFAULT_ENTER_K)
    loom.setdefault("exit_k", DEFAULT_EXIT_K)
    loom["enabled"] = True

    if args.no_per_class:
        loom["enter_k_by_class"] = {}
        loom["exit_k_by_class"] = {}
    if args.enter_k_by_class:
        loom["enter_k_by_class"] = {**loom.get("enter_k_by_class", {}), **json.loads(args.enter_k_by_class)}
    if args.exit_k_by_class:
        loom["exit_k_by_class"] = {**loom.get("exit_k_by_class", {}), **json.loads(args.exit_k_by_class)}

    loom.setdefault("advisory_enabled", True)
    loom.setdefault("advisory_enter_k", DEFAULT_ADVISORY_ENTER_K)
    loom.setdefault("advisory_exit_k", DEFAULT_ADVISORY_EXIT_K)
    if args.no_advisory:
        loom["advisory_enabled"] = False
    if args.advisory_enter_k is not None:
        loom["advisory_enter_k"] = int(args.advisory_enter_k)
    if args.advisory_exit_k is not None:
        loom["advisory_exit_k"] = int(args.advisory_exit_k)

    loom.setdefault("ttb_gate_enabled", False)
    loom.setdefault("ttb_gate_tolerance", 0)
    if args.ttb_gate:
        loom["ttb_gate_enabled"] = True
    if args.no_ttb_gate:
        loom["ttb_gate_enabled"] = False
    if args.ttb_gate_tolerance is not None:
        loom["ttb_gate_tolerance"] = int(args.ttb_gate_tolerance)

    loom.setdefault("soft_streak_enabled", False)
    if args.soft_streak:
        loom["soft_streak_enabled"] = True
    if args.no_soft_streak:
        loom["soft_streak_enabled"] = False

    loom.setdefault("branch_agreement_enabled", False)
    loom.setdefault("branch_secondary_family", "wm")
    if args.branch_agreement:
        loom["branch_agreement_enabled"] = True
    if args.no_branch_agreement:
        loom["branch_agreement_enabled"] = False
    if args.branch_family:
        loom["branch_secondary_family"] = str(args.branch_family)

    loom.setdefault("topology_gate_enabled", False)
    loom.setdefault("topology_min_neighbors", 1)
    if args.topology_gate:
        loom["topology_gate_enabled"] = True
    if args.no_topology_gate:
        loom["topology_gate_enabled"] = False
    if args.topology_min_neighbors is not None:
        loom["topology_min_neighbors"] = int(args.topology_min_neighbors)

    ttb = None
    if loom.get("ttb_gate_enabled", False):
        lstm_bundle = load_lstm_bundle()
        if lstm_bundle is None:
            print("  ttb_gate requested but models/lstm/ unavailable — gate has no effect")
        else:
            ttb = predict_ttb_stream(X, lstm_bundle)
            print(
                f"  ttb_gate ENABLED  tolerance={loom['ttb_gate_tolerance']}  "
                f"({int(np.sum(~np.isnan(ttb)))}/{len(ttb)} frames have a TTB prediction)"
            )

    conf = None
    if loom.get("soft_streak_enabled", False):
        raw, conf = predict_weighted_multiclass_with_confidence(
            bundle["gate"],
            bundle["full_clf"],
            X,
            healthy_idx=healthy_idx,
            gate_thr=float(bundle["gate_thr"]),
            class_thr={int(k): float(v) for k, v in bundle.get("class_thr", {}).items()},
        )
        print(
            f"  soft_streak ENABLED  enter threshold={loom['enter_k']} cumulative confidence  "
            f"(mean fault conf={float(np.mean(conf[raw != healthy_idx])):.3f} when gate open)"
            if np.any(raw != healthy_idx)
            else f"  soft_streak ENABLED  enter threshold={loom['enter_k']} cumulative confidence"
        )
    else:
        raw = predict_weighted_multiclass(
            bundle["gate"],
            bundle["full_clf"],
            X,
            healthy_idx=healthy_idx,
            gate_thr=float(bundle["gate_thr"]),
            class_thr={int(k): float(v) for k, v in bundle.get("class_thr", {}).items()},
        )

    branch_preds = None
    branch_stats = None
    if loom.get("branch_agreement_enabled", False):
        family = str(loom.get("branch_secondary_family", "wm"))
        train_net = net.loc[net.index < cut]
        val_cut = train_net.index[int(len(train_net) * 0.8)]
        tr = train_net.loc[train_net.index < val_cut]
        va = train_net.loc[train_net.index >= val_cut]
        y_tr = tr["unified_label"].astype(str).map(class_to_idx).astype(int).values
        y_va = va["unified_label"].astype(str).map(class_to_idx).astype(int).values
        rare_ids = {class_to_idx[c] for c in RARE if c in class_to_idx}
        print(
            f"  branch_agreement: training secondary head '{family}' on "
            f"{len(tr):,} rows (val {len(va):,})"
        )
        _, branch_clf, branch_thr = train_secondary_branch(
            tr[feats],
            y_tr,
            va[feats],
            y_va,
            healthy_idx=healthy_idx,
            rare_ids=rare_ids,
            family=family,
            gate=bundle["gate"],
        )
        branch_preds = predict_weighted_multiclass(
            bundle["gate"],
            branch_clf,
            X,
            healthy_idx=healthy_idx,
            gate_thr=float(branch_thr["gate_thr"]),
            class_thr={int(k): float(v) for k, v in branch_thr.get("class_thr", {}).items()},
        )
        branch_stats = summarize_branch_agreement(raw, branch_preds, healthy_idx=healthy_idx)
        print(
            f"  branch_agreement ENABLED  family={family}  "
            f"agree {branch_stats['agree_frames']}/{branch_stats['fault_frames']} fault frames "
            f"({branch_stats['agree_rate']:.3f})"
        )

    topo_agrees = None
    topo_stats = None
    if loom.get("topology_gate_enabled", False):
        graph = load_topology_graph()
        if not graph.get("nodes"):
            print("  topology_gate requested but models/topology/ unavailable — gate has no effect")
        elif "run_id" not in te.columns:
            print("  topology_gate requested but run_id missing from lake — gate has no effect")
        else:
            topo_agrees = build_topology_agreement_mask(
                te.index,
                te["run_id"].astype(str).values,
                raw,
                healthy_idx=healthy_idx,
                graph=graph,
                min_neighbors=int(loom.get("topology_min_neighbors", 1)),
            )
            fault_mask = raw != healthy_idx
            n_fault = int(np.sum(fault_mask))
            n_open = int(np.sum(topo_agrees[fault_mask])) if n_fault else 0
            topo_stats = {
                "fault_frames": n_fault,
                "neighbor_agree_frames": n_open,
                "neighbor_agree_rate": (n_open / n_fault) if n_fault else 0.0,
                "min_neighbors": int(loom.get("topology_min_neighbors", 1)),
            }
            print(
                f"  topology_gate ENABLED  min_neighbors={loom['topology_min_neighbors']}  "
                f"neighbor agree {n_open}/{n_fault} fault frames ({topo_stats['neighbor_agree_rate']:.3f})"
            )

    sticky = apply_loom(
        raw,
        healthy_idx=healthy_idx,
        loom=loom,
        classes=le_classes,
        ttb=ttb,
        confidences=conf,
        branch_preds=branch_preds,
        topo_agrees=topo_agrees,
    )
    advisory = (
        apply_advisory(raw, healthy_idx=healthy_idx, loom=loom, classes=le_classes)
        if loom.get("advisory_enabled", True)
        else None
    )

    def pack(name, pred):
        rare_ids = [class_to_idx[c] for c in RARE if c in class_to_idx]
        rare = float(
            np.mean([recall_score(y == c, pred == c, zero_division=0) for c in rare_ids])
        ) if rare_ids else 0.0
        report = classification_report(
            y, pred, labels=list(range(len(le_classes))), target_names=le_classes,
            zero_division=0, output_dict=True,
        )
        return {
            "name": name,
            "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
            "accuracy": float(accuracy_score(y, pred)),
            "mean_rare_recall": rare,
            "per_class_f1": {c: float(report[c]["f1-score"]) for c in le_classes if c in report},
        }

    raw_m = pack("raw_frame", raw)
    sticky_m = pack("persistent", sticky)
    advisory_m = pack("advisory", advisory) if advisory is not None else None
    summary = summarize_persistence(raw, sticky, healthy_idx=healthy_idx)
    delta = float(sticky_m["macro_f1"] - raw_m["macro_f1"])
    lead_stats = (
        summarize_advisory_lead(y, advisory, sticky, healthy_idx=healthy_idx)
        if advisory is not None
        else None
    )

    print("\n=== Temporal Loom score (chronological network tail) ===")
    print(f"  loom global fallback  enter_k={loom['enter_k']}  exit_k={loom['exit_k']}")
    if loom.get("ttb_gate_enabled", False) and ttb is not None:
        print(
            f"  ttb_gate ON   entry also requires falling LSTM TTB trend "
            f"(tolerance={loom['ttb_gate_tolerance']})"
        )
    if loom.get("soft_streak_enabled", False):
        print(
            f"  soft_streak ON   entry uses cumulative confidence >= enter_k "
            f"({loom['enter_k']}); exit stays frame-based"
        )
    if loom.get("branch_agreement_enabled", False) and branch_stats is not None:
        print(
            f"  branch_agreement ON   family={loom.get('branch_secondary_family', 'wm')}  "
            f"raw agree rate={branch_stats['agree_rate']:.3f}"
        )
    if loom.get("topology_gate_enabled", False) and topo_stats is not None:
        print(
            f"  topology_gate ON   min_neighbors={loom.get('topology_min_neighbors', 1)}  "
            f"fault frames with neighbor echo={topo_stats['neighbor_agree_rate']:.3f}"
        )
    enter_by_class = loom.get("enter_k_by_class") or {}
    exit_by_class = loom.get("exit_k_by_class") or {}
    if enter_by_class or exit_by_class:
        for c in le_classes:
            if c == "healthy" or (c not in enter_by_class and c not in exit_by_class):
                continue
            print(
                f"    {c:20s} enter_k={enter_by_class.get(c, loom['enter_k'])}  "
                f"exit_k={exit_by_class.get(c, loom['exit_k'])}"
            )
    for m in (raw_m, sticky_m, advisory_m):
        if m is None:
            continue
        print(
            f"  {m['name']:12s}  Macro-F1={m['macro_f1']:.4f}  Acc={m['accuracy']:.4f}  "
            f"rareR={m['mean_rare_recall']:.4f}"
        )
        for c in RARE:
            if c in m["per_class_f1"]:
                print(f"    {c}: F1={m['per_class_f1'][c]:.3f}")
    print(
        f"  boost ΔMacro-F1={delta:+.4f}  frames_changed={summary['frames_changed']}  "
        f"fault frames {summary['raw_fault_frames']} → {summary['sticky_fault_frames']} "
        f"(suppressed {summary['fault_frames_suppressed']})"
    )
    if lead_stats is not None:
        print(
            f"\n  advisory tier  enter_k={loom['advisory_enter_k']}  exit_k={loom['advisory_exit_k']}"
        )
        print(
            f"    events={lead_stats['events']}  advisory caught={lead_stats['advisory_caught_events']}  "
            f"confirmed caught={lead_stats['confirmed_caught_events']}"
        )
        print(
            f"    mean lead={lead_stats['mean_lead_frames']:.2f} frames  "
            f"max lead={lead_stats['max_lead_frames']} frames  "
            f"(over {lead_stats['events_with_measurable_lead']} events where both caught it)"
        )
        print(
            f"    advisory-only window: {lead_stats['lead_frames_total']} frames — "
            f"{lead_stats['lead_correct_frames']} correct early warning, "
            f"{lead_stats['lead_wrong_class_frames']} wrong-class, "
            f"{lead_stats['lead_false_frames']} pure noise  "
            f"(precision={lead_stats['lead_precision']:.3f})"
        )

    out = {
        "date": datetime.now(timezone.utc).isoformat(),
        "enter_k": int(loom["enter_k"]),
        "exit_k": int(loom["exit_k"]),
        "enter_k_by_class": enter_by_class,
        "exit_k_by_class": exit_by_class,
        "tail_frac": args.tail_frac,
        "n_test": int(len(te)),
        "raw": raw_m,
        "persistent": sticky_m,
        "delta_macro_f1": delta,
        "persistence_summary": summary,
        "advisory": advisory_m,
        "advisory_enter_k": int(loom["advisory_enter_k"]),
        "advisory_exit_k": int(loom["advisory_exit_k"]),
        "advisory_lead": lead_stats,
        "ttb_gate_enabled": bool(loom.get("ttb_gate_enabled", False)),
        "ttb_gate_tolerance": int(loom.get("ttb_gate_tolerance", 0)),
        "ttb_coverage_frames": int(np.sum(~np.isnan(ttb))) if ttb is not None else 0,
        "soft_streak_enabled": bool(loom.get("soft_streak_enabled", False)),
        "branch_agreement_enabled": bool(loom.get("branch_agreement_enabled", False)),
        "branch_secondary_family": str(loom.get("branch_secondary_family", "wm")),
        "branch_agreement": branch_stats,
        "topology_gate_enabled": bool(loom.get("topology_gate_enabled", False)),
        "topology_min_neighbors": int(loom.get("topology_min_neighbors", 1)),
        "topology_agreement": topo_stats,
        "note": "Duration is not a feature — persistence is consecutive pattern agreement only",
    }
    path = MODELS_DIR / "temporal_persist_score.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {path}")

    if not args.no_write_promoted:
        thr = write_loom_into_promoted(
            loom,
            metrics={
                "date": out["date"],
                "tail_frac": args.tail_frac,
                "n_test": out["n_test"],
                "delta_macro_f1": delta,
                "raw": {
                    "macro_f1": raw_m["macro_f1"],
                    "accuracy": raw_m["accuracy"],
                    "mean_rare_recall": raw_m["mean_rare_recall"],
                    "per_class_f1": raw_m["per_class_f1"],
                },
                "persistent": {
                    "macro_f1": sticky_m["macro_f1"],
                    "accuracy": sticky_m["accuracy"],
                    "mean_rare_recall": sticky_m["mean_rare_recall"],
                    "per_class_f1": sticky_m["per_class_f1"],
                },
                "persistence_summary": summary,
                "advisory": advisory_m,
                "advisory_lead": lead_stats,
            },
        )
        print(f"Patched loom into promoted artifacts ({thr})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
