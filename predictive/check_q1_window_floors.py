"""Post-campaign Q1 window-floor check (CAPTURE_CONTRACT).

L1/L4 were trimmed ×8→×4 on *repeat count* only. Loss LSTM at n=41 was a real
thin-class failure this week until densified — do not assume ×4 is fine without
counting usable train windows after the run lands.

Default floors (usable label_usable=True windows across the stamp):
  loss / jitter / latency: soft≥100, hard≥50 (near-41 = fail)
  util (schedule-gated): soft≥60, hard≥20
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .preprocess import align_1hz, ema_smooth
from .q1_windows import DEFAULT_LOSS_SLA_PCT, DEFAULT_SLA_MS, LOSS_COL, build_windows

# Soft = "comfortably above thin-class range"; hard = refuse to pretend it's OK
DEFAULT_FLOORS = {
    "latency": {"soft": 100, "hard": 50, "stride": 5},
    "loss": {"soft": 100, "hard": 50, "stride": 1},  # L4×4 trim requires densify
    "jitter": {"soft": 100, "hard": 50, "stride": 1},  # densify (PROMOTE path)
    "util": {"soft": 60, "hard": 20, "stride": 5},
}
JITTER_SLA_MS = 5.0


def _count_usable(
    series_paths: list[Path],
    *,
    target_col: str,
    sla: float,
    win: int = 30,
    stride: int = 5,
    schedule_gated_util: bool = False,
) -> dict:
    n = 0
    n_series = 0
    per: list[dict] = []
    for path in series_paths:
        if not path.exists():
            continue
        df = ema_smooth(align_1hz(pd.read_csv(path)), span=5)
        n_series += 1
        if schedule_gated_util:
            sched = path.parent / "util_ceil_schedule.jsonl"
            if not sched.exists():
                per.append({"path": str(path), "n": 0, "note": "missing schedule"})
                continue
            from .util_schedule import build_util_windows_contract

            w, meta = build_util_windows_contract(df, sched, win=win, stride=stride)
        else:
            w, meta = build_windows(df, win=win, stride=stride, sla=sla, target_col=target_col)
        usable = int((w["label_usable"] == True).sum()) if not w.empty else 0  # noqa: E712
        n += usable
        per.append(
            {
                "path": str(path),
                "n": usable,
                "breach_ts": meta.get("breach_ts") or meta.get("util_breach_ts"),
            }
        )
    return {"n_usable": n, "n_series": n_series, "per_series": per}


def check_stamp(
    root: Path,
    *,
    floors: dict | None = None,
    stride: int | None = None,
) -> dict:
    floors = floors or DEFAULT_FLOORS
    root = Path(root)
    l1 = sorted(root.glob("L1_*/iter_*/series.csv"))
    l4 = sorted(root.glob("L4_*/iter_*/series.csv"))
    l5 = sorted(root.glob("L5_*/iter_*/series.csv"))

    def _stride(head: str) -> int:
        if stride is not None:
            return int(stride)
        return int(floors[head].get("stride", 5))

    counts = {
        "latency": _count_usable(
            l1, target_col="latency_gre_ms", sla=DEFAULT_SLA_MS, stride=_stride("latency")
        ),
        "jitter": _count_usable(
            l1, target_col="jitter_gre_ms", sla=JITTER_SLA_MS, stride=_stride("jitter")
        ),
        "loss": _count_usable(
            l4, target_col=LOSS_COL, sla=DEFAULT_LOSS_SLA_PCT, stride=_stride("loss")
        ),
        "util": _count_usable(
            l5,
            target_col="util_gre_mbps",
            sla=1e9,
            stride=_stride("util"),
            schedule_gated_util=True,
        ),
    }

    failures: list[str] = []
    warnings: list[str] = []
    for head, floor in floors.items():
        n = int(counts[head]["n_usable"])
        soft, hard = int(floor["soft"]), int(floor["hard"])
        st = _stride(head)
        counts[head]["stride"] = st
        if n < hard:
            failures.append(
                f"{head}: n_usable={n} @stride={st} < hard={hard} "
                "(thin-class risk — loss@41 this week; densify or add variants)"
            )
        elif n < soft:
            warnings.append(
                f"{head}: n_usable={n} @stride={st} < soft={soft} "
                "(above hard floor but not comfortably dense)"
            )

    report = {
        "protocol_dir": str(root),
        "floors": floors,
        "counts": {
            k: {
                "n_usable": v["n_usable"],
                "n_series": v["n_series"],
                "stride": v.get("stride"),
            }
            for k, v in counts.items()
        },
        "detail": counts,
        "warnings": warnings,
        "failures": failures,
        "ok": len(failures) == 0,
        "note": (
            "Mandatory after L1/L4 ×4 trim. Loss/jitter default stride=1 densify. "
            "Prior pre-flight: loss×4 stride5≈25 (fail) · stride1≈115 (soft OK)."
        ),
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--protocol-dir", required=True, help="campaign stamp root")
    ap.add_argument("--out", default="", help="write JSON report (default: <dir>/Q1_WINDOW_FLOORS.json)")
    ap.add_argument("--stride", type=int, default=None, help="override all head strides (default: per-head)")
    ap.add_argument(
        "--fail-soft",
        action="store_true",
        help="exit 0 on soft warnings; still exit 1 on hard failures",
    )
    args = ap.parse_args()
    root = Path(args.protocol_dir).resolve()
    report = check_stamp(root, stride=args.stride)
    out = Path(args.out) if args.out else root / "Q1_WINDOW_FLOORS.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("ok", "counts", "warnings", "failures", "note")}, indent=2))
    print(f"wrote {out}")
    if report["failures"]:
        raise SystemExit(1)
    if report["warnings"] and not args.fail_soft:
        # warnings still exit 0 — soft floor is advisory
        pass


if __name__ == "__main__":
    main()
