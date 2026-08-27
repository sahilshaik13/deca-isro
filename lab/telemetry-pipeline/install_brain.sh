#!/usr/bin/env bash
# install_brain.sh — install Docker + start DECA telemetry compose on the laptop.
# Run in a real terminal (needs your sudo password once):
#   bash lab/telemetry-pipeline/install_brain.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PIPE="$ROOT/lab/telemetry-pipeline"
cd "$PIPE"

echo "=== [1/4] Install docker.io + compose ==="
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true

echo "=== [2/4] Detect lab LAN for Kafka advertised host ==="
ADV="${KAFKA_ADVERTISED_HOST:-}"
if [[ -z "$ADV" ]]; then
  ADV="$(ip -4 -br addr show | awk '/192\.168\.50\./ {print $3}' | head -1 | cut -d/ -f1 || true)"
fi
ADV="${ADV:-192.168.50.1}"
export KAFKA_ADVERTISED_HOST="$ADV"
export DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
echo "KAFKA_ADVERTISED_HOST=$KAFKA_ADVERTISED_HOST"

echo "=== [3/4] Pull images + compose up ==="
# New shell group may not apply yet — use sg/docker or sudo docker
if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
elif sudo docker info >/dev/null 2>&1; then
  DOCKER=(sudo docker)
else
  echo "Docker daemon not ready"; exit 1
fi

"${DOCKER[@]}" compose pull
"${DOCKER[@]}" compose up -d

echo "=== [4/4] Wire host Prometheus (:9090) — authoritative TSDB ==="
HOST_PROM="$PIPE/host-prometheus.yml"
if [[ -f /etc/prometheus/prometheus.yml ]] && [[ -f "$HOST_PROM" ]]; then
  echo "Installing $HOST_PROM → /etc/prometheus/prometheus.yml"
  sudo cp "$HOST_PROM" /etc/prometheus/prometheus.yml
  sudo systemctl reload prometheus || sudo systemctl restart prometheus || true
else
  echo "WARN: skip host Prom patch (missing /etc/prometheus/prometheus.yml or host-prometheus.yml)"
fi

echo
echo "=== Status ==="
"${DOCKER[@]}" compose ps
echo
echo "Pi Prometheus:       http://127.0.0.1:9090  (host — Pi fabric only)"
echo "GNS3 Prometheus:     http://127.0.0.1:9091  (compose — GNS3 fabric only)"
echo "Kafka EXTERNAL:      ${KAFKA_ADVERTISED_HOST}:9092"
echo "Pi bridge:           http://127.0.0.1:9274/metrics  (topic sdwan_telemetry_pi)"
echo "GNS3 bridge:         http://127.0.0.1:9276/metrics  (topic sdwan_telemetry_gns3)"
echo "GNS3 exporter:       http://127.0.0.1:9275/metrics"
echo "Kafka exporter:      http://127.0.0.1:9308/metrics"
echo "SD-WAN controller:   http://127.0.0.1:9280/metrics (scraped by :9090 only)"
echo
echo "Next: deploy edge on Pis (topic sdwan_telemetry_pi):"
echo "  bash lab/telemetry-pipeline/install_edge.sh station1"
echo "  bash lab/telemetry-pipeline/install_edge.sh station2"
echo "GNS3 stubs (optional): bash lab/gns3/telemetry/install_gns3_edge.sh"
echo
echo "If 'permission denied' on docker: log out/in (or: newgrp docker)"
