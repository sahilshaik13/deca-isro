#!/usr/bin/env bash
# inject_loss_progression.sh — progressive packet loss on gre-te-core (real GT for loss-TTI).
#
# Default: 24 steps × 5s ramp 0% → 3.5% loss on station1 GRE (crosses Payload 2% SLA).
# Does NOT use synthetic overlays — netem loss is the training label source.
#
# Usage:
#   bash scripts/inject_loss_progression.sh
#   bash scripts/inject_loss_progression.sh --clear
#   bash scripts/inject_loss_progression.sh --host station1 --end-pct 3.5
set -euo pipefail

HOST=station1
DEV=gre-te-core
STEPS=24
STEP_SEC=5
START_PCT=0
END_PCT=3.5
CLEAR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --dev) DEV="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-pct) START_PCT="$2"; shift 2 ;;
    --end-pct) END_PCT="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s" -- "$@"; }

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  echo "Clearing netem on $HOST $DEV"
  run <<EOF2
tc qdisc del dev $DEV root 2>/dev/null || true
tc qdisc show dev $DEV
EOF2
  exit 0
fi

echo "Loss progression on $HOST/$DEV: ${START_PCT}→${END_PCT}% over $((STEPS * STEP_SEC))s"
run <<EOF2
set -euo pipefail
DEV="$DEV"
STEPS=$STEPS
STEP_SEC=$STEP_SEC
START_PCT=$START_PCT
END_PCT=$END_PCT
tc qdisc del dev "\$DEV" root 2>/dev/null || true
for i in \$(seq 0 \$((STEPS - 1))); do
  # awk for float pct
  pct=\$(awk -v s="\$START_PCT" -v e="\$END_PCT" -v i="\$i" -v n="\$STEPS" 'BEGIN{printf "%.3f", s+(e-s)*i/(n-1)}')
  echo "[\$(date -u +%H:%M:%S)] step \$i/\$STEPS loss \${pct}%"
  tc qdisc replace dev "\$DEV" root netem loss \${pct}%
  sleep "\$STEP_SEC"
done
echo "[\$(date -u +%H:%M:%S)] left netem loss=\${END_PCT}% on \$DEV (use --clear to remove)"
tc qdisc show dev "\$DEV"
EOF2
