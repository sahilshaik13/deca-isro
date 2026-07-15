---
tags:
  - deca
  - architecture
  - training
aliases:
  - Training Architecture
  - School Exam Architecture
cssclasses:
  - wide
---

# DECA — training architecture

How models are taught, tested, and promoted. Diagrams only — prose docs: `docs/DECA_MLOps_Continuous_Learning_Pipeline.md`.  
Models’ internals: [[DECA_Model_Architectures]]

---

## Continuous learning loop

```mermaid
flowchart TB
    subgraph lake["Data lake"]
        L["deca_unified_dataset.parquet"]
    end

    subgraph orch["Orchestrator (until PASS or max-cycles)"]
        direction TB
        R["① RANDOM PAPER<br/>fresh exam_seed → stratified holdout"]
        U["② TEST<br/>score active model"]
        T["③ TEACH<br/>β weight sweep on study rows"]
        E["④ EXAMINE<br/>score candidate on same paper"]
        S["⑤ SCORE / GATE<br/>Macro-F1 ≥ baseline ∧ rare-recall floor"]
        I["⑥ IMPROVE<br/>widen β · new questions next"]
        P["PROMOTE → models/fault_classifier/"]
        K["KEEP ACTIVE"]

        R --> U --> T --> E --> S
        S -->|PASS| P
        S -->|FAIL & cycles left| I
        I -->|new random seed| R
        S -->|FAIL & max cycles| K
    end

    L --> R
```

---

## One cycle (sequence)

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant A as Active model
    participant H as Study hall
    participant X as Exam paper
    participant G as Gate

    O->>X: Draw random stratified holdout
    O->>A: Unit TEST on exam paper
    A-->>O: Macro-F1 / rare-recall
    O->>H: TEACH — Phase-1 for each β
    Note over H: Never sees exam rows
    H-->>O: candidates + thresholds
    O->>X: EXAMINE candidates
    X-->>O: exam metrics
    O->>G: SCORE vs baseline
    alt PASS
        G-->>O: promote → stop
    else FAIL
        G-->>O: IMPROVE β + new paper
    end
```

---

## Study hall (weight adjust)

```mermaid
flowchart LR
    Pool["Study rows"] --> Fit["Fit / val split"]
    Fit --> W["w_i = N/(K·n_y)"]
    W --> B["× β on BGP / VRF"]
    B --> Gate["Gate XGB"]
    B --> Full["Full multiclass XGB"]
    Gate & Full --> Thr["Tune τ_gate, t_c on val"]
    Thr --> Cand["Candidate"]
```

---

## Promotion gate

```mermaid
flowchart TD
    C["Candidate Macro-F1"] --> Q{"≥ M* (manifest)?"}
    Q -->|no| F["FAIL → IMPROVE"]
    Q -->|yes| R{"Rare recall ≥ floor?"}
    R -->|no| F
    R -->|yes| P["PASS → PROMOTE"]
```

$$
\mathrm{PASS}\iff\mathrm{Macro\text{-}F1}\ge M^\star
\;\land\;
R_{\mathrm{rare}}\ge R_{\max}-\delta
$$

---

## Mode A vs Mode B

```mermaid
flowchart LR
    A["Mode A<br/>same lake"] --> Loop["Training loop"]
    B["Mode B<br/>finished campaign"] --> Ingest["rebuild_unified"] --> Loop
    Loop --> Out["promoted | exhausted_kept_active"]
```
