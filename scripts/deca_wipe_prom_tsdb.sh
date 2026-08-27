#!/usr/bin/env bash
# Wipe Prometheus TSDB only (no VPN heal). Use after clock jumps / "No data points".
# Requires laptop sudo.
set -euo pipefail
echo "Stopping prometheus and clearing /var/lib/prometheus/metrics2 ..."
sudo systemctl stop prometheus
sudo rm -rf /var/lib/prometheus/metrics2/*
sudo mkdir -p /var/lib/prometheus/metrics2
sudo chown -R prometheus:prometheus /var/lib/prometheus/metrics2
sudo chmod 0755 /var/lib/prometheus/metrics2
sudo systemctl reset-failed prometheus
sudo systemctl start prometheus
sleep 4
curl -sf --max-time 3 http://127.0.0.1:9090/-/ready && echo " Prometheus ready"
curl -sf http://127.0.0.1:9090/api/v1/targets | python3 -c '
import sys, json
for t in json.load(sys.stdin)["data"]["activeTargets"]:
    print(" ", t["health"], t["labels"].get("job"), t["labels"].get("instance"), t.get("lastError") or "-")
'
echo "Done. Wait ~30s for rate() panels to fill."
