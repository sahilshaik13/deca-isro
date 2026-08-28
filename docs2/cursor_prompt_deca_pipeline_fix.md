# Cursor task: close DECA lab gaps found in live verification (2026-07-29)

> **STATUS (2026-08-01):** Historical prompt. **Do not treat Gap 1 (Dual-P) as open work** —
> dual-P stays design-only by product choice (singular P satisfies PS13). Gaps 2–3
> (pathd / orchestrator systemd) were addressed separately; live truth is
> [`docs/DECA_SDWAN_PROCESS_FLOW.md`](docs/DECA_SDWAN_PROCESS_FLOW.md).

## Context
`docs/DECA_SDWAN_PROCESS_FLOW.md` documents the DECA SD-WAN/MPLS NOC copilot lab (PS13, Bharatiya Antariksh Hackathon). A verification pass today found the pipeline doesn't fully match what the docs/diagrams claim. Fix the actual system — don't just edit docs to hide the gap.

Read `docs/DECA_SDWAN_PROCESS_FLOW.md` §0 and §1 status table first for full current-state context before touching anything.

## Gap 1 — Dual-P CORE netns missing (CLOSED AS WONTFIX / design-only)
**Current:** `station3` runs as a single CORE (`10.1.3.1` on host `lo`) with two GRE legs (`gre-te-pe1`, `gre-te-pe2`). Design/bootstrap scripts exist for `CORE-NORTH`/`CORE-SOUTH` as separate network namespaces but they are not applied.
**Decision:** Leave single CORE. Dual-P is not required by PS13 literal text.

## Gap 2 — SR-TE / pathd not running
**Current:** `bash lab/deca_te_verify.sh` reports 1 pass / 9 fail. `pathd` is not among running FRR daemons. TED/SR-TE policy/BSID (40001/40002) checks fail.
**Target:** `bash lab/deca_te_verify.sh` full pass. `vtysh -c "show daemon"` lists `pathd` running. TED populated, SR-TE policies with BSID 40001/40002 active.
**Do:**
1. Check the FRR daemons config (`/etc/frr/daemons` or equivalent) — confirm `pathd=yes` is set and the daemon is actually enabled/started, not just configured in files.
2. Find and run (or fix) `ensure_te` referenced in the docs — this is supposed to bring pathd up; identify why it isn't doing so currently (missing service restart, wrong interface binding, config syntax error — check `pathd` logs first).
3. Confirm OSPF-TE is advertising TED info that pathd can consume (`show pathd ted` or equivalent) before checking policy/BSID status.
4. Do NOT attempt to add RSVP-TE — this lab intentionally uses OSPF-TE + SR-TE (pathd) only; FRR 10.6 doesn't support RSVP-TE and that's an accepted, documented boundary.

## Gap 3 — Orchestrator API down
**Current:** Q3 RAG code + Chroma DB are live on disk (144 chunks, 6 pinpoint SOPs), but the orchestrator FastAPI (`:8000`) was down at last check — meaning the Decide rail can't actually surface confidence score / playbook / Q3 merge to the UI even though the underlying pieces (Q1/Q2 gate, Q3 RAG) work individually.
**Target:** `:8000` orchestrator API is running and stays running (not just started manually and left to die) through a full demo cycle — inject fault → Decide card appears with confidence + ETA + root cause + playbook → Q3 English NLP merges async → Approve → controller `force_path` → recovery.
**Do:**
1. Start the orchestrator (`uvicorn` per the doc's launch instructions) and check why it went down — look for a crash in logs, not just "it wasn't started."
2. If it's not already, wire it into the same watchdog/systemd pattern used for the other DECA services (station1/station2 rc.local reference in project history) so it survives a reboot and restarts on crash — a manually-started uvicorn process that dies mid-demo is a real risk.
3. Confirm the full HITL sequence end-to-end (see `docs/DECA_SDWAN_PROCESS_FLOW.md` §2.2 sequence diagram) actually produces a populated Decide card in the UI, not just correct API responses via curl.

## Acceptance criteria — run these and paste output back
```bash
# Dual-P
ssh station3 'ip netns list'
ssh station3 'ip netns exec core-north vtysh -c "show mpls ldp neighbor"'
ssh station3 'ip netns exec core-south vtysh -c "show mpls ldp neighbor"'

# SR-TE
bash lab/deca_te_verify.sh          # expect full pass, not 1/9
vtysh -c "show daemon"              # pathd present
vtysh -c "show pathd te-policy"     # or equivalent — BSID 40001/40002 active

# Orchestrator
curl -sf http://127.0.0.1:8000/health   # or whatever health endpoint exists
# then run one full inject → Decide → Approve → recover cycle and confirm
# the Decide card shows: issue, confidence, ETA, root cause, playbook, Q3 NLP
```

## Constraints
- Don't touch or regress what's already verified working: LDP on GRE (confirmed operational today), Q1 LSTM / Q2 XGBoost live gate, Q3 RAG pipeline code.
- Don't add RSVP-TE.
- Once done, do NOT go back and mark things "Active" in the docs yourself — flag back to me with the command outputs above and I'll update `DECA_SDWAN_PROCESS_FLOW.md` §0/§1 to match the real, re-verified state.
