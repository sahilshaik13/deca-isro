#!/usr/bin/env python3
"""DECA Temporal Loom — live inference persistence / hysteresis.

Faults are rare, slow to start, and often *almost* happen then die. A single-frame
classifier score will false-alarm on those spikes. Persistence keeps the decision
on **patterns over a short stretch of time**, not on fault duration as a feature.

Rules (sticky hysteresis)
-------------------------
- Start in ``healthy``.
- Switch to a fault class only after the **same** non-healthy class wins
  ``enter_k`` consecutive frames (default 3).
- Return to healthy only after ``exit_k`` consecutive healthy frames (default 2).
- While undecided, keep the previous **committed** label.

Apply on **time-ordered** network series only. Random exam papers are not
sequences — School Exam promote still scores raw frames; production / temporal
eval uses the loom.

See docs/DECA_TEMPORAL_LOOM.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

# Production defaults — also written into decision_thresholds.json on promote
DEFAULT_ENTER_K = 3
DEFAULT_EXIT_K = 2
DEFAULT_LOOM = {
    "enabled": True,
    "enter_k": DEFAULT_ENTER_K,
    "exit_k": DEFAULT_EXIT_K,
    "circumstance_prearm": True,
    "prearm_enter_k": 2,
    "note": "Sticky hysteresis on chronological streams only; duration is not a feature",
}


def apply_persistence(
    preds: np.ndarray,
    *,
    healthy_idx: int,
    enter_k: int = DEFAULT_ENTER_K,
    exit_k: int = DEFAULT_EXIT_K,
) -> np.ndarray:
    """Sticky hysteresis on a chronological prediction stream."""
    preds = np.asarray(preds, dtype=int)
    out = np.empty_like(preds)
    if len(preds) == 0:
        return out

    enter_k = max(1, int(enter_k))
    exit_k = max(1, int(exit_k))

    state = int(healthy_idx)
    run_label = int(preds[0])
    run_len = 0

    for i, p in enumerate(preds):
        p = int(p)
        if p == run_label:
            run_len += 1
        else:
            run_label = p
            run_len = 1

        if state == healthy_idx:
            if run_label != healthy_idx and run_len >= enter_k:
                state = run_label
        else:
            if run_label == healthy_idx and run_len >= exit_k:
                state = healthy_idx
            elif run_label != healthy_idx and run_label != state and run_len >= enter_k:
                state = run_label

        out[i] = state
    return out


def summarize_persistence(raw: np.ndarray, sticky: np.ndarray, *, healthy_idx: int) -> dict:
    raw = np.asarray(raw, dtype=int)
    sticky = np.asarray(sticky, dtype=int)
    flipped = int(np.sum(raw != sticky))
    raw_fault = int(np.sum(raw != healthy_idx))
    sticky_fault = int(np.sum(sticky != healthy_idx))
    return {
        "n": int(len(raw)),
        "frames_changed": flipped,
        "raw_fault_frames": raw_fault,
        "sticky_fault_frames": sticky_fault,
        "fault_frames_suppressed": max(0, raw_fault - sticky_fault),
    }


def loom_config_from_bundle(bundle: dict | None) -> dict[str, Any]:
    """Read loom knobs from a promoted classifier bundle (with defaults)."""
    cfg = dict(DEFAULT_LOOM)
    if not bundle:
        return cfg
    loom = bundle.get("loom") or {}
    if isinstance(loom, dict):
        cfg.update(
            {
                k: loom[k]
                for k in (
                    "enabled",
                    "enter_k",
                    "exit_k",
                    "note",
                    "circumstance_prearm",
                    "prearm_enter_k",
                )
                if k in loom
            }
        )
    # legacy flat keys
    if "enter_k" in bundle:
        cfg["enter_k"] = int(bundle["enter_k"])
    if "exit_k" in bundle:
        cfg["exit_k"] = int(bundle["exit_k"])
    return cfg


def apply_loom(
    preds: np.ndarray,
    *,
    healthy_idx: int,
    loom: dict | None = None,
    enabled: bool | None = None,
) -> np.ndarray:
    """Apply sticky loom if enabled. Safe no-op when disabled or enter_k<=1 and exit_k<=1 with no state."""
    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if not cfg.get("enabled", True):
        return np.asarray(preds, dtype=int)
    return apply_persistence(
        preds,
        healthy_idx=healthy_idx,
        enter_k=int(cfg.get("enter_k", DEFAULT_ENTER_K)),
        exit_k=int(cfg.get("exit_k", DEFAULT_EXIT_K)),
    )


def predict_fault_stream(
    gate,
    full_clf,
    X,
    *,
    healthy_idx: int,
    gate_thr: float,
    class_thr: dict,
    loom: dict | None = None,
    apply: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Frame scores then optional loom. Returns ``(raw, final)``.

    ``X`` must be in chronological order when ``apply=True``.
    """
    # Local import avoids circular import at module load
    from deca_school_exam_train import predict_weighted_multiclass

    raw = predict_weighted_multiclass(
        gate,
        full_clf,
        X,
        healthy_idx=healthy_idx,
        gate_thr=gate_thr,
        class_thr=class_thr,
    )
    if not apply:
        return raw, raw
    final = apply_loom(raw, healthy_idx=healthy_idx, loom=loom)
    return raw, final


def load_promoted_loom(models_dir: Path | None = None) -> dict[str, Any]:
    """Load loom block from decision_thresholds.json if present."""
    import json

    from _paths import MODELS_DIR

    root = Path(models_dir) if models_dir else MODELS_DIR
    path = root / "fault_classifier" / "decision_thresholds.json"
    cfg = dict(DEFAULT_LOOM)
    if not path.exists():
        return cfg
    data = json.loads(path.read_text())
    loom = data.get("loom") or {}
    if isinstance(loom, dict):
        cfg.update({k: loom[k] for k in ("enabled", "enter_k", "exit_k", "note", "metrics") if k in loom})
    return cfg


def write_loom_into_promoted(
    loom: dict[str, Any],
    *,
    models_dir: Path | None = None,
    metrics: dict[str, Any] | None = None,
) -> Path:
    """Persist loom knobs (+ optional temporal metrics) into the live classifier artifacts.

    Updates ``decision_thresholds.json``, and the ``loom`` key on both pickles when present.
    Does not retrain — only wires inference-time hysteresis into the promoted bundle.
    """
    import json

    import joblib

    from _paths import MODELS_DIR

    root = Path(models_dir) if models_dir else MODELS_DIR
    clf_dir = root / "fault_classifier"
    cfg = dict(DEFAULT_LOOM)
    cfg.update({k: loom[k] for k in loom if k in ("enabled", "enter_k", "exit_k", "note", "metrics")})
    if metrics is not None:
        cfg["metrics"] = metrics

    thr_path = clf_dir / "decision_thresholds.json"
    thr: dict[str, Any] = {}
    if thr_path.exists():
        thr = json.loads(thr_path.read_text())
    thr["loom"] = cfg
    thr_path.write_text(json.dumps(thr, indent=2))

    for name in ("fault_classifier_xgb.pkl", "label_encoder.pkl"):
        p = clf_dir / name
        if not p.exists():
            continue
        obj = joblib.load(p)
        if isinstance(obj, dict):
            obj["loom"] = cfg
            joblib.dump(obj, p)

    man_path = root / "manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text())
        man.setdefault("school_exam", {})
        if isinstance(man["school_exam"], dict):
            man["school_exam"]["loom"] = {
                "enabled": cfg.get("enabled", True),
                "enter_k": cfg.get("enter_k"),
                "exit_k": cfg.get("exit_k"),
            }
            if metrics:
                man["school_exam"]["loom_metrics"] = {
                    "raw_macro_f1": (metrics.get("raw") or {}).get("macro_f1"),
                    "persistent_macro_f1": (metrics.get("persistent") or {}).get("macro_f1"),
                    "delta_macro_f1": metrics.get("delta_macro_f1"),
                }
        for m in man.get("models", []):
            if m.get("name") == "fault_classifier_xgb":
                m.setdefault("metrics", {})
                m["metrics"]["loom"] = man["school_exam"].get("loom")
                if metrics:
                    m["metrics"]["loom_persistent_macro_f1"] = (
                        metrics.get("persistent") or {}
                    ).get("macro_f1")
        man_path.write_text(json.dumps(man, indent=2))

    return thr_path


# ── Circumstance existence head (Warp 4) ─────────────────────────────────────

DEFAULT_PREARM_ENTER_K = 2  # faster declare when existence agrees (still ≥1)


def load_circumstance_bundle(models_dir: Path | None = None) -> dict[str, Any] | None:
    """Load trained circumstance head, or None if deferred / missing."""
    import json

    import joblib

    from _paths import MODELS_DIR

    root = Path(models_dir) if models_dir else MODELS_DIR
    deferred = root / "circumstance" / "deferred.json"
    pkl = root / "circumstance" / "circumstance_xgb.pkl"
    if deferred.exists() and not pkl.exists():
        return None
    if not pkl.exists():
        return None
    bundle = joblib.load(pkl)
    if not isinstance(bundle, dict) or "clf" not in bundle:
        return None
    return bundle


def predict_circumstance(X, bundle: dict[str, Any] | None = None) -> np.ndarray | None:
    """Frame-wise existence classes. Returns None if head not ready."""
    b = bundle if bundle is not None else load_circumstance_bundle()
    if b is None:
        return None
    feats = b.get("feature_columns")
    if feats:
        missing = [c for c in feats if c not in getattr(X, "columns", [])]
        if missing:
            raise ValueError(f"circumstance head missing features: {missing[:5]}…")
        X = X[feats]
    return np.asarray(b["clf"].predict(X), dtype=int)


def apply_persistence_with_prearm(
    preds: np.ndarray,
    circ: np.ndarray,
    *,
    healthy_idx: int,
    enter_k: int = DEFAULT_ENTER_K,
    exit_k: int = DEFAULT_EXIT_K,
    prearm_enter_k: int = DEFAULT_PREARM_ENTER_K,
) -> np.ndarray:
    """Sticky loom; when existence agrees with the current fault streak, enter faster.

    If every frame in the current non-healthy run also has ``circ == run_label``,
    only ``prearm_enter_k`` consecutive votes are required (default 2) instead of
    ``enter_k`` (default 3). Still no duration feature.
    """
    preds = np.asarray(preds, dtype=int)
    circ = np.asarray(circ, dtype=int)
    if len(circ) != len(preds):
        raise ValueError("circ and preds length mismatch")
    out = np.empty_like(preds)
    if len(preds) == 0:
        return out

    enter_k = max(1, int(enter_k))
    exit_k = max(1, int(exit_k))
    prearm_enter_k = max(1, min(int(prearm_enter_k), enter_k))

    state = int(healthy_idx)
    run_label = int(preds[0])
    run_len = 0
    agree_len = 0  # consecutive frames where circ matches run_label (fault only)

    for i, p in enumerate(preds):
        p = int(p)
        c = int(circ[i])
        if p == run_label:
            run_len += 1
            if p != healthy_idx and c == p:
                agree_len += 1
            else:
                agree_len = 0
        else:
            run_label = p
            run_len = 1
            agree_len = 1 if (p != healthy_idx and c == p) else 0

        if state == healthy_idx:
            # Full streak agrees with existence → pre-arm (faster declare)
            need = (
                prearm_enter_k
                if (run_label != healthy_idx and agree_len >= run_len)
                else enter_k
            )
            if run_label != healthy_idx and run_len >= need:
                state = run_label
        else:
            if run_label == healthy_idx and run_len >= exit_k:
                state = healthy_idx
            elif run_label != healthy_idx and run_label != state:
                need = (
                    prearm_enter_k
                    if agree_len >= run_len
                    else enter_k
                )
                if run_len >= need:
                    state = run_label

        out[i] = state
    return out


def predict_fault_stream_with_circumstance(
    gate,
    full_clf,
    X,
    *,
    healthy_idx: int,
    gate_thr: float,
    class_thr: dict,
    loom: dict | None = None,
    circumstance_bundle: dict | None = None,
    apply: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Frame fault + optional existence + sticky loom (with pre-arm if ready).

    Returns ``(raw_fault, final, circ_or_None)``.
    """
    from deca_school_exam_train import predict_weighted_multiclass

    raw = predict_weighted_multiclass(
        gate,
        full_clf,
        X,
        healthy_idx=healthy_idx,
        gate_thr=gate_thr,
        class_thr=class_thr,
    )
    circ = predict_circumstance(X, circumstance_bundle)
    if not apply:
        return raw, raw, circ

    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    if not cfg.get("enabled", True):
        return raw, raw, circ

    enter_k = int(cfg.get("enter_k", DEFAULT_ENTER_K))
    exit_k = int(cfg.get("exit_k", DEFAULT_EXIT_K))
    prearm = int(cfg.get("prearm_enter_k", DEFAULT_PREARM_ENTER_K))

    if circ is not None and cfg.get("circumstance_prearm", True):
        final = apply_persistence_with_prearm(
            raw,
            circ,
            healthy_idx=healthy_idx,
            enter_k=enter_k,
            exit_k=exit_k,
            prearm_enter_k=prearm,
        )
    else:
        final = apply_persistence(
            raw, healthy_idx=healthy_idx, enter_k=enter_k, exit_k=exit_k
        )
    return raw, final, circ
