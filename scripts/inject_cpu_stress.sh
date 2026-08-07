#!/usr/bin/env bash
# inject_cpu_stress.sh — Crypto/CPU exhaustion profile (Q2 label 2).
# Ctrl+C kills remote SSH + burners (healthy).
set -euo pipefail

HOST=station1
SECONDS_RUN=90
WORKERS=0
CLEAR_ONLY=0
TAG=deca-cpu-stress
PIDFILE=/tmp/deca_cpu_stress.pid
SSH_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --seconds) SECONDS_RUN="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --clear) CLEAR_ONLY=1; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

kill_ssh() {
  if [[ -n "${SSH_PID}" ]] && kill -0 "$SSH_PID" 2>/dev/null; then
    kill -TERM "$SSH_PID" 2>/dev/null || true
    sleep 0.4
    kill -KILL "$SSH_PID" 2>/dev/null || true
    wait "$SSH_PID" 2>/dev/null || true
    SSH_PID=""
  fi
}

clear_burn() {
  echo "Clearing CPU stress on $HOST (healthy)"
  ssh -T "$HOST" "sudo bash -s" <<EOF || true
if [[ -f $PIDFILE ]]; then
  pid=\$(cat $PIDFILE 2>/dev/null || true)
  if [[ -n "\$pid" ]]; then
    kill -TERM "\$pid" 2>/dev/null || true
    pkill -P "\$pid" 2>/dev/null || true
    sleep 0.2
    kill -KILL "\$pid" 2>/dev/null || true
  fi
  rm -f $PIDFILE
fi
pkill -f '$TAG' 2>/dev/null || true
pkill -f 'stress-ng.*deca-cpu' 2>/dev/null || true
echo "cleared cpu stress on $HOST"
EOF
}

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  clear_burn
  exit 0
fi

on_interrupt() {
  echo
  echo "Interrupted — killing remote inject, restoring healthy CPU on $HOST"
  kill_ssh
  clear_burn
  exit 130
}
trap on_interrupt INT TERM

echo "CPU stress on $HOST for ${SECONDS_RUN}s (workers=${WORKERS:-nproc})"
echo "(Ctrl+C kills remote loop + burners → healthy)"
clear_burn >/dev/null 2>&1 || true

TMP="$(mktemp /tmp/deca_cpu_remote.XXXXXX)"
cat >"$TMP" <<EOF
set -euo pipefail
TAG='$TAG'
SECS=$SECONDS_RUN
WORKERS=$WORKERS
PIDFILE=$PIDFILE
if [[ "\$WORKERS" -le 0 ]]; then
  WORKERS=\$(nproc)
fi

cleanup() {
  rm -f "\$PIDFILE"
  echo "[\$(date -u +%H:%M:%S)] clearing CPU burners (healthy)"
  pkill -f "\$TAG" 2>/dev/null || true
  pkill -f 'stress-ng.*deca-cpu' 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP
echo \$\$ > "\$PIDFILE"

if command -v stress-ng >/dev/null 2>&1; then
  echo "[\$(date -u +%H:%M:%S)] stress-ng --cpu \$WORKERS --timeout \${SECS}s"
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
echo "[\$(date -u +%H:%M:%S)] CPU stress complete — cleanup will restore healthy"
EOF

ssh -T "$HOST" "sudo bash -s" <"$TMP" &
SSH_PID=$!
wait "$SSH_PID" || true
SSH_PID=""
rm -f "$TMP"
trap - INT TERM
echo "CPU stress finished — burners cleared (healthy)."
