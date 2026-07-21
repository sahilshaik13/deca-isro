#!/usr/bin/env python3
"""DECA blind chaos scheduler — the adversary for the live network test.

Randomly stresses the CE-PE-CE lab so the models have to predict what is coming
with **no schedule to lean on**. Every real circumstance and every benign
near-miss is written to a *sealed* ground-truth log that the live operator never
reads. Only after the run does ``deca_blind_scorecard.py`` open the seal and
compare what the network actually did against what the models declared.

Design
------
- Reuses the *proven* injectors in ``deca_fault_campaign.py`` verbatim (same
  ``tc`` / ``vtysh`` commands, same internal severity randomisation) so live
  fault dynamics match the training campaigns.
- Chooses fault types, count, ordering and rest gaps at random from a seed that
  is sealed for audit but unknown to the operator at runtime.
- Sprinkles benign near-misses (short aborted onsets) to bait false alarms.
- BGP flaps stamp real ``bgp_update_rate`` telemetry into the run dir (a signal,
  not a label) so the operator can see BGP churn the lab Prometheus can't scrape.
- Always leaves the lab clean: SIGINT/SIGTERM and a hard time budget both route
  through ``clear_all_faults()``.

Blindness is a discipline, not a lock: the operator is pointed only at
Prometheus and the bgp-pulse file, never at ``ground_truth.sealed.jsonl``.

Usage
-----
    python scripts/deca_blind_chaos.py --run-id blind_2359 --minutes 90
    python scripts/deca_blind_chaos.py --start-at 23:00 --minutes 90 --seed 7
    python scripts/deca_blind_chaos.py --simulate            # no hardware, fast
"""
from __future__ import annotations

import argparse
import atexit
import json
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import deca_fault_campaign as campaign
from deca_live_common import (
    FAULT_HOST,
    append_jsonl,
    ground_truth_path,
    live_run_dir,
    run_meta_path,
)

FAULT_TYPES = ["congestion_breach", "tunnel_degradation", "bgp_route_flap", "vrf_leakage"]

# Faults that act on PE1 (station1). vrf_leakage acts on PE2 (station2) and is
# the natural overlapping partner: a compound event fires one PE1 fault and the
# PE2 leak concurrently — different hosts, so no ``tc qdisc`` collision, and the
# scorecard (which clips detection windows per host) grades each leg cleanly.
PE1_FAULTS = ["congestion_breach", "tunnel_degradation", "bgp_route_flap"]
PE2_FAULT = "vrf_leakage"


def now() -> datetime:
    return datetime.now(timezone.utc)


def run_compound(
    run_id: str,
    group_idx: int,
    budget_left,
    *,
    pe1_fault: str | None = None,
) -> int:
    """Fire a PE1 fault and the PE2 vrf leak concurrently — a real cascade.

    Each leg is a full injector run in its own thread; both are sealed as real
    events sharing a ``compound_group`` id. Faults are cleared only after both
    threads join. Returns the number of legs successfully sealed.
    """
    primary = pe1_fault if pe1_fault else random.choice(PE1_FAULTS)
    if primary not in PE1_FAULTS:
        raise ValueError(f"compound PE1 fault must be one of {PE1_FAULTS}, got {primary!r}")
    legs = [primary, PE2_FAULT]
    group = f"{run_id}_cg{group_idx:02d}"
    campaign.log(f"[chaos] === COMPOUND {group}: {primary} (station1) + {PE2_FAULT} "
                 f"(station2) OVERLAPPING, {budget_left():.0f} min budget left ===")

    results: dict[str, tuple] = {}
    errors: dict[str, Exception] = {}

    def worker(fault_type: str) -> None:
        try:
            results[fault_type] = campaign.INJECTORS[fault_type](f"{group}_{fault_type}")
        except Exception as exc:  # noqa: BLE001 — record, keep sibling leg alive
            errors[fault_type] = exc

    threads = [threading.Thread(target=worker, args=(ft,), name=ft) for ft in legs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    sealed = 0
    for i, ft in enumerate(legs, start=1):
        if ft in errors:
            campaign.log(f"[chaos] COMPOUND leg {ft} ERROR: {errors[ft]}")
            continue
        fs, bt = results[ft]
        ev_id = f"{group}_e{i:02d}_{ft}"
        seal_event(run_id, event_id=ev_id, fault_type=ft, fault_start=fs,
                   breach_time=bt, is_near_miss=False, compound_group=group)
        campaign.log(f"[chaos] sealed {ev_id} (compound {group}): "
                     f"{fs.isoformat()} -> {bt.isoformat()}")
        sealed += 1
    campaign.clear_all_faults()
    return sealed


def seal_event(run_id: str, *, event_id: str, fault_type: str, fault_start: datetime,
               breach_time: datetime, is_near_miss: bool,
               compound_group: str | None = None) -> None:
    """Append one sealed ground-truth record and mirror it to the campaign CSV.

    ``compound_group`` links the two legs of an overlapping (compound) event so
    the scorecard can report them as a cascade rather than two isolated faults.
    """
    host = FAULT_HOST.get(fault_type, "station1")
    record = {
        "event_id": event_id,
        "fault_type": fault_type,
        "host": host,
        "fault_start": fault_start.isoformat(),
        "breach_time": breach_time.isoformat(),
        "is_near_miss": is_near_miss,
    }
    if compound_group is not None:
        record["compound_group"] = compound_group
    append_jsonl(ground_truth_path(run_id), record)
    # Mirror into fault_injection_log.csv so this run stays rebuild-compatible.
    log_type = "precursor_aborted" if is_near_miss else fault_type
    campaign.append_log_row(log_type, f"real_{event_id}", fault_start, breach_time)


def wait_until(hhmm: str) -> None:
    """Block until the next local occurrence of HH:MM."""
    target_h, target_m = (int(x) for x in hhmm.split(":"))
    while True:
        local = datetime.now()
        if local.hour == target_h and local.minute == target_m:
            return
        remaining = ((target_h * 60 + target_m) - (local.hour * 60 + local.minute)) % (24 * 60)
        campaign.log(f"Holding for {remaining} min until {hhmm} local to arm the blind run...")
        time.sleep(min(remaining, 5) * 60 if remaining else 30)


def install_time_scale(scale: float) -> None:
    """Compress injector waits (SIMULATE / rehearsal only). Real runs keep 1.0."""
    if scale == 1.0:
        return
    real_sleep = time.sleep

    def scaled(seconds):
        real_sleep(max(seconds * scale, 0.0))

    campaign.time.sleep = scaled  # injectors call campaign.time.sleep


def install_dry_ssh() -> None:
    """Replace SSH with a no-op so the harness can be rehearsed without hardware."""
    def fake_ssh(target, command, *, quiet=False, timeout=20):
        return True

    campaign.run_ssh = fake_ssh
    campaign.generate_dynamic_traffic = lambda: campaign.log("[simulate] baseline traffic (skipped)")


def exam_phases_path(run_id: str) -> Path:
    return live_run_dir(run_id) / "exam_phases.jsonl"


def stamp_phase(
    run_id: str,
    *,
    phase_id: str,
    kind: str,
    status: str,
    **extra,
) -> None:
    """Append a phase boundary for the deterministic exam report."""
    rec = {
        "ts": now().isoformat(),
        "phase_id": phase_id,
        "kind": kind,
        "status": status,  # start | end
        **extra,
    }
    append_jsonl(exam_phases_path(run_id), rec)


def run_playlist(run_id: str, playlist_path: Path, budget_left, time_scale: float) -> None:
    """Deterministic specificity exam — fixed calm / near-miss playlist, no RNG schedule.

    Walks human-authored phases from ``playlist_path``. Stamps ``exam_phases.jsonl``
    boundaries so ``deca_blind_exam_report.py`` can grade per-phase. v1 supports
    ``kind: calm|near_miss`` only (no real faults).
    """
    spec = json.loads(playlist_path.read_text(encoding="utf-8"))
    phases = spec.get("phases") or []
    if not phases:
        raise SystemExit(f"Playlist empty: {playlist_path}")

    nm_done = 0
    campaign.log(f"[playlist] loaded {playlist_path} id={spec.get('id')} phases={len(phases)}")

    for phase in phases:
        if campaign._shutdown_requested or budget_left() <= 0:
            break
        phase_id = str(phase.get("id") or f"phase_{nm_done}")
        kind = str(phase.get("kind") or "").strip()
        if kind == "calm":
            minutes = float(phase.get("minutes") or 0)
            minutes = min(minutes, max(budget_left(), 0))
            stamp_phase(
                run_id,
                phase_id=phase_id,
                kind=kind,
                status="start",
                minutes=minutes,
                score_spurious=bool(phase.get("score_spurious", True)),
                note=phase.get("note"),
            )
            campaign.log(f"[playlist] {phase_id}: calm {minutes:.1f} min "
                         f"(score_spurious={phase.get('score_spurious', True)})")
            time.sleep(max(minutes, 0) * 60 * time_scale)
            stamp_phase(
                run_id,
                phase_id=phase_id,
                kind=kind,
                status="end",
                score_spurious=bool(phase.get("score_spurious", True)),
            )
        elif kind == "near_miss":
            hold_s = float(phase.get("hold_s") if phase.get("hold_s") is not None else 30)
            nm_done += 1
            nm_id = f"{run_id}_{phase_id}"
            stamp_phase(
                run_id,
                phase_id=phase_id,
                kind=kind,
                status="start",
                hold_s=hold_s,
                event_id=nm_id,
                score_near_miss=bool(phase.get("score_near_miss", True)),
                note=phase.get("note"),
            )
            campaign.log(f"[playlist] {phase_id}: near-miss {nm_id} hold_s={hold_s:.0f} "
                         f"(MUST stay healthy)")
            try:
                fs, bt = campaign.inject_near_miss_aborted(nm_id, hold_s=hold_s)
                seal_event(
                    run_id,
                    event_id=nm_id,
                    fault_type="near_miss",
                    fault_start=fs,
                    breach_time=bt,
                    is_near_miss=True,
                )
                campaign.log(f"[playlist] sealed {nm_id}: {fs.isoformat()} -> {bt.isoformat()}")
            except Exception as exc:  # noqa: BLE001
                campaign.log(f"[playlist] ERROR during near-miss {nm_id}: {exc}")
            finally:
                campaign.clear_all_faults()
            stamp_phase(
                run_id,
                phase_id=phase_id,
                kind=kind,
                status="end",
                event_id=nm_id,
                score_near_miss=bool(phase.get("score_near_miss", True)),
            )
        else:
            raise SystemExit(f"Unsupported playlist kind {kind!r} in phase {phase_id}")

    campaign.log("=" * 64)
    campaign.log(f"PLAYLIST EXAM COMPLETE — 0 real faults, {nm_done} near-misses "
                 f"({spec.get('id')})")
    campaign.log("Grade with scorecard + exam report:")
    campaign.log(f"  python scripts/deca_blind_scorecard.py --run-id {run_id}")
    campaign.log(f"  python scripts/deca_blind_exam_report.py --run-id {run_id}")
    campaign.log("=" * 64)
    campaign.clear_all_faults()


def run_control(run_id: str, args, budget_left, time_scale: float) -> None:
    """All-healthy control run — the clean false-positive-rate experiment.

    Injects zero real faults for the whole budget; the only stress is
    ``--near-misses`` benign aborted onsets, spread evenly across the window.
    Every near-miss is sealed with ``is_near_miss=True``, so the scorecard's
    near-miss + spurious counts become the model's cry-wolf rate under fully
    benign conditions — a single strong number that answers "how often does it
    alarm when nothing is actually wrong?".
    """
    nm_total = max(args.near_misses, 0)
    nm_done = 0
    # Space baits across the budget with jittered rests around it.
    while budget_left() > 0 and not campaign._shutdown_requested:
        remaining_baits = nm_total - nm_done
        if remaining_baits <= 0:
            # Ride out the entire rest of the budget healthy in one sleep.
            rest = budget_left()
            campaign.log(f"[control] healthy baseline {rest:.1f} min to end (no baits left)...")
            time.sleep(max(rest, 0) * 60 * time_scale)
            break
        # Aim to place the next bait around an even slice of the time left.
        slice_min = max(budget_left() / (remaining_baits + 1), 0.1)
        rest = max(random.uniform(0.5, 1.5) * slice_min, args.rest_min)
        rest = min(rest, budget_left())
        campaign.log(f"[control] healthy baseline {rest:.1f} min...")
        time.sleep(rest * 60 * time_scale)
        if campaign._shutdown_requested or budget_left() <= 0.2:
            break
        nm_done += 1
        nm_id = f"{run_id}_nm{nm_done:02d}"
        campaign.log(f"[control] near-miss {nm_id} (bait — MUST stay healthy)")
        try:
            fs, bt = campaign.inject_near_miss_aborted(nm_id)
            seal_event(run_id, event_id=nm_id, fault_type="near_miss",
                       fault_start=fs, breach_time=bt, is_near_miss=True)
            campaign.log(f"[control] sealed {nm_id}: {fs.isoformat()} -> {bt.isoformat()}")
        except Exception as exc:  # noqa: BLE001
            campaign.log(f"[control] ERROR during near-miss: {exc}")
        finally:
            campaign.clear_all_faults()

    campaign.log("=" * 64)
    campaign.log(f"BLIND CONTROL COMPLETE — 0 real faults, {nm_done} near-misses")
    campaign.log("Any confirmed alarm here is a false positive. Grade with:")
    campaign.log(f"  python scripts/deca_blind_scorecard.py --run-id {run_id}")
    campaign.log("=" * 64)
    campaign.clear_all_faults()
    if not args.simulate:
        campaign.run_ssh(campaign.PE1_SSH, "pkill iperf3", quiet=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="DECA blind chaos scheduler")
    parser.add_argument("--run-id", default=None, help="Live run id (default: blind_<UTC time>)")
    parser.add_argument("--minutes", type=float, default=90.0, help="Hard wall-clock budget")
    parser.add_argument("--min-events", type=int, default=5, help="Target minimum real circumstances")
    parser.add_argument("--max-events", type=int, default=6, help="Target maximum real circumstances")
    parser.add_argument("--near-misses", type=int, default=2, help="Benign aborted onsets to bait")
    parser.add_argument("--rest-min", type=float, default=1.0, help="Min rest minutes between events")
    parser.add_argument("--rest-max", type=float, default=3.0, help="Max rest minutes between events")
    parser.add_argument("--compound-prob", type=float, default=0.0,
                        help="Probability [0..1] that an event slot fires a compound, "
                        "overlapping cascade (a PE1 fault + the PE2 vrf leak at once) "
                        "instead of one isolated fault")
    parser.add_argument(
        "--compound-pe1",
        default=None,
        choices=PE1_FAULTS,
        help="Force the PE1 leg of every compound (default: random among PE1 faults). "
        "Use with --compound-prob 1.0 for a deliberate dual-fault series.",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed (sealed for audit)")
    parser.add_argument("--start-at", default=None, metavar="HH:MM", help="Arm at this local time")
    parser.add_argument("--time-scale", type=float, default=1.0, help="Scale injector waits (sim only)")
    parser.add_argument("--simulate", action="store_true", help="No SSH, fast waits — rehearse harness")
    parser.add_argument(
        "--control",
        action="store_true",
        help="All-healthy control run: inject NO real faults, only healthy baseline "
        "plus periodic near-misses. Yields a clean false-positive rate under fully "
        "benign conditions. Use --near-misses / --rest-min/max to pace the baits.",
    )
    parser.add_argument(
        "--playlist",
        default=None,
        metavar="PATH",
        help="Deterministic specificity exam: fixed calm/near-miss playlist JSON "
        "(no RNG schedule). Mutually exclusive with --control and random chaos.",
    )
    parser.add_argument(
        "--fault-types",
        default=None,
        metavar="LIST",
        help="Comma-separated subset of fault types to draw from (default: all four). "
        "Example for echo-suppress proof: congestion_breach,tunnel_degradation",
    )
    args = parser.parse_args()

    if args.playlist and args.control:
        raise SystemExit("--playlist and --control are mutually exclusive")

    fault_pool = list(FAULT_TYPES)
    if args.fault_types:
        fault_pool = [t.strip() for t in args.fault_types.split(",") if t.strip()]
        bad = [t for t in fault_pool if t not in FAULT_TYPES]
        if bad:
            raise SystemExit(f"Unknown --fault-types: {bad}; allowed={FAULT_TYPES}")
        if not fault_pool:
            raise SystemExit("--fault-types resolved to empty list")

    run_id = args.run_id or f"blind_{now().strftime('%Y%m%d_%H%M%S')}"
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    random.seed(seed)

    playlist_path: Path | None = None
    if args.playlist:
        playlist_path = Path(args.playlist).expanduser().resolve()
        if not playlist_path.is_file():
            raise SystemExit(f"Playlist not found: {playlist_path}")

    run_dir = live_run_dir(run_id)
    # Point the campaign module's file handles at the live run dir so bgp pulses
    # (bgp_update_samples.csv) and the mirror CSV land alongside the sealed truth.
    campaign.LOG_FILE = run_dir / "fault_injection_log.csv"
    campaign.STATE_FILE = run_dir / "chaos_state.json"
    campaign.RUN_LOG = run_dir / "chaos_run.log"
    campaign.ensure_log_header()

    time_scale = 0.02 if (args.simulate and args.time_scale == 1.0) else args.time_scale
    if args.simulate:
        install_dry_ssh()
    install_time_scale(time_scale)

    meta = {
        "run_id": run_id,
        "seed": seed,
        "minutes_budget": args.minutes,
        "min_events": args.min_events,
        "max_events": args.max_events,
        "near_misses": args.near_misses,
        "simulate": args.simulate,
        "time_scale": time_scale,
        "armed_at": None,
        "control": bool(args.control),
        "playlist": str(playlist_path) if playlist_path else None,
        "fault_types": list(fault_pool),
        "compound_prob": float(args.compound_prob),
        "compound_pe1": args.compound_pe1,
    }
    if playlist_path is not None:
        meta["playlist_id"] = json.loads(playlist_path.read_text(encoding="utf-8")).get("id")
        meta["exam_phases"] = str(exam_phases_path(run_id))
    run_meta_path(run_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if args.start_at:
        wait_until(args.start_at)

    started = now()
    campaign.log("=" * 64)
    if playlist_path is not None:
        mode = "PLAYLIST EXAM"
    elif args.control:
        mode = "CONTROL (all-healthy)"
    else:
        mode = "CHAOS"
    campaign.log(f"DECA BLIND {mode} armed — run_id={run_id} seed={seed} (SEALED)")
    if playlist_path is not None:
        campaign.log(f"Budget {args.minutes:.0f} min | playlist={playlist_path} | "
                     f"simulate={args.simulate}")
    elif args.control:
        campaign.log(f"Budget {args.minutes:.0f} min | NO real faults | "
                     f"{args.near_misses} near-miss bait(s) | simulate={args.simulate}")
    else:
        campaign.log(f"Budget {args.minutes:.0f} min | target {args.min_events}-{args.max_events} events "
                     f"+ {args.near_misses} near-misses | simulate={args.simulate}")
        campaign.log(f"Fault pool: {fault_pool}")
        if args.compound_prob:
            campaign.log(
                f"Compound prob={args.compound_prob} pe1="
                f"{args.compound_pe1 or 'random'}"
            )
    campaign.log("Sealed truth: " + str(ground_truth_path(run_id)))
    campaign.log("=" * 64)

    atexit.register(campaign.clear_all_faults)
    campaign.clear_all_faults()
    if not args.simulate:
        campaign.generate_dynamic_traffic()

    def budget_left() -> float:
        return args.minutes - (now() - started).total_seconds() / 60.0

    if playlist_path is not None:
        run_playlist(run_id, playlist_path, budget_left, time_scale)
        if not args.simulate:
            campaign.run_ssh(campaign.PE1_SSH, "pkill iperf3", quiet=True)
        return

    if args.control:
        run_control(run_id, args, budget_left, time_scale)
        return

    target_events = random.randint(args.min_events, args.max_events)
    # Pre-plan near-miss slots randomly among the event gaps.
    total_slots = max(target_events, 1)
    near_miss_slots = set(random.sample(range(total_slots), min(args.near_misses, total_slots)))

    real_done = 0
    nm_done = 0
    idx = 0
    compound_idx = 0
    while real_done < target_events and budget_left() > 0 and not campaign._shutdown_requested:
        # Optional near-miss before this event.
        if idx in near_miss_slots and nm_done < args.near_misses and budget_left() > 2:
            nm_done += 1
            nm_id = f"{run_id}_nm{nm_done:02d}"
            campaign.log(f"[chaos] near-miss {nm_id} (bait — should stay healthy)")
            fs, bt = campaign.inject_near_miss_aborted(nm_id)
            seal_event(run_id, event_id=nm_id, fault_type="near_miss",
                       fault_start=fs, breach_time=bt, is_near_miss=True)

        rest = random.uniform(args.rest_min, args.rest_max)
        campaign.log(f"[chaos] normal ops {rest:.1f} min...")
        time.sleep(rest * 60 * time_scale)
        if campaign._shutdown_requested or budget_left() <= 0:
            break

        # Compound (#3): occasionally fire two real faults at once on different
        # hosts (a PE1 fault + the PE2 vrf leak) — a real cascade, not one clean
        # fault in isolation. Needs room for >=2 more events in the target.
        want_compound = (
            random.random() < args.compound_prob
            and (target_events - real_done) >= 2
        )
        if want_compound:
            compound_idx += 1
            sealed = run_compound(
                run_id,
                compound_idx,
                budget_left,
                pe1_fault=args.compound_pe1,
            )
            real_done += sealed
        else:
            fault_type = random.choice(fault_pool)
            real_done += 1
            ev_id = f"{run_id}_e{real_done:02d}_{fault_type}"
            campaign.log(f"[chaos] === circumstance {real_done}/{target_events}: {fault_type} "
                         f"(event_id={ev_id}, {budget_left():.0f} min budget left) ===")
            try:
                fs, bt = campaign.INJECTORS[fault_type](ev_id)
                seal_event(run_id, event_id=ev_id, fault_type=fault_type,
                           fault_start=fs, breach_time=bt, is_near_miss=False)
                campaign.log(f"[chaos] sealed {ev_id}: {fs.isoformat()} -> {bt.isoformat()}")
            except Exception as exc:  # noqa: BLE001 — keep the run alive, clean up
                campaign.log(f"[chaos] ERROR during {fault_type}: {exc}")
            finally:
                campaign.clear_all_faults()
        idx += 1

    campaign.log("=" * 64)
    campaign.log(f"BLIND CHAOS COMPLETE — {real_done} circumstances, {nm_done} near-misses in "
                 f"{(now() - started).total_seconds() / 60.0:.1f} min")
    campaign.log("Run the scorecard AFTER the operator has stopped:")
    campaign.log(f"  python scripts/deca_blind_scorecard.py --run-id {run_id}")
    campaign.log("=" * 64)
    campaign.clear_all_faults()
    if not args.simulate:
        campaign.run_ssh(campaign.PE1_SSH, "pkill iperf3", quiet=True)


if __name__ == "__main__":
    main()
