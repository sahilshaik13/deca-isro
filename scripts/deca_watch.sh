#!/usr/bin/env bash
# =============================================================================
# DECA Live Watcher — backend-owned live view of orchestrator state
# Spawned by deca-backend terminal_manager (tab "6. Live Watch").
# Manual: bash scripts/deca_watch.sh
# =============================================================================

API="${DECA_API_URL:-http://127.0.0.1:8000}"
INTERVAL="${DECA_WATCH_INTERVAL:-2}"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
MAG='\033[0;35m'
WHT='\033[1;37m'
DIM='\033[2m'
RST='\033[0m'
BOLD='\033[1m'

sep() { printf "${DIM}────────────────────────────────────────────────────────${RST}\n"; }

active_run() {
  curl -sf "$API/api/v1/runs" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('sim-live')
    raise SystemExit
print(d.get('active_run_id') or 'sim-live')
" 2>/dev/null || echo "sim-live"
}

while true; do
    clear
    RUN_ID="$(active_run)"
    echo -e "${BOLD}${CYN}╔══════════════════════════════════════════════════════╗${RST}"
    echo -e "${BOLD}${CYN}║        DECA NOC — Live System Watcher (backend)      ║${RST}"
    echo -e "${BOLD}${CYN}║  API $API · every ${INTERVAL}s · Ctrl+C stop            ║${RST}"
    echo -e "${BOLD}${CYN}╚══════════════════════════════════════════════════════╝${RST}"
    echo -e "  ${DIM}$(date '+%Y-%m-%d %H:%M:%S') · run_id=${RUN_ID}${RST}\n"

    # ── 1. FAULT INJECTION STATUS ────────────────────────────────────────────
    echo -e "${BOLD}${YLW}[1] FAULT INJECTION${RST}"
    sep
    FAULT=$(curl -sf "$API/api/v1/faults/status" 2>/dev/null)
    if [ -z "$FAULT" ]; then
        echo -e "  ${RED}Backend unreachable at $API${RST}"
    else
        RUNNING=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('running','?'))")
        FAULT_ID=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fault_id') or 'none')")
        PHASE=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('phase') or '-')")
        MSG=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message') or '')")
        FABRIC=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('active_fabric') or d.get('fabric') or '?')")
        STARTED=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('started_at') or '-')")

        if [ "$RUNNING" = "True" ] || [ "$PHASE" = "injecting" ] || [ "$PHASE" = "seeded" ]; then
            echo -e "  Status  : ${RED}● LIVE${RST}  phase=${PHASE}"
        elif [ "$PHASE" = "recovering" ]; then
            echo -e "  Status  : ${YLW}● RECOVERING${RST}  phase=${PHASE}"
        else
            echo -e "  Status  : ${GRN}● idle${RST}  phase=${PHASE}"
        fi
        echo -e "  Fault   : ${WHT}$FAULT_ID${RST}"
        echo -e "  Fabric  : ${BLU}$FABRIC${RST}"
        echo -e "  Started : ${DIM}$STARTED${RST}"
        echo -e "  Message : ${YLW}$MSG${RST}"

        echo ""
        echo -e "  ${MAG}▸ Q1/Q2 model detection:${RST}"
        echo "$FAULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
m = d.get('model_detection') or {}
print(f\"    Severity     : {m.get('severity') or '-'}\")
print(f\"    Confidence   : {m.get('q2_confidence') or '-'}\")
print(f\"    ETA (min)    : {m.get('eta_minutes') or '-'}\")
print(f\"    Raise        : {m.get('raise') if m.get('raise') is not None else '-'}\")
print(f\"    Fault Match  : {m.get('matches_demo_fault') or '-'}\")
print(f\"    Explanation  : {str(m.get('explanation') or '')[:120]}\")
" 2>/dev/null

        echo ""
        echo -e "  ${MAG}▸ Inject log (last 5):${RST}"
        echo "$FAULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for line in (d.get('log_tail') or [])[-5:]:
    print('    ' + str(line))
" 2>/dev/null
    fi

    echo ""

    # ── 2. ACTIVE ALERTS (Decide Rail) ─────────────────────────────────────
    echo -e "${BOLD}${RED}[2] ACTIVE ALERTS — Decide Rail${RST}"
    sep
    ALERTS=$(curl -sf "$API/api/v1/alerts?run_id=${RUN_ID}" 2>/dev/null)
    if [ -z "$ALERTS" ]; then
        echo -e "  ${DIM}No data${RST}"
    else
        echo "$ALERTS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
active = d.get('active') or []
if not active:
    print('  (no active alerts)')
for a in active[-3:]:
    p = a.get('payload') or {}
    title = p.get('title') or a.get('title') or ''
    conf = a.get('confidence')
    if conf is None:
        conf = p.get('confidence', '-')
    eta = a.get('eta')
    if eta is None:
        eta = p.get('eta_minutes', '-')
    print(f\"  Alert #{a.get('id')}  class={a.get('class')}  status={a.get('status')}\")
    print(f\"    Title      : {str(title)[:80]}\")
    print(f\"    Severity   : {p.get('severity','-')}   Confidence: {conf}\")
    print(f\"    ETA (min)  : {eta}\")
    print(f\"    Root cause : {p.get('root_cause','-')}\")
    print(f\"    eta_source : {p.get('eta_source','-')}\")
    print(f\"    Q3 NLP     : {str(p.get('q3_nlp',''))[:100]}\")
    print()
" 2>/dev/null
    fi

    echo ""

    # ── 3. LAST APPROVE / REJECT ACTION ────────────────────────────────────
    echo -e "${BOLD}${GRN}[3] LAST ACTION — Controller / HITL${RST}"
    sep
    HIST=$(curl -sf "$API/api/v1/history?run_id=${RUN_ID}" 2>/dev/null)
    if [ -z "$HIST" ]; then
        echo -e "  ${DIM}No history yet${RST}"
    else
        echo "$HIST" | python3 -c "
import sys, json
d = json.load(sys.stdin)
actions = d.get('actions') or []
if not actions:
    print('  (no actions yet — Approve/Reject via API or NOC UI)')
else:
    a = actions[-1]
    result = a.get('result') or {}
    print(f\"  Action     : {str(a.get('action','?')).upper()}  alert_id={a.get('alert_id')}\")
    print(f\"  Timestamp  : {a.get('created_at') or a.get('ts') or '?'}\")
    print(f\"  Overall OK : {result.get('ok','-')}\")
    print(f\"  Wall clock : {result.get('wall_clock_sec','-')} sec\")
    print()
    for step in (result.get('sequence') or []):
        ok_str = 'OK' if (step.get('result') or {}).get('ok') else 'FAIL'
        op = step.get('op') or '?'
        print(f\"    Step: {op:20s}  budget={step.get('budget_sec')}s  elapsed={step.get('elapsed_sec')}s  [{ok_str}]\")
        ctrl = step.get('result') or {}
        print(f\"           → controller: {str(ctrl)[:100]}\")
" 2>/dev/null
    fi

    echo ""

    # ── 4. FLEET STATUS ────────────────────────────────────────────────────
    echo -e "${BOLD}${BLU}[4] FLEET — Station Health (via backend → Prometheus)${RST}"
    sep
    FLEET=$(curl -sf "$API/api/v1/fleet?run_id=${RUN_ID}" 2>/dev/null)
    if [ -z "$FLEET" ]; then
        echo -e "  ${DIM}No data${RST}"
    else
        echo "$FLEET" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  Fabric  : {d.get('fabric','?')}   Prometheus: {d.get('prometheus','?')}\")
for site in (d.get('sites') or []):
    status = site.get('status','?')
    color = {'ok':'[OK]','alert':'[!!]','offline':'[--]'}.get(status,'[??]')
    print(f\"  {color} {str(site.get('name','?')):20s}  mission={str(site.get('mission_class','?')):8s}  status={status}\")
    for h in (site.get('hosts_state') or []):
        m = h.get('metrics') or {}
        lat = m.get('latency_gre_ms','-')
        loss = m.get('packet_loss_pct','-')
        conf = h.get('confidence','-')
        eta = h.get('eta_minutes','-')
        print(f\"         host={str(h.get('host','?')):12s}  lat={lat}ms  loss={loss}%  conf={conf}  eta={eta}min\")
" 2>/dev/null
    fi

    echo ""
    echo -e "${DIM}  Backend watcher · $API · run=${RUN_ID} · refresh ${INTERVAL}s (Ctrl+C)${RST}"
    sleep "$INTERVAL"
done
