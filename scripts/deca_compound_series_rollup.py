#!/usr/bin/env python3
"""Write compound series rollup from /tmp/deca_compound_results.jsonl."""
from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path("/tmp/deca_compound_results.jsonl")
ROLLUP = Path("data/rpi-net/blind-tests/compound_series_20260719_rollup.md")


def main() -> None:
    results = []
    if RESULTS.is_file():
        for line in RESULTS.read_text().splitlines():
            if line.strip():
                results.append(json.loads(line))

    lines = [
        "# Compound series rollup — 2026-07-19",
        "",
        "Forced dual-fault: PE1 leg + `vrf_leakage` on station2 (`--compound-prob 1.0`).",
        "",
        "| PE1 leg | Run | Detect | Class | NM FA | Spur | Notes |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in results:
        s = r.get("summary", {})
        rid = r["run_id"]
        pe1 = r.get("pe1", "?")
        det = f"{s.get('detected', '?')}/{s.get('circumstances_created', '?')}"
        cls = s.get("class_accuracy")
        cls_s = f"{100 * cls:.0f}%" if isinstance(cls, (int, float)) else "?"
        nm = s.get("near_miss_false_alarms", "?")
        nm_n = s.get("near_misses", "?")
        spur = s.get("spurious_false_alarms", "?")
        notes = []
        for e in r.get("events") or []:
            ft = e.get("fault_type")
            if not e.get("detected"):
                notes.append(f"miss {ft}")
            elif e.get("predicted_class") != ft:
                notes.append(f"{ft}→{e.get('predicted_class')}")
        lines.append(
            f"| {pe1} | `{rid}` | {det} | {cls_s} | {nm}/{nm_n} | {spur} | "
            f"{'; '.join(notes) or '-'} |"
        )
    lines += ["", "Artifacts under `data/rpi-net/blind-tests/blind_compound_*`.", ""]
    ROLLUP.write_text("\n".join(lines))
    print(f"wrote {ROLLUP}")
    for r in results:
        s = r["summary"]
        print(
            f"  {r.get('pe1')}: detect {s.get('detected')}/{s.get('circumstances_created')} "
            f"spur {s.get('spurious_false_alarms')}"
        )


if __name__ == "__main__":
    main()
