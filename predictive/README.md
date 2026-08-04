# DECA predictive analysis layer (Q1 + Q2 + protocol)

Live Prom (fabric-aware) → feature align → **shared Q1 LSTM** + **fabric-selected Q2 XGBoost** →
`infer_q1_q2_live.py` → Decide rail.

| Fabric | Prometheus | Env |
| --- | --- | --- |
| Pi | `http://127.0.0.1:9090` | `DECA_PROM_URL_PI` (legacy `DECA_PROM_URL`) |
| GNS3 | `http://127.0.0.1:9091` | `DECA_PROM_URL_GNS3` |

`prom_url_for_fabric()` in `predictive/prom_export.py` selects the base from active fabric
(`DECA_FABRIC` / `data/deca/active_fabric.json`).

## Unified dual-architecture models

| Stage | Policy |
| --- | --- |
| **Q1 LSTM** | Shared “blinking light” — train on **Pi**; GNS3 reuses weights after L1–L5 texture matches ([`shared_fault_book.json`](../docs/shared_fault_book.json)); **same** SLA thresholds |
| **Q2 XGBoost** | Fabric-selected severity head (`q2_pi` / `q2_gns3`) or one head with a `fabric` feature |
| **Training** | Do **not** mash Pi + GNS3 into one unlabeled CSV until inject shapes match |
| **Docs** | [`unified_dual_architecture_ml.md`](../deca-backend/runbooks/unified_dual_architecture_ml.md) · [predictive plan §2b](../docs/DECA_PREDICTIVE_ENGINE_PLAN.md) · fault book |

Today’s cutover still loads the **Pi-trained** Q2 until a GNS3-labeled head is trained; fabric switch already retargets Prom + SLAs.

## Protocol volumes

| Dataset | Pilot (default) | Full (`--full`) |
| --- | --- | --- |
| L0 healthy | 180 s | 24 h |
| L1 rain fade | 2 × ~160 s | 10 × 2 h |
| L2 CPU | 2 × ~120 s | 10 × 1 h |
| L3 BGP | 2 × ~120 s | 10 × 1 h |
| L4 loss progression | 2 × ~160 s | 8 × ~12 min (0→3.5% netem) |
| L5 util congestion | 2 × ~160 s | 8 × ~12 min (HTB 1:15 ToS 0x80) |
| Chaos (never train) | 240 s | 12 h |

Series schema v2 also captures `util_gre_mbps`, `ipsec_rekey_events_1h`, `ipsec_rekey_anomaly`, `path_asymmetry` (plus derived gre−eth0 asymmetry in preprocess).

**Active full stamp (Pi):** `20260729T202832Z` under `data/deca/predictive/protocol/` · resume: `resume_active_protocol.sh` · systemd `deca-protocol-campaign` + `deca-protocol-watchdog`.

### Dual protocol corpora (do not mash)

| Fabric | Data root | Prom | Orchestrator |
| --- | --- | --- | --- |
| **Pi** | `data/deca/predictive/protocol/<stamp>/` | `:9090` | `run_protocol_campaign.sh` |
| **GNS3** | `data/deca/predictive/protocol_gns3/<stamp>/` | `:9091` | `run_protocol_campaign_gns3.sh` |

GNS3 ACTIVE file: `protocol_gns3/ACTIVE_STAMP_GNS3.json` (never overwrites Pi `ACTIVE_STAMP.json`).  
Injectors: `lab/gns3/inject/*` · capture: `python -m predictive.capture_live --fabric gns3`.

```bash
# GNS3 pilot (~30–60 min) — parallel-safe with Pi :9090 campaign
DECA_FABRIC=gns3 bash predictive/run_protocol_campaign_gns3.sh --pilot
# Full later: bash predictive/run_protocol_campaign_gns3.sh --full
# Single label: bash predictive/run_q2_campaign_gns3.sh --label 1 --inject-sec 90
```

Train Q2 heads separately (`q2_pi` vs `q2_gns3`); shared Q1 LSTM stays Pi-trained.

```bash
python3 -m venv .venv-predictive && . .venv-predictive/bin/activate
pip install -r predictive/requirements.txt

# Pilot protocol (isolated faults + chaos) — Pi
bash predictive/run_protocol_campaign.sh
# Full multi-day: bash predictive/run_protocol_campaign.sh --full
# Resume after power-cut / pause:
bash predictive/resume_active_protocol.sh

# Build windows (preprocess + severity 1A/1B/1C…4A/4B/5A/5B)
.venv-predictive/bin/python -m predictive.build_protocol_dataset \
  --protocol-dir data/deca/predictive/protocol/<stamp>

# Train
.venv-predictive/bin/python -m predictive.train_q1_lstm \
  --data data/deca/predictive/protocol/<stamp>/dataset/q1_windows_train.csv \
  --out-dir data/deca/predictive/protocol_models/lstm_q1 --epochs 80
.venv-predictive/bin/python -m predictive.train_q2_xgb --severity \
  --data data/deca/predictive/protocol/<stamp>/dataset/q2_windows.csv \
  --out-dir data/deca/predictive/protocol_models/xgb_q2_sev

# Chaos eval (held-out)
.venv-predictive/bin/python -m predictive.eval_chaos \
  --chaos-dir data/deca/predictive/protocol/<stamp>/chaos \
  --q2-model data/deca/predictive/protocol_models/xgb_q2_sev/q2_severity.joblib \
  --q1-model data/deca/predictive/protocol_models/lstm_q1/q1_tti_lstm.keras \
  --q1-scaler data/deca/predictive/protocol_models/lstm_q1/q1_scaler.npz

# Live gate (cutover: latency + loss + jitter + util + Q2)
bash predictive/launch_infer_q1_q2_cutover.sh --seconds 0
```

## Severity tiers (Q2)

| Code | Meaning | Red HITL? |
| --- | --- | --- |
| 0 | normal | no |
| 1A | physical early 10–18 ms | yellow |
| 1B | physical critical 19–24 ms | yes |
| 1C | physical breach ≥25 ms | yes |
| 2A / 2B | CPU moderate / severe | 2B yes |
| 3A / 3B | BGP mild / severe rate | 3B yes |
| 4A / 4B | loss moderate / ≥2% SLA | 4B yes |
| 5A / 5B | util elevated / ≥35 Mbps | 5B yes |

## Preprocess

[`predictive/preprocess.py`](preprocess.py): 1 Hz align + linear interpolate → EMA(span=5) on drift metrics → optional z-score scaler → Q2 downsample / SMOTE.

## Outage / desktop power-cut

| Event | Behavior |
| --- | --- |
| Pis down, desktop up | `watch_protocol_capture.sh` pauses (SIGSTOP) until stations + Prom healthy |
| Desktop power-cut | On boot/login, `deca-protocol-campaign.service` runs `resume_active_protocol.sh` |
| Manual pause | `CAPTURE_PAUSE` latch + `manual: true` in `capture_paused.json` |

Health: `data/deca/predictive/protocol/<stamp>/capture_health.json`.
