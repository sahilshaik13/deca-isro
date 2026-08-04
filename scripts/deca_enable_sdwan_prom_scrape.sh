#!/usr/bin/env bash
# Enable Prometheus scrape of the local SD-WAN controller (:9280).
# Fixes empty Graph panels for sdwan_* when only the (broken) Telegraf mirror existed.
# Requires laptop sudo.
set -euo pipefail
YML=/etc/prometheus/prometheus.yml
SNIP='# DECA SD-WAN controller (lab/deca_sdwan_controller.py)
  - job_name: "deca_sdwan_controller"
    static_configs:
      - targets: ["127.0.0.1:9280"]
'
if [[ ! -f "$YML" ]]; then
  echo "missing $YML"; exit 1
fi
if grep -q 'job_name: "deca_sdwan_controller"' "$YML"; then
  echo "scrape job already present in $YML"
else
  echo "Appending deca_sdwan_controller scrape job to $YML"
  sudo cp -a "$YML" "$YML.bak.$(date +%s)"
  printf '\n%s\n' "$SNIP" | sudo tee -a "$YML" >/dev/null
fi
sudo systemctl reload prometheus 2>/dev/null || sudo systemctl restart prometheus
sleep 3
curl -sf http://127.0.0.1:9090/-/ready && echo " Prometheus ready"
curl -sf http://127.0.0.1:9090/api/v1/targets | python3 -c '
import json,sys
for t in json.load(sys.stdin)["data"]["activeTargets"]:
    j=t["labels"].get("job");
    if j and "sdwan" in j or t["labels"].get("instance","").endswith(":9280"):
        print(" ", t["health"], j, t["labels"].get("instance"), t.get("lastError") or "-")
'
echo "Try Graph: sdwan_active_path or sdwan_path_latency_ms (last 15m)"
