#!/usr/bin/env bash
# GNS3 L2 CPU / crypto stress — twin of scripts/inject_cpu_stress.sh.
# stress-ng --cpu $(nproc); else Python burn. No dd.
#
# Prom metrics come from chaos_state overlay (PE container CPU is not scraped).
# Overlay *user* % scales with WORKERS so variant recipes are visible in captures
# (stress-ng burns user time, matching Pi / severity_label root_label==2).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_common.sh"
ensure_exporter

TAG=deca-cpu-stress
DUR=${DUR:-${DURATION_S:-${SECONDS_RUN:-90}}}
WORKERS=${WORKERS:-0}
CLEAR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clear) CLEAR_ONLY=1; shift ;;
    --seconds|--duration) DUR="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown: $1"; exit 2 ;;
  esac
done

if [[ "$CLEAR_ONLY" -eq 1 ]]; then
  cid="$(find_pe1_container || true)"
  if [[ -n "$cid" ]]; then
    docker exec "$cid" sh -c \
      "pkill -f '$TAG' 2>/dev/null; pkill -f 'stress-ng.*deca-cpu' 2>/dev/null; pkill -f stress-ng 2>/dev/null; true" \
      2>/dev/null || true
  fi
  patch_state fault_id= cpu_usage_system=5 cpu_usage_user=8
  echo "cleared cpu_stress"
  exit 0
fi

# Worker → published CPU texture (user-dominant, like real stress-ng)
if [[ "$WORKERS" -le 0 ]]; then
  CPU_USER=92; CPU_SYS=18   # all cores
elif [[ "$WORKERS" -eq 1 ]]; then
  CPU_USER=55; CPU_SYS=12
elif [[ "$WORKERS" -eq 2 ]]; then
  CPU_USER=72; CPU_SYS=14
elif [[ "$WORKERS" -eq 3 ]]; then
  CPU_USER=85; CPU_SYS=16
else
  CPU_USER=95; CPU_SYS=18
fi

cid="$(require_pe1)"
patch_state fault_id=cpu_stress cpu_usage_system="$CPU_SYS" cpu_usage_user="$CPU_USER"

if [[ -z "$cid" ]]; then
  echo "WARN: no PE1 — state overlay only (user=${CPU_USER} sys=${CPU_SYS})"
  sleep "$DUR"
  patch_state fault_id= cpu_usage_system=5 cpu_usage_user=8
  exit 0
fi

echo "cpu_stress on PE1 for ${DUR}s (workers=${WORKERS:-nproc}; overlay user=${CPU_USER} sys=${CPU_SYS})"
docker exec -i "$cid" sh -s <<EOF
set -e
TAG='$TAG'
SECS=$DUR
WORKERS=$WORKERS
pkill -f "\$TAG" 2>/dev/null || true
pkill -f 'stress-ng.*deca-cpu' 2>/dev/null || true
if [ "\$WORKERS" -le 0 ]; then
  WORKERS=\$(nproc 2>/dev/null || echo 2)
fi
cleanup() {
  pkill -f "\$TAG" 2>/dev/null || true
  pkill -f 'stress-ng.*deca-cpu' 2>/dev/null || true
}
trap cleanup EXIT INT TERM
if command -v stress-ng >/dev/null 2>&1; then
  echo "[\$(date -u +%H:%M:%S)] stress-ng --cpu \$WORKERS --timeout \${SECS}s"
  stress-ng --cpu "\$WORKERS" --timeout "\${SECS}s" --metrics-brief 2>/dev/null \
    || stress-ng --cpu "\$WORKERS" --timeout "\${SECS}s"
elif command -v python3 >/dev/null 2>&1; then
  echo "[\$(date -u +%H:%M:%S)] fallback python burn (\$WORKERS workers)"
  python3 -c "
import multiprocessing as mp, time
def burn():
    x = 0
    while True:
        x = (x * x + 1) % 9973
workers, secs = int('\$WORKERS'), int('\$SECS')
ps = [mp.Process(target=burn) for _ in range(workers)]
for p in ps:
    p.daemon = True
    p.start()
time.sleep(secs)
for p in ps:
    p.terminate()
for p in ps:
    p.join(timeout=2)
"
else
  echo "ERROR: need stress-ng or python3 on PE1 (Pi twin — no dd)" >&2
  exit 1
fi
echo "[\$(date -u +%H:%M:%S)] CPU stress complete"
EOF

patch_state fault_id= cpu_usage_system=5 cpu_usage_user=8
echo "cpu_stress done"
