#!/usr/bin/env python3
"""DECA blind scorecard — open the seal and grade the run.

After the chaos scheduler and live operator have both stopped, this reconciles
what the network *actually* did (``ground_truth.sealed.jsonl``) against what the
models *declared* live (``declarations.jsonl``). For every real circumstance it
reports whether it was caught, how early (advisory + confirmed lead), whether
the class was right, how close the LSTM ETA was, and whether the declared
physical severity matched what actually happened. Benign near-misses and
un-matched alarms are tallied as false alarms.

Outputs:
- a text summary to the terminal,
- ``scorecard.json`` in the run directory,
- a Cursor Canvas (``deca-blind-test.canvas.tsx``) for the visual verdict.

Usage
-----
    python scripts/deca_blind_scorecard.py --run-id blind_2359
    python scripts/deca_blind_scorecard.py --run-id rehearsal --no-prom
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deca_live_common import (
    declarations_path,
    fetch_telemetry_long,
    ground_truth_path,
    live_run_dir,
    physical_severity,
    read_jsonl,
)

HEALTHY = "healthy"
POST_BREACH_GRACE_MIN = 8.0  # detection may confirm during the hold after breach
NEAR_MISS_GRACE_MIN = 3.0


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None when undefined (n<2 or a flat series)."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / (sxx**0.5 * syy**0.5), 3)


def first_active(host_decls: list[dict], a: datetime, b: datetime, tier: str):
    """Earliest moment ``tier`` (confirmed/advisory) is non-healthy within [a, b].

    Accounts for a sticky alarm that was already raised before the window opened
    (carry-over) by inspecting the last declaration prior to ``a``.
    """
    prev = None
    for d in host_decls:
        if parse_ts(d["ts"]) < a:
            prev = d
    if prev is not None and prev.get(tier, HEALTHY) != HEALTHY:
        return a, prev.get(tier), prev
    for d in host_decls:
        ts = parse_ts(d["ts"])
        if a <= ts <= b and d.get(tier, HEALTHY) != HEALTHY:
            return ts, d.get(tier), d
    return None


def actual_severity_bucket(host: str, start: datetime, end: datetime, *, use_prom: bool):
    if not use_prom:
        return None, None
    try:
        raw = fetch_telemetry_long(start, end)
    except Exception:
        return None, None
    if raw is None or len(raw) == 0:
        return None, None
    host_raw = raw[raw["host"] == host]
    sev = physical_severity(host_raw)
    if sev is None:
        return None, None
    return sev.bucket, sev.score


def grade(run_id: str, *, use_prom: bool, truth: list[dict] | None = None,
          decls: list[dict] | None = None) -> dict:
    # ``truth``/``decls`` let callers (self-check, tests) inject fixtures instead
    # of reading the sealed files — the reconciliation logic is identical.
    if truth is None:
        truth = read_jsonl(ground_truth_path(run_id))
    if decls is None:
        decls = read_jsonl(declarations_path(run_id))

    by_host: dict[str, list[dict]] = {}
    for d in decls:
        by_host.setdefault(d["host"], []).append(d)
    for host in by_host:
        by_host[host].sort(key=lambda d: parse_ts(d["ts"]))

    real_events = [e for e in truth if not e.get("is_near_miss")]
    near_misses = [e for e in truth if e.get("is_near_miss")]

    def next_event_start(host: str, after: datetime):
        """Start of the next event on the same host — used to clip detection windows
        so a later event's (or near-miss's) alarm can't be credited to this one."""
        later = [
            parse_ts(e["fault_start"])
            for e in truth
            if e["host"] == host and parse_ts(e["fault_start"]) > after
        ]
        return min(later) if later else None

    results = []
    matched_confirmed_windows = []  # (host, a, b) that legitimately explain an alarm

    for ev in real_events:
        host = ev["host"]
        fault_start = parse_ts(ev["fault_start"])
        breach = parse_ts(ev["breach_time"])
        raw_win_end = breach + timedelta(minutes=POST_BREACH_GRACE_MIN)
        # Explaining window (generous) keeps late-but-real alarms from being called
        # spurious; the detection window is clipped at the next event's onset.
        matched_confirmed_windows.append((host, fault_start, raw_win_end))
        ns = next_event_start(host, fault_start)
        win_end = min(raw_win_end, ns) if ns else raw_win_end
        host_decls = by_host.get(host, [])

        conf = first_active(host_decls, fault_start, win_end, "confirmed")
        adv = first_active(host_decls, fault_start, win_end, "advisory")

        detected = conf is not None
        predicted_class = conf[1] if conf else None
        # Scored on the FIRST confirmed declaration (what an operator would act on).
        class_correct = bool(predicted_class == ev["fault_type"])
        # Softer signal: did the confirmed tier EVER name the right class in-window?
        class_correct_eventually = any(
            d.get("confirmed") == ev["fault_type"]
            and fault_start <= parse_ts(d["ts"]) <= win_end
            and d["host"] == host
            for d in host_decls
        )
        # advisory_lead below is class-agnostic (any non-healthy advisory); this
        # flags whether that early advisory actually named the right class.
        advisory_class_correct = bool(adv is not None and adv[1] == ev["fault_type"])

        confirmed_lead = advisory_lead = None
        eta_pred = eta_actual = eta_err = None
        model_sev = model_sev_score = None
        if conf is not None:
            ts_det, _, d = conf
            confirmed_lead = round((breach - ts_det).total_seconds() / 60.0, 1)
            eta_pred = d.get("eta_minutes")
            eta_actual = round((breach - ts_det).total_seconds() / 60.0, 1)
            if eta_pred is not None:
                eta_err = round(eta_pred - eta_actual, 1)
            model_sev = d.get("severity_bucket")
            model_sev_score = d.get("severity_score")
        if adv is not None:
            advisory_lead = round((breach - adv[0]).total_seconds() / 60.0, 1)

        act_sev, act_sev_score = actual_severity_bucket(
            host, fault_start, breach + timedelta(minutes=POST_BREACH_GRACE_MIN), use_prom=use_prom
        )

        results.append(
            {
                "event_id": ev["event_id"],
                "fault_type": ev["fault_type"],
                "compound_group": ev.get("compound_group"),
                "host": host,
                "fault_start": ev["fault_start"],
                "breach_time": ev["breach_time"],
                "detected": detected,
                "predicted_class": predicted_class,
                "class_correct": class_correct,
                "class_correct_eventually": class_correct_eventually,
                "advisory_class_correct": advisory_class_correct,
                "confirmed_lead_min": confirmed_lead,
                "advisory_lead_min": advisory_lead,
                "eta_pred_min": eta_pred,
                "eta_actual_min": eta_actual,
                "eta_error_min": eta_err,
                "model_severity": model_sev,
                "model_severity_score": model_sev_score,
                "actual_severity": act_sev,
                "actual_severity_score": act_sev_score,
                "severity_match": (act_sev is not None and model_sev == act_sev),
            }
        )

    # False alarms on baited near-misses (should have stayed healthy).
    near_miss_fa = []
    for ev in near_misses:
        host = ev["host"]
        a = parse_ts(ev["fault_start"])
        b = parse_ts(ev["breach_time"]) + timedelta(minutes=NEAR_MISS_GRACE_MIN)
        matched_confirmed_windows.append((host, a, b))  # a confirm here is a FA, not spurious
        ns = next_event_start(host, a)
        det_b = min(b, ns) if ns else b
        hit = first_active(by_host.get(host, []), a, det_b, "confirmed")
        near_miss_fa.append(
            {
                "event_id": ev["event_id"],
                "host": host,
                "false_alarm": hit is not None,
                "class": hit[1] if hit else None,
            }
        )

    # Spurious confirmed raises outside every known window (real or near-miss).
    spurious = []
    for host, host_decls in by_host.items():
        for d in host_decls:
            if d.get("event") != "confirmed_raise":
                continue
            ts = parse_ts(d["ts"])
            inside = any(
                h == host and a <= ts <= b for (h, a, b) in matched_confirmed_windows
            )
            if not inside:
                spurious.append({"host": host, "ts": d["ts"], "class": d.get("confirmed")})

    n = len(real_events)
    detected = [r for r in results if r["detected"]]
    correct = [r for r in results if r["class_correct"]]
    correct_eventually = [r for r in results if r["class_correct_eventually"]]
    conf_leads = [r["confirmed_lead_min"] for r in results if r["confirmed_lead_min"] is not None]
    adv_leads = [r["advisory_lead_min"] for r in results if r["advisory_lead_min"] is not None]
    eta_errs = [abs(r["eta_error_min"]) for r in results if r["eta_error_min"] is not None]
    sev_scored = [r for r in results if r["actual_severity"] is not None and r["model_severity"] is not None]
    sev_match = [r for r in sev_scored if r["severity_match"]]

    def mean(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    # #6 — continuous severity: Pearson r between predicted and actual raw scores,
    # a stronger claim than coarse bucket agreement. Needs >=2 varied pairs.
    sev_pairs = [
        (r["model_severity_score"], r["actual_severity_score"])
        for r in results
        if r["model_severity_score"] is not None and r["actual_severity_score"] is not None
    ]
    severity_pearson_r = _pearson([p for p, _ in sev_pairs], [a for _, a in sev_pairs])

    nm_fa_count = sum(1 for x in near_miss_fa if x["false_alarm"])
    summary = {
        "run_id": run_id,
        "circumstances_created": n,
        "detected": len(detected),
        "detection_rate": round(len(detected) / n, 3) if n else None,
        "class_correct": len(correct),
        "class_accuracy": round(len(correct) / n, 3) if n else None,
        "class_correct_eventually": len(correct_eventually),
        "class_accuracy_eventually": round(len(correct_eventually) / n, 3) if n else None,
        "missed": n - len(detected),
        "compound_events": sum(1 for r in results if r.get("compound_group")),
        "near_misses": len(near_misses),
        "near_miss_false_alarms": nm_fa_count,
        "spurious_false_alarms": len(spurious),
        "mean_confirmed_lead_min": mean(conf_leads),
        "mean_advisory_lead_min": mean(adv_leads),
        "eta_mae_min": mean(eta_errs),
        "severity_scored": len(sev_scored),
        "severity_agreement": round(len(sev_match) / len(sev_scored), 3) if sev_scored else None,
        "severity_pearson_r": severity_pearson_r,
        "severity_pairs": len(sev_pairs),
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "severity_from_prometheus": use_prom,
    }
    return {
        "summary": summary,
        "events": results,
        "near_miss_false_alarms": near_miss_fa,
        "spurious_false_alarms": spurious,
    }


# ── Terminal report ───────────────────────────────────────────────────────
def print_report(report: dict) -> None:
    s = report["summary"]
    line = "=" * 68
    print(line)
    print(f"  DECA BLIND TEST SCORECARD — {s['run_id']}")
    print(line)
    print(f"  Circumstances the network created : {s['circumstances_created']}")
    print(f"  Detected by the models            : {s['detected']}  "
          f"(rate {s['detection_rate']})")
    print(f"  Correct fault class (first decl)  : {s['class_correct']}  "
          f"(accuracy {s['class_accuracy']})")
    print(f"  Correct class (ever, in-window)   : {s['class_correct_eventually']}  "
          f"(accuracy {s['class_accuracy_eventually']})")
    print(f"  Missed                            : {s['missed']}")
    print(f"  Mean confirmed lead before breach : {s['mean_confirmed_lead_min']} min")
    print(f"  Mean advisory lead before breach  : {s['mean_advisory_lead_min']} min  "
          f"(class-agnostic; 'something forming')")
    print(f"  LSTM ETA mean abs error           : {s['eta_mae_min']} min")
    print(f"  Severity bucket agreement         : {s['severity_agreement']}  "
          f"({s['severity_scored']} scored)")
    print(f"  Severity continuous Pearson r     : {s['severity_pearson_r']}  "
          f"({s['severity_pairs']} pairs)")
    print(f"  Near-miss false alarms            : {s['near_miss_false_alarms']} / {s['near_misses']}")
    print(f"  Spurious false alarms             : {s['spurious_false_alarms']}")
    print(line)
    print("  Per-circumstance:")
    for r in report["events"]:
        verdict = "HIT " if r["detected"] else "MISS"
        cls = "ok" if r["class_correct"] else f"->{r['predicted_class']}"
        cg = f" [cascade {r['compound_group'].split('_')[-1]}]" if r.get("compound_group") else ""
        print(f"   [{verdict}] {r['fault_type']:<18} {r['host']:<9} "
              f"lead(conf/adv)={r['confirmed_lead_min']}/{r['advisory_lead_min']}min "
              f"ETA={r['eta_pred_min']}/{r['eta_actual_min']} "
              f"sev={r['model_severity']}~{r['actual_severity']} {cls}{cg}")
    print(line)


# ── Canvas verdict ────────────────────────────────────────────────────────
def canvases_dir() -> Path:
    from _paths import REPO_ROOT

    slug = str(REPO_ROOT).strip("/").replace("/", "-")
    d = Path.home() / ".cursor" / "projects" / slug / "canvases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_canvas(report: dict) -> Path:
    payload = json.dumps(report, indent=2)
    tsx = _CANVAS_TEMPLATE.replace("__REPORT_JSON__", payload)
    out = canvases_dir() / "deca-blind-test.canvas.tsx"
    out.write_text(tsx, encoding="utf-8")
    return out


_CANVAS_TEMPLATE = r'''import {
  Stack, H1, H2, Text, Grid, Stat, Table, Callout, Divider, BarChart,
} from "cursor/canvas";

const REPORT = __REPORT_JSON__ as const;

const S = REPORT.summary;
const EVENTS = REPORT.events;

function pct(x: number | null): string {
  return x === null || x === undefined ? "n/a" : `${Math.round(x * 100)}%`;
}
function num(x: number | null | undefined, suffix = ""): string {
  return x === null || x === undefined ? "n/a" : `${x}${suffix}`;
}

export default function DecaBlindTest() {
  const detTone = (S.detection_rate ?? 0) >= 0.8 ? "success" : (S.detection_rate ?? 0) >= 0.5 ? "warning" : "danger";
  const faTotal = (S.near_miss_false_alarms ?? 0) + (S.spurious_false_alarms ?? 0);

  const leadCats = EVENTS.map((e: any) => e.fault_type);
  const confLeads = EVENTS.map((e: any) => e.confirmed_lead_min ?? 0);
  const advLeads = EVENTS.map((e: any) => e.advisory_lead_min ?? 0);
  const hasLeads = [...confLeads, ...advLeads].some((v: number) => v > 0);

  const rows = EVENTS.map((e: any) => [
    e.fault_type,
    e.host,
    e.detected ? "detected" : "missed",
    e.class_correct ? "correct" : (e.predicted_class ?? "-"),
    num(e.confirmed_lead_min, "m"),
    num(e.advisory_lead_min, "m"),
    num(e.eta_pred_min, "m"),
    num(e.eta_actual_min, "m"),
    `${e.model_severity ?? "-"} / ${e.actual_severity ?? "-"}`,
  ]);
  const rowTone = EVENTS.map((e: any) =>
    !e.detected ? "danger" : e.class_correct ? "success" : "warning",
  );

  return (
    <Stack gap={20}>
      <Stack gap={4}>
        <H1>DECA blind live-network test</H1>
        <Text tone="secondary" size="small">
          Run {S.run_id} · models flew blind on the Pi lab · graded {new Date(S.graded_at).toLocaleString()}
          {S.severity_from_prometheus ? "" : " · severity from live feed only (no Prometheus replay)"}
        </Text>
      </Stack>

      <Grid columns={4} gap={16}>
        <Stat value={String(S.circumstances_created)} label="Circumstances created" />
        <Stat value={`${S.detected}/${S.circumstances_created}`} label="Detected" tone={detTone as any} />
        <Stat value={pct(S.detection_rate)} label="Detection rate" tone={detTone as any} />
        <Stat value={pct(S.class_accuracy)} label="Class accuracy" />
      </Grid>
      <Grid columns={4} gap={16}>
        <Stat value={num(S.mean_confirmed_lead_min, "m")} label="Mean confirmed lead" tone="info" />
        <Stat value={num(S.mean_advisory_lead_min, "m")} label="Mean advisory lead" tone="info" />
        <Stat value={num(S.eta_mae_min, "m")} label="LSTM ETA mean abs error" />
        <Stat value={String(faTotal)} label="False alarms" tone={faTotal > 0 ? "warning" : "success"} />
      </Grid>

      {S.missed > 0 ? (
        <Callout tone="warning" title={`${S.missed} circumstance(s) missed`}>
          The network created faults the confirmed tier never declared within the detection window.
        </Callout>
      ) : (
        <Callout tone="success" title="Every circumstance was caught">
          The confirmed tier declared each injected fault before or during its breach window.
        </Callout>
      )}

      <Stack gap={8}>
        <H2>Per-circumstance verdict</H2>
        <Table
          headers={["Fault", "Host", "Detected", "Class", "Conf lead", "Adv lead", "ETA pred", "ETA actual", "Sev model/actual"]}
          rows={rows}
          rowTone={rowTone as any}
          columnAlign={["left", "left", "left", "left", "right", "right", "right", "right", "center"]}
        />
        <Text tone="tertiary" size="small">
          Lead = minutes before breach the tier declared. ETA = LSTM time-to-breach at declaration vs
          the true remaining time. Severity = physical-impact bucket (loss/jitter/throughput deviation).
        </Text>
      </Stack>

      {hasLeads ? (
        <Stack gap={8}>
          <H2>Warning lead time by circumstance</H2>
          <BarChart
            categories={leadCats}
            series={[
              { name: "Advisory lead", data: advLeads, tone: "warning" },
              { name: "Confirmed lead", data: confLeads, tone: "info" },
            ]}
            valueSuffix=" min"
          />
          <Text tone="tertiary" size="small">
            Minutes of warning before breach · higher is earlier · Source: declarations.jsonl
          </Text>
        </Stack>
      ) : null}

      <Divider />
      <Text tone="secondary" size="small">
        False alarms — near-miss bait: {S.near_miss_false_alarms}/{S.near_misses} · spurious: {S.spurious_false_alarms}.
        A well-behaved loom leaves benign near-misses healthy.
      </Text>
    </Stack>
  );
}
'''


def selfcheck() -> int:
    """Verify the judge's own logic against a fixture with hand-computed answers.

    Trust the model's output only as far as the grader is verified. This builds a
    synthetic run where every expected outcome is known, then asserts grade()
    reproduces it: a clean hit, an eventually-correct hit (wrong first class), a
    miss, a baited near-miss, and a spurious alarm outside all windows. No lab, no
    Prometheus (use_prom=False), no files — pure reconciliation logic.
    """
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def iso(minute):
        return (base + timedelta(minutes=minute)).isoformat()

    truth = [
        # E1: clean hit — confirmed 3 min before breach, right class.
        {"event_id": "E1", "fault_type": "congestion_breach", "host": "station1",
         "fault_start": iso(0), "breach_time": iso(10), "is_near_miss": False},
        # E2: wrong first class, corrects later (eventual-correct).
        {"event_id": "E2", "fault_type": "vrf_leakage", "host": "station2",
         "fault_start": iso(20), "breach_time": iso(30), "is_near_miss": False},
        # E3: miss — no declaration at all.
        {"event_id": "E3", "fault_type": "tunnel_degradation", "host": "station1",
         "fault_start": iso(40), "breach_time": iso(50), "is_near_miss": False},
        # NM: benign near-miss that the model wrongly confirms (false alarm).
        {"event_id": "NM", "fault_type": "near_miss", "host": "station2",
         "fault_start": iso(52), "breach_time": iso(53), "is_near_miss": True},
    ]
    decls = [
        {"ts": iso(6), "host": "station1", "event": "advisory_raise", "confirmed": "healthy",
         "advisory": "congestion_breach", "confidence": 0.6, "eta_minutes": 5.0,
         "severity_bucket": "medium", "severity_score": 0.5},
        {"ts": iso(7), "host": "station1", "event": "confirmed_raise", "confirmed": "congestion_breach",
         "advisory": "congestion_breach", "confidence": 0.9, "eta_minutes": 4.0,
         "severity_bucket": "high", "severity_score": 0.9},
        {"ts": iso(11), "host": "station1", "event": "confirmed_clear", "confirmed": "healthy",
         "advisory": "healthy", "confidence": 0.8, "eta_minutes": None,
         "severity_bucket": "low", "severity_score": 0.1},
        # E2: first confirmed is WRONG (congestion), then corrects to vrf_leakage.
        {"ts": iso(27), "host": "station2", "event": "confirmed_raise", "confirmed": "congestion_breach",
         "advisory": "congestion_breach", "confidence": 0.55, "eta_minutes": 3.0,
         "severity_bucket": "medium", "severity_score": 0.4},
        {"ts": iso(28), "host": "station2", "event": "confirmed_raise", "confirmed": "vrf_leakage",
         "advisory": "vrf_leakage", "confidence": 0.8, "eta_minutes": 2.0,
         "severity_bucket": "low", "severity_score": 0.2},
        {"ts": iso(31), "host": "station2", "event": "confirmed_clear", "confirmed": "healthy",
         "advisory": "healthy", "confidence": 0.8, "eta_minutes": None,
         "severity_bucket": "low", "severity_score": 0.1},
        # NM false alarm.
        {"ts": iso(52.4), "host": "station2", "event": "confirmed_raise", "confirmed": "vrf_leakage",
         "advisory": "vrf_leakage", "confidence": 0.7, "eta_minutes": 1.0,
         "severity_bucket": "low", "severity_score": 0.2},
        {"ts": iso(52.8), "host": "station2", "event": "confirmed_clear", "confirmed": "healthy",
         "advisory": "healthy", "confidence": 0.7, "eta_minutes": None,
         "severity_bucket": "low", "severity_score": 0.1},
        # Spurious: confirmed raise at min 60, outside every window.
        {"ts": iso(60), "host": "station1", "event": "confirmed_raise", "confirmed": "bgp_route_flap",
         "advisory": "bgp_route_flap", "confidence": 0.6, "eta_minutes": 2.0,
         "severity_bucket": "low", "severity_score": 0.2},
    ]

    rep = grade("selfcheck", use_prom=False, truth=truth, decls=decls)
    s = rep["summary"]
    ev = {e["event_id"]: e for e in rep["events"]}

    checks = [
        ("circumstances_created==3", s["circumstances_created"] == 3),
        ("detected==2", s["detected"] == 2),
        ("missed==1", s["missed"] == 1),
        ("class_correct(first)==1", s["class_correct"] == 1),
        ("class_correct_eventually==2", s["class_correct_eventually"] == 2),
        ("E1 detected & correct", ev["E1"]["detected"] and ev["E1"]["class_correct"]),
        ("E1 confirmed_lead==3.0", ev["E1"]["confirmed_lead_min"] == 3.0),
        ("E1 advisory_lead==4.0", ev["E1"]["advisory_lead_min"] == 4.0),
        ("E2 first-class wrong", not ev["E2"]["class_correct"]),
        ("E2 eventually correct", ev["E2"]["class_correct_eventually"]),
        ("E3 missed", not ev["E3"]["detected"]),
        ("near_miss_false_alarms==1", s["near_miss_false_alarms"] == 1),
        ("spurious==1", s["spurious_false_alarms"] == 1),
    ]
    ok = True
    print("=" * 60)
    print("  DECA scorecard self-check (verifying the judge)")
    print("=" * 60)
    for name, passed in checks:
        print(f"   [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("=" * 60)
    print("  RESULT:", "PASS — grader logic verified" if ok else "FAIL — grader logic is WRONG")
    print("=" * 60)
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Grade a DECA blind live-network test")
    parser.add_argument("--run-id", help="Live run id to grade")
    parser.add_argument("--no-prom", action="store_true",
                        help="Skip the Prometheus replay for actual severity (e.g. rehearsals)")
    parser.add_argument("--selfcheck", action="store_true",
                        help="Verify the grader's own logic on a synthetic fixture and exit")
    args = parser.parse_args()

    if args.selfcheck:
        raise SystemExit(selfcheck())

    if not args.run_id:
        parser.error("--run-id is required (or use --selfcheck)")

    if not ground_truth_path(args.run_id).exists():
        raise SystemExit(f"No sealed ground truth for run '{args.run_id}' at "
                         f"{ground_truth_path(args.run_id)}")

    report = grade(args.run_id, use_prom=not args.no_prom)
    out_json = live_run_dir(args.run_id) / "scorecard.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print_report(report)
    print(f"\n  scorecard.json -> {out_json}")
    try:
        canvas = write_canvas(report)
        print(f"  canvas         -> {canvas}")
    except Exception as exc:  # noqa: BLE001
        print(f"  (canvas render skipped: {exc})")


if __name__ == "__main__":
    main()
