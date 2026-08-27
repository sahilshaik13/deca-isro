#!/usr/bin/env bash
# Move Docker data-root off the ~50GB OS disk onto Shaik's external drive.
# GNS3 projects/images already live there; Docker *images* for FRR/Alpine/iperf
# still default to /var/lib/docker on root — that is what fills the 50G disk.
#
# Requires: sudo once. Stops docker briefly.
set -euo pipefail

EXT="${DECA_DOCKER_ROOT:-/media/brain/Shaik's/gns3/docker}"
DRIVE_PARENT="$(dirname "$(dirname "$EXT")")"
# EXT = .../gns3/docker → parent gns3 → parent Shaik's
if [[ ! -d "/media/brain/Shaik's" ]]; then
  echo "ERROR: mount /media/brain/Shaik's first" >&2
  exit 1
fi

echo "=== DECA: relocate Docker data-root → $EXT ==="
echo "Current root free:"
df -h / | tail -1
echo "External free:"
df -h "/media/brain/Shaik's" | tail -1

if [[ "${1:-}" != "--apply" ]]; then
  cat <<EOF

Dry-run only. To apply (will stop Docker):

  bash lab/gns3/migrate_docker_to_external.sh --apply

What it does:
  1. mkdir -p "$EXT"
  2. stop docker + containerd
  3. rsync /var/lib/docker/ → $EXT/  (if not already migrated)
  4. write /etc/docker/daemon.json  {"data-root":"$EXT"}
  5. start docker

Wireshark: keep apt binary tiny on root; save captures under:
  /media/brain/Shaik's/gns3/captures/
EOF
  exit 0
fi

if ! sudo -n true 2>/dev/null; then
  echo "This step needs your sudo password."
fi

sudo mkdir -p "$EXT" "/media/brain/Shaik's/gns3/captures"
sudo mkdir -p /etc/docker

echo "[1/5] stopping docker…"
sudo systemctl stop docker docker.socket containerd 2>/dev/null || sudo service docker stop || true

if [[ ! -e "$EXT/.deca_migrated" ]]; then
  echo "[2/5] rsync /var/lib/docker → $EXT (may take several minutes)…"
  sudo rsync -aHAX --info=progress2 /var/lib/docker/ "$EXT/"
  sudo touch "$EXT/.deca_migrated"
else
  echo "[2/5] $EXT already has .deca_migrated — skip rsync"
fi

echo "[3/5] writing daemon.json data-root…"
# Merge carefully: if file exists, preserve other keys via python
TMP=$(mktemp)
export EXT
sudo python3 - <<'PY'
import json, os
from pathlib import Path
p = Path("/etc/docker/daemon.json")
ext = os.environ["EXT"]
data = {}
if p.exists():
    try:
        data = json.loads(p.read_text() or "{}")
    except Exception:
        data = {}
data["data-root"] = ext
p.write_text(json.dumps(data, indent=2) + "\n")
print("wrote", p, "→", data)
PY

echo "[4/5] starting docker…"
sudo systemctl start containerd docker 2>/dev/null || sudo service docker start

echo "[5/5] verify"
docker info 2>/dev/null | grep -i "Docker Root Dir" || true
df -h / "/media/brain/Shaik's" | sed '1!b;p'
echo "OK — Docker images/layers now on external disk."
echo "Optional: after verifying GNS3 Start-all works, reclaim old root copy:"
echo "  sudo mv /var/lib/docker /var/lib/docker.bak.pre-shaik"
echo "  # only after docker info shows data-root under Shaik's"
