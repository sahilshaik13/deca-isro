#!/usr/bin/env bash
# Alias entrypoint for Next.js / FastAPI Start Simulation button.
exec "$(cd "$(dirname "$0")" && pwd)/run_deca_orchestrator_sim.sh" "$@"
