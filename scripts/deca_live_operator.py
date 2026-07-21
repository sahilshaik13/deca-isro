#!/usr/bin/env python3
"""DECA live operator — the model flying blind on the real network.

Polls Prometheus on a fixed cadence, rebuilds the *exact* multi-scale features
the classifier was trained on (via ``rebuild_unified`` — no parallel feature
code to drift), and runs the promoted stack per host every tick:

    gate  ->  weighted multiclass head  ->  soft-streak Temporal Loom
              (confirmed + advisory tiers)
    LSTM time-to-breach  ->  ETA (minutes)
    circumstance head    ->  "a circumstance exists" pre-arm
    live telemetry       ->  physical severity (low / medium / high)

It streams a colourised NOC feed to the terminal and appends every state
transition to ``declarations.jsonl``. It reads **only** Prometheus and the BGP
pulse file — never the sealed ground truth — so the test stays honest.

Stop it with Ctrl-C once the chaos run has finished, then run the scorecard.

Usage
-----
    python scripts/deca_live_operator.py --run-id blind_2359
    python scripts/deca_live_operator.py --run-id blind_2359 --start-at 23:00
    python scripts/deca_live_operator.py --run-id rehearsal --simulate
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from deca_live_common import (
    FAULT_HOST,
    append_jsonl,
    bgp_pulse_evidence,
    declarations_path,
    fetch_telemetry_long,
    live_run_dir,
    load_bgp_pulses,
    physical_severity,
    utcnow,
)

# ── ANSI colours for the NOC feed ─────────────────────────────────────────
RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

SEV_COLOR = {"low": GREEN, "medium": YELLOW, "high": RED}


@dataclass
class ModelSuite:
    gate: Any
    full_clf: Any
    classes: list[str]
    healthy_idx: int
    gate_thr: float
    class_thr: dict[int, float]
    loom: dict[str, Any]
    features: list[str]
    lstm_bundle: Any
    circ_bundle: Any
    seq_len: int
    ensemble_head: Any = None  # optional wm companion for plain+wm agreement (#5)


def load_suite(*, ensemble: bool = False) -> ModelSuite:
    import joblib

    from _paths import MODELS_DIR
    from deca_inference import load_circumstance_bundle, load_lstm_bundle

    clf_dir = MODELS_DIR / "fault_classifier"
    bundle = joblib.load(clf_dir / "fault_classifier_xgb.pkl")
    le = joblib.load(clf_dir / "label_encoder.pkl")
    classes = list(le["classes"])
    gate = bundle["gate"]
    features = list(getattr(gate, "feature_names_in_", []))
    if not features:
        # Fall back to any step that recorded names.
        for step in getattr(gate, "named_steps", {}).values():
            fn = getattr(step, "feature_names_in_", None)
            if fn is not None:
                features = list(fn)
                break
    lstm_bundle = load_lstm_bundle()
    circ_bundle = load_circumstance_bundle()
    seq_len = int(lstm_bundle["seq_len"]) if lstm_bundle else 0

    ensemble_head = None
    if ensemble:
        wm_path = clf_dir / "fault_classifier_wm.pkl"
        if not wm_path.exists():
            raise FileNotFoundError(
                f"--ensemble needs the wm companion head at {wm_path}. "
                "Train it first: python scripts/deca_blind_ensemble_head.py"
            )
        wm = joblib.load(wm_path)
        if list(wm.get("classes", [])) != classes:
            raise ValueError(
                "wm head class ordering differs from the promoted head; "
                "retrain it with deca_blind_ensemble_head.py against the current label encoder."
            )
        ensemble_head = wm["full_clf"]

    return ModelSuite(
        gate=gate,
        full_clf=bundle["full_clf"],
        classes=classes,
        healthy_idx=int(bundle["healthy_idx"]),
        gate_thr=float(bundle["gate_thr"]),
        class_thr={int(k): float(v) for k, v in bundle.get("class_thr", {}).items()},
        loom=dict(bundle.get("loom", {})),
        features=features,
        lstm_bundle=lstm_bundle,
        circ_bundle=circ_bundle,
        seq_len=seq_len,
        ensemble_head=ensemble_head,
    )


# ── Feature build (reuse the training pipeline exactly) ───────────────────
def build_host_features(raw_long, bgp_long):
    """Long-form raw telemetry -> per-host wide feature frames (training-identical)."""
    import pandas as pd

    from deca_live_common import densify_bgp_pulses
    from rebuild_unified import _clean_telemetry, engineer_features

    if len(raw_long) == 0 and len(bgp_long) == 0:
        return {}
    # Always densify onto the Prom grid — including the calm path with zero pulses.
    # Empty bgp_long used to skip densify → missing BGP columns → NaN after reindex
    # → soft-streak invents bgp_route_flap on healthy control hours.
    bgp_dense = densify_bgp_pulses(bgp_long, raw_long)
    merged = pd.concat([raw_long, bgp_dense], ignore_index=True) if len(bgp_dense) else raw_long
    cleaned = _clean_telemetry(merged, campaign_id="live")
    if cleaned.empty:
        return {}
    feats = engineer_features(cleaned)
    if feats.empty:
        return {}
    out = {}
    for run_id, group in feats.groupby("run_id"):
        host = str(run_id).replace("rpi_live_", "")
        # Belt: any residual BGP NaNs are "no flap", not missingness.
        bgp_cols = [c for c in group.columns if "bgp_update_rate" in c]
        if bgp_cols:
            group = group.copy()
            group[bgp_cols] = group[bgp_cols].fillna(0.0)
        out[host] = group.sort_index()
    return out


@dataclass
class HostState:
    confirmed: str = "healthy"
    advisory: str = "healthy"
    first_seen_fault_ts: dict[str, str] = field(default_factory=dict)
    # Cross-host echo bookkeeping (station1 origin of shared-link classes).
    last_nonhealthy_confirmed: str | None = None
    last_confirmed_clear_at: datetime | None = None


# Shared-link classes originate on PE1 (station1). Station2 is the iperf3 receiver
# for that traffic, so the same fault echoes into station2's received-path
# telemetry. Blind nights 0848 + 2219: all 9 "spurious" station2 confirms were
# same-class echoes of a real station1 fault (during or ~2–3.5 min after; two
# led station1's confirm by ~15–90 s). Origin-lock kills all nine; a confirm-
# window-only rule misses the leading-echo pair.
SHARED_LINK_ECHO_CLASSES = frozenset({"congestion_breach", "tunnel_degradation"})
ECHO_ORIGIN_HOST = "station1"
ECHO_PEER_HOST = "station2"
CROSS_HOST_ECHO_GRACE = timedelta(minutes=5)

# vrf_leakage is injected on PE2 (station2) only — mirror of the shared-link echo lock.
VRF_ORIGIN_CLASS = "vrf_leakage"
VRF_ORIGIN_HOST = FAULT_HOST[VRF_ORIGIN_CLASS]


def should_suppress_vrf_origin_lock(host: str, confirmed_class: str) -> bool:
    """Only station2 may *confirm* vrf_leakage (PE2-origin fault)."""
    if confirmed_class == "healthy" or confirmed_class != VRF_ORIGIN_CLASS:
        return False
    return host != VRF_ORIGIN_HOST


def should_suppress_cross_host_echo(
    host: str,
    confirmed_class: str,
    states: dict[str, HostState],
    *,
    now: datetime,
    grace: timedelta = CROSS_HOST_ECHO_GRACE,
    origin_lock: bool = True,
) -> bool:
    """Suppress station2 confirms of PE1 shared-link classes (cross-host echo).

    Default ``origin_lock=True``: station2 never *confirms* congestion/tunnel
    (advisory may still name them). Lab injections attribute those classes to
    station1 only; station2's job on that path is receiver echo.

    When ``origin_lock=False``, fall back to the narrower rule: suppress only
    while station1 has an active or recently-cleared confirm of the same class.
    """
    if host != ECHO_PEER_HOST:
        return False
    if confirmed_class == "healthy" or confirmed_class not in SHARED_LINK_ECHO_CLASSES:
        return False
    if origin_lock:
        return True
    origin = states.get(ECHO_ORIGIN_HOST)
    if origin is None:
        return False
    if origin.confirmed == confirmed_class:
        return True
    if (
        origin.last_nonhealthy_confirmed == confirmed_class
        and origin.last_confirmed_clear_at is not None
        and now - origin.last_confirmed_clear_at <= grace
    ):
        return True
    return False


def infer_host(
    suite: ModelSuite,
    group,
    *,
    bgp_evidence: bool | None = None,
    host: str | None = None,
    states: dict[str, HostState] | None = None,
    now: datetime | None = None,
    cross_host_echo_suppress: bool = True,
    cross_host_echo_origin_lock: bool = True,
    vrf_origin_lock: bool = True,
):
    """Run the full stack on one host's chronological feature frame; return tail state.

    ``bgp_evidence``: when False, refuse to *confirm* ``bgp_route_flap`` (no stamped
    pulse in the lookback). Advisory may still name BGP; confirmed requires lab
    telemetry that a flap actually occurred. ``None`` skips the gate (tests).

    Cross-host echo gate: see ``should_suppress_cross_host_echo``.
    VRF origin gate: only station2 may confirm ``vrf_leakage``.
    """
    from deca_inference import apply_two_tier_loom, predict_fault_stream_with_circumstance, predict_ttb_stream
    from deca_school_exam_train import predict_weighted_multiclass_with_confidence

    X = group.reindex(columns=suite.features)
    if len(X) == 0:
        return None
    bgp_feat_cols = [c for c in X.columns if "bgp_update_rate" in c]
    if bgp_feat_cols:
        X = X.copy()
        X[bgp_feat_cols] = X[bgp_feat_cols].fillna(0.0)

    raw, confirmed, circ = predict_fault_stream_with_circumstance(
        suite.gate,
        suite.full_clf,
        X,
        healthy_idx=suite.healthy_idx,
        gate_thr=suite.gate_thr,
        class_thr=suite.class_thr,
        loom=suite.loom,
        circumstance_bundle=suite.circ_bundle,
        classes=suite.classes,
    )
    _, conf = predict_weighted_multiclass_with_confidence(
        suite.gate, suite.full_clf, X,
        healthy_idx=suite.healthy_idx, gate_thr=suite.gate_thr, class_thr=suite.class_thr,
    )
    tiers = apply_two_tier_loom(
        raw, healthy_idx=suite.healthy_idx, loom=suite.loom, classes=suite.classes, confidences=conf,
    )
    advisory = tiers["advisory"]

    confirmed_class = suite.classes[int(confirmed[-1])]

    # Ensemble agreement gate (#5): require the independent wm head to also name
    # the plain head's confirmed class at this frame before allowing a confirmed
    # declaration. Disagreement holds the tier at advisory (suppresses a possibly
    # spurious confirm) — the hypothesis being tested under blind conditions.
    ensemble_wm_class = None
    ensemble_agree = None
    if suite.ensemble_head is not None:
        wm_preds, _ = predict_weighted_multiclass_with_confidence(
            suite.gate, suite.ensemble_head, X,
            healthy_idx=suite.healthy_idx, gate_thr=suite.gate_thr, class_thr=suite.class_thr,
        )
        ensemble_wm_class = suite.classes[int(wm_preds[-1])]
        if confirmed_class != "healthy":
            ensemble_agree = ensemble_wm_class == confirmed_class
            if not ensemble_agree:
                confirmed_class = "healthy"  # heads disagree — do not confirm

    # BGP evidence gate: no stamped pulse ⇒ never confirm bgp_route_flap.
    # Control cry-wolf was 18/21 BGP with an empty pulse file; densify-to-zero
    # removes NaN invention, and this gate is the hard second line.
    bgp_evidence_blocked = False
    if (
        bgp_evidence is False
        and confirmed_class == "bgp_route_flap"
    ):
        confirmed_class = "healthy"
        bgp_evidence_blocked = True

    # Cross-host echo gate: station2 receiver echo of PE1 shared-link faults.
    cross_host_echo_suppressed = False
    cross_host_echo_class = None
    if cross_host_echo_suppress and host is not None:
        if should_suppress_cross_host_echo(
            host,
            confirmed_class,
            states or {},
            now=now or utcnow(),
            origin_lock=cross_host_echo_origin_lock,
        ):
            cross_host_echo_class = confirmed_class
            confirmed_class = "healthy"
            cross_host_echo_suppressed = True

    # VRF origin gate: vrf_leakage is PE2-only; station1 must not confirm it.
    vrf_origin_suppressed = False
    vrf_origin_class = None
    if vrf_origin_lock and host is not None:
        if should_suppress_vrf_origin_lock(host, confirmed_class):
            vrf_origin_class = confirmed_class
            confirmed_class = "healthy"
            vrf_origin_suppressed = True

    ttb = None
    if suite.lstm_bundle is not None:
        try:
            ttb = predict_ttb_stream(X, suite.lstm_bundle)
        except Exception:
            ttb = None

    eta = None
    if ttb is not None:
        tail = float(ttb[-1])
        eta = None if np.isnan(tail) else round(tail, 1)

    return {
        "confirmed": confirmed_class,
        "advisory": suite.classes[int(advisory[-1])],
        "confidence": round(float(conf[-1]), 3),
        "eta_minutes": eta,
        "circumstance": bool(circ[-1]) if circ is not None else None,
        "frames": int(len(X)),
        "ensemble_wm_class": ensemble_wm_class,
        "ensemble_agree": ensemble_agree,
        "bgp_evidence": bgp_evidence,
        "bgp_evidence_blocked": bgp_evidence_blocked,
        "cross_host_echo_suppressed": cross_host_echo_suppressed,
        "cross_host_echo_class": cross_host_echo_class,
        "vrf_origin_suppressed": vrf_origin_suppressed,
        "vrf_origin_class": vrf_origin_class,
    }


def declare(run_id: str, host: str, tail: dict, severity, *, event: str) -> None:
    append_jsonl(
        declarations_path(run_id),
        {
            "ts": utcnow().isoformat(),
            "host": host,
            "event": event,
            "confirmed": tail["confirmed"],
            "advisory": tail["advisory"],
            "confidence": tail["confidence"],
            "eta_minutes": tail["eta_minutes"],
            "circumstance": tail["circumstance"],
            "severity_bucket": severity.bucket if severity else None,
            "severity_score": severity.score if severity else None,
            "ensemble_wm_class": tail.get("ensemble_wm_class"),
            "ensemble_agree": tail.get("ensemble_agree"),
            "cross_host_echo_suppressed": tail.get("cross_host_echo_suppressed"),
            "cross_host_echo_class": tail.get("cross_host_echo_class"),
            "vrf_origin_suppressed": tail.get("vrf_origin_suppressed"),
            "vrf_origin_class": tail.get("vrf_origin_class"),
        },
    )


def feed_line(host: str, tail: dict, severity) -> str:
    conf_c = tail["confirmed"]
    adv_c = tail["advisory"]
    eta = tail["eta_minutes"]
    eta_s = f"{eta:>5.1f}m" if eta is not None else "  -- "
    sev = severity.bucket if severity else "--"
    sev_c = SEV_COLOR.get(sev, DIM)
    if conf_c != "healthy":
        head = f"{RED}{BOLD}CONFIRMED {conf_c:<18}{RESET}"
    elif adv_c != "healthy":
        head = f"{YELLOW}ADVISORY  {adv_c:<18}{RESET}"
    else:
        head = f"{GREEN}healthy{RESET}{'':<21}"
    circ = "circ" if tail["circumstance"] else "    "
    ens = ""
    if tail.get("ensemble_agree") is False:
        ens = f" {YELLOW}[wm≠:{tail.get('ensemble_wm_class')} → held]{RESET}"
    elif tail.get("ensemble_agree") is True:
        ens = f" {DIM}[wm✓]{RESET}"
    echo = ""
    if tail.get("cross_host_echo_suppressed"):
        echo = (
            f" {DIM}[echo↓:{tail.get('cross_host_echo_class')} → held]{RESET}"
        )
    vrf_hold = ""
    if tail.get("vrf_origin_suppressed"):
        vrf_hold = f" {DIM}[vrf↓:{tail.get('vrf_origin_class')} → held]{RESET}"
    return (
        f"  {CYAN}{host:<9}{RESET} {head} "
        f"conf={tail['confidence']:<5.2f} ETA={eta_s} "
        f"sev={sev_c}{sev:<6}{RESET} {DIM}{circ} f={tail['frames']}{RESET}{ens}{echo}{vrf_hold}"
    )


# ── Simulation source (rehearse without hardware) ─────────────────────────
def build_sim_timeline():
    """~50 min of station1 telemetry: healthy, then a congestion breach ramp+hold."""
    import pandas as pd

    total_min = 50
    t0 = utcnow() - timedelta(minutes=total_min)
    rows = []
    n = int(total_min * 60 / 15)
    for k in range(n):
        ts = t0 + timedelta(seconds=15 * k)
        minute = 15 * k / 60.0
        if minute < 18:
            tput, loss, jit = 90e6, 0.0, 2.0
        else:
            frac = min((minute - 18) / 8.0, 1.0)  # ramp over 8 min, then hold
            tput = (90 - 82 * frac) * 1e6
            loss = 10.0 * frac
            jit = 2.0 + 33.0 * frac
        noise = np.random.default_rng(k).normal
        for metric, val in (
            ("throughput_in_bps", max(tput + noise(0, 1e6), 1e5)),
            ("throughput_out_bps", max(tput * 0.9 + noise(0, 1e6), 1e5)),
            ("packet_loss_pct", max(loss + noise(0, 0.2), 0.0)),
            ("jitter_ms", max(jit + noise(0, 0.5), 0.0)),
            ("latency_ms", max(jit + 5 + noise(0, 0.5), 0.0)),
            ("drop_out_rate", max(loss * 0.1 + noise(0, 0.05), 0.0)),
        ):
            rows.append({"timestamp": ts, "host": "station1", "metric": metric, "value": float(val)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="DECA live blind-test operator")
    parser.add_argument("--run-id", required=True, help="Live run id (matches the chaos run)")
    parser.add_argument("--interval", type=float, default=15.0, help="Poll cadence seconds")
    parser.add_argument("--lookback-min", type=float, default=25.0, help="Feature window minutes")
    parser.add_argument("--start-at", default=None, metavar="HH:MM", help="Begin polling at local time")
    parser.add_argument("--simulate", action="store_true", help="Synthetic telemetry, no Prometheus")
    parser.add_argument("--sim-ticks", type=int, default=40, help="Simulation ticks before exit")
    parser.add_argument(
        "--hosts",
        default="station1,station2",
        help="Comma-separated hosts to infer/declare on, or 'all'. CORE (station3) "
        "carries no CE ping / BGP telemetry and is never a fault target, so it is "
        "excluded by default to avoid meaningless alarms.",
    )
    parser.add_argument(
        "--ensemble",
        action="store_true",
        help="Run the plain+wm ensemble: require both heads to agree on the class "
        "before a confirmed declaration (#5). Needs fault_classifier_wm.pkl "
        "(train via deca_blind_ensemble_head.py).",
    )
    parser.add_argument(
        "--no-cross-host-echo-suppress",
        action="store_true",
        help="Disable station2 shared-link echo suppression (congestion/tunnel).",
    )
    parser.add_argument(
        "--cross-host-echo-confirm-window",
        action="store_true",
        help="Use confirm-window rule only (active/recent station1 confirm) "
        "instead of the default station2 origin-lock for shared-link classes. "
        "Origin-lock also catches leading echoes where station2 confirms first.",
    )
    parser.add_argument(
        "--no-vrf-origin-lock",
        action="store_true",
        help="Disable vrf_leakage origin-lock (only station2 may confirm VRF).",
    )
    args = parser.parse_args()

    allowed_hosts = None if args.hosts.strip().lower() == "all" else {
        h.strip() for h in args.hosts.split(",") if h.strip()
    }

    # Line-buffer stdout so a detached `tail -f` on the feed log stays live
    # (Python block-buffers stdout when it is redirected to a file).
    try:
        import sys

        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print(f"{BOLD}Loading DECA model stack...{RESET}")
    suite = load_suite(ensemble=args.ensemble)
    live_run_dir(args.run_id)
    print(f"  classes={suite.classes}")
    print(f"  ensemble (plain+wm agreement): {'ON' if suite.ensemble_head is not None else 'off'}")
    print(f"  loom: soft_streak={suite.loom.get('soft_streak_enabled')} enter_k={suite.loom.get('enter_k')} "
          f"advisory_enter_k={suite.loom.get('advisory_enter_k')}")
    print(f"  LSTM ETA: {'ready' if suite.lstm_bundle else 'UNAVAILABLE'} | "
          f"circumstance head: {'ready' if suite.circ_bundle else 'UNAVAILABLE'}")
    print(f"  scoped hosts: {'all' if allowed_hosts is None else sorted(allowed_hosts)}")
    echo_on = not args.no_cross_host_echo_suppress
    echo_mode = (
        "off"
        if not echo_on
        else ("confirm-window" if args.cross_host_echo_confirm_window else "origin-lock")
    )
    vrf_lock_on = not args.no_vrf_origin_lock
    print(f"  cross-host echo suppress: {echo_mode}")
    print(f"  vrf origin-lock: {'on' if vrf_lock_on else 'off'}")
    print(f"  declarations -> {declarations_path(args.run_id)}")

    if args.start_at and not args.simulate:
        th, tm = (int(x) for x in args.start_at.split(":"))
        while not (datetime.now().hour == th and datetime.now().minute == tm):
            time.sleep(20)

    states: dict[str, HostState] = {}
    sim_timeline = build_sim_timeline() if args.simulate else None
    sim_start = utcnow() if args.simulate else None

    print(f"\n{BOLD}=== DECA LIVE OPERATOR watching {args.run_id} "
          f"({'SIMULATE' if args.simulate else 'PROMETHEUS :9090'}) ==={RESET}\n")

    tick = 0
    try:
        while True:
            tick += 1
            if args.simulate:
                # Advance a virtual clock so the tail frame traverses the ramp:
                # start with ~14 min of history, then step 15 s per tick.
                virt_now = sim_timeline["timestamp"].min() + timedelta(
                    minutes=14, seconds=15 * tick
                )
                start = virt_now - timedelta(minutes=args.lookback_min)
                raw_long = sim_timeline[
                    (sim_timeline["timestamp"] >= start) & (sim_timeline["timestamp"] <= virt_now)
                ].copy()
                import pandas as pd

                bgp_long = pd.DataFrame(columns=["timestamp", "host", "metric", "value"])
            else:
                end = utcnow()
                start = end - timedelta(minutes=args.lookback_min)
                raw_long = fetch_telemetry_long(start, end)
                bgp_long = load_bgp_pulses(args.run_id, start, end)

            host_frames = build_host_features(raw_long, bgp_long)
            evidence_by_host = bgp_pulse_evidence(bgp_long)
            stamp = (start if args.simulate else utcnow()).strftime("%H:%M:%S")
            if not host_frames:
                print(f"{DIM}[{stamp}] tick {tick}: warming up / no telemetry yet...{RESET}")
            else:
                print(f"{DIM}[{stamp}] tick {tick}{RESET}")
                # station1 before station2 so confirm-window mode sees origin state.
                for host in sorted(host_frames):
                    if allowed_hosts is not None and host not in allowed_hosts:
                        continue
                    # Missing host in pulse map ⇒ no pulses stamped ⇒ no BGP confirm.
                    has_bgp = bool(evidence_by_host.get(host, False))
                    tick_now = virt_now if args.simulate else end
                    tail = infer_host(
                        suite,
                        host_frames[host],
                        bgp_evidence=has_bgp,
                        host=host,
                        states=states,
                        now=tick_now,
                        cross_host_echo_suppress=echo_on,
                        cross_host_echo_origin_lock=not args.cross_host_echo_confirm_window,
                        vrf_origin_lock=vrf_lock_on,
                    )
                    if tail is None:
                        continue
                    # Per-host physical severity from the raw window.
                    host_raw = raw_long[raw_long["host"] == host] if len(raw_long) else raw_long
                    sev = physical_severity(host_raw)
                    print(feed_line(host, tail, sev))

                    st = states.setdefault(host, HostState())
                    changed = tail["confirmed"] != st.confirmed or tail["advisory"] != st.advisory
                    if changed:
                        if tail["confirmed"] != "healthy" and st.confirmed == "healthy":
                            event = "confirmed_raise"
                        elif tail["confirmed"] == "healthy" and st.confirmed != "healthy":
                            event = "confirmed_clear"
                        elif tail["advisory"] != "healthy" and st.advisory == "healthy":
                            event = "advisory_raise"
                        elif tail["advisory"] == "healthy" and st.advisory != "healthy":
                            event = "advisory_clear"
                        else:
                            event = "change"
                        declare(args.run_id, host, tail, sev, event=event)
                        prev_conf = st.confirmed
                        if prev_conf != "healthy" and tail["confirmed"] == "healthy":
                            st.last_nonhealthy_confirmed = prev_conf
                            st.last_confirmed_clear_at = tick_now
                        elif tail["confirmed"] != "healthy":
                            st.last_nonhealthy_confirmed = tail["confirmed"]
                        st.confirmed = tail["confirmed"]
                        st.advisory = tail["advisory"]

            if args.simulate:
                if tick >= args.sim_ticks:
                    print(f"\n{BOLD}Simulation complete after {tick} ticks.{RESET}")
                    break
                time.sleep(0.05)
            else:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n{BOLD}Operator stopped by user. Declarations saved to "
              f"{declarations_path(args.run_id)}{RESET}")


def _selfcheck_cross_host_echo() -> None:
    """Pure-function checks for the station2 echo gate (no models / Prom)."""
    now = datetime(2026, 7, 18, 17, 22, 5, tzinfo=timezone.utc)
    empty: dict[str, HostState] = {}

    # Origin-lock: any station2 shared-link confirm is suppressed.
    assert should_suppress_cross_host_echo(
        "station2", "tunnel_degradation", empty, now=now, origin_lock=True
    )
    assert not should_suppress_cross_host_echo(
        "station1", "tunnel_degradation", empty, now=now, origin_lock=True
    )
    assert not should_suppress_cross_host_echo(
        "station2", "vrf_leakage", empty, now=now, origin_lock=True
    )

    # Confirm-window: active origin same class.
    states = {
        "station1": HostState(confirmed="congestion_breach", last_nonhealthy_confirmed="congestion_breach"),
    }
    assert should_suppress_cross_host_echo(
        "station2", "congestion_breach", states, now=now, origin_lock=False
    )
    assert not should_suppress_cross_host_echo(
        "station2", "tunnel_degradation", states, now=now, origin_lock=False
    )

    # Confirm-window: recently cleared (within grace).
    states = {
        "station1": HostState(
            confirmed="healthy",
            last_nonhealthy_confirmed="tunnel_degradation",
            last_confirmed_clear_at=now - timedelta(minutes=3),
        ),
    }
    assert should_suppress_cross_host_echo(
        "station2", "tunnel_degradation", states, now=now, origin_lock=False
    )
    # Outside grace — do not suppress (leading-echo case needs origin-lock).
    states["station1"].last_confirmed_clear_at = now - timedelta(minutes=10)
    assert not should_suppress_cross_host_echo(
        "station2", "tunnel_degradation", states, now=now, origin_lock=False
    )
    print("cross_host_echo selfcheck OK")


def _selfcheck_vrf_origin() -> None:
    assert should_suppress_vrf_origin_lock("station1", "vrf_leakage")
    assert not should_suppress_vrf_origin_lock("station2", "vrf_leakage")
    assert not should_suppress_vrf_origin_lock("station1", "tunnel_degradation")
    print("vrf_origin selfcheck OK")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck-echo":
        _selfcheck_cross_host_echo()
    elif len(sys.argv) > 1 and sys.argv[1] == "--selfcheck-gates":
        _selfcheck_cross_host_echo()
        _selfcheck_vrf_origin()
    else:
        main()
