#!/usr/bin/env python3
"""Write FINDINGS.md for compound_fix_round_2 from SUMMARY + replay artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import os

from _paths import MODELS_DIR

OUT = Path(
    os.environ.get(
        "COMPOUND_FIX_OUT",
        str(MODELS_DIR / "experiments" / "compound_fix_round_2"),
    )
)


def main() -> None:
    summary = json.loads((OUT / "SUMMARY.json").read_text())
    meta = json.loads((OUT / "campaign_meta.json").read_text())
    replay = json.loads((OUT / "live_faithful_replay.json").read_text())
    lake = summary.get("lake_fold", {})
    gate = summary.get("exam_gate", {})
    rises = summary.get("live_faithful_failing_legs", {})
    hard_stop = bool(summary.get("hard_stop"))

    lines = [
        "# Compound fix round 2 — findings",
        "",
        f"**Isolated to** `models/experiments/compound_fix_round_2/` · "
        f"**promoted untouched** (`{summary['promoted_untouched']['sha16_after']}`).",
        "",
        "## What was tried",
        "",
        f"- Campaign `{meta['run_id']}` with `--counts {meta.get('counts_cli')}`",
        f"- Rationale: {json.dumps(meta.get('rationale', {}), indent=2)}",
        f"- Logged fault types: `{meta.get('logged_fault_types')}`",
        f"- Lake fold after `rebuild_unified.py --all-rpi-runs`: "
        f"**{lake.get('campaign_rows', '?')}** rows; `_z_*` cols in lake: "
        f"**{lake.get('n_z_cols_in_lake', '?')}**; ortho `_z_*` present: "
        f"`{lake.get('ortho_z_cols_present', [])[:6]}`",
        f"- New-camp labels: `{lake.get('by_label')}`",
        "- Mixed retrain via `deca_school_exam_train` on the **full** lake "
        "(existing + new) — not new-rows-only.",
        "- No promote; candidate under `candidate/`.",
        "",
        "## Promotion gate (honest same-paper)",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Candidate macro-F1 | {gate.get('exam_macro_f1')} |",
        f"| Bar (max champion same-paper, manifest 0.717) | {gate.get('bar_macro')} |",
        f"| Champion same-paper macro-F1 | {gate.get('champion_same_paper_macro_f1')} |",
        f"| Rare recall | {gate.get('exam_rare_recall')} |",
        f"| Family / β | {gate.get('family')} / {gate.get('rare_boost')} |",
        f"| GATE | {'PASS' if gate.get('gate_passed') else 'FAIL'} |",
        "",
        "## Live-faithful before/after (failing legs)",
        "",
        "| Leg | Prior max p(truth) | Candidate max p(truth) | Δ | Diagnosis | Meaningful rise? |",
        "|---|---|---|---|---|---|",
    ]
    for k, v in rises.items():
        lines.append(
            f"| `{k}` | {v.get('prior_max')} | {v.get('new_max')} | "
            f"{v.get('delta')} | {v.get('diagnosis')} | {v.get('meaningful_rise')} |"
        )

    lines += [
        "",
        "### Full replay snapshot (candidate)",
        "",
    ]
    for k, v in replay.get("candidate", {}).items():
        lines.append(
            f"- `{k}`: max_p={v.get('max_p_truth')} mean_p={v.get('mean_p_truth')} "
            f"diag={v.get('diagnosis')} preds={v.get('pred_counts')}"
        )

    lines += ["", "### Promoted (frozen) replay on same windows", ""]
    for k, v in replay.get("promoted", {}).items():
        lines.append(
            f"- `{k}`: max_p={v.get('max_p_truth')} mean_p={v.get('mean_p_truth')} "
            f"diag={v.get('diagnosis')} preds={v.get('pred_counts')}"
        )

    lines += ["", "### Control FA rate (live-faithful)", ""]
    for tag, hosts in replay.get("control_fa", {}).items():
        lines.append(f"- **{tag}**: `{hosts}`")

    lines += ["", "## Verdict", ""]
    if hard_stop:
        lines += [
            "**Hard stop.** After this one time-boxed round, neither failing leg’s "
            "live-faithful p(truth) rose meaningfully above baseline.",
            "",
            "What was tried did not close the gap. This remains a documented, "
            "root-caused, time-boxed limitation: a compound class-imbalance / "
            "feature-interaction problem large enough that fully closing it would "
            "need more compound campaign volume than fits in the remaining timeline.",
            "",
            "No second round and no alternate weighting scheme proposed.",
        ]
    else:
        lines += [
            "At least one failing leg’s live-faithful p(truth) rose meaningfully. "
            "Candidate remains **unpromoted** — dry-run only. Compare gate + "
            "regression legs before any human promote decision.",
        ]

    lines += [
        "",
        "## Blind scoreboard",
        "",
        "| Window | Prior | This round |",
        "|---|---|---|",
        "| control | on record | see replay / notes |",
        "| tunnel+VRF | VRF miss (p≈0.15) | see table above |",
        "| BGP+VRF | BGP miss (p≈0.06) | see table above |",
        "",
        f"Promoted path unchanged: `{summary['promoted_untouched']}`.",
        "",
    ]
    (OUT / "FINDINGS.md").write_text("\n".join(lines))
    print(f"Wrote {OUT / 'FINDINGS.md'}")


if __name__ == "__main__":
    main()
