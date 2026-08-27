#!/usr/bin/env bash
# deca_rtc_ds3231_sync.sh — enable DS3231 RTC on station1/2/3, sync from internet
# (via laptop chrony/NTP), then write the corrected time into the hardware clock.
#
# Why: cold-boot / wrong wall clocks poison Prometheus ("out of bounds"). A battery
# DS3231 keeps time across power loss so Telegraf scrapes stay monotonic.
#
# Steady state on each Pi: kernel DS3231 driver (boot time) + chrony → laptop NTP.
# This script is only for first-time overlay enable / rare re-stamp of the RTC module.
# Do not add userspace hwclock-set hacks on the Pis — they fight the driver + chrony.
#
# Usage (from laptop on lab LAN):
#   bash lab/deca_rtc_ds3231_sync.sh           # configure + force time + write RTC
#   bash lab/deca_rtc_ds3231_sync.sh status    # read-only check
#   bash lab/deca_rtc_ds3231_sync.sh sync      # force time + hwclock -w only
#   STATIONS="station1 station2" bash lab/deca_rtc_ds3231_sync.sh
set -euo pipefail

MODE="${1:-all}"
STATIONS=(${STATIONS:-station1 station2 station3})
OVERLAY_LINE='dtoverlay=i2c-rtc,ds3231'
MIN_YEAR=2024

log() { printf '%s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

ssh_ok() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' 2>/dev/null
}

remote() {
  local host="$1"
  shift
  ssh -o BatchMode=yes -o ConnectTimeout=15 -T "$host" "$@"
}

brain_utc() {
  date -u +'%Y-%m-%d %H:%M:%S'
}

ensure_brain_time() {
  log "== brain (internet NTP source for stations) =="
  if command -v chronyc >/dev/null 2>&1; then
    # Best-effort; laptop chronyc often needs root password for makestep
    sudo -n chronyc makestep 2>/dev/null || true
    chronyc tracking 2>/dev/null | head -6 || true
  fi
  local y
  y=$(date -u +%Y)
  if [ "$y" -lt "$MIN_YEAR" ]; then
    die "brain clock year $y looks wrong — fix laptop internet/NTP first"
  fi
  date -u +"brain UTC: %Y-%m-%d %H:%M:%S"
  log ""
}

station_status() {
  local h="$1"
  log "== $h =="
  if ! ssh_ok "$h"; then
    log "  UNREACHABLE"
    return 1
  fi
  remote "$h" bash -s <<'EOF'
set -e
echo "  host: $(hostname)"
echo "  sys:  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
if [ -e /dev/rtc0 ] || [ -e /dev/rtc ]; then
  echo "  rtc:  $(sudo hwclock -r --utc 2>/dev/null || sudo hwclock -r 2>/dev/null || echo 'present but unreadable')"
else
  echo "  rtc:  (no /dev/rtc*)"
fi
echo "  ntp:  $(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo '?')"
chronyc tracking 2>/dev/null | grep -E 'Reference|System time|Last offset|Stratum' | sed 's/^/  /' || true
grep -E '^(dtparam=i2c_arm|dtoverlay=i2c-rtc)' /boot/firmware/config.txt /boot/config.txt 2>/dev/null | sed 's/^/  cfg: /' || true
ls -1 /dev/rtc* 2>/dev/null | sed 's/^/  /' || echo "  /dev/rtc*: none"
year=$(date -u +%Y)
if [ "$year" -lt 2024 ]; then
  echo "  WARN: system year $year is not credible"
  exit 3
fi
EOF
  log ""
}

configure_station() {
  local h="$1"
  log "-- configure $h --"
  remote "$h" bash -s <<EOF
set -euo pipefail
OVERLAY_LINE='$OVERLAY_LINE'

CFG=""
for c in /boot/firmware/config.txt /boot/config.txt; do
  if [ -f "\$c" ]; then CFG="\$c"; break; fi
done
if [ -z "\$CFG" ]; then
  echo "  FAIL: no boot config.txt"
  exit 1
fi
if ! grep -qE '^dtparam=i2c_arm=on' "\$CFG"; then
  echo 'dtparam=i2c_arm=on' | sudo tee -a "\$CFG" >/dev/null
  echo "  added dtparam=i2c_arm=on -> \$CFG"
fi
if ! grep -qE '^dtoverlay=i2c-rtc,ds3231' "\$CFG"; then
  echo "\$OVERLAY_LINE" | sudo tee -a "\$CFG" >/dev/null
  echo "  added \$OVERLAY_LINE -> \$CFG"
else
  echo "  overlay already in \$CFG"
fi

# Load overlay now if needed. Kernel may briefly apply RTC (often year 2000) to OS —
# caller MUST force-correct system time immediately after this.
if [ ! -e /dev/rtc0 ] && [ ! -e /dev/rtc ]; then
  if command -v dtoverlay >/dev/null 2>&1; then
    sudo dtoverlay i2c-rtc ds3231 2>/dev/null && echo "  live dtoverlay applied" || echo "  live dtoverlay skipped/failed"
  fi
  if [ ! -e /dev/rtc0 ] && [ -d /sys/class/i2c-adapter/i2c-1 ]; then
    echo ds3231 0x68 | sudo tee /sys/class/i2c-adapter/i2c-1/new_device >/dev/null 2>&1 || true
  fi
fi

if [ -f /lib/udev/hwclock-set ]; then
  # Do NOT patch udev to force hwclock --hctosys. With dtoverlay=i2c-rtc,ds3231 the
  # kernel driver already loads RTC time; extra userspace sets fight chrony.
  if grep -q 'DECA: allow RTC' /lib/udev/hwclock-set; then
    sudo sed -i 's/if false; then  # DECA: allow RTC (was systemd early-exit)/if [ -e \/run\/systemd\/system ] ; then/' /lib/udev/hwclock-set || true
    echo "  restored stock /lib/udev/hwclock-set"
  fi
fi

sudo systemctl enable --now chrony 2>/dev/null || sudo systemctl enable --now chronyd 2>/dev/null || true

if [ -e /dev/rtc0 ] || [ -e /dev/rtc ]; then
  echo "  RTC device: \$(ls /dev/rtc* 2>/dev/null | tr '\\n' ' ')"
else
  echo "  WARN: no /dev/rtc* yet — reboot once, then: bash lab/deca_rtc_ds3231_sync.sh sync"
fi
EOF
}

# Force the SAME UTC onto every station at one barrier instant, then stamp all RTCs.
# Sequential per-host `date -s` is what created the apparent drifts — we never do that here.
ssh_ctl() {
  local host="$1"
  shift
  ssh -o ControlPath="$SSH_CTL_DIR/%h" -o ControlMaster=auto -o ControlPersist=60 \
    -o BatchMode=yes -o ConnectTimeout=12 -T "$host" "$@"
}

open_ssh_masters() {
  SSH_CTL_DIR="${SSH_CTL_DIR:-$(mktemp -d /tmp/deca-rtc-ssh.XXXXXX)}"
  export SSH_CTL_DIR
  mkdir -p "$SSH_CTL_DIR"
  local h
  for h in "${STATIONS[@]}"; do
    ssh -o ControlMaster=yes -o ControlPath="$SSH_CTL_DIR/%h" -o ControlPersist=60 \
      -o BatchMode=yes -o ConnectTimeout=12 -fN "$h" 2>/dev/null || true
  done
}

close_ssh_masters() {
  local h
  [[ -n "${SSH_CTL_DIR:-}" ]] || return 0
  for h in "${STATIONS[@]}"; do
    ssh -O exit -o ControlPath="$SSH_CTL_DIR/%h" "$h" 2>/dev/null || true
  done
  rm -rf "$SSH_CTL_DIR"
  SSH_CTL_DIR=""
}

tighten_chrony_station() {
  local h="$1"
  ssh_ctl "$h" bash -s <<'EOF'
set -euo pipefail
# Fast follow of laptop NTP (internet upstream on brain).
CONF=/etc/chrony/chrony.conf
if [ -f "$CONF" ]; then
  sudo cp -a "$CONF" "$CONF.deca-bak.$(date +%s)" 2>/dev/null || true
  # Replace server line(s) pointing at brain with aggressive poll + unlimited makestep
  if grep -qE '^server[[:space:]]+192\.168\.50\.1' "$CONF"; then
    sudo sed -i -E 's/^server[[:space:]]+192\.168\.50\.1.*/server 192.168.50.1 iburst minpoll 2 maxpoll 3/' "$CONF"
  else
    echo 'server 192.168.50.1 iburst minpoll 2 maxpoll 3' | sudo tee -a "$CONF" >/dev/null
  fi
  if grep -qE '^makestep' "$CONF"; then
    sudo sed -i -E 's/^makestep.*/makestep 0.1 -1/' "$CONF"
  else
    echo 'makestep 0.1 -1' | sudo tee -a "$CONF" >/dev/null
  fi
fi
sudo systemctl restart chrony 2>/dev/null || sudo systemctl restart chronyd 2>/dev/null || true
EOF
}

# Parallel snapshot: brain + all stations (fair Δ)
print_parallel_times() {
  local tmp
  tmp=$(mktemp -d)
  date -u +'%s.%N|%Y-%m-%d %H:%M:%S.%N UTC' >"$tmp/brain"
  local h
  for h in "${STATIONS[@]}"; do
    ssh_ctl "$h" 'printf "%s|%s|%s" "$(date -u +%s.%N)" "$(date -u +%Y-%m-%d\ %H:%M:%S.%N\ UTC)" "$(sudo hwclock -r --utc 2>/dev/null | awk "{print \$1\" \"\$2}")"' \
      >"$tmp/$h" &
  done
  wait
  python3 - "$tmp" "${STATIONS[*]}" <<'PY'
import sys
from pathlib import Path
td = Path(sys.argv[1])
hosts = sys.argv[2].split()
b_epoch, b_sys = td.joinpath("brain").read_text().strip().split("|", 1)
b = float(b_epoch)
print(f"{'Host':<10} {'System UTC':<36} {'RTC':<28} {'Δ vs PC'}")
print(f"{'brain':<10} {b_sys:<36} {'(PC chrony/internet)':<28} {0.0:+.4f}s")
for h in hosts:
    raw = td.joinpath(h).read_text().strip().split("|")
    epoch, sysu = float(raw[0]), raw[1]
    rtc = raw[2] if len(raw) > 2 else "?"
    print(f"{h:<10} {sysu:<36} {rtc:<28} {epoch - b:+.4f}s")
PY
  rm -rf "$tmp"
}

sync_all_simultaneous() {
  log "== simultaneous sync (one shared UTC, all stations at once) =="
  open_ssh_masters
  trap 'close_ssh_masters' EXIT

  local h stamp target target_str

  # 1) Freeze chrony so it cannot fight the barrier set
  for h in "${STATIONS[@]}"; do
    ssh_ctl "$h" 'sudo systemctl stop chrony 2>/dev/null || sudo systemctl stop chronyd 2>/dev/null || true' &
  done
  wait

  # 2) Rough align — identical stamp, parallel (gets everyone onto the same second)
  stamp=$(brain_utc)
  log "  rough set -> $stamp UTC (parallel)"
  for h in "${STATIONS[@]}"; do
    ssh_ctl "$h" "sudo date -u -s '$stamp'" >/dev/null &
  done
  wait
  sleep 0.3

  # 3) Barrier: every station busy-waits to the same epoch, then sets that exact second
  target=$(( $(date -u +%s) + 3 ))
  target_str=$(date -u -d "@$target" +'%Y-%m-%d %H:%M:%S')
  log "  barrier -> $target_str UTC (epoch $target)"
  for h in "${STATIONS[@]}"; do
    ssh_ctl "$h" bash -s <<EOF &
set -euo pipefail
TARGET=$target
TSTR='$target_str'
# Spin until the shared epoch (clocks already rough-aligned)
while [ "\$(date -u +%s)" -lt "\$TARGET" ]; do :; done
sudo date -u -s "\$TSTR"
# Record fire time before slow hwclock
echo "FIRE \$(hostname) \$(date -u +%s.%N)"
sudo hwclock -w --utc
EOF
  done
  wait

  # 4) Tight chrony follow of laptop (ongoing sub-ms lock)
  log "  tightening chrony -> 192.168.50.1 (minpoll 2)"
  for h in "${STATIONS[@]}"; do
    tighten_chrony_station "$h" &
  done
  wait
  sleep 2
  for h in "${STATIONS[@]}"; do
    ssh_ctl "$h" 'sudo chronyc -a makestep 2>/dev/null || true' &
  done
  wait
  sleep 1

  log ""
  log "== result =="
  print_parallel_times
  close_ssh_masters
  trap - EXIT
}

# Legacy single-host path kept for configure recovery only
sync_station() {
  local h="$1"
  log "-- single-host emergency set $h (prefer: sync mode for all-at-once) --"
  local stamp
  stamp=$(brain_utc)
  remote "$h" "sudo systemctl stop chrony 2>/dev/null || true; sudo date -u -s '$stamp'; sudo hwclock -w --utc; sudo systemctl start chrony 2>/dev/null || true"
}

probe_station() {
  local h="$1"
  log "-- probe I2C 0x68 on $h --"
  remote "$h" 'python3 - <<"PY"
import fcntl, os, sys
I2C_SLAVE = 0x0703
try:
    fd = os.open("/dev/i2c-1", os.O_RDWR)
except OSError as e:
    print("NO_I2C", e)
    sys.exit(2)
try:
    fcntl.ioctl(fd, I2C_SLAVE, 0x68)
    os.write(fd, b"\x00")
    data = os.read(fd, 1)
    print("OK", data.hex() if data else "empty")
except OSError as e:
    # Kernel driver may own 0x68 (shows as UU) — still fine
    print("BUSY_OR_OK", e)
finally:
    try:
        os.close(fd)
    except OSError:
        pass
PY'
}

case "$MODE" in
  status)
    ensure_brain_time
    open_ssh_masters
    trap 'close_ssh_masters' EXIT
    print_parallel_times
    close_ssh_masters
    trap - EXIT
    rc=0
    for h in "${STATIONS[@]}"; do station_status "$h" || rc=1; done
    exit "$rc"
    ;;
  sync)
    ensure_brain_time
    sync_all_simultaneous
    ;;
  all|configure|"")
    ensure_brain_time
    fail=0
    need_reboot=()
    for h in "${STATIONS[@]}"; do
      if ! ssh_ok "$h"; then
        log "skip unreachable $h"
        fail=1
        continue
      fi
      probe_station "$h" || true
      configure_station "$h" || fail=1
      # Detect missing RTC via remote
      if ! remote "$h" 'test -e /dev/rtc0 -o -e /dev/rtc'; then
        need_reboot+=("$h")
        fail=1
      fi
    done
    if ((${#need_reboot[@]})); then
      log ""
      log "Stations needing ONE reboot then re-sync: ${need_reboot[*]}"
      log "  ssh <host> 'sudo reboot'"
      log "  bash lab/deca_rtc_ds3231_sync.sh sync"
      exit "$fail"
    fi
    # One shared barrier for everyone (no per-station sequential drift)
    sync_all_simultaneous
    exit "$fail"
    ;;
  *)
    die "unknown mode '$MODE' (use: all | status | sync)"
    ;;
esac
