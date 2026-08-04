#!/usr/bin/env bash
# inject_cpu_stress.sh — Crypto/CPU exhaustion profile (Q2 label 2).
#
# Spikes cpu_usage_user on the PE to mimic heavy IPsec crypto load
# (stress-ng --cpu burns user time; cpu_usage_system alone is a bad L2 signal).
# Prefers stress-ng when installed; otherwise falls back to a Python burn.
#
# Usage:
#   bash scripts/inject_cpu_stress.sh                 # 90s burn on station1
#   bash scripts/inject_cpu_stress.sh --seconds 120 --workers 4
#   bash scripts/inject_cpu_stress.sh --clear          # kill leftover burners
set -euo pipefail

HOST=station1
SECONDS_RUN=90
WORKERS=0   # 0 = nproc on remote
CLEAR_ONLY=0
TAG=deca-cpu-stress

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --seconds) SECONDS_RUN="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

run() { ssh -T "$HOST" "sudo bash -s" -- "$@"; }

clear_burn() {
  run <<EOF
pkill -f '$TAG' 2>/dev/null || true
pkill -f 'stress-ng.*deca-cpu' 2>/dev/null || true
echo "cleared cpu stress on $HOST"
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  clear_burn
  exit 0
fi

echo "CPU stress on $HOST for ${SECONDS_RUN}s (workers=${WORKERS:-nproc})"
# Always clear leftovers first
clear_burn >/dev/null 2>&1 || true

run <<EOF
set -euo pipefail
TAG='$TAG'
SECS=$SECONDS_RUN
WORKERS=$WORKERS
if [[ "\$WORKERS" -le 0 ]]; then
  WORKERS=\$(nproc)
fi

cleanup() {
  pkill -f "\$TAG" 2>/dev/null || true
  pkill -f 'stress-ng.*deca-cpu' 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if command -v stress-ng >/dev/null 2>&1; then
  echo "[\$(date -u +%H:%M:%S)] stress-ng --cpu \$WORKERS --timeout \${SECS}s"
  # marker in cmdline for --clear
  stress-ng --cpu "\$WORKERS" --timeout "\${SECS}s" --metrics-brief --job deca-cpu || \
    stress-ng --cpu "\$WORKERS" --timeout "\${SECS}s" --metrics-brief
else
  echo "[\$(date -u +%H:%M:%S)] fallback python burn (\$WORKERS workers, no stress-ng)"
  python3 - "\$TAG" "\$WORKERS" "\$SECS" <<'PY'
import multiprocessing as mp, sys, time, os
tag, workers, secs = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
os.environ["DECA_CPU_STRESS_TAG"] = tag

def burn():
    x = 0
    while True:
        x = (x * x + 1) % 9973

def main():
    ps = [mp.Process(target=burn, name=f"{tag}-{i}") for i in range(workers)]
    for p in ps:
        p.daemon = True
        p.start()
    time.sleep(secs)
    for p in ps:
        p.terminate()
    for p in ps:
        p.join(timeout=2)

if __name__ == "__main__":
    main()
PY
fi
echo "[\$(date -u +%H:%M:%S)] CPU stress complete"
EOF

echo "Done. Clear leftovers with: $0 --clear --host $HOST"
