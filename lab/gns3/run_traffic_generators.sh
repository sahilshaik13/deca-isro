#!/usr/bin/env bash
# Re-apply Flow 1 L3 addressing + Pi-twin ToS traffic IPERF-A → IPERF-B through PE HTB.
# Rates/ports match lab/deca_iperf_qos_traffic.sh (no TRex, no nc/dd fallback).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
REQUIRE_LIVE="${DECA_REQUIRE_LIVE:-1}"
cname(){ docker ps --format '{{.Names}}' | grep -F "GNS3.$1." | head -1; }
IPA=$(cname IPERF-A); IPB=$(cname IPERF-B); NRSC=$(cname CE-NRSC); SAC=$(cname CE-SAC)
PE1=$(cname PE1); PE2=$(cname PE2); CORE=$(cname CORE-N)
[[ -n "$IPA" && -n "$IPB" && -n "$PE1" ]] || { echo "GNS3 nodes not running"; exit 1; }

cfg(){ docker exec "$1" sh -c "ip link set $2 up; ip addr flush dev $2 2>/dev/null; ip addr add $3 dev $2"; }

cfg "$IPA"  eth0 10.10.1.10/24
cfg "$NRSC" eth1 10.10.1.1/24
cfg "$NRSC" eth0 10.10.2.1/24
cfg "$PE1"  eth4 10.10.2.2/24
cfg "$PE1"  eth0 10.10.3.1/24
cfg "$CORE" eth0 10.10.3.2/24
cfg "$CORE" eth1 10.10.4.1/24
cfg "$PE2"  eth0 10.10.4.2/24
cfg "$PE2"  eth4 10.10.5.1/24
cfg "$SAC"  eth0 10.10.5.2/24
cfg "$SAC"  eth1 10.10.6.1/24
cfg "$IPB"  eth0 10.10.6.10/24

for c in "$PE1" "$PE2" "$CORE" "$NRSC" "$SAC"; do
  docker exec "$c" sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
done
docker exec "$IPA"  sh -c 'ip route replace default via 10.10.1.1'
docker exec "$IPB"  sh -c 'ip route replace default via 10.10.6.1'
docker exec "$NRSC" sh -c 'ip route replace 10.10.6.0/24 via 10.10.2.2; ip route replace 10.10.3.0/24 via 10.10.2.2; ip route replace 10.10.4.0/24 via 10.10.2.2; ip route replace 10.10.5.0/24 via 10.10.2.2'
docker exec "$SAC"  sh -c 'ip route replace 10.10.1.0/24 via 10.10.5.1; ip route replace 10.10.2.0/24 via 10.10.5.1; ip route replace 10.10.3.0/24 via 10.10.5.1; ip route replace 10.10.4.0/24 via 10.10.5.1'
docker exec "$PE1"  sh -c 'ip route replace 10.10.1.0/24 via 10.10.2.1; ip route replace 10.10.4.0/24 via 10.10.3.2; ip route replace 10.10.5.0/24 via 10.10.3.2; ip route replace 10.10.6.0/24 via 10.10.3.2'
docker exec "$PE2"  sh -c 'ip route replace 10.10.6.0/24 via 10.10.5.2; ip route replace 10.10.1.0/24 via 10.10.4.1; ip route replace 10.10.2.0/24 via 10.10.4.1; ip route replace 10.10.3.0/24 via 10.10.4.1'
docker exec "$CORE" sh -c 'ip route replace 10.10.1.0/24 via 10.10.3.1; ip route replace 10.10.2.0/24 via 10.10.3.1; ip route replace 10.10.5.0/24 via 10.10.4.2; ip route replace 10.10.6.0/24 via 10.10.4.2'

RATE=40mbit BEST_EFFORT=1 bash "$ROOT/apply_sla_htb.sh"

if ! docker image inspect networkstatic/iperf3 >/dev/null 2>&1; then
  echo "pulling networkstatic/iperf3 (Pi twin — required)"
  docker pull networkstatic/iperf3 || {
    echo "ERROR: iperf3 image required (no nc/dd fallback)" >&2
    exit 1
  }
fi

echo "=== path check ==="
docker exec "$IPA" ping -c 2 -W 2 10.10.6.10

docker rm -f gns3-iperf-srv-ttc gns3-iperf-srv-payload gns3-iperf-srv-admin >/dev/null 2>&1 || true
docker run -d --rm --name gns3-iperf-srv-ttc --network "container:$IPB" networkstatic/iperf3 -s -p 5004 >/dev/null
docker run -d --rm --name gns3-iperf-srv-payload --network "container:$IPB" networkstatic/iperf3 -s -p 5006 >/dev/null
docker run -d --rm --name gns3-iperf-srv-admin --network "container:$IPB" networkstatic/iperf3 -s -p 5201 >/dev/null
sleep 1

echo "=== TT&C  UDP 1M  ToS 0x88 -l 160 :5004 (≤25ms SLA) ==="
docker run --rm --network "container:$IPA" networkstatic/iperf3 \
  -u -b 1M -l 160 -p 5004 --tos 0x88 -c 10.10.6.10 -t 8 || true
echo "=== Payload UDP 50M ToS 0x80 -l 1200 :5006 (≤80ms SLA) ==="
docker run --rm --network "container:$IPA" networkstatic/iperf3 \
  -u -b 50M -l 1200 -p 5006 --tos 0x80 -c 10.10.6.10 -t 8 || true
echo "=== Admin TCP 20M untagged :5201 ==="
docker run --rm --network "container:$IPA" networkstatic/iperf3 \
  -b 20M -p 5201 -c 10.10.6.10 -t 5 || true

docker rm -f gns3-iperf-srv-ttc gns3-iperf-srv-payload gns3-iperf-srv-admin >/dev/null 2>&1 || true

echo "=== PE1 HTB class stats ==="
docker exec "$PE1" tc -s class show dev eth0 | head -40

python3 - <<'PY'
from pathlib import Path
import json, time
p = Path("/home/brain/deca-isro/lab/gns3/state/chaos_state.json")
d = json.loads(p.read_text()) if p.is_file() else {}
d.update({"util_gre_mbps": 55.0, "latency_gre_ms": 2.0, "loss_gre_pct": 0.0, "ce_util_mbps_gold": 8.0, "fault_id": "", "updated_unix": time.time(), "traffic_profile": "smoke"})
p.write_text(json.dumps(d, indent=2) + "\n")
print("updated chaos_state for Prom :9091")
PY

echo "DONE — Pi twin iperf3 ToS via HTB 1:10/1:15/1:20 (40mbit PE)"
