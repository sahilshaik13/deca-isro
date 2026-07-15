# DECA MLOps Continuous Learning Pipeline

This is the **training methodology** for DECA — not “wait for more data then click retrain.”  
The stack already uses Phase‑1 gates / inverse‑frequency weights / thresholds; this pipeline adds a **School Exam** around that so you **adjust weights under a blind test + promotion gate** instead of trusting a single random split.

| Mode | When | New campaign data? |
| --- | --- | --- |
| **A — Same-lake School Exam** | **Now** (Tier‑6 still running / no time for another campaign) | No — hold out a blind slice of the **current** 17,050‑row lake |
| **B — Continuous training** | After `20260714_165648_tier6_x10` finishes | Yes — rebuild lake → re-exam → promote |

Related: [`MODELS.md`](MODELS.md) · [`DECA_ROI_TIERS.md`](DECA_ROI_TIERS.md) · [`notebook/DECA_Model_Training.ipynb`](../notebook/DECA_Model_Training.ipynb)

---

## Overview

Normal training: fit → report once on a **fixed** split the model can overfit across reruns.  
**School Exam training:** 

1. **New paper every sitting** — draw a **fresh** blind holdout (new questions) so the model cannot memorise last exam’s answers  
2. **Unit test** — score the *active* model on that new paper first  
3. **Study hall** — retrain with **recomputed / boosted** sample weights + threshold retune (**never** on exam rows)  
4. **Great exam** — score the candidate on the **same new paper**  
5. **Promote** only if the candidate beats `models/manifest.json` (Macro‑F1 **0.721** baseline)

No SMOTE. Weights change because class counts (or an explicit rare boost) change — that is the “adjust the weights” lever when you cannot inject more BGP/VRF faults yet.

### Anti-memorization rule (non-negotiable)

| Sitting | What changes |
| --- | --- |
| Every Mode A run | New `exam_seed` (default = UTC epoch) → new stratified random sample of each class for the quiz |
| Mode B (after campaign) | Entirely new physical fault windows — strongest “new questions” |
| Optional replay | `--exam-seed N` only when you need to re-grade one paper for audit |

Studying on the exam set is forbidden. If the same fixed split were reused every night, the stack would memorize that paper; the gate would lie.

---

## The School Exam Methodology

### 1. Unit Test (blind — new questions)

Hold out a slice the train loop must **not** see while studying.

| Mode A (now) | Mode B (after campaign) |
| --- | --- |
| **Random stratified** per-class holdout (default); optional `time_tail` for drift stress | New campaign export windows (literally new lab questions) |

Report recall / precision on BGP + VRF especially (“quiz on scarce faults”).

### 2. Study Hall (weight adjust + retrain)

- Rebuild feature matrix only if Mode B (new run id). Mode A **skips** ingest — lake already on disk.  
- Refit Isolation Forest + Phase‑1 XGB (+ optional LSTM).  
- Apply **inverse‑frequency weights** + optional rare boost $\beta$ (formulas below).  
- Retune gate / class thresholds on an inner val split (Tier 3). Sweep $\beta \in \{1.0, 1.5, 2.0, 3.0\}$ under the **same** new paper.

### 3. Great Exam + promotion gate

Score the candidate on the **same** blind paper. **Pass** only if Macro‑F1 and rare‑recall guardrails clear (formulas below) → write `models/` + update manifest. **Fail** → keep previous artifacts.

---

## Formulas

### Exam paper (anti‑memorization)

For each class $c$ with support $n_c$ on the lake, hold out

$$
n_c^{\mathrm{exam}} = \max\bigl(1,\ \lfloor \alpha\, n_c \rfloor\bigr)
\quad\text{when } n_c \ge 2
$$

with holdout fraction $\alpha$ (default $0.2$). Under `random`, draw those rows with a fresh `exam_seed` each sitting. Remainder = study hall. Studying never touches exam indices.

### Inverse‑frequency weights + rare boost

Fit‑set size $N$, $K$ classes, class counts $n_c$:

$$
w_i = \frac{N}{K \cdot n_{y_i}}
$$

Optional Mode‑A / Mode‑B lever on scarce faults:

$$
w_i' =
\begin{cases}
w_i \cdot \beta & \text{if } y_i \in \{\texttt{bgp\_route\_flap},\ \texttt{vrf\_leakage}\} \\
w_i & \text{otherwise}
\end{cases}
$$

### Tier‑1 gate + Tier‑3 prediction

Binary gate target $y^{\mathrm{bin}} = \mathbf{1}[y \neq \texttt{healthy}]$. After scoring:

$$
\hat{y}(x) =
\begin{cases}
\texttt{healthy} & \text{if } P(\mathrm{anomaly}\mid x) < \tau_{\mathrm{gate}} \\
\displaystyle\arg\max_{c}\, \dfrac{p_c(x)}{t_c} & \text{otherwise}
\end{cases}
$$

where $t_c$ are validation‑tuned per‑class divisors.

### Rare‑aware validation score (threshold sweep)

On the inner val split, pick $(\tau_{\mathrm{gate}}, \{t_c\})$ that maximizes

$$
S = 0.4\cdot\mathrm{Macro\text{-}F1} + 0.6\cdot\overline{F1}_{\mathrm{rare}}
$$

with “rare” = BGP + VRF (and other low‑support faults in notebook Tier‑3).

### Precision, recall, F1, Macro‑F1

For class $c$ (true $=\mathrm{TP}_c+\mathrm{FN}_c$, predicted $=\mathrm{TP}_c+\mathrm{FP}_c$):

$$
\mathrm{Precision}_c = \frac{\mathrm{TP}_c}{\mathrm{TP}_c+\mathrm{FP}_c},\quad
\mathrm{Recall}_c = \frac{\mathrm{TP}_c}{\mathrm{TP}_c+\mathrm{FN}_c},\quad
F1_c = \frac{2\cdot\mathrm{Precision}_c\cdot\mathrm{Recall}_c}{\mathrm{Precision}_c+\mathrm{Recall}_c}
$$

$$
\mathrm{Macro\text{-}F1} = \frac{1}{K}\sum_{c=1}^{K} F1_c
$$

### Promotion gate

Let $M^\star$ = baseline Macro‑F1 from `models/manifest.json` (≈ **0.721**), $R$ = mean BGP+VRF recall on the exam, $R_{\max}$ = best mean rare recall among this sitting’s $\beta$ sweep, $\delta$ = `--min-rare-recall-drop` (default soft slack).

$$
\mathrm{GATE} =
\begin{cases}
\mathrm{PASS} & \text{if }\ \mathrm{Macro\text{-}F1}_{\mathrm{cand}} \ge M^\star
\ \land\
R \ge R_{\max}-\delta \\
\mathrm{FAIL} & \text{otherwise}
\end{cases}
$$

---

## Mode A — run now (no new data)

Script: [`scripts/deca_school_exam_train.py`](../scripts/deca_school_exam_train.py)

```bash
cd /home/brain/deca-isro
source .venv/bin/activate

# New exam paper every run (fresh seed) + weight sweeps — does NOT overwrite models/
python scripts/deca_school_exam_train.py

# Replay one paper for audit
python scripts/deca_school_exam_train.py --exam-seed 42

# Drift-hard quiz (latest per class) still with a fresh seed for which rows if combined later
python scripts/deca_school_exam_train.py --holdout-policy time_tail

# Promote only if GATE PASS
python scripts/deca_school_exam_train.py --promote
```

| Flag | Meaning |
| --- | --- |
| `--holdout-frac` | Per-class fraction held blind (default `0.2`) |
| `--holdout-policy` | `random` (default, new questions) or `time_tail` |
| `--exam-seed` | Fix the paper; **omit** for a new paper every sitting |
| `--rare-boosts` | Comma list of $\beta$ to sweep (default `1,1.5,2,3`) |
| `--promote` | Write best candidate into `models/` if gate passes |
| `--baseline-macro-f1` | Override baseline (default: read manifest or `0.721`) |

**What you get without waiting for Tier‑6:** another way to squeeze Tiers 1–3 on the lake you already have — correct weights / thresholds under a promotion gate — instead of hoping a single notebook Run All is the best operating point.

---

## Mode B — after the campaign finishes

1. Wait for `data/rpi-net/runs/20260714_165648_tier6_x10/` to write `network_telemetry.csv` + `network_campaign_export.csv`  
2. Point `RPI_RUN` in `rebuild_unified.py` at that run id  
3. `python scripts/rebuild_unified.py`  
4. Re-run Mode A script (or notebook) — inverse‑frequency weights **automatically** shift as BGP/VRF support grows; optional $\beta$ still available  
5. Promote only if exam clears the new gate  

That is the full “continuous learning” path from this document; Mode A is the same exam **without** the ingest step.

---

## Pipeline steps (target orchestrator)

When `deca_mlops_orchestrator.py` exists, it will wrap Mode B end‑to‑end. Until then Mode A’s script is the concrete exam.

| Step | Action |
| --- | --- |
| 1 Unit test | Score active model on blind holdout / new campaign windows |
| 2 Ingest | Mode B only — `rebuild_unified.py` |
| 3 Study | Headless Phase‑1 (+ IF; optional LSTM) with weight adjust |
| 4 Exam + gate | Compare to `manifest.json`; promote or discard |

### Mixture sandbox (later)

Overlapping faults in `deca_fault_campaign.py` (congestion ∧ VRF). Great exam for compound signatures — **after** Tier‑6 volume exists.

---

## Honest expectations

- Mode A **can** lift Macro‑F1 / rare F1 a bit by better $\beta$ + thresholds; it **cannot** invent BGP/VRF physics you do not have — that remains Tier‑6.  
- If every $\beta$ fails the gate, keep the current **0.721** stack; that is a successful exam, not a failure.  
- Notebook Stage 2 already is Study Hall for one default $\beta=1$; Mode A is the exam harness around that idea.
- **First Mode A dry-run on this lake:** all $\beta\in\{1,1.5,2,3\}$ **failed** the promotion gate (best exam Macro‑F1 ≈ **0.52** vs baseline **0.721**). That is expected: the blind holdout is a harder *time-tail* slice than the notebook’s random 25% split, and boosting weights without new rare-fault physics does not clear the gate. Leave `--promote` off until Tier‑6 grows the lake (or until a sweep clearly beats baseline on the exam).
