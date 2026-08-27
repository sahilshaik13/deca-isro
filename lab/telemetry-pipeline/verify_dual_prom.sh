#!/usr/bin/env bash
# Verify dual Flow 2 Prometheus split (Pi :9090 vs GNS3 :9091).
set -euo pipefail

ok=0
fail=0

check() {
  local name="$1" url="$2"
  if curl -sf --max-time 5 --http1.1 "$url" >/dev/null; then
    echo "OK  $name"
    ok=$((ok + 1))
  else
    echo "FAIL $name  ($url)"
    fail=$((fail + 1))
  fi
}

echo "=== Dual Flow 2 collector verify ==="
check "Pi bridge :9274" "http://127.0.0.1:9274/metrics"
check "GNS3 bridge :9276" "http://127.0.0.1:9276/metrics"
check "GNS3 exporter :9275" "http://127.0.0.1:9275/metrics"
check "GNS3 Prom :9091 healthy" "http://127.0.0.1:9091/-/healthy"
check "Pi Prom :9090 healthy" "http://127.0.0.1:9090/-/healthy"

echo
echo "--- GNS3 Prom targets (expect bridge_gns3 + gns3_fabric UP) ---"
curl -sf 'http://127.0.0.1:9091/api/v1/targets' 2>/dev/null | python3 -c '
import sys, json
try:
  d = json.load(sys.stdin)
except Exception as e:
  print("no :9091 targets:", e); sys.exit(0)
for t in d.get("data", {}).get("activeTargets", []):
  job = t.get("labels", {}).get("job", "?")
  health = t.get("health", "?")
  err = t.get("lastError") or ""
  print(f"  {job}: {health}" + (f"  err={err}" if err else ""))
' || echo "  (compose Prom not up)"

echo
echo "--- Pi Prom targets (must NOT list deca_gns3_fabric) ---"
curl -sf 'http://127.0.0.1:9090/api/v1/targets' 2>/dev/null | python3 -c '
import sys, json
try:
  d = json.load(sys.stdin)
except Exception as e:
  print("no :9090 targets (apply_host_prometheus.sh needs sudo):", e); sys.exit(0)
jobs = []
for t in d.get("data", {}).get("activeTargets", []):
  job = t.get("labels", {}).get("job", "?")
  health = t.get("health", "?")
  jobs.append(job)
  print(f"  {job}: {health}")
if "deca_gns3_fabric" in jobs:
  print("WARN: :9090 still scrapes GNS3 — re-apply host-prometheus.yml")
else:
  print("  (no GNS3 job on :9090 — good)")
' || echo "  (host Prom not reachable)"

echo
echo "--- sample GNS3 latency (exporter on :9091) ---"
curl -sf --get 'http://127.0.0.1:9091/api/v1/query' \
  --data-urlencode 'query=sdwan_path_latency_ms{job="deca_gns3_fabric"}' \
  | python3 -c 'import sys,json; r=json.load(sys.stdin).get("data",{}).get("result",[]); print("series", len(r), "sample", r[0]["value"] if r else None)' \
  || echo "no gns3 series yet"

echo
echo "--- sample GNS3 bridge kafka path ---"
curl -sf --get 'http://127.0.0.1:9091/api/v1/query' \
  --data-urlencode 'query=sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge_gns3"}' \
  | python3 -c 'import sys,json; r=json.load(sys.stdin).get("data",{}).get("result",[]); print("bridge series", len(r))' \
  || echo "bridge series pending"

echo
echo "summary ok=$ok fail=$fail"
[[ "$fail" -eq 0 ]]
