#!/usr/bin/env bash
# Create/update $HOME symlinks → current lab/ scripts (post-expansion).
# Superseded scripts live under lab/archive/pre-expansion/ — not linked.
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

unlink_stale() {
  local name="$1"
  local dst="${HOME_DIR}/${name}"
  if [[ -L "${dst}" ]]; then
    rm -f "${dst}"
    echo "removed stale ~/${name}"
  fi
}

echo "LAB_DIR=${LAB_DIR}"
# Current day-to-day
for name in \
  deca_diagnostic.sh \
  deca_station_map.sh \
  deca_ops.sh \
  deca-deploy.sh \
  run_traffic.sh
do
  link_one "${name}"
done

# Compatibility: old name → current diagnostic
ln -sfn "${LAB_DIR}/deca_diagnostic.sh" "${HOME_DIR}/check_stations.sh"
echo "relinked ~/check_stations.sh -> lab/deca_diagnostic.sh"
ln -sfn "${LAB_DIR}/deca_station_map.sh" "${HOME_DIR}/stations"
echo "relinked ~/stations -> lab/deca_station_map.sh"

# Drop home links to archived scripts
for name in \
  check_step7.sh \
  trace_step7.sh \
  apply_boot_fix.sh \
  deca-heal-telemetry.sh \
  startupppp \
  forwardss \
  cisco_scraper.py
do
  unlink_stale "${name}"
done

echo "Done. Try: stations   OR   check stations   OR   bash ~/deca_station_map.sh"
