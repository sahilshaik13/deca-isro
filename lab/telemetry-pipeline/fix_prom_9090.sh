#!/usr/bin/env bash
# Reset host Prometheus TSDB after clock jump / out-of-bounds scrapes.
# Requires sudo. GNS3 compose Prom :9091 is unaffected.
set -euo pipefail
if [[ "${1:-}" != "--yes" ]]; then
  echo "usage: $0 --yes"
  echo "Stops host prometheus, wipes TSDB, restarts. Does NOT touch GNS3 :9091."
  exit 1
fi
sudo systemctl stop prometheus 2>/dev/null || sudo service prometheus stop 2>/dev/null || true
sudo rm -rf /var/lib/prometheus/metrics2/* /var/lib/prometheus/prometheus/* 2>/dev/null || \
  sudo rm -rf /var/lib/prometheus/* 2>/dev/null || true
sudo systemctl start prometheus 2>/dev/null || sudo service prometheus start 2>/dev/null || true
sleep 2
curl -sf http://127.0.0.1:9090/-/healthy && echo "host :9090 healthy (Pi fabric)" || echo "WARN: :9090 not healthy — run with sudo password"
echo "Pi:   DECA_PROM_URL_PI=http://127.0.0.1:9090"
echo "GNS3: DECA_PROM_URL_GNS3=http://127.0.0.1:9091"
