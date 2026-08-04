#!/usr/bin/env bash
# inject_rain_fade.sh — slow latency drift on gre-te-core (Rain Fade profile).
#
# Default: 24 steps × 5s = 120s ramp from ~5ms → ~100ms delay on station1 GRE.
# Use while Prometheus/Kafka scrape sdwan_path_* for LSTM training export.
#
# Usage:
#   bash scripts/inject_rain_fade.sh              # run fade, leave netem
#   bash scripts/inject_rain_fade.sh --clear      # remove netem only
#   bash scripts/inject_rain_fade.sh --host station1 --steps 24 --step-sec 5
set -euo pipefail

HOST=station1
DEV=gre-te-core
STEPS=24
STEP_SEC=5
START_MS=5
END_MS=100
JITTER_MS=5
CLEAR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --dev) DEV="$2"; shift 2 ;;
    --steps) STEPS="$2"; shift 2 ;;
    --step-sec) STEP_SEC="$2"; shift 2 ;;
    --start-ms) START_MS="$2"; shift 2 ;;
    --end-ms) END_MS="$2"; shift 2 ;;
    --jitter-ms) JITTER_MS="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s" -- "$@"; }

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  echo "Clearing netem on $HOST $DEV"
  run <<EOF
tc qdisc del dev $DEV root 2>/dev/null || true
tc qdisc show dev $DEV
EOF
  exit 0
fi

echo "Rain fade on $HOST/$DEV: ${START_MS}→${END_MS}ms over $((STEPS * STEP_SEC))s (${STEPS}×${STEP_SEC}s)"
run <<EOF
set -euo pipefail
DEV="$DEV"
STEPS=$STEPS
STEP_SEC=$STEP_SEC
START_MS=$START_MS
END_MS=$END_MS
JITTER_MS=$JITTER_MS
tc qdisc del dev "\$DEV" root 2>/dev/null || true
for i in \$(seq 0 \$((STEPS - 1))); do
  delay=\$(( START_MS + (END_MS - START_MS) * i / (STEPS - 1) ))
  tc qdisc replace dev "\$DEV" root netem delay \${delay}ms \${JITTER_MS}ms distribution normal
  echo "[\$(date -u +%H:%M:%S)] delay=\${delay}ms"
  sleep "\$STEP_SEC"
done
echo "Fade complete — netem left at \${END_MS}ms. Clear with: $0 --clear --host $HOST"
tc qdisc show dev "\$DEV"
EOF
