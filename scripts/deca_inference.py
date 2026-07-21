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

Per-class hysteresis
---------------------
A single global ``(enter_k, exit_k)`` forces every fault family through the same
debounce window even though onset/recovery patterns genuinely differ by family.
``enter_k_by_class`` / ``exit_k_by_class`` (keyed by fault class name) override
the global default per family. Tune with empirical sweeps
(``deca_score_temporal.py --enter-k-by-class/--exit-k-by-class``), not intuition
alone — a fast ``enter_k`` sounds right for a "fast/instant" fault like BGP flap,
but if that class's raw frame scores are noisy, a short entry window mostly picks
up single-frame noise, not real onsets. What measurably helped here was patience
on the *exit* side for flappy/leaky classes (one extra confirming healthy frame
before declaring recovered). Unlisted classes fall back to the global
``enter_k``/``exit_k``.

Two-tier loom (advisory + confirmed)
-------------------------------------
Same state machine, run **twice in parallel** on the same frame stream with
different knobs — no new architecture, just two honest outputs instead of one:

- **advisory** — shallow ``advisory_enter_k`` (default 2), fast exit (default 1).
  "Something may be forming." Expected to be noisier; it trades false starts for
  lead time.
- **confirmed** — the tuned sticky loom above. "This is now declared."

Soft streak (confidence-weighted entry)
---------------------------------------
When ``soft_streak_enabled`` is true, entry accumulates per-frame classifier
confidence (threshold-adjusted winning score) instead of counting consecutive
frames equally. ``enter_k`` is the cumulative confidence threshold; exit stays
frame-based. Strong single-frame signals commit faster; weak wobbles need more
evidence — see ``predict_weighted_multiclass_with_confidence``.

This matches the human-in-the-loop stance: soft probabilities plus loom
stability, what is *likely forming*, not prophecy. Dashboards can show both —
operators decide what an early advisory is worth versus waiting for confirmation.

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

# Per-class overrides — empirically swept on the merged-lake chrono tail
# (scripts/deca_score_temporal.py --enter-k-by-class/--exit-k-by-class), not
# guessed from onset-speed intuition alone. The intuitive fix ("BGP flap is
# instant, so let it enter fast") actually *hurt* BGP F1 (0.774 → 0.543 at
# enter_k=1): BGP's raw frame scores are the noisiest of the four fault
# classes, so a short entry window mostly picks up single-frame noise instead
# of a real onset. What genuinely helped was patience on the way OUT: BGP
# flaps and VRF leakage both have brief quiet frames mid-event, so declaring
# "recovered" needs one extra confirming healthy frame vs. the global default.
# Sweep result: exit_k 2→3 on these two classes alone lifted the sticky tail
# Macro-F1 0.9077 → 0.9120 (BGP F1 0.774→0.790, VRF F1 0.903→0.911) with no
# change to congestion/tunnel, which were already at their best global exit_k.
# Classes not listed fall back to enter_k/exit_k above.
# Soft-streak cumulative confidence thresholds (when soft_streak_enabled).
# Specificity exam v1 failures: calm_a=vrf@s2, calm_b/nm03=tunnel — raise VRF
# enter and give tunnel one more soft unit of patience.
DEFAULT_ENTER_K_BY_CLASS: dict[str, int] = {
    "tunnel_degradation": 4,
    "congestion_breach": 3,
    "bgp_route_flap": 3,
    "vrf_leakage": 3,
}
DEFAULT_EXIT_K_BY_CLASS = {
    "bgp_route_flap": 3,
    "vrf_leakage": 3,
}

# Advisory tier — same state machine as confirmed, shallower entry, fast exit.
# "Something may be forming" is allowed to flicker; it costs nothing to be wrong
# because it never commits an alarm on its own, only the confirmed tier does.
DEFAULT_ADVISORY_ENTER_K = 2
DEFAULT_ADVISORY_EXIT_K = 1

DEFAULT_LOOM = {
    "enabled": True,
    "enter_k": DEFAULT_ENTER_K,
    "exit_k": DEFAULT_EXIT_K,
    "enter_k_by_class": dict(DEFAULT_ENTER_K_BY_CLASS),
    "exit_k_by_class": dict(DEFAULT_EXIT_K_BY_CLASS),
    # Pre-arm shortened confirmed entry on near-miss onsets (live cry-wolf).
    # Off for specificity trust; circumstance head still runs for the feed flag.
    "circumstance_prearm": False,
    "prearm_enter_k": 2,
    "advisory_enabled": True,
    "advisory_enter_k": DEFAULT_ADVISORY_ENTER_K,
    "advisory_exit_k": DEFAULT_ADVISORY_EXIT_K,
    "advisory_enter_k_by_class": {},
    # "What" (classifier streak) + "when" (LSTM time-to-breach trend) binding.
    # Off by default — needs the LSTM companion and is measured, not assumed,
    # to help. See docs/DECA_TEMPORAL_LOOM.md §4 for the sweep.
    "ttb_gate_enabled": False,
    "ttb_gate_tolerance": 0,
    # Soft streak — accumulate per-frame confidence toward enter_k instead of a
    # hard consecutive-frame count. Measured before enabling; see §4.
    "soft_streak_enabled": False,
    # Multi-branch agreement — secondary head must match the primary streak to enter.
    "branch_agreement_enabled": False,
    "branch_secondary_family": "wm",
    # Topology correlation — CE neighbors must echo the same fault at this timestamp.
    "topology_gate_enabled": False,
    "topology_min_neighbors": 1,
    "note": (
        "Sticky hysteresis on chronological streams only; duration is not a feature. "
        "enter_k/exit_k are per-class fallbacks — see enter_k_by_class/exit_k_by_class. "
        "advisory_* runs the same state machine shallower/faster for an early "
        "'may be forming' signal alongside the confirmed declaration. ttb_gate_* "
        "additionally requires a falling LSTM time-to-breach trend to commit entry. "
        "soft_streak_enabled replaces the hard entry counter with a running sum of "
        "frame confidence (exit stays frame-based). branch_agreement_* binds a "
        "secondary classifier head; topology_gate_* requires neighbor-node agreement."
    ),
}


def _resolve_k(
    label_idx: int,
    classes: list[str] | None,
    k_by_class: dict[str, int] | None,
    default_k: int,
) -> int:
    """Look up the per-class enter/exit patience for ``label_idx``, else the default."""
    if not classes or not k_by_class or label_idx < 0 or label_idx >= len(classes):
        return default_k
    name = classes[label_idx]
    return max(1, int(k_by_class.get(name, default_k)))


def _ttb_falling(
    ttb: np.ndarray | None,
    i: int,
    run_len: int,
    *,
    tolerance: int = 0,
) -> bool:
    """Is the LSTM time-to-breach trend falling over the current streak window?

    Compares ``ttb[i - run_len + 1 : i + 1]`` (the same window the classifier's
    streak was built over) and allows at most ``tolerance`` upticks between
    consecutive frames. Returns ``True`` (gate open — don't block) whenever the
    signal isn't available: no ``ttb`` array, not enough history yet, or a NaN
    in the window. This is an *additional* binding condition, not a replacement
    — it should never block a decision the classifier alone would make when the
    "when" branch simply has nothing to say.
    """
    if ttb is None:
        return True
    start = i - run_len + 1
    if start < 0:
        return True
    window = ttb[start : i + 1]
    if len(window) < 2 or np.any(np.isnan(window)):
        return True
    diffs = np.diff(window)
    upticks = int(np.sum(diffs > 0))
    return upticks <= tolerance


def _entry_ready(
    *,
    soft_streak: bool,
    run_len: int,
    run_conf: float,
    need: int,
) -> bool:
    """Has the current streak satisfied the entry threshold?"""
    if soft_streak:
        return run_conf >= float(need)
    return run_len >= need


def _branch_streak_agrees(
    branch: np.ndarray | None,
    i: int,
    run_len: int,
    run_label: int,
    *,
    healthy_idx: int,
) -> bool:
    """Does the secondary branch agree on every frame of the current fault streak?"""
    if branch is None:
        return True
    if run_label == healthy_idx:
        return True
    start = i - run_len + 1
    if start < 0:
        return True
    window = np.asarray(branch[start : i + 1], dtype=int)
    return bool(np.all(window == run_label))


def _topo_gate_open(topo_agrees: np.ndarray | None, i: int) -> bool:
    """Neighbor-node correlation gate — open when unavailable or neighbors agree."""
    if topo_agrees is None:
        return True
    return bool(topo_agrees[i])


def apply_persistence(
    preds: np.ndarray,
    *,
    healthy_idx: int,
    enter_k: int = DEFAULT_ENTER_K,
    exit_k: int = DEFAULT_EXIT_K,
    classes: list[str] | None = None,
    enter_k_by_class: dict[str, int] | None = None,
    exit_k_by_class: dict[str, int] | None = None,
    ttb: np.ndarray | None = None,
    ttb_gate_tolerance: int = 0,
    confidences: np.ndarray | None = None,
    soft_streak: bool = False,
    branch_preds: np.ndarray | None = None,
    topo_agrees: np.ndarray | None = None,
) -> np.ndarray:
    """Sticky hysteresis on a chronological prediction stream.

    ``enter_k``/``exit_k`` are the global fallbacks. Pass ``classes`` (index→name,
    e.g. a label encoder's ``classes_``) together with ``enter_k_by_class`` /
    ``exit_k_by_class`` to give each fault family its own onset/recovery patience —
    unlisted classes still use the global default.

    ``ttb`` (optional, same length as ``preds``) binds the "what" branch (this
    streak) to the "when" branch (LSTM time-to-breach): entry only commits if
    the streak *also* has a falling TTB trend over the same window — see
    ``_ttb_falling``. Exit is unaffected (recovery doesn't need a TTB opinion).

    ``soft_streak`` + ``confidences`` (same length as ``preds``): replace the hard
    consecutive-frame entry counter with a running sum of per-frame confidence.
    ``enter_k`` becomes the cumulative confidence threshold (e.g. 3.0). A single
    strong frame (score well above its class threshold) can commit faster than
    several weak wobbles; exit still uses consecutive healthy **frames**.

    ``branch_preds`` (optional): secondary classifier head — entry requires the
    full streak to match this parallel opinion. ``topo_agrees`` (optional): per-row
    bool from ``build_topology_agreement_mask`` — entry blocked when neighbors
    disagree at that frame.
    """
    preds = np.asarray(preds, dtype=int)
    out = np.empty_like(preds)
    if len(preds) == 0:
        return out

    enter_k = max(1, int(enter_k))
    exit_k = max(1, int(exit_k))
    use_soft = bool(soft_streak and confidences is not None)
    conf = np.asarray(confidences, dtype=np.float64) if use_soft else None
    if use_soft and len(conf) != len(preds):
        raise ValueError("confidences and preds length mismatch")
    if branch_preds is not None and len(branch_preds) != len(preds):
        raise ValueError("branch_preds and preds length mismatch")
    if topo_agrees is not None and len(topo_agrees) != len(preds):
        raise ValueError("topo_agrees and preds length mismatch")

    state = int(healthy_idx)
    run_label = int(preds[0])
    run_len = 0
    run_conf = 0.0

    for i, p in enumerate(preds):
        p = int(p)
        frame_conf = float(conf[i]) if use_soft else 0.0
        if p == run_label:
            run_len += 1
            run_conf += frame_conf
        else:
            run_label = p
            run_len = 1
            run_conf = frame_conf

        if state == healthy_idx:
            need = _resolve_k(run_label, classes, enter_k_by_class, enter_k)
            if (
                run_label != healthy_idx
                and _entry_ready(
                    soft_streak=use_soft, run_len=run_len, run_conf=run_conf, need=need
                )
                and _ttb_falling(ttb, i, run_len, tolerance=ttb_gate_tolerance)
                and _branch_streak_agrees(
                    branch_preds, i, run_len, run_label, healthy_idx=healthy_idx
                )
                and _topo_gate_open(topo_agrees, i)
            ):
                state = run_label
        else:
            if run_label == healthy_idx:
                need = _resolve_k(state, classes, exit_k_by_class, exit_k)
                if run_len >= need:
                    state = healthy_idx
            elif run_label != healthy_idx and run_label != state:
                need = _resolve_k(run_label, classes, enter_k_by_class, enter_k)
                if (
                    _entry_ready(
                        soft_streak=use_soft, run_len=run_len, run_conf=run_conf, need=need
                    )
                    and _ttb_falling(ttb, i, run_len, tolerance=ttb_gate_tolerance)
                    and _branch_streak_agrees(
                        branch_preds, i, run_len, run_label, healthy_idx=healthy_idx
                    )
                    and _topo_gate_open(topo_agrees, i)
                ):
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


def summarize_advisory_lead(
    y: np.ndarray,
    advisory: np.ndarray,
    confirmed: np.ndarray,
    *,
    healthy_idx: int,
) -> dict:
    """Honest cost/benefit of the advisory tier vs. the confirmed tier.

    Per contiguous ground-truth fault run: how many frames earlier does advisory
    correctly call the fault than confirmed does (``mean_lead_frames``)? Then,
    over every frame where advisory has already flagged something but confirmed
    hasn't (``lead_frames_total``): what fraction of that "advisory-only" window
    was actually correct (``lead_precision``) vs. pure noise on a healthy frame
    (``lead_false_frames``)? This is the "may be forming vs pure noise" tradeoff,
    reported instead of assumed.
    """
    y = np.asarray(y, dtype=int)
    advisory = np.asarray(advisory, dtype=int)
    confirmed = np.asarray(confirmed, dtype=int)
    n = len(y)

    events = 0
    advisory_caught = 0
    confirmed_caught = 0
    leads: list[int] = []
    i = 0
    while i < n:
        if y[i] != healthy_idx:
            j = i
            while j < n and y[j] == y[i]:
                j += 1
            events += 1
            fault_cls = int(y[i])
            adv_idx = next((k for k in range(i, j) if advisory[k] == fault_cls), None)
            conf_idx = next((k for k in range(i, j) if confirmed[k] == fault_cls), None)
            if adv_idx is not None:
                advisory_caught += 1
            if conf_idx is not None:
                confirmed_caught += 1
            if adv_idx is not None and conf_idx is not None:
                leads.append(conf_idx - adv_idx)
            i = j
        else:
            i += 1

    lead_mask = (advisory != healthy_idx) & (confirmed == healthy_idx)
    lead_frames = int(np.sum(lead_mask))
    lead_correct = int(np.sum(lead_mask & (advisory == y)))
    lead_wrong_class = int(np.sum(lead_mask & (y != healthy_idx) & (advisory != y)))
    lead_false = int(np.sum(lead_mask & (y == healthy_idx)))

    return {
        "events": events,
        "advisory_caught_events": advisory_caught,
        "confirmed_caught_events": confirmed_caught,
        "events_with_measurable_lead": len(leads),
        "mean_lead_frames": float(np.mean(leads)) if leads else 0.0,
        "max_lead_frames": int(max(leads)) if leads else 0,
        "lead_frames_total": lead_frames,
        "lead_correct_frames": lead_correct,
        "lead_wrong_class_frames": lead_wrong_class,
        "lead_false_frames": lead_false,
        "lead_precision": (lead_correct / lead_frames) if lead_frames else 0.0,
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
                    "enter_k_by_class",
                    "exit_k_by_class",
                    "note",
                    "circumstance_prearm",
                    "prearm_enter_k",
                    "advisory_enabled",
                    "advisory_enter_k",
                    "advisory_exit_k",
                    "advisory_enter_k_by_class",
                    "ttb_gate_enabled",
                    "ttb_gate_tolerance",
                    "soft_streak_enabled",
                    "branch_agreement_enabled",
                    "branch_secondary_family",
                    "topology_gate_enabled",
                    "topology_min_neighbors",
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
    classes: list[str] | None = None,
    ttb: np.ndarray | None = None,
    confidences: np.ndarray | None = None,
    branch_preds: np.ndarray | None = None,
    topo_agrees: np.ndarray | None = None,
) -> np.ndarray:
    """Apply sticky loom if enabled. Safe no-op when disabled or enter_k<=1 and exit_k<=1 with no state.

    Pass ``classes`` (index→name) to activate the per-class ``enter_k_by_class`` /
    ``exit_k_by_class`` overrides carried in ``loom``/``DEFAULT_LOOM``. Pass ``ttb``
    (per-frame LSTM time-to-breach predictions) to activate the "what"+"when"
    binding gate when ``loom.ttb_gate_enabled`` is true. Pass ``confidences`` together
    with ``loom.soft_streak_enabled`` to use cumulative confidence for entry.
    Pass ``branch_preds`` / ``topo_agrees`` for multi-head and topology binding gates.
    """
    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if not cfg.get("enabled", True):
        return np.asarray(preds, dtype=int)
    soft = bool(cfg.get("soft_streak_enabled", False))
    branch_arg = branch_preds if cfg.get("branch_agreement_enabled", False) else None
    topo_arg = topo_agrees if cfg.get("topology_gate_enabled", False) else None
    return apply_persistence(
        preds,
        healthy_idx=healthy_idx,
        enter_k=int(cfg.get("enter_k", DEFAULT_ENTER_K)),
        exit_k=int(cfg.get("exit_k", DEFAULT_EXIT_K)),
        classes=classes,
        enter_k_by_class=cfg.get("enter_k_by_class") or None,
        exit_k_by_class=cfg.get("exit_k_by_class") or None,
        ttb=ttb if cfg.get("ttb_gate_enabled", False) else None,
        ttb_gate_tolerance=int(cfg.get("ttb_gate_tolerance", 0)),
        confidences=confidences,
        soft_streak=soft,
        branch_preds=branch_arg,
        topo_agrees=topo_arg,
    )


def apply_advisory(
    preds: np.ndarray,
    *,
    healthy_idx: int,
    loom: dict | None = None,
    enabled: bool | None = None,
    classes: list[str] | None = None,
) -> np.ndarray:
    """Shallow/fast-exit hysteresis — the "may be forming" tier.

    Exactly the same state machine as ``apply_loom``, just with a shorter entry
    window (``advisory_enter_k``, default 2) and a 1-frame exit (default), so it
    can flicker cheaply — it never commits an alarm on its own; only the
    confirmed tier (``apply_loom``) does that.
    """
    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    if enabled is not None:
        cfg["advisory_enabled"] = bool(enabled)
    if not cfg.get("advisory_enabled", True):
        return np.asarray(preds, dtype=int)
    return apply_persistence(
        preds,
        healthy_idx=healthy_idx,
        enter_k=int(cfg.get("advisory_enter_k", DEFAULT_ADVISORY_ENTER_K)),
        exit_k=int(cfg.get("advisory_exit_k", DEFAULT_ADVISORY_EXIT_K)),
        classes=classes,
        enter_k_by_class=cfg.get("advisory_enter_k_by_class") or None,
        exit_k_by_class=None,
    )


def apply_two_tier_loom(
    preds: np.ndarray,
    *,
    healthy_idx: int,
    loom: dict | None = None,
    classes: list[str] | None = None,
    ttb: np.ndarray | None = None,
    confidences: np.ndarray | None = None,
    branch_preds: np.ndarray | None = None,
    topo_agrees: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Run the confirmed and advisory tiers on the same raw stream.

    Same state machine, run twice with different knobs — no new architecture,
    two honest outputs: ``advisory`` ("may be forming", fast/noisy, never
    ttb-gated — it's meant to be cheap and early) and ``confirmed`` (the tuned
    sticky loom, slower/robust, optionally bound to a falling ``ttb`` trend and/or
    a soft confidence streak).
    """
    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    return {
        "confirmed": apply_loom(
            preds,
            healthy_idx=healthy_idx,
            loom=loom,
            classes=classes,
            ttb=ttb,
            confidences=confidences,
            branch_preds=branch_preds,
            topo_agrees=topo_agrees,
        ),
        "advisory": apply_advisory(preds, healthy_idx=healthy_idx, loom=loom, classes=classes),
    }


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
    classes: list[str] | None = None,
    ttb: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Frame scores then optional loom. Returns ``(raw, final)``.

    ``X`` must be in chronological order when ``apply=True``. Pass ``classes``
    (index→name) to activate per-class enter/exit hysteresis, and ``ttb`` (LSTM
    time-to-breach stream) to activate the "what"+"when" binding gate.
    """
    from deca_school_exam_train import (
        predict_weighted_multiclass,
        predict_weighted_multiclass_with_confidence,
    )

    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    conf = None
    if cfg.get("soft_streak_enabled", False):
        raw, conf = predict_weighted_multiclass_with_confidence(
            gate,
            full_clf,
            X,
            healthy_idx=healthy_idx,
            gate_thr=gate_thr,
            class_thr=class_thr,
        )
    else:
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
    final = apply_loom(
        raw, healthy_idx=healthy_idx, loom=loom, classes=classes, ttb=ttb, confidences=conf
    )
    return raw, final


def predict_fault_stream_two_tier(
    gate,
    full_clf,
    X,
    *,
    healthy_idx: int,
    gate_thr: float,
    class_thr: dict,
    loom: dict | None = None,
    apply: bool = True,
    classes: list[str] | None = None,
    ttb: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Frame scores then both loom tiers. Returns ``(raw, confirmed, advisory)``.

    ``X`` must be in chronological order when ``apply=True``.
    """
    from deca_school_exam_train import (
        predict_weighted_multiclass,
        predict_weighted_multiclass_with_confidence,
    )

    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    conf = None
    if cfg.get("soft_streak_enabled", False):
        raw, conf = predict_weighted_multiclass_with_confidence(
            gate,
            full_clf,
            X,
            healthy_idx=healthy_idx,
            gate_thr=gate_thr,
            class_thr=class_thr,
        )
    else:
        raw = predict_weighted_multiclass(
            gate,
            full_clf,
            X,
            healthy_idx=healthy_idx,
            gate_thr=gate_thr,
            class_thr=class_thr,
        )
    if not apply:
        return raw, raw, raw
    tiers = apply_two_tier_loom(
        raw, healthy_idx=healthy_idx, loom=loom, classes=classes, ttb=ttb, confidences=conf
    )
    return raw, tiers["confirmed"], tiers["advisory"]


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
        cfg.update(
            {
                k: loom[k]
                for k in (
                    "enabled",
                    "enter_k",
                    "exit_k",
                    "enter_k_by_class",
                    "exit_k_by_class",
                    "advisory_enabled",
                    "advisory_enter_k",
                    "advisory_exit_k",
                    "advisory_enter_k_by_class",
                    "ttb_gate_enabled",
                    "ttb_gate_tolerance",
                    "soft_streak_enabled",
                    "branch_agreement_enabled",
                    "branch_secondary_family",
                    "topology_gate_enabled",
                    "topology_min_neighbors",
                    "note",
                    "metrics",
                )
                if k in loom
            }
        )
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
    cfg.update(
        {
            k: loom[k]
            for k in loom
            if k
            in (
                "enabled",
                "enter_k",
                "exit_k",
                "enter_k_by_class",
                "exit_k_by_class",
                "advisory_enabled",
                "advisory_enter_k",
                "advisory_exit_k",
                "advisory_enter_k_by_class",
                "ttb_gate_enabled",
                "ttb_gate_tolerance",
                "soft_streak_enabled",
                "branch_agreement_enabled",
                "branch_secondary_family",
                "topology_gate_enabled",
                "topology_min_neighbors",
                "note",
                "metrics",
            )
        }
    )
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
                "enter_k_by_class": cfg.get("enter_k_by_class"),
                "exit_k_by_class": cfg.get("exit_k_by_class"),
                "advisory_enabled": cfg.get("advisory_enabled"),
                "advisory_enter_k": cfg.get("advisory_enter_k"),
                "advisory_exit_k": cfg.get("advisory_exit_k"),
                "ttb_gate_enabled": cfg.get("ttb_gate_enabled"),
                "ttb_gate_tolerance": cfg.get("ttb_gate_tolerance"),
                "soft_streak_enabled": cfg.get("soft_streak_enabled"),
                "branch_agreement_enabled": cfg.get("branch_agreement_enabled"),
                "branch_secondary_family": cfg.get("branch_secondary_family"),
                "topology_gate_enabled": cfg.get("topology_gate_enabled"),
                "topology_min_neighbors": cfg.get("topology_min_neighbors"),
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


# ── Topology graph — cross-node correlation gate (#6) ───────────────────────


def load_topology_graph(models_dir: Path | None = None) -> dict[str, Any]:
    """Load the lab topology graph (``models/topology/topology_graph.json``)."""
    import json

    from _paths import MODELS_DIR

    root = Path(models_dir) if models_dir else MODELS_DIR
    path = root / "topology" / "topology_graph.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def host_from_run_id(run_id: str) -> str | None:
    """``rpi_<campaign>_station1`` → ``station1``."""
    text = str(run_id)
    if "_station" not in text:
        return None
    return text.rsplit("_", 1)[-1]


def topology_neighbor_hosts(graph: dict[str, Any], host: str) -> list[str]:
    """Neighbor station hosts for a lab node (undirected over ``edges``)."""
    id_by_host = {n["host"]: n["id"] for n in graph.get("nodes", []) if "host" in n}
    host_by_id = {n["id"]: n["host"] for n in graph.get("nodes", []) if "host" in n}
    node_id = id_by_host.get(host)
    if not node_id:
        return []
    neighbors: set[str] = set()
    for edge in graph.get("edges", []):
        src, tgt = edge.get("source"), edge.get("target")
        if src == node_id:
            nh = host_by_id.get(tgt)
            if nh:
                neighbors.add(nh)
        if tgt == node_id:
            nh = host_by_id.get(src)
            if nh:
                neighbors.add(nh)
    return sorted(neighbors)


def build_topology_agreement_mask(
    timestamps,
    run_ids,
    preds: np.ndarray,
    *,
    healthy_idx: int,
    graph: dict[str, Any] | None = None,
    min_neighbors: int = 1,
) -> np.ndarray:
    """Per-row bool — do enough topology neighbors echo this fault at this timestamp?

    Healthy frames are always ``True`` (gate only binds fault entry). When the
    graph is missing or a host has no neighbors, defaults to open (``True``).
    """
    import pandas as pd

    preds = np.asarray(preds, dtype=int)
    n = len(preds)
    out = np.ones(n, dtype=bool)
    if graph is None or not graph.get("nodes"):
        return out

    frame = pd.DataFrame(
        {
            "ts": pd.DatetimeIndex(timestamps),
            "run_id": [str(r) for r in run_ids],
            "pred": preds,
            "idx": np.arange(n),
        }
    )
    need = max(1, int(min_neighbors))

    for _ts, grp in frame.groupby("ts"):
        host_pred: dict[str, int] = {}
        for _, row in grp.iterrows():
            host = host_from_run_id(row["run_id"])
            if host:
                host_pred[host] = int(row["pred"])

        for _, row in grp.iterrows():
            pred = int(row["pred"])
            if pred == healthy_idx:
                continue
            host = host_from_run_id(row["run_id"])
            if not host:
                continue
            neighbors = topology_neighbor_hosts(graph, host)
            if not neighbors:
                continue
            n_agree = sum(1 for nh in neighbors if host_pred.get(nh) == pred)
            out[int(row["idx"])] = n_agree >= need

    return out


def summarize_branch_agreement(
    primary: np.ndarray,
    secondary: np.ndarray,
    *,
    healthy_idx: int,
) -> dict[str, float | int]:
    """How often do the two classifier branches agree on fault frames?"""
    primary = np.asarray(primary, dtype=int)
    secondary = np.asarray(secondary, dtype=int)
    fault = primary != healthy_idx
    agree = fault & (primary == secondary)
    n_fault = int(np.sum(fault))
    return {
        "fault_frames": n_fault,
        "agree_frames": int(np.sum(agree)),
        "agree_rate": (float(np.sum(agree)) / n_fault) if n_fault else 0.0,
    }


def train_secondary_branch(
    X_train,
    y_train,
    X_val,
    y_val,
    *,
    healthy_idx: int,
    rare_ids: set[int],
    family: str = "wm",
    gate=None,
    boost: float = 1.0,
):
    """Fit a challenger head (default ``wm``) on chrono train, sharing the promoted gate."""
    from deca_school_exam_train import train_phase1

    return train_phase1(
        X_train,
        y_train,
        X_val,
        y_val,
        healthy_idx=healthy_idx,
        rare_ids=rare_ids,
        boost=boost,
        family=family,
        gate=gate,
    )


# ── "When" branch — LSTM time-to-breach, for the ttb_gate binding ───────────


def load_lstm_bundle(models_dir: Path | None = None) -> dict[str, Any] | None:
    """Load the trained LSTM time-to-breach companion, or ``None`` if unavailable.

    Missing tensorflow / missing artifacts both degrade to ``None`` — callers
    must treat that as "the 'when' branch has nothing to say", not an error.
    """
    import joblib

    from _paths import MODELS_DIR

    root = Path(models_dir) if models_dir else MODELS_DIR
    lstm_dir = root / "lstm"
    scaler_path = lstm_dir / "lstm_scaler.pkl"
    model_path = lstm_dir / "fault_lstm_v1.keras"
    if not scaler_path.exists() or not model_path.exists():
        return None
    try:
        from tensorflow import keras
    except ImportError:
        return None
    scaler = joblib.load(scaler_path)
    model = keras.models.load_model(model_path)
    return {
        "model": model,
        "feature_columns": list(scaler["feature_columns"]),
        "seq_len": int(scaler["seq_len"]),
        "mean": np.asarray(scaler["mean"]),
        "std": np.asarray(scaler["std"]),
    }


def predict_ttb_stream(X, bundle: dict[str, Any] | None = None) -> np.ndarray | None:
    """Per-row LSTM time-to-breach prediction on a **chronologically ordered** ``X``.

    Returns an array aligned 1:1 with ``X``'s rows; rows before ``seq_len - 1``
    frames of history are available get ``NaN`` (not enough context yet).
    Returns ``None`` if the LSTM companion isn't available.
    """
    b = bundle if bundle is not None else load_lstm_bundle()
    if b is None:
        return None
    cols = b["feature_columns"]
    missing = [c for c in cols if c not in getattr(X, "columns", [])]
    if missing:
        raise ValueError(f"LSTM ttb gate missing features: {missing[:5]}…")
    import pandas as pd

    seq_len = b["seq_len"]
    mean, std = b["mean"], np.where(b["std"] < 1e-9, 1.0, b["std"])
    # Same imputation as training (deca_retrain_companions.train_lstm): column
    # median, then 0.0 for columns that are entirely missing in this slice
    # (e.g. a telemetry gap — bgp_update_rate had no live counter for a stretch).
    sub = X[cols].apply(pd.to_numeric, errors="coerce")
    sub = sub.fillna(sub.median(numeric_only=True)).fillna(0.0)
    mat = sub.to_numpy(dtype=np.float64)
    n = len(mat)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < seq_len:
        return out
    seqs = np.stack([mat[i - seq_len + 1 : i + 1] for i in range(seq_len - 1, n)])
    seqs = (seqs - mean) / std
    preds = b["model"].predict(seqs, verbose=0).ravel()
    out[seq_len - 1 :] = preds
    return out


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
    classes: list[str] | None = None,
    enter_k_by_class: dict[str, int] | None = None,
    exit_k_by_class: dict[str, int] | None = None,
    ttb: np.ndarray | None = None,
    ttb_gate_tolerance: int = 0,
    confidences: np.ndarray | None = None,
    soft_streak: bool = False,
) -> np.ndarray:
    """Sticky loom; when existence agrees with the current fault streak, enter faster.

    If every frame in the current non-healthy run also has ``circ == run_label``,
    only ``prearm_enter_k`` consecutive votes are required (default 2) instead of
    the (possibly per-class) enter threshold. Still no duration feature. Pass
    ``classes`` + ``enter_k_by_class``/``exit_k_by_class`` for per-family patience —
    the pre-arm threshold is capped at each class's own base ``enter_k``. Pass
    ``ttb`` to additionally require a falling LSTM time-to-breach trend to commit
    entry — see ``_ttb_falling``. Pass ``confidences`` + ``soft_streak`` for a
    cumulative-confidence entry counter instead of hard frame counts.
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
    prearm_enter_k = max(1, int(prearm_enter_k))
    use_soft = bool(soft_streak and confidences is not None)
    conf = np.asarray(confidences, dtype=np.float64) if use_soft else None
    if use_soft and len(conf) != len(preds):
        raise ValueError("confidences and preds length mismatch")

    state = int(healthy_idx)
    run_label = int(preds[0])
    run_len = 0
    run_conf = 0.0
    agree_len = 0  # consecutive frames where circ matches run_label (fault only)

    for i, p in enumerate(preds):
        p = int(p)
        c = int(circ[i])
        frame_conf = float(conf[i]) if use_soft else 0.0
        if p == run_label:
            run_len += 1
            run_conf += frame_conf
            if p != healthy_idx and c == p:
                agree_len += 1
            else:
                agree_len = 0
        else:
            run_label = p
            run_len = 1
            run_conf = frame_conf
            agree_len = 1 if (p != healthy_idx and c == p) else 0

        if state == healthy_idx:
            base_need = _resolve_k(run_label, classes, enter_k_by_class, enter_k)
            # Full streak agrees with existence → pre-arm (faster declare)
            need = (
                min(prearm_enter_k, base_need)
                if (run_label != healthy_idx and agree_len >= run_len)
                else base_need
            )
            if (
                run_label != healthy_idx
                and _entry_ready(
                    soft_streak=use_soft, run_len=run_len, run_conf=run_conf, need=need
                )
                and _ttb_falling(ttb, i, run_len, tolerance=ttb_gate_tolerance)
            ):
                state = run_label
        else:
            if run_label == healthy_idx:
                exit_need = _resolve_k(state, classes, exit_k_by_class, exit_k)
                if run_len >= exit_need:
                    state = healthy_idx
            elif run_label != healthy_idx and run_label != state:
                base_need = _resolve_k(run_label, classes, enter_k_by_class, enter_k)
                need = min(prearm_enter_k, base_need) if agree_len >= run_len else base_need
                if (
                    _entry_ready(
                        soft_streak=use_soft, run_len=run_len, run_conf=run_conf, need=need
                    )
                    and _ttb_falling(ttb, i, run_len, tolerance=ttb_gate_tolerance)
                ):
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
    classes: list[str] | None = None,
    ttb: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Frame fault + optional existence + sticky loom (with pre-arm if ready).

    Pass ``classes`` (index→name) to activate per-class enter/exit hysteresis.
    Pass ``ttb`` (LSTM time-to-breach stream, e.g. from ``predict_ttb_stream``) to
    activate the "what"+"when" binding gate when ``loom.ttb_gate_enabled`` is true.
    Returns ``(raw_fault, final, circ_or_None)``.
    """
    from deca_school_exam_train import (
        predict_weighted_multiclass,
        predict_weighted_multiclass_with_confidence,
    )

    cfg = dict(DEFAULT_LOOM)
    if loom:
        cfg.update(loom)
    conf = None
    if cfg.get("soft_streak_enabled", False):
        raw, conf = predict_weighted_multiclass_with_confidence(
            gate,
            full_clf,
            X,
            healthy_idx=healthy_idx,
            gate_thr=gate_thr,
            class_thr=class_thr,
        )
    else:
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

    if not cfg.get("enabled", True):
        return raw, raw, circ

    enter_k = int(cfg.get("enter_k", DEFAULT_ENTER_K))
    exit_k = int(cfg.get("exit_k", DEFAULT_EXIT_K))
    prearm = int(cfg.get("prearm_enter_k", DEFAULT_PREARM_ENTER_K))
    enter_k_by_class = cfg.get("enter_k_by_class") or None
    exit_k_by_class = cfg.get("exit_k_by_class") or None
    ttb_arg = ttb if cfg.get("ttb_gate_enabled", False) else None
    ttb_gate_tolerance = int(cfg.get("ttb_gate_tolerance", 0))
    soft = bool(cfg.get("soft_streak_enabled", False))

    if circ is not None and cfg.get("circumstance_prearm", True):
        final = apply_persistence_with_prearm(
            raw,
            circ,
            healthy_idx=healthy_idx,
            enter_k=enter_k,
            exit_k=exit_k,
            prearm_enter_k=prearm,
            classes=classes,
            enter_k_by_class=enter_k_by_class,
            exit_k_by_class=exit_k_by_class,
            ttb=ttb_arg,
            ttb_gate_tolerance=ttb_gate_tolerance,
            confidences=conf,
            soft_streak=soft,
        )
    else:
        final = apply_persistence(
            raw,
            healthy_idx=healthy_idx,
            enter_k=enter_k,
            exit_k=exit_k,
            classes=classes,
            enter_k_by_class=enter_k_by_class,
            ttb=ttb_arg,
            ttb_gate_tolerance=ttb_gate_tolerance,
            confidences=conf,
            soft_streak=soft,
            exit_k_by_class=exit_k_by_class,
        )
    return raw, final, circ
