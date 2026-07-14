import argparse
import csv
import json
import random
import signal
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, stdev

from _paths import RPI_NET_DIR

# ── DECA lab stations ────────────────────────────────────────────────────
PE1_SSH = "station1@192.168.50.10"
PE2_SSH = "station2@192.168.50.20"
CORE_SSH = "station3@192.168.50.30"

IPERF_LAN_TARGET = "192.168.50.20"

# ── Campaign sizing ───────────────────────────────────────────────────────
# Quota-driven: run until each fault type hits its per-type target (5–7 by default).
MIN_RUNS_PER_TYPE = 5
MAX_RUNS_PER_TYPE = 7
REST_MINUTES = (15, 25)  # normal ops between faults

LOG_FILE = RPI_NET_DIR / "fault_injection_log.csv"
STATE_FILE = RPI_NET_DIR / "campaign_state.json"
RUN_LOG = RPI_NET_DIR / "campaign_run.log"

FAULT_TYPES = ["congestion_breach", "tunnel_degradation", "bgp_route_flap", "vrf_leakage"]

PROMETHEUS_URL = "http://localhost:9090/api/v1/query_range"
PROMETHEUS_STEP = "15"

_shutdown_requested = False
_campaign_start: datetime | None = None


def init_run_paths(run_id: str | None = None) -> str:
    """Each campaign run gets its own directory under data/rpi-net/runs/."""
    global LOG_FILE, STATE_FILE, RUN_LOG
    rid = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RPI_NET_DIR / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    LOG_FILE = run_dir / "fault_injection_log.csv"
    STATE_FILE = run_dir / "campaign_state.json"
    RUN_LOG = run_dir / "campaign_run.log"
    return rid


def ensure_log_header() -> None:
    """Create CSV header only when starting fresh — never wipe on resume."""
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 0:
        return
    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(["fault_type", "fault_start", "breach_time", "run_id"])


# ── Logging ──────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(RUN_LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_ssh(target: str, command: str, *, quiet: bool = False, timeout: int = 20) -> bool:
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", target, command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and not quiet:
            err = (result.stderr or result.stdout or "").strip()
            log(f"   SSH failed on {target}: {err[:200]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        if not quiet:
            log(f"   SSH timeout on {target}")
        return False


def handle_signal(signum, frame):
    global _shutdown_requested
    log(f"Signal {signum} received, finishing current step then shutting down cleanly...")
    _shutdown_requested = True


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ── Background traffic ────────────────────────────────────────────────────
def ensure_iperf_server() -> None:
    run_ssh(PE2_SSH, "pkill iperf3", quiet=True)
    time.sleep(1)
    if run_ssh(PE2_SSH, "iperf3 -s -D"):
        log(f"   iperf3 server listening on station2 ({IPERF_LAN_TARGET})")
    else:
        log("   Could not start iperf3 server on station2")


def generate_dynamic_traffic() -> None:
    ensure_iperf_server()
    run_ssh(PE1_SSH, "pkill iperf3", quiet=True)
    time.sleep(1)

    bw = random.randint(15, 85)
    log(f"Baseline traffic: {bw} Mbps (station1 -> {IPERF_LAN_TARGET} via eth0)")

    traffic_cmd = (
        f"nohup iperf3 -c {IPERF_LAN_TARGET} -u -b {bw}M -t 36000 "
        f"</dev/null >/tmp/iperf3-lan.log 2>&1 & echo iperf_started"
    )
    if run_ssh(PE1_SSH, traffic_cmd, timeout=30):
        time.sleep(4)
        running = run_ssh(PE1_SSH, "pgrep -f 'iperf3 -c 192.168.50.20' >/dev/null", quiet=True)
        if running:
            log(f"   iperf3 client running (~{bw} Mbps)")
        else:
            log("   iperf3 client exited unexpectedly, check /tmp/iperf3-lan.log on station1")
    else:
        log("   Could not launch iperf3 client on station1")


def clear_all_faults() -> None:
    run_ssh(PE1_SSH, "sudo tc qdisc del dev eth0 root 2>/dev/null", quiet=True)
    run_ssh(PE2_SSH, "sudo tc qdisc del dev eth0 root 2>/dev/null", quiet=True)
    run_ssh(
        PE2_SSH,
        "sudo vtysh -c 'conf t' -c 'router bgp 65001 vrf ADMIN' "
        "-c 'address-family ipv4 unicast' -c 'no rt vpn import 65001:100' "
        "-c 'exit-address-family' -c 'end'",
        quiet=True,
    )


# ── Fault implementations ─────────────────────────────────────────────────
def inject_congestion_breach(run_id: str):
    severity = random.uniform(0.6, 1.4)
    precursor_minutes = random.uniform(6, 14)
    steps = random.randint(3, 5)
    final_rate = max(int(20 - 12 * severity), 5)
    start_rate = 95
    step_gap = (precursor_minutes * 60) / steps
    breach_hold_minutes = random.uniform(3, 7)

    fault_start = datetime.now(timezone.utc)
    log(
        f"  congestion_breach run={run_id}: {start_rate}->{final_rate}mbit "
        f"over {precursor_minutes:.1f}min, {steps} steps"
    )

    rates = [int(start_rate - i * (start_rate - final_rate) / steps) for i in range(steps + 1)]
    for rate in rates[:-1]:
        run_ssh(PE1_SSH, f"sudo tc qdisc replace dev eth0 root tbf rate {rate}mbit burst 32k latency 400ms")
        time.sleep(step_gap)
        if _shutdown_requested:
            return fault_start, datetime.now(timezone.utc)

    breach_time = datetime.now(timezone.utc)
    run_ssh(PE1_SSH, f"sudo tc qdisc replace dev eth0 root tbf rate {rates[-1]}mbit burst 32k latency 400ms")
    time.sleep(breach_hold_minutes * 60)
    return fault_start, breach_time


def inject_tunnel_degradation(run_id: str):
    severity = random.uniform(0.6, 1.4)
    precursor_minutes = random.uniform(6, 12)
    steps = random.randint(3, 5)
    final_loss = min(4 + 6 * severity, 12)
    final_delay = int(min(15 + 25 * severity, 45))
    step_gap = (precursor_minutes * 60) / steps
    breach_hold_minutes = random.uniform(3, 6)

    fault_start = datetime.now(timezone.utc)
    log(
        f"  tunnel_degradation run={run_id}: ramping to {final_loss:.1f}% loss / "
        f"{final_delay}ms delay over {precursor_minutes:.1f}min"
    )

    for i in range(1, steps):
        loss = final_loss * i / steps
        delay = int(final_delay * i / steps)
        run_ssh(
            PE1_SSH,
            f"sudo tc qdisc replace dev eth0 root netem delay {delay}ms "
            f"{max(delay // 3, 1)}ms loss {loss:.1f}%",
        )
        time.sleep(step_gap)
        if _shutdown_requested:
            return fault_start, datetime.now(timezone.utc)

    breach_time = datetime.now(timezone.utc)
    run_ssh(
        PE1_SSH,
        f"sudo tc qdisc replace dev eth0 root netem delay {final_delay}ms "
        f"{final_delay // 3}ms loss {final_loss:.1f}%",
    )
    time.sleep(breach_hold_minutes * 60)
    return fault_start, breach_time


def inject_bgp_route_flap(run_id: str):
    precursor_minutes = random.uniform(6, 12)
    num_precursor_flaps = random.randint(2, 4)
    breach_flaps = random.randint(4, 7)
    breach_interval = random.uniform(10, 20)

    fault_start = datetime.now(timezone.utc)
    log(
        f"  bgp_route_flap run={run_id}: {num_precursor_flaps} slow flaps over "
        f"{precursor_minutes:.1f}min, then {breach_flaps} rapid flaps"
    )

    gap = (precursor_minutes * 60) / max(num_precursor_flaps, 1)
    for _ in range(num_precursor_flaps):
        run_ssh(PE1_SSH, "sudo vtysh -c 'clear bgp 10.1.3.1 soft'")
        time.sleep(gap)
        if _shutdown_requested:
            return fault_start, datetime.now(timezone.utc)

    breach_time = datetime.now(timezone.utc)
    for _ in range(breach_flaps):
        run_ssh(PE1_SSH, "sudo vtysh -c 'clear bgp 10.1.3.1 soft'")
        time.sleep(breach_interval)

    return fault_start, breach_time


def inject_vrf_leakage(run_id: str):
    # Match other faults: variable precursor until "breach", then variable hold.
    # (Old code slept a fixed 90s before stamping breach_time → every duration ~1.5min.)
    precursor_minutes = random.uniform(3, 8)
    breach_hold_minutes = random.uniform(4, 9)

    fault_start = datetime.now(timezone.utc)
    log(
        f"  vrf_leakage run={run_id}: injecting wrong route-target import on "
        f"station2 ADMIN vrf, precursor {precursor_minutes:.1f}min + "
        f"hold {breach_hold_minutes:.1f}min"
    )

    ok = run_ssh(
        PE2_SSH,
        "sudo vtysh -c 'conf t' -c 'router bgp 65001 vrf ADMIN' "
        "-c 'address-family ipv4 unicast' -c 'rt vpn import 65001:100' "
        "-c 'exit-address-family' -c 'end'",
    )
    if not ok:
        log("  vrf_leakage: failed to inject route-target, skipping this run")
        return fault_start, fault_start

    time.sleep(precursor_minutes * 60)
    if _shutdown_requested:
        return fault_start, datetime.now(timezone.utc)

    breach_time = datetime.now(timezone.utc)
    time.sleep(breach_hold_minutes * 60)
    return fault_start, breach_time


INJECTORS = {
    "congestion_breach": inject_congestion_breach,
    "tunnel_degradation": inject_tunnel_degradation,
    "bgp_route_flap": inject_bgp_route_flap,
    "vrf_leakage": inject_vrf_leakage,
}

_bag: list[str] = []  # unused; kept for demo mode shuffle


def assign_targets(
    completed_by_type: dict[str, int],
    min_per: int,
    max_per: int,
) -> dict[str, int]:
    """Pick a random target in [min_per, max_per] per type; never below already completed."""
    targets: dict[str, int] = {}
    for fault_type in FAULT_TYPES:
        done = completed_by_type.get(fault_type, 0)
        target = random.randint(min_per, max_per)
        targets[fault_type] = max(target, done, min_per)
    return targets


def next_fault_type(completed_by_type: dict[str, int], target_per_type: dict[str, int]) -> str | None:
    """Pick the fault type furthest behind its quota; tie-break randomly."""
    remaining = [
        fault_type
        for fault_type in FAULT_TYPES
        if completed_by_type.get(fault_type, 0) < target_per_type[fault_type]
    ]
    if not remaining:
        return None

    min_done = min(completed_by_type.get(fault_type, 0) for fault_type in remaining)
    candidates = [
        fault_type
        for fault_type in remaining
        if completed_by_type.get(fault_type, 0) == min_done
    ]
    return random.choice(candidates)


def campaign_complete(completed_by_type: dict[str, int], target_per_type: dict[str, int]) -> bool:
    return all(
        completed_by_type.get(fault_type, 0) >= target_per_type[fault_type]
        for fault_type in FAULT_TYPES
    )


def total_target_runs(target_per_type: dict[str, int]) -> int:
    return sum(target_per_type.values())


def _rebuild_state_from_log(min_per: int, max_per: int) -> dict | None:
    """Recover resume state when campaign_state.json is missing or corrupt."""
    if not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
        return None

    with LOG_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return None

    completed_by_type = {t: 0 for t in FAULT_TYPES}
    for row in rows:
        fault_type = row.get("fault_type", "")
        if fault_type in completed_by_type:
            completed_by_type[fault_type] += 1

    started_at = datetime.now(timezone.utc)
    if RUN_LOG.exists():
        for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
            if "DECA CAMPAIGN STARTING" in line:
                ts = line.split("]")[0].lstrip("[")
                try:
                    started_at = datetime.fromisoformat(ts)
                except ValueError:
                    pass
                break

    target_per_type = assign_targets(completed_by_type, min_per, max_per)
    return {
        "completed": len(rows),
        "completed_by_type": completed_by_type,
        "target_per_type": target_per_type,
        "min_per_type": min_per,
        "max_per_type": max_per,
        "started_at": started_at.isoformat(),
    }


def _ensure_state_targets(state: dict, min_per: int, max_per: int) -> None:
    state.setdefault("completed", 0)
    state.setdefault("completed_by_type", {t: 0 for t in FAULT_TYPES})
    state["min_per_type"] = min_per
    state["max_per_type"] = max_per
    if "target_per_type" not in state:
        state["target_per_type"] = assign_targets(state["completed_by_type"], min_per, max_per)
    else:
        for fault_type in FAULT_TYPES:
            done = state["completed_by_type"].get(fault_type, 0)
            target = state["target_per_type"].get(fault_type, min_per)
            state["target_per_type"][fault_type] = max(target, done, min_per)


def load_or_create_state(min_per: int, max_per: int) -> dict:
    if STATE_FILE.exists() and STATE_FILE.stat().st_size > 0:
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("campaign_state.json corrupt — rebuilding from fault_injection_log.csv")
            state = _rebuild_state_from_log(min_per, max_per)
            if state is None:
                STATE_FILE.unlink(missing_ok=True)
            else:
                save_state(state)
        if state is not None:
            _ensure_state_targets(state, min_per, max_per)
            save_state(state)
            log(
                f"Resuming campaign: {state['completed']}/{total_target_runs(state['target_per_type'])} "
                f"runs done — by type: {state['completed_by_type']} "
                f"(targets: {state['target_per_type']})"
            )
            return state

    rebuilt = _rebuild_state_from_log(min_per, max_per)
    if rebuilt is not None:
        save_state(rebuilt)
        log(
            f"Resuming campaign from log: {rebuilt['completed']}/{total_target_runs(rebuilt['target_per_type'])} "
            f"runs done — by type: {rebuilt['completed_by_type']} "
            f"(targets: {rebuilt['target_per_type']})"
        )
        return rebuilt

    target_per_type = assign_targets({t: 0 for t in FAULT_TYPES}, min_per, max_per)
    state = {
        "completed": 0,
        "completed_by_type": {t: 0 for t in FAULT_TYPES},
        "target_per_type": target_per_type,
        "min_per_type": min_per,
        "max_per_type": max_per,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    log(
        f"New campaign: quota-driven — {min_per}–{max_per} runs per fault type "
        f"(targets: {target_per_type}, total {total_target_runs(target_per_type)} runs)"
    )
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_log_row(fault_type: str, run_id: str, fault_start: datetime, breach_time: datetime) -> None:
    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(
            [fault_type, fault_start.isoformat(), breach_time.isoformat(), run_id]
        )


def export_prometheus_csv() -> None:
    """Pull Prometheus telemetry for this campaign window into the run directory."""
    try:
        import pandas as pd
        import requests
    except ImportError:
        log("Prometheus export skipped: pandas/requests not available")
        return

    run_dir = LOG_FILE.parent
    start = _campaign_start
    if start is None and STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        started = state.get("started_at")
        if started:
            start = datetime.fromisoformat(started)
    if start is None:
        start = datetime.now(timezone.utc) - timedelta(hours=24)

    end = datetime.now(timezone.utc)
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())

    queries = {
        "throughput_in_bps": 'sum by (host) (rate(net_bytes_recv{interface="eth0"}[1m]))',
        "throughput_out_bps": 'sum by (host) (rate(net_bytes_sent{interface="eth0"}[1m]))',
        "packet_loss_pct": "avg by (host) (ping_percent_packet_loss)",
        "jitter_ms": "avg by (host) (ping_standard_deviation_ms)",
        "latency_ms": "avg by (host) (ping_average_response_ms)",
        "drop_out_rate": 'sum by (host) (rate(net_drop_out{interface="eth0"}[1m]))',
    }

    rows = []
    for metric_name, promql in queries.items():
        try:
            resp = requests.get(
                PROMETHEUS_URL,
                params={"query": promql, "start": start_ts, "end": end_ts, "step": PROMETHEUS_STEP},
                timeout=120,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log(f"Prometheus export warn ({metric_name}): {exc}")
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
                if v != v:
                    continue
                rows.append(
                    {
                        "timestamp": datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(),
                        "host": host,
                        "metric": metric_name,
                        "value": v,
                    }
                )

    if not rows:
        log("Prometheus export: no rows (is Prometheus running on localhost:9090?)")
        return

    tele = pd.DataFrame(rows)
    tele_path = run_dir / "network_telemetry.csv"
    tele.to_csv(tele_path, index=False)
    log(f"Exported {tele_path} ({len(tele)} rows)")

    pivot = tele.pivot_table(
        index=["timestamp", "host"], columns="metric", values="value", aggfunc="mean"
    ).reset_index()
    if "throughput_in_bps" in pivot.columns:
        pivot["throughput_in_mbps"] = pivot["throughput_in_bps"] * 8 / 1e6
    if "throughput_out_bps" in pivot.columns:
        pivot["throughput_out_mbps"] = pivot["throughput_out_bps"] * 8 / 1e6

    if LOG_FILE.exists():
        faults = pd.read_csv(LOG_FILE)
        pivot["timestamp_dt"] = pd.to_datetime(pivot["timestamp"], utc=True)
        pivot["fault_type"] = "none"
        pivot["run_id"] = ""
        for _, fault in faults.iterrows():
            fs = pd.to_datetime(fault["fault_start"], utc=True)
            bt = pd.to_datetime(fault["breach_time"], utc=True)
            fe = bt + pd.Timedelta(minutes=30)
            mask = (pivot["timestamp_dt"] >= fs) & (pivot["timestamp_dt"] <= fe)
            pivot.loc[mask, "fault_type"] = fault["fault_type"]
            pivot.loc[mask, "run_id"] = fault["run_id"]
        pivot = pivot.drop(columns=["timestamp_dt"])

    export_path = run_dir / "network_campaign_export.csv"
    pivot.to_csv(export_path, index=False)
    log(f"Exported {export_path} ({len(pivot)} rows)")


def validate_campaign_log(min_per: int = MIN_RUNS_PER_TYPE) -> None:
    log("=" * 60)
    log("VALIDATING fault_injection_log.csv")
    log("=" * 60)

    if not LOG_FILE.exists():
        log("No log file found -- nothing to validate.")
        return

    with open(LOG_FILE, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        log("Log file exists but has zero rows.")
        return

    by_type: dict[str, list[float]] = {}
    for row in rows:
        ft = row["fault_type"]
        start = datetime.fromisoformat(row["fault_start"])
        end = datetime.fromisoformat(row["breach_time"])
        duration_min = (end - start).total_seconds() / 60
        by_type.setdefault(ft, []).append(duration_min)

    log(f"Total runs: {len(rows)}")
    all_pass = True

    for ft in FAULT_TYPES:
        durations = by_type.get(ft, [])
        if not durations:
            log(f"  {ft:20s}  WARN: zero runs recorded")
            all_pass = False
            continue

        n = len(durations)
        avg = mean(durations)
        spread = stdev(durations) if n > 1 else 0.0
        uniformity_ratio = spread / avg if avg > 0 else 0
        flag = ""
        if n < min_per:
            flag = f"  WARN: fewer than {min_per} runs"
            all_pass = False
        elif uniformity_ratio < 0.12:
            flag = "  WARN: durations suspiciously uniform"
            all_pass = False
        log(f"  {ft:20s}  n={n}  avg={avg:5.1f}min  spread={spread:4.1f}min{flag}")

    degenerate = sum(
        1
        for row in rows
        if datetime.fromisoformat(row["fault_start"]) == datetime.fromisoformat(row["breach_time"])
    )
    if degenerate:
        log(f"  WARN: {degenerate} degenerate rows (fault_start == breach_time)")
        all_pass = False

    log("VALIDATION RESULT: " + ("PASS" if all_pass else "WARN -- review flags before training"))
    log("=" * 60)


def run_one(fault_type: str, run_index: int) -> None:
    run_id = f"real_{fault_type}_{run_index:03d}"
    log(f"--- Run {run_index}: {fault_type} (run_id={run_id}) ---")
    try:
        fault_start, breach_time = INJECTORS[fault_type](run_id)
        append_log_row(fault_type, run_id, fault_start, breach_time)
        log(f"  Logged: {fault_start.isoformat()} -> {breach_time.isoformat()}")
    except Exception as exc:
        log(f"  ERROR during {fault_type}: {exc}")
    finally:
        clear_all_faults()
        log(f"  Cleanup complete for {run_id}")


def _demo_next_fault_type() -> str:
    global _bag
    if not _bag:
        _bag = FAULT_TYPES.copy()
        random.shuffle(_bag)
    return _bag.pop()


def main() -> None:
    global _campaign_start

    parser = argparse.ArgumentParser(description="DECA lab fault-injection campaign")
    parser.add_argument(
        "--min-per-type",
        type=int,
        default=MIN_RUNS_PER_TYPE,
        help=f"Minimum runs per fault type (default: {MIN_RUNS_PER_TYPE})",
    )
    parser.add_argument(
        "--max-per-type",
        type=int,
        default=MAX_RUNS_PER_TYPE,
        help=f"Maximum runs per fault type (default: {MAX_RUNS_PER_TYPE})",
    )
    parser.add_argument("--run-id", type=str, default=None, help="Run directory name (default: new timestamp)")
    parser.add_argument("--demo", action="store_true", help="Short cycles for dashboard testing only")
    args = parser.parse_args()

    if args.min_per_type < 1 or args.max_per_type < args.min_per_type:
        parser.error("--max-per-type must be >= --min-per-type and both must be >= 1")

    init_run_paths(args.run_id)
    ensure_log_header()
    log(f"Run directory: {LOG_FILE.parent}")
    log(f"Data root: {RPI_NET_DIR.resolve()}")

    log("=" * 60)
    log(
        f"DECA CAMPAIGN STARTING — quota-driven, "
        f"{args.min_per_type}–{args.max_per_type} runs per fault type"
    )
    log("=" * 60)

    clear_all_faults()
    generate_dynamic_traffic()

    if args.demo:
        for i in range(1, 4):
            run_one(_demo_next_fault_type(), i)
            time.sleep(60)
        log("Demo complete.")
        export_prometheus_csv()
        validate_campaign_log(args.min_per_type)
        return

    state = load_or_create_state(args.min_per_type, args.max_per_type)
    _campaign_start = datetime.fromisoformat(
        state.get("started_at", datetime.now(timezone.utc).isoformat())
    )
    run_index = state["completed"]
    targets = state["target_per_type"]

    while not campaign_complete(state["completed_by_type"], targets):
        if _shutdown_requested:
            log("Shutdown requested, stopping.")
            break

        rest_minutes = random.uniform(*REST_MINUTES)
        log(f"Normal operations for {rest_minutes:.1f} minutes...")
        half_rest_sec = (rest_minutes / 2) * 60
        time.sleep(half_rest_sec)
        generate_dynamic_traffic()
        time.sleep(half_rest_sec)

        if _shutdown_requested:
            break

        fault_type = next_fault_type(state["completed_by_type"], targets)
        if fault_type is None:
            break

        run_index += 1
        run_one(fault_type, run_index)

        state["completed"] = run_index
        state["completed_by_type"][fault_type] = state["completed_by_type"].get(fault_type, 0) + 1
        save_state(state)

        done = state["completed_by_type"][fault_type]
        target = targets[fault_type]
        log(f"  Progress {fault_type}: {done}/{target}")

    log("=" * 60)
    log(f"CAMPAIGN FINISHED: {state['completed']}/{total_target_runs(targets)} runs completed")
    log(f"By type: {state['completed_by_type']} (targets: {targets})")
    clear_all_faults()
    run_ssh(PE1_SSH, "pkill iperf3", quiet=True)
    export_prometheus_csv()
    validate_campaign_log(args.min_per_type)


if __name__ == "__main__":
    main()
