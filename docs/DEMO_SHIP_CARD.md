# DEMO SHIP CARD — frozen d2 (stop here)

**Status:** SHIP. Cite board LOCKED. Do not retrain / densify / chaos for promote before demo.

**Verified 2026-08-06:** frozen `q2_severity.joblib` loads; BGP specialist @0.85 loads; `infer_q1_q2_live` dry-run completes (Q1+Q2+specialist). Improvement chaos killed/ignored.

---

## Say these numbers (cite)

| Claim | Number |
| --- | ---: |
| Pi holdout (severity) | **0.884** |
| Chaos_final (one-shot, same model) | **0.815** |
| GNS3 transfer (Pi `d2` on twin) | **0.655** |
| Root-cause holdout | **0.992** |
| Q1 loss val MAE | **7.1 s** |
| BGP phase exact (fresh oneshot + specialist @0.85) | **0.886** |
| Overall with locked BGP specialist (fresh oneshot) | **0.823** |

**Model:** `data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib`  
**Pick:** `d2_e100_l6_mcw3`  
**BGP refine:** `protocol_models/bgp_3a3b_specialist/honest_threshold/bgp_3a3b_locked.joblib` (`min_3a_proba=0.85`)

Canonical dump: `data/deca/predictive/SCOREBOARD.json` · index: `docs/PREDICTIVE_MODEL_SCORES.md`

---

## One sentence each if asked (weak spots — not secrets)

- **BGP mild vs severe:** Family detection is strong; exact mild-flap grading is the softer part — we disclose it and ship a locked 3A/3B specialist rather than pretend 0.95.
- **GNS3 transfer:** Pi-primary demo; twin transfer is **0.655** on the same `d2` (shared-host CPU / CE-SLA texture gaps) — documented, not hidden.
- **Util on older dirty L5:** Pre-contract util captures were physically wrong; densify fixed physics. Cite board stays on frozen `d2`; do not swap cite numbers for unpromoted candidates mid-demo.

---

## Live infer (demo path)

```bash
cd /home/brain/deca-isro
export PYTHONPATH=/home/brain/deca-isro
.venv-predictive/bin/python -m predictive.infer_q1_q2_live \
  --q1-model data/deca/predictive/protocol_models/lstm_q1_unified/q1_tti_lstm.keras \
  --q1-scaler data/deca/predictive/protocol_models/lstm_q1_unified/q1_scaler.npz \
  --q2-model data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib \
  --bgp-specialist data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/bgp_3a3b_locked.joblib \
  --dry-run --seconds 30
```

**Pi ultimate demo (leave GNS3):** `bash scripts/demo_pi_bringup.sh`  
Then: Fabric=Pi → Simple fault button → Decide card → Approve (controller `:9280` → station1).  
Q3 (Phi-3 + Chroma RAG) enriches the card async (~1–2 min); Approve does not wait on it.

Jury dual-fabric script (optional): `docs/JURY_DUAL_FABRIC_DEMO.md`  
Dashboard: `http://localhost:3000` · API `:8000`

---

## Do not cite

0.101 · 0.533 · 0.544 · ~1838s loss MAE · circular remap · unpromoted util-clean / τ experiments as “the” score.

**Rule:** Ship frozen `d2`. Judges prefer honest 0.815 over a number that doesn’t reproduce live.
