#!/usr/bin/env bash
# Start gns3-server with external-drive config. GUI optional if DISPLAY is set.
set -euo pipefail

if [[ -n "${DECA_GNS3_ROOT:-}" ]]; then
  GNS3_ROOT="$DECA_GNS3_ROOT"
else
  GNS3_ROOT="/media/brain/Shaik's/gns3"
fi

DRIVE="$(dirname "$GNS3_ROOT")"
[[ -d "$DRIVE" ]] || { echo "ERROR: mount $DRIVE first" >&2; exit 1; }

CONF="$GNS3_ROOT/configs/gns3_server.conf"
VENV="$GNS3_ROOT/venv"
[[ -x "$VENV/bin/gns3server" ]] || {
  echo "ERROR: GNS3 not installed. Run: bash lab/gns3/install_gns3.sh" >&2
  exit 1
}
[[ -f "$CONF" ]] || { echo "ERROR: missing $CONF" >&2; exit 1; }

LOG="$GNS3_ROOT/logs"
# Wireshark/GNS3 GUI dumps live capture temps as /tmp/GNS3.* — that fills the
# ~50GB root disk. Force TMPDIR onto the external drive before server/GUI start.
TMPDIR_EXT="$GNS3_ROOT/tmp"
mkdir -p "$LOG" "$TMPDIR_EXT" "$GNS3_ROOT/captures"
export TMPDIR="$TMPDIR_EXT"
export TMP="$TMPDIR_EXT"
export TEMP="$TMPDIR_EXT"

# Already listening?
if curl -sf -o /dev/null http://127.0.0.1:3080/v2/version 2>/dev/null; then
  echo "gns3-server already up on :3080"
  curl -s http://127.0.0.1:3080/v2/version
  echo
else
  echo "Starting gns3-server (config=$CONF TMPDIR=$TMPDIR)…"
  nohup env TMPDIR="$TMPDIR" TMP="$TMPDIR" TEMP="$TMPDIR" \
    "$VENV/bin/gns3server" --config "$CONF" \
    >"$LOG/gns3-server.log" 2>&1 &
  echo "pid=$! log=$LOG/gns3-server.log"
  for i in $(seq 1 20); do
    if curl -sf -o /dev/null http://127.0.0.1:3080/v2/version 2>/dev/null; then
      curl -s http://127.0.0.1:3080/v2/version
      echo
      break
    fi
    sleep 0.5
  done
fi

if [[ "${1:-}" == "--gui" ]]; then
  if [[ -z "${DISPLAY:-}" ]]; then
    echo "No DISPLAY — skip GUI (server is running; use GNS3 web/remote client)"
    exit 0
  fi
  echo "Launching GNS3 GUI (TMPDIR=$TMPDIR)…"
  exec env TMPDIR="$TMPDIR" TMP="$TMPDIR" TEMP="$TMPDIR" "$VENV/bin/gns3"
fi
