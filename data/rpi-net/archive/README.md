# Archive — non-essential lab / experiment clutter

Active (model-building) paths stay in place:

| Keep | Why |
| --- | --- |
| `data/processed/deca_unified_*.parquet` | Training lake |
| `data/rpi-net/runs/<campaign>/` (telemetry + fault logs) | Source for `rebuild_unified.py --all-rpi-runs` |
| `models/fault_classifier/` | Promoted model |
| `data/rpi-net/blind-tests/` scoreboard subset | Tier-5c blinds + foundational proofs |

This tree holds **historical detail only** — not required to rebuild or promote.

| Path | Contents |
| --- | --- |
| `data/rpi-net/archive/blind-tests/` | Intermediate compound rechecks, duplicate controls/specificity |
| `data/rpi-net/archive/live/` | Matching live/ copies of those archived blinds |
| `data/rpi-net/archive/runs_logs/` | Orchestrator/nohup logs (campaign dirs themselves stay active) |
| `data/processed/archive/` | Pre-rebuild `.bak` parquets + Tier A/B scale samples |
| `models/archive/experiments/` | Dry-run experiment trees (drowning diagnosis, compound fix r2/r3, Tier B) |

Scoreboards remain: `data/rpi-net/{blind-tests,live,runs}/CUMULATIVE.md` and `docs/results/`.
