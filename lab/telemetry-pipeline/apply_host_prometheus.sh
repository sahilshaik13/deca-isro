#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
sudo cp "$ROOT/host-prometheus.yml" /etc/prometheus/prometheus.yml
sudo systemctl reload prometheus 2>/dev/null || sudo systemctl restart prometheus
curl -sS 'http://127.0.0.1:9090/api/v1/targets' | python3 -c '
import sys,json
d=json.load(sys.stdin)
for t in sorted(d["data"]["activeTargets"], key=lambda x: x["labels"].get("job","")):
  print(t["health"], t["labels"].get("job"), t["labels"].get("instance"))
'
