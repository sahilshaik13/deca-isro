#!/usr/bin/env python3
"""DECA circumstance campaign — temporal of faults *with their circumstances*.

The Temporal Loom is not only "was the breach on?". It also learns the
**circumstance**: the run-up pattern of conditions that precedes and *causes*
a fault. This campaign runs a clean, balanced experiment — **5 events for each
of the 4 classified faults** (20 events) — and records **three phases** per
event so we can train on the *existence* of a fault's circumstance, not just the
loud breach frame:

    circumstance_start ──ramp──► breach_time ──hold──► recovery_time
      (pre-conditions forming)     (fault commits)      (cleared)

- ``circumstance`` phase = ``circumstance_start`` → ``breach_time`` (the cause pattern).
- ``breach`` phase      = ``breach_time`` → ``recovery_time`` (the event itself).
- Everything else       = healthy ops (with occasional aborted near-misses).

Duration is **never** a classifier feature. Phases only *label rows*; existence
training asks "does this fault's circumstance exist here?" from telemetry shape.

Outputs (per run dir under ``data/rpi-net/runs/<id>/``):
- ``fault_injection_log.csv``      — compatible with rebuild_unified (fault_start/breach_time).
- ``circumstance_log.csv``         — event_id, fault_type, 3 phase stamps, run_id.
- ``network_telemetry.csv``        — raw Prometheus scrape (for rebuild).
- ``network_campaign_export.csv``  — pivoted + phase/existence labels (analysis).
- ``campaign_state.json`` / ``campaign_run.log`` — resume + audit.

This is a *hardware* campaign: it SSHes to the lab Pis and injects real faults.
Reuses the proven injectors from ``deca_fault_campaign``; adds phase capture,
a fixed 5×4 quota, and phase-aware export.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from _paths import RPI_NET_DIR

import deca_fault_campaign as dfc

FAULT_TYPES = dfc.FAULT_TYPES
DEFAULT_PER_TYPE = 5
RECOVERY_SETTLE = (3, 6)  # minutes of clean ops after each breach clears
REST_MINUTES = (10, 18)   # normal ops between events (circumstance baseline)
NEAR_MISS_PROB = 0.40     # aborted onset during rest → healthy false-start pattern


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CircumstanceCampaign:
    def __init__(self, run_id: str | None, per_type: int):
        self.per_type = per_type
        # Route dfc's low-level helpers/logging into our run directory.
        self.run_id = dfc.init_run_paths(run_id)
        self.run_dir: Path = dfc.LOG_FILE.parent
        self.circ_log: Path = self.run_dir / "circumstance_log.csv"
        self.state_file: Path = self.run_dir / "campaign_state.json"
        dfc.ensure_log_header()
        self._ensure_circ_header()

    # ── logging ────────────────────────────────────────────────────────────
    def _ensure_circ_header(self) -> None:
        if self.circ_log.exists() and self.circ_log.stat().st_size > 0:
            return
        with open(self.circ_log, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(
                [
                    "event_id",
                    "fault_type",
                    "circumstance_start",
                    "breach_time",
                    "recovery_time",
                    "precursor_minutes",
                    "breach_minutes",
                    "run_id",
                ]
            )

    def _append_circ(
        self,
        event_id: int,
        fault_type: str,
        circ_start: datetime,
        breach: datetime,
        recovery: datetime,
        run_id: str,
    ) -> None:
        precursor_min = max((breach - circ_start).total_seconds() / 60.0, 0.0)
        breach_min = max((recovery - breach).total_seconds() / 60.0, 0.0)
        with open(self.circ_log, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(
                [
                    event_id,
                    fault_type,
                    circ_start.isoformat(),
                    breach.isoformat(),
                    recovery.isoformat(),
                    f"{precursor_min:.3f}",
                    f"{breach_min:.3f}",
                    run_id,
                ]
            )

    # ── state (resume) ───────────────────────────────────────────────────────
    def _load_state(self) -> dict:
        if self.state_file.exists():
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            state.setdefault("completed_by_type", {t: 0 for t in FAULT_TYPES})
            state.setdefault("completed", 0)
            state.setdefault("started_at", _now().isoformat())
            return state
        # Reconstruct from an existing circumstance log if present (crash-safe).
        completed_by_type = {t: 0 for t in FAULT_TYPES}
        completed = 0
        if self.circ_log.exists():
            with open(self.circ_log, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ft = row.get("fault_type")
                    if ft in completed_by_type:
                        completed_by_type[ft] += 1
                        completed += 1
        return {
            "started_at": _now().isoformat(),
            "completed": completed,
            "completed_by_type": completed_by_type,
        }

    def _save_state(self, state: dict) -> None:
        state["updated_at"] = _now().isoformat()
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _next_type(self, completed_by_type: dict[str, int]) -> str | None:
        """Pick the fault furthest from its quota → balanced 5×4 interleave."""
        remaining = [t for t in FAULT_TYPES if completed_by_type.get(t, 0) < self.per_type]
        if not remaining:
            return None
        fewest = min(completed_by_type.get(t, 0) for t in remaining)
        pool = [t for t in remaining if completed_by_type.get(t, 0) == fewest]
        return random.choice(pool)

    def _complete(self, completed_by_type: dict[str, int]) -> bool:
        return all(completed_by_type.get(t, 0) >= self.per_type for t in FAULT_TYPES)

    # ── one event: capture 3 phases ───────────────────────────────────────────
    def run_event(self, fault_type: str, event_id: int) -> None:
        run_id = f"real_{fault_type}_{event_id:03d}"
        dfc.log(f"--- EVENT {event_id}: {fault_type} (run_id={run_id}) ---")
        dfc.log("  phase=circumstance: pre-conditions forming (ramp)...")
        try:
            # Injector: fault_start = circumstance_start, returns after breach hold.
            circ_start, breach_time = dfc.INJECTORS[fault_type](run_id)
            recovery_time = _now()
            # Compat log for rebuild_unified (labels circumstance ramp as the fault).
            dfc.append_log_row(fault_type, run_id, circ_start, breach_time)
            # Rich three-phase log for circumstance / existence training.
            self._append_circ(
                event_id, fault_type, circ_start, breach_time, recovery_time, run_id
            )
            dfc.log(
                f"  phases: circumstance {circ_start.isoformat()} → breach "
                f"{breach_time.isoformat()} → recovery {recovery_time.isoformat()}"
            )
        except Exception as exc:  # noqa: BLE001 — never let one event kill the run
            dfc.log(f"  ERROR during {fault_type}: {exc}")
        finally:
            dfc.clear_all_faults()
            dfc.log(f"  cleanup complete for {run_id}")

    # ── phase-aware Prometheus export ─────────────────────────────────────────
    def export(self) -> None:
        try:
            import pandas as pd
            import requests
        except ImportError:
            dfc.log("Prometheus export skipped: pandas/requests not available")
            return

        start = dfc._campaign_start or (_now() - timedelta(hours=24))
        end = _now()
        queries = {
            "throughput_in_bps": 'sum by (host) (rate(net_bytes_recv{interface="eth0"}[1m]))',
            "throughput_out_bps": 'sum by (host) (rate(net_bytes_sent{interface="eth0"}[1m]))',
            "packet_loss_pct": "avg by (host) (ping_percent_packet_loss)",
            "jitter_ms": "avg by (host) (ping_standard_deviation_ms)",
            "latency_ms": "avg by (host) (ping_average_response_ms)",
            "drop_out_rate": 'sum by (host) (rate(net_drop_out{interface="eth0"}[1m]))',
        }

        rows: list[dict] = []
        for metric_name, promql in queries.items():
            try:
                resp = requests.get(
                    dfc.PROMETHEUS_URL,
                    params={
                        "query": promql,
                        "start": int(start.timestamp()),
                        "end": int(end.timestamp()),
                        "step": dfc.PROMETHEUS_STEP,
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                dfc.log(f"Prometheus export warn ({metric_name}): {exc}")
                continue
            if payload.get("status") != "success":
                continue
            for series in payload.get("data", {}).get("result", []):
                host = series.get("metric", {}).get("host", "unknown")
                for ts, val in series.get("values", []):
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        continue
                    if v != v:  # NaN
                        continue
                    rows.append(
                        {
                            "timestamp": datetime.fromtimestamp(
                                float(ts), tz=timezone.utc
                            ).isoformat(),
                            "host": host,
                            "metric": metric_name,
                            "value": v,
                        }
                    )

        if not rows:
            dfc.log("Prometheus export: no rows (is Prometheus running on localhost:9090?)")
            return

        tele = pd.DataFrame(rows)
        tele_path = self.run_dir / "network_telemetry.csv"
        tele.to_csv(tele_path, index=False)
        dfc.log(f"Exported {tele_path} ({len(tele)} rows)")

        pivot = tele.pivot_table(
            index=["timestamp", "host"], columns="metric", values="value", aggfunc="mean"
        ).reset_index()
        if "throughput_in_bps" in pivot.columns:
            pivot["throughput_in_mbps"] = pivot["throughput_in_bps"] * 8 / 1e6
        if "throughput_out_bps" in pivot.columns:
            pivot["throughput_out_mbps"] = pivot["throughput_out_bps"] * 8 / 1e6

        # Phase-aware + existence labels from the rich circumstance log.
        pivot["timestamp_dt"] = pd.to_datetime(pivot["timestamp"], utc=True)
        pivot["fault_type"] = "none"        # breach-only class (event)
        pivot["event_phase"] = "none"       # circumstance | breach | none
        pivot["circumstance_label"] = "healthy"  # existence: fault situation present?
        pivot["run_id"] = ""
        if self.circ_log.exists():
            events = pd.read_csv(self.circ_log)
            for _, ev in events.iterrows():
                cs = pd.to_datetime(ev["circumstance_start"], utc=True)
                bt = pd.to_datetime(ev["breach_time"], utc=True)
                rt = pd.to_datetime(ev["recovery_time"], utc=True)
                circ_mask = (pivot["timestamp_dt"] >= cs) & (pivot["timestamp_dt"] < bt)
                breach_mask = (pivot["timestamp_dt"] >= bt) & (pivot["timestamp_dt"] <= rt)
                exist_mask = circ_mask | breach_mask
                pivot.loc[circ_mask, "event_phase"] = "circumstance"
                pivot.loc[breach_mask, "event_phase"] = "breach"
                pivot.loc[breach_mask, "fault_type"] = ev["fault_type"]
                pivot.loc[exist_mask, "circumstance_label"] = ev["fault_type"]
                pivot.loc[exist_mask, "run_id"] = ev["run_id"]
        pivot = pivot.drop(columns=["timestamp_dt"])

        export_path = self.run_dir / "network_campaign_export.csv"
        pivot.to_csv(export_path, index=False)
        dfc.log(f"Exported {export_path} ({len(pivot)} rows)")

    # ── validation ────────────────────────────────────────────────────────────
    def validate(self) -> None:
        dfc.log("=" * 60)
        dfc.log("VALIDATING circumstance_log.csv")
        dfc.log("=" * 60)
        if not self.circ_log.exists():
            dfc.log("No circumstance log — nothing to validate.")
            return
        with open(self.circ_log, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            dfc.log("Circumstance log empty.")
            return

        by_type: dict[str, int] = {t: 0 for t in FAULT_TYPES}
        bad_order = 0
        degenerate = 0
        for r in rows:
            ft = r["fault_type"]
            by_type[ft] = by_type.get(ft, 0) + 1
            cs = datetime.fromisoformat(r["circumstance_start"])
            bt = datetime.fromisoformat(r["breach_time"])
            rt = datetime.fromisoformat(r["recovery_time"])
            if not (cs <= bt <= rt):
                bad_order += 1
            if cs == bt or bt == rt:
                degenerate += 1

        for ft in FAULT_TYPES:
            flag = "OK" if by_type.get(ft, 0) == self.per_type else "WARN"
            dfc.log(f"  {ft}: {by_type.get(ft, 0)}/{self.per_type} events [{flag}]")
        if bad_order:
            dfc.log(f"  WARN: {bad_order} events with non-monotonic phase timestamps")
        if degenerate:
            dfc.log(f"  WARN: {degenerate} events with a zero-length phase (interrupted?)")

        all_ok = all(by_type.get(t, 0) == self.per_type for t in FAULT_TYPES) and not bad_order
        dfc.log("VALIDATION RESULT: " + ("PASS" if all_ok else "WARN — review before training"))
        dfc.log("=" * 60)

    # ── main loop ──────────────────────────────────────────────────────────────
    def run(self) -> None:
        dfc._campaign_start = _now()
        dfc.log(f"Run directory: {self.run_dir}")
        dfc.log("=" * 60)
        dfc.log(
            f"DECA CIRCUMSTANCE CAMPAIGN — {self.per_type} events × "
            f"{len(FAULT_TYPES)} faults = {self.per_type * len(FAULT_TYPES)} total"
        )
        dfc.log("=" * 60)

        dfc.clear_all_faults()
        dfc.generate_dynamic_traffic()

        state = self._load_state()
        dfc._campaign_start = datetime.fromisoformat(state["started_at"])
        event_index = state["completed"]

        while not self._complete(state["completed_by_type"]):
            if dfc._shutdown_requested:
                dfc.log("Shutdown requested, stopping.")
                break

            # Baseline circumstance context before the next event.
            rest = random.uniform(*REST_MINUTES)
            dfc.log(f"Normal operations for {rest:.1f} minutes (circumstance baseline)...")
            half = (rest / 2) * 60
            time.sleep(half)
            dfc.generate_dynamic_traffic()
            if random.random() < NEAR_MISS_PROB and not dfc._shutdown_requested:
                nm_id = f"near_miss_{event_index + 1:03d}"
                fs, bt = dfc.inject_near_miss_aborted(nm_id)
                dfc.append_log_row("precursor_aborted", f"real_{nm_id}", fs, bt)
                dfc.log(f"Logged near-miss {nm_id} (healthy / precursor_aborted)")
            time.sleep(half)

            if dfc._shutdown_requested:
                break

            fault_type = self._next_type(state["completed_by_type"])
            if fault_type is None:
                break

            event_index += 1
            self.run_event(fault_type, event_index)

            state["completed"] = event_index
            state["completed_by_type"][fault_type] = (
                state["completed_by_type"].get(fault_type, 0) + 1
            )
            self._save_state(state)
            dfc.log(
                f"  Progress {fault_type}: "
                f"{state['completed_by_type'][fault_type]}/{self.per_type}"
            )

            # Let the network fully recover so the next circumstance starts clean.
            settle = random.uniform(*RECOVERY_SETTLE)
            dfc.log(f"  recovery settle {settle:.1f} min...")
            time.sleep(settle * 60)

        dfc.log("=" * 60)
        total = self.per_type * len(FAULT_TYPES)
        dfc.log(f"CIRCUMSTANCE CAMPAIGN FINISHED: {state['completed']}/{total} events")
        dfc.log(f"By type: {state['completed_by_type']}")
        dfc.clear_all_faults()
        dfc.run_ssh(dfc.PE1_SSH, "pkill iperf3", quiet=True)
        self.export()
        self.validate()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DECA circumstance campaign — 5 events × 4 faults with 3-phase capture"
    )
    parser.add_argument(
        "--per-type",
        type=int,
        default=DEFAULT_PER_TYPE,
        metavar="N",
        help=f"Events per fault type (default {DEFAULT_PER_TYPE} → {DEFAULT_PER_TYPE * 4} total)",
    )
    parser.add_argument(
        "--run-id", type=str, default=None, help="Run directory name (default: new timestamp)"
    )
    args = parser.parse_args()
    if args.per_type < 1:
        parser.error("--per-type must be >= 1")

    campaign = CircumstanceCampaign(args.run_id, args.per_type)
    campaign.run()


if __name__ == "__main__":
    main()
