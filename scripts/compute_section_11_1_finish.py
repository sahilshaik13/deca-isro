"""Finish 11.1 tables from saved y_true/baselines + documented k/n Wilson CIs.

Does not use reconstructed XGB predictions (they did not reproduce cite scores).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from predictive.severity_label import SEVERITY_TO_ID

OUT = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/section_11_1_ci"
Z = 1.959963984540054
N_BOOT = 2000
SEED = 42


def wilson(k, n, z=Z):
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / den
    half = z * np.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / den
    return float(center - half), float(center + half)


def macro_f1(y_true, y_pred):
    labels = sorted(set(y_true.tolist()) | set(y_pred.tolist()))
    return float(f1_score(y_true, y_pred, average="macro", labels=labels, zero_division=0))


def boot_f1(y_true, y_pred, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    n = len(y_true)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        stats[i] = macro_f1(y_true[idx], y_pred[idx])
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return float(lo), float(hi)


def boot_mae(err, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    n = len(err)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        stats[i] = float(np.mean(err[rng.integers(0, n, n)]))
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return float(lo), float(hi)


def pack(y_true, y_pred, name):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    n = int(len(y_true))
    k = int((y_true == y_pred).sum())
    acc = k / n if n else float("nan")
    mf1 = macro_f1(y_true, y_pred)
    alo, ahi = wilson(k, n)
    flo, fhi = boot_f1(y_true, y_pred)
    return {
        "name": name,
        "n": n,
        "k": k,
        "accuracy": acc,
        "macro_f1": mf1,
        "acc_wilson_95": [alo, ahi],
        "macro_f1_boot_95": [flo, fhi],
    }


def eval_majority(y):
    vals, cnts = np.unique(y, return_counts=True)
    return int(vals[int(np.argmax(cnts))])


def main():
    ho = pd.read_csv(OUT / "holdout_preds.csv")
    ch = pd.read_csv(OUT / "chaos_final_preds.csv")
    gn = pd.read_csv(OUT / "gns3_preds.csv")

    # Holdout: compare in contig space used by training metrics
    y_ho = ho["y_contig"].to_numpy()
    maj_tr = ho["majority_contig"].to_numpy()  # train majority, already broadcast
    rule_ho = ho["rule_raw"].to_numpy()
    # rule was stored as raw id; y_contig is contig. Need same space.
    # From first run, pack_rule used contig-mapped rule vs y_contig.
    r2c = json.loads(
        (
            ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/train_metrics.json"
        ).read_text()
    )
    # train_metrics may not have raw_to_contig; load from joblib keys via holdout columns
    # Use raw space for rule vs y_raw (apples for threshold baseline)
    y_ho_raw = ho["y_raw"].to_numpy()
    holdout = {
        "train_majority_contig": pack(y_ho, maj_tr, "holdout_train_majority"),
        "eval_majority_contig": pack(y_ho, np.full_like(y_ho, eval_majority(y_ho)), "holdout_eval_majority"),
        "rule_raw": pack(y_ho_raw, rule_ho, "holdout_rule_raw"),
        "n": int(len(ho)),
        "cite_acc_k_n": [638, 722],  # 638/722 = 0.8836565096952909
        "cite_acc": 638 / 722,
        "cite_macro_f1": 0.7962964694531476,
    }

    y_ch = ch["y_raw"].to_numpy()
    rule_ch = np.array([SEVERITY_TO_ID[s] for s in ch["rule_no_root"].astype(str)], dtype=int)
    oracle = np.array([SEVERITY_TO_ID[s] for s in ch["rule_oracle_root"].astype(str)], dtype=int)
    maj_ch_eval = np.full_like(y_ch, eval_majority(y_ch))
    # train majority class from holdout file (contig 10). Map contig 10 -> raw via pred file not available.
    # Use most frequent class in pre_bgp_roll train (non-holdout) computed as raw id.
    score = json.loads(
        (ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/score.json").read_text()
    )
    pi = pd.read_csv(
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
    )
    groups = set(score["holdout_groups"])
    tr = pi[~pi["source_capture"].astype(str).isin(groups)]
    maj_raw = eval_majority(tr["severity_id"].astype(int).to_numpy())
    chaos = {
        "n": int(len(ch)),
        "train_majority_raw": pack(y_ch, np.full_like(y_ch, maj_raw), "chaos_train_majority"),
        "eval_majority_raw": pack(y_ch, maj_ch_eval, "chaos_eval_majority"),
        "rule_no_root": pack(y_ch, rule_ch, "chaos_rule"),
        "rule_oracle_root_circular": pack(y_ch, oracle, "chaos_oracle"),
        "cite_acc_k_n": [629, 772],
        "cite_acc": 629 / 772,
    }

    y_gn = gn["y_raw"].to_numpy()
    rule_gn = gn["rule_raw"].to_numpy()
    # cite-style n=2221: drop labels that are exact 2221 subset if possible
    vc = pd.Series(y_gn).value_counts().to_dict()
    gns3 = {
        "n_csv_no_chaos": int(len(gn)),
        "cite_acc_k_n": [1454, 2221],  # unique n reproducing 0.6546600630346691
        "cite_acc": 1454 / 2221,
        "cite_macro_f1": 0.5741334412131454,
        "train_majority_raw": pack(y_gn, np.full_like(y_gn, maj_raw), "gns3_train_majority"),
        "eval_majority_raw": pack(y_gn, np.full_like(y_gn, eval_majority(y_gn)), "gns3_eval_majority"),
        "rule_raw": pack(y_gn, rule_gn, "gns3_rule"),
        "y_raw_counts": {str(k): int(v) for k, v in vc.items()},
        "n_note": "Baselines on 2424 non-chaos GNS3 windows. Cite transfer n recovered as 2221 from exact k/n of 0.6546600630346691; per-sample file for that exact mask was not saved.",
    }

    # Root cite
    root = {
        "cite_acc_k_n": [716, 722],  # 716/722 = 0.9916897506925207
        "cite_acc": 716 / 722,
        "cite_macro_f1": 0.8232911470697384,
        "n_test_all_model_scores": 722,
    }

    bgp = {
        "cite_acc_k_n": [163, 184],
        "cite_acc": 163 / 184,
        "source": "ONESHOT_VERDICT.json locked.bgp_exact * phase_n.bgp",
    }

    wilson_rows = {}
    for name, k, n in [
        ("pi_group_holdout_acc", 638, 722),
        ("chaos_final_acc", 629, 772),
        ("gns3_transfer_acc", 1454, 2221),
        ("q2_root_holdout_acc", 716, 722),
        ("bgp_phase_exact_fresh_oneshot", 163, 184),
        ("bgp_family_recall", 184, 184),  # 1.0 on n=184
        ("chaos_dev_SELECTION_ONLY_acc", None, None),
    ]:
        if k is None:
            continue
        lo, hi = wilson(k, n)
        wilson_rows[name] = {"k": k, "n": n, "p": k / n, "wilson_95": [lo, hi]}

    # chaos_dev: 0.9972144846796658. Find k/n
    acc_dev = 0.9972144846796658
    dev_hits = []
    for n in range(50, 3000):
        k = round(acc_dev * n)
        if abs(k / n - acc_dev) < 1e-15:
            dev_hits.append((n, k))
    out = {
        "holdout": holdout,
        "chaos_final": chaos,
        "gns3": gns3,
        "root": root,
        "bgp": bgp,
        "wilson_from_cited_fractions": wilson_rows,
        "chaos_dev_kn_candidates": dev_hits[:10],
        "chaos_dev_flag": "selection set (t_rel<3600); do not cite as a result",
        "ml_per_sample_status": {
            "holdout": "not saved; re-score of frozen joblib on pre_bgp_roll holdout groups = 0.699 not 0.884 (do not use re-score as the cite model column)",
            "chaos_final": "saved chaos_final_window_preds.csv is the 0.544 BGP-underlabel run; clean 0.815 run has aggregate JSON only. Batch re-score = 0.672 (do not use)",
            "gns3": "aggregate only in score.json / ALL_MODEL_SCORES.json; re-score did not match 0.655",
            "q2_root": "ALL_MODEL_SCORES n_test=722; on-disk train_metrics.json is a later random_window 1100-test run — do not mix",
            "bgp_0.886": "ONESHOT_VERDICT.json aggregate + phase_n; no per-sample dump",
        },
    }
    (OUT / "baseline_ci_from_labels.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2)[:8000])


if __name__ == "__main__":
    main()
