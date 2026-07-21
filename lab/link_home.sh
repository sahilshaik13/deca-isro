#!/usr/bin/env bash
# Create/update $HOME symlinks → this lab/ folder so existing docs that say
# ~/deca_diagnostic.sh keep working.
set -euo pipefail
LAB_DIR="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="${HOME:-/home/brain}"

link_one() {
  local name="$1"
  local src="${LAB_DIR}/${name}"
  local dst="${HOME_DIR}/${name}"
  if [[ ! -e "${src}" ]]; then
    echo "skip (missing): ${name}"
    return
  fi
  if [[ -L "${dst}" ]]; then
    ln -sfn "${src}" "${dst}"
    echo "relinked ~/${name}"
  elif [[ -e "${dst}" ]]; then
    # Preserve a one-time backup of a real home file, then replace with symlink.
    local bak="${dst}.bak_before_lab_link"
    if [[ ! -e "${bak}" ]]; then
      mv "${dst}" "${bak}"
      echo "backed up ~/${name} -> ${bak}"
    else
      rm -f "${dst}"
    fi
    ln -sfn "${src}" "${dst}"
    echo "linked ~/${name} (old file backed up)"
  else
    ln -sfn "${src}" "${dst}"
    echo "linked ~/${name}"
  fi
}

echo "LAB_DIR=${LAB_DIR}"
for name in \
  deca_diagnostic.sh \
  check_stations.sh \
  check_step7.sh \
  trace_step7.sh \
  deca-deploy.sh \
  apply_boot_fix.sh \
  deca-heal-telemetry.sh \
  run_traffic.sh \
  forwardss \
  startupppp \
  cisco_scraper.py
do
  link_one "${name}"
done
echo "Done. Try: bash ~/deca_diagnostic.sh"
