#!/usr/bin/env bash
# Ensure GNS3 data lives on the external drive — never on the ~50GB root.
set -euo pipefail

# Apostrophe in mount name: set default outside ${var:-...} (quoting pitfall).
if [[ -n "${DECA_GNS3_ROOT:-}" ]]; then
  GNS3_ROOT="$DECA_GNS3_ROOT"
else
  GNS3_ROOT="/media/brain/Shaik's/gns3"
fi
DRIVE_PARENT="$(dirname "$GNS3_ROOT")"
MIN_FREE_GB="${DECA_GNS3_MIN_FREE_GB:-20}"

die() { echo "ERROR: $*" >&2; exit 1; }

if [[ ! -d "$DRIVE_PARENT" ]]; then
  die "external drive not mounted at: $DRIVE_PARENT (mount Shaik drive first)"
fi

mkdir -p \
  "$GNS3_ROOT/images" \
  "$GNS3_ROOT/projects" \
  "$GNS3_ROOT/configs" \
  "$GNS3_ROOT/appliances" \
  "$GNS3_ROOT/symbols" \
  "$GNS3_ROOT/captures" \
  "$GNS3_ROOT/docker"

free_kb=$(df -Pk "$DRIVE_PARENT" | awk 'NR==2 {print $4}')
free_gb=$(( free_kb / 1024 / 1024 ))
if (( free_gb < MIN_FREE_GB )); then
  die "only ${free_gb}G free on $DRIVE_PARENT (need >= ${MIN_FREE_GB}G)"
fi

# Warn if OS root is nearly full (Docker images still default there until migrate).
root_avail_kb=$(df -Pk / | awk 'NR==2 {print $4}')
root_avail_gb=$(( root_avail_kb / 1024 / 1024 ))
if (( root_avail_gb < 5 )); then
  echo "WARN: root / has only ~${root_avail_gb}G free."
  echo "      Docker images still live under /var/lib/docker on the 50G disk."
  echo "      Run: bash lab/gns3/migrate_docker_to_external.sh --apply"
fi

CONF_SNIPPET="$GNS3_ROOT/configs/deca_paths.ini"
{
  echo "# DECA dual-fabric — point GNS3 GUI Preferences at these paths."
  echo "# Edit → Preferences → General / Server"
  echo "#"
  echo "# images_path = $GNS3_ROOT/images"
  echo "# projects_path = $GNS3_ROOT/projects"
  echo "# appliances_path = $GNS3_ROOT/appliances"
  echo "# symbols_path = $GNS3_ROOT/symbols"
  echo "# packet captures → $GNS3_ROOT/captures"
  echo "#"
  echo "# Do NOT use ~/GNS3 on the root disk."
  echo "# Docker data-root (after migrate): $GNS3_ROOT/docker"
} > "$CONF_SNIPPET"

{
  echo "DECA GNS3 storage root"
  echo "======================"
  echo "Created by lab/gns3/ensure_storage.sh"
  echo ""
  echo "images/     — appliance / QEMU / IOS images"
  echo "projects/   — GNS3 project files (DECA lab)"
  echo "configs/    — path snippets / server overrides"
  echo "appliances/ — .gns3a files"
  echo "symbols/    — custom symbols"
  echo "captures/   — Wireshark / pcap dumps (keep off root)"
  echo "docker/     — Docker data-root after migrate_docker_to_external.sh"
  echo ""
  echo "When the minimal topology + Prom exporters are ready, create:"
  echo "  projects/DECA_READY"
  echo "so the NOC fabric selector marks GNS3 as ready."
  echo ""
  echo "Never copy large images onto the laptop root (~50G)."
} > "$GNS3_ROOT/README_DECA.txt"

echo "OK gns3_root=$GNS3_ROOT free=${free_gb}G (root free ~${root_avail_gb}G)"
echo "    images/ projects/ configs/ appliances/ symbols/ captures/ docker/ ready"
echo "    prefs snippet: $CONF_SNIPPET"
ls -la "$GNS3_ROOT"
