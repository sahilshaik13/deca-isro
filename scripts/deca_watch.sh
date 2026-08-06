#!/usr/bin/env bash
# =============================================================================
# DECA Live Watcher — see EVERYTHING in one terminal
# Run: bash scripts/deca_watch.sh
# Trigger faults from the UI and watch this terminal update every 2 seconds
# =============================================================================

API="http://127.0.0.1:8000"
INTERVAL=2

# Colors
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

while true; do
    clear
    echo -e "${BOLD}${CYN}╔══════════════════════════════════════════════════════╗${RST}"
    echo -e "${BOLD}${CYN}║        DECA NOC — Live System Watcher                ║${RST}"
    echo -e "${BOLD}${CYN}║  Refresh every ${INTERVAL}s · Ctrl+C to stop                   ║${RST}"
    echo -e "${BOLD}${CYN}╚══════════════════════════════════════════════════════╝${RST}"
    echo -e "  ${DIM}$(date '+%Y-%m-%d %H:%M:%S')${RST}\n"

    # ── 1. FAULT INJECTION STATUS ────────────────────────────────────────────
    echo -e "${BOLD}${YLW}[1] FAULT INJECTION${RST}"
    sep
    FAULT=$(curl -sf "$API/api/v1/faults/status" 2>/dev/null)
    if [ -z "$FAULT" ]; then
        echo -e "  ${RED}Backend unreachable at $API${RST}"
    else
        RUNNING=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('running','?'))")
        FAULT_ID=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fault_id') or 'none')")
        MSG=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message') or '')")
        FABRIC=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('active_fabric') or '?')")
        STARTED=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('started_at') or '-')")

        if [ "$RUNNING" = "True" ]; then
            echo -e "  Status  : ${RED}● RUNNING${RST}"
        else
            echo -e "  Status  : ${GRN}● idle${RST}"
        fi
        echo -e "  Fault   : ${WHT}$FAULT_ID${RST}"
        echo -e "  Fabric  : ${BLU}$FABRIC${RST}"
        echo -e "  Started : ${DIM}$STARTED${RST}"
        echo -e "  Message : ${YLW}$MSG${RST}"

        # Model detection sub-block
        DET_SEV=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); m=d.get('model_detection') or {}; print(m.get('severity') or '-')")
        DET_CONF=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); m=d.get('model_detection') or {}; print(m.get('q2_confidence') or '-')")
        DET_MATCH=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); m=d.get('model_detection') or {}; print(m.get('matches_demo_fault') or '-')")
        DET_EXPL=$(echo "$FAULT" | python3 -c "import sys,json; d=json.load(sys.stdin); m=d.get('model_detection') or {}; print((m.get('explanation') or '')[:120])")

        echo ""
        echo -e "  ${MAG}▸ Q2 XGBoost Model Detection:${RST}"
        echo -e "    Severity     : ${RED}$DET_SEV${RST}"
        echo -e "    Confidence   : ${WHT}$DET_CONF${RST}"
        echo -e "    Fault Match  : ${GRN}$DET_MATCH${RST}"
        echo -e "    Explanation  : ${DIM}$DET_EXPL${RST}"

        # Log tail
        echo ""
        echo -e "  ${MAG}▸ Inject Log (last 5 lines):${RST}"
        echo "$FAULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tail = d.get('log_tail') or []
for line in tail[-5:]:
    print('    ' + str(line))
" 2>/dev/null
    fi

    echo ""

    # ── 2. ACTIVE ALERTS (Decide Rail) ─────────────────────────────────────
    echo -e "${BOLD}${RED}[2] ACTIVE ALERTS — Decide Rail${RST}"
    sep
    ALERTS=$(curl -sf "$API/api/v1/alerts?run_id=sim-live" 2>/dev/null)
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
    print(f\"  Alert #{a.get('id')}  class={a.get('class')}  status={a.get('status')}\")
    print(f\"    Title      : {a.get('title','')[:80]}\")
    print(f\"    Severity   : {p.get('severity','-')}   Confidence: {p.get('confidence',p.get('confidence_score','-'))}\")
    print(f\"    ETA (min)  : {p.get('eta_minutes','-')}\")
    print(f\"    Root cause : {p.get('root_cause','-')}\")
    print(f\"    Q3 NLP     : {str(p.get('q3_nlp',''))[:100]}\")
    print()
" 2>/dev/null
    fi

    echo ""

    # ── 3. LAST APPROVE ACTION (controller call + timing) ──────────────────
    echo -e "${BOLD}${GRN}[3] LAST APPROVE ACTION — What was sent to the SD-WAN Controller${RST}"
    sep
    HIST=$(curl -sf "$API/api/v1/history?run_id=sim-live" 2>/dev/null)
    if [ -z "$HIST" ]; then
        echo -e "  ${DIM}No history yet${RST}"
    else
        echo "$HIST" | python3 -c "
import sys, json
d = json.load(sys.stdin)
actions = d.get('actions') or []
if not actions:
    print('  (no actions yet — click Approve in the UI)')
else:
    a = actions[-1]   # most recent
    result = a.get('result') or {}
    proposal = a.get('proposal') or {}
    print(f\"  Action     : {a.get('action','?').upper()}  alert_id={a.get('alert_id')}\")
    print(f\"  Timestamp  : {a.get('created_at','?')}\")
    print(f\"  Overall OK : {result.get('ok','-')}\")
    print(f\"  Wall clock : {result.get('wall_clock_sec','-')} sec\")
    print()
    for step in (result.get('sequence') or []):
        ok_str = 'OK' if (step.get('result') or {}).get('ok') else 'FAIL'
        print(f\"    Step: {step.get('op'):20s}  budget={step.get('budget_sec')}s  \
elapsed={step.get('elapsed_sec')}s  [{ok_str}]\")
        ctrl = step.get('result') or {}
        print(f\"           → controller response: {str(ctrl)[:100]}\")
" 2>/dev/null
    fi

    echo ""

    # ── 4. FLEET STATUS (Station health from Prometheus) ───────────────────
    echo -e "${BOLD}${BLU}[4] FLEET — Station Health (from Prometheus)${RST}"
    sep
    FLEET=$(curl -sf "$API/api/v1/fleet?run_id=sim-live" 2>/dev/null)
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
    print(f\"  {color} {site.get('name','?'):20s}  mission={site.get('mission_class','?'):8s}  status={status}\")
    for h in (site.get('hosts_state') or []):
        m = h.get('metrics') or {}
        lat = m.get('latency_gre_ms','-')
        loss = m.get('packet_loss_pct','-')
        conf = h.get('confidence','-')
        eta = h.get('eta_minutes','-')
        print(f\"         host={h.get('host','?'):12s}  lat={lat}ms  loss={loss}%  conf={conf}  eta={eta}min\")
" 2>/dev/null
    fi

    echo ""
    echo -e "${DIM}  Refreshing in ${INTERVAL}s... (Ctrl+C to stop) · Trigger faults from http://localhost:3000${RST}"
    sleep $INTERVAL
done
