#!/usr/bin/env bash
# setup_softflowd.sh — install/configure softflowd for DECA IPFIX → Telegraf
#
# Attaches to eth0 + gre-te-core, exports IPFIX to local Telegraf on
# 127.0.0.1:2055 (inputs.netflow). Air-gapped: uses apt local cache / already
# installed package only — does not curl the Internet.
#
# Usage (on station1 / station2 as root):
#   sudo bash setup_softflowd.sh
#   sudo bash setup_softflowd.sh status
set -euo pipefail

CMD="${1:-install}"
IFACES="${SOFTFLOWD_IFACES:-eth0,gre-te-core}"
SINK="${SOFTFLOWD_SINK:-127.0.0.1:2055}"
CTL="${SOFTFLOWD_CTL:-/var/run/softflowd.ctl}"
UNIT=/etc/systemd/system/deca-softflowd.service

need_root() {
  [[ "$(id -u)" -eq 0 ]] || { echo "Run as root"; exit 1; }
}

install_pkg() {
  if command -v softflowd >/dev/null 2>&1; then
    echo "[softflowd] already installed: $(command -v softflowd)"
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    # Air-gap: only succeeds if package is in local apt cache / mirror
    apt-get install -y softflowd || {
      echo "FAIL: softflowd not in local apt cache. Copy arm64 .deb onto the Pi and dpkg -i."
      exit 1
    }
  else
    echo "FAIL: softflowd missing and no apt-get"
    exit 1
  fi
}

write_unit() {
  # One softflowd instance can only bind a single interface; run two units if needed.
  # This primary unit watches eth0; gre helper below.
  cat >"$UNIT" <<EOF
[Unit]
Description=DECA softflowd IPFIX exporter (eth0 → Telegraf :2055)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/sbin/softflowd -v 10 -i eth0 -n ${SINK} -c ${CTL} -d
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/deca-softflowd-gre.service <<EOF
[Unit]
Description=DECA softflowd IPFIX exporter (gre-te-core → Telegraf :2055)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Separate control socket; same IPFIX sink (Telegraf multiplexes on :2055)
ExecStart=/bin/bash -c 'IF=gre-te-core; ip link show \$IF >/dev/null 2>&1 || exit 0; exec /usr/sbin/softflowd -v 10 -i \$IF -n ${SINK} -c /var/run/softflowd-gre.ctl -d'
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

start_services() {
  systemctl daemon-reload
  systemctl enable --now deca-softflowd.service
  systemctl enable --now deca-softflowd-gre.service || true
  sleep 1
  systemctl --no-pager --full status deca-softflowd.service | head -15 || true
  ss -ulnp | grep -E '2055|softflow' || true
  echo "[softflowd] exporting IPFIX to ${SINK} (ifaces: ${IFACES})"
  echo "[softflowd] ensure Telegraf inputs.netflow listens on udp://:2055"
}

status() {
  systemctl is-active deca-softflowd.service || true
  systemctl is-active deca-softflowd-gre.service || true
  softflowctl -c "$CTL" statistics 2>/dev/null | head -20 || true
  softflowctl -c /var/run/softflowd-gre.ctl statistics 2>/dev/null | head -10 || true
}

case "$CMD" in
  install)
    need_root
    install_pkg
    write_unit
    start_services
    ;;
  status)
    status
    ;;
  *)
    echo "Usage: $0 install|status"
    exit 2
    ;;
esac
