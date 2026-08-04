# DECA Orchestrator Dashboard

**DECA** is the Flow 3 orchestrator UI: live Decide rail + Q3 NLP + human-gated SD-WAN steers, with SQLite audit history.

## What talks to what

```
Prometheus (Pi :9090 | GNS3 :9091 by fabric) → shared Q1 LSTM + fabric Q2 head → seed-preemption
                ↘
Prometheus → DECA FastAPI → SQLite → Next.js Decide (:3000)
                              ↓ (Approve)
              Controller :9280  soft-clear? → force_path
                              ↘ async Q3 Phi-3 + Chroma (deca_lnc)
```

**Models:** shared LSTM blinking light; XGBoost severity head selected by fabric
([`unified_dual_architecture_ml.md`](deca-backend/runbooks/unified_dual_architecture_ml.md)).
Prometheus remains the live TSDB (**two instances** — see dual Flow 2). SQLite stores runs, ticks, alerts, Q&A, and action audit — not time-series. Fabric selector: `GET/POST /api/v1/fabric`.

## Underlay topology (as-built)

**station3 is a single CORE** (`10.1.3.1`) with GRE legs to PE1/PE2. Dual-P netns scripts (`lab/deca_dual_core_*.sh`) exist but are **not applied** — do not claim CORE-NORTH/SOUTH unless `ip netns list` shows them.

| Role | Host | Notes |
|------|------|-------|
| PE1 | station1 | NRSC `ce-a` + Mauritius `ce-mauritius` · HTB/IPsec/inject |
| PE2 | station2 | SAC `ce-b` + MCF `ce-mcf` |
| P | station3 | OSPF + LDP + BGP RR · pathd SR-TE |

## Prerequisites

- Lab Python venv: `.venv/` (FastAPI / uvicorn)
- Node ≥ 20 (repo ships `.tools/node-v20…` used by frontend scripts)
- SD-WAN controller on `:9280` (`lab/deca_sdwan_controller.py`) with ISRO QoS labels (`ttc` / `payload`)
- Optional: a live or replay `--run-id` under `data/rpi-net/live/<run_id>/`

## Start backend

```bash
cd deca-backend
# Light mode (orchestrator endpoints; skip eager GGUF/Chroma). Ask still lazy-loads CopilotEngine.
DECA_HEAVY_INIT=0 ../.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Full Prom ML dashboard path:
# DECA_HEAVY_INIT=1 ../.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

SQLite file: `data/deca/deca_orchestrator.db` (created on startup; gitignored).

Useful env:

| Var | Default | Meaning |
|-----|---------|---------|
| `DECA_ORCHESTRATOR_DB` | `data/deca/deca_orchestrator.db` | SQLite path |
| `DECA_SDWAN_CONTROLLER_URL` | `http://127.0.0.1:9280` | Controller metrics + `/action` |
| `DECA_HEAVY_INIT` | `0` | Eager GGUF + Chroma for `/dashboard` ML |
| `DECA_COPILOT_SKIP_RAG` | `1` | Ask path honesty (no Chroma) |

## Start frontend

```bash
cd deca-frontend
cp .env.example .env.local   # if needed; points at :8000
npm run dev                  # http://localhost:3000
```

Browser calls `/api/deca/*` which proxies to `DECA_API_URL` `/api/v1/*`.

## Bind a run

In the UI run selector, or:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"blind_pd_originlock_20260724_1614","mode":"replay"}'
```

## API surface

| Method | Path | Role |
|--------|------|------|
| GET | `/api/v1/fleet` | ISRO sites + host ticks + TT&C/Payload path state |
| GET | `/api/v1/alerts` | Active + history from SQLite (ingests declarations) |
| POST | `/api/v1/ask` | Responder Q&A → `queries` table (`CopilotEngine(skip_rag=True)`) |
| POST | `/api/v1/actions/{id}/approve` | Audit + budgeted sequence (`bgp_soft_clear` then `force_path` when applicable) |
| POST | `/api/v1/actions/{id}/reject` | Audit only |
| GET/POST | `/api/v1/runs` | List / bind run context |
| GET | `/api/v1/history` | alerts / queries / actions |
| POST | `/api/v1/simulation/start` | Background `scripts/run_simulation.sh` (Phases 0–6) |
| GET | `/api/v1/simulation/status` | Phase / HITL wait / log tail |
| POST | `/api/v1/simulation/stop` | Stop flag + SIGTERM process group |
| POST | `/api/v1/simulation/seed-preemption` | Phase 4: insert "Impending Congestion" alert for Approve |
| GET | `/health` | liveness |

## Lab simulation (Start button)

UI **Lab simulation → Start** calls `POST /api/v1/simulation/start`, which spawns
`scripts/run_simulation.sh` (~4 minutes):

| Phase | T≈ | Action |
|-------|----|--------|
| 0 | 0s | iperf3 receivers on station2 `sac-srv` (:5004/:5006/:5201) |
| 1 | 5s | TT&C / Payload / Bulk clients from station1 (DSCP EF/AF41) |
| 2 | 30s | Soft netem (~40 ms) → TT&C red, Payload green, `policy_conflict` |
| 3 | 60s | Hard netem + loss → `enter_k=3` steer to eth0 |
| 4 | 120s | Clear netem; congestion ramp; seed preemption alert; **wait Approve** (90s) |
| 5 | 180s | `clear_force`; wait `exit_k=10` recovery toward GRE (~50s) |
| 6 | 240s | Kill iperf + clear qdiscs; `reset_autonomy` |

Use **Dry run** (`{"dry":true}`) to advance the timeline without SSH when stations are offline.

Policy catalog: [`docs/DECA_SDWAN_POLICY_RULES.md`](docs/DECA_SDWAN_POLICY_RULES.md).
Orchestrator Preemption: predictive alert ($T_{breach}$ &lt; 180s) + Approve →
`POST /action` `force_path` before SLA breach.

## Controller gate

`lab/deca_sdwan_controller.py` exports:

- Metrics: `class="ttc"|"payload"` (dual-export `voice`/`video` aliases for the ML lake)
- **Classification:** TT&C ToS `0x88` (136) · Payload ToS `0x80` (128) · Admin BE/`0x00` on `vrf-admin`→eth0
- **HTB:** `1:10` LLQ · `1:15` ~70% + RED@85% · `1:20` scavenger (`lab/deca_htb_qos.sh`)
- **AAR SLA:** TT&C ≤25 ms / ≤5 ms / ≤0.1%; Payload ≤80 / ≤15 / ≤2%; Admin none
- **Steer:** `gre-te-core` (OSPF 5) preferred, `eth0` (OSPF 50) backup; TT&C preempts; BE never steers
- **Hysteresis:** `ENTER_K=3`, `EXIT_K=10`
- **Traffic:** iperf3 only — **no Cisco TRex** (`lab/deca_iperf_qos_traffic.sh`)
- **IPsec:** `copy_dscp = out` (`lab/swanctl/`)
- `POST /action` **localhost only**: `{ "op": "force_path"|"clear_force"|"reset_autonomy"|"bgp_soft_clear", ... }`
  - `bgp_soft_clear` = **remediation one-shot** (not the multi-cycle flap inducer)

Restart the controller after pulling so `/action` and SLA constants are live.

## Live predictive gate

```bash
bash predictive/launch_infer_q1_q2_cutover.sh --seconds 0
```

See [`docs/DECA_SDWAN_PROCESS_FLOW.md`](docs/DECA_SDWAN_PROCESS_FLOW.md).

## Smoke checklist

1. Backend `/health` → ok  
2. Select a run with `declarations.jsonl` → alerts appear  
3. Ask “is NRSC healthy?” → answer + SQLite `queries` row  
4. Approve an actionable alert → SQLite `actions` + controller ack  
5. UI topology shows MCF / SAC / NRSC / Mauritius / CORE  

## Explicit non-goals (this cut)

- No classifier retune / pickle edits  
- No Kafka / TRex / auto-remediate without Approve  
- RAG stays off by default on the orchestrator ask path  
