#!/usr/bin/env bash
# GNS3 traffic — twin of lab/deca_iperf_qos_traffic.sh (Pi).
#
#   TT&C:    UDP 1M  --tos 0x88 (136)  -l 160  → :5004  → HTB 1:10
#   Payload: UDP 50M --tos 0x80 (128)  -l 1200 → :5006  → HTB 1:15
#   Admin:   TCP 20M untagged                   → :5201  → HTB 1:20
#
# Usage:
#   bash lab/gns3/traffic_control.sh start [ttc|payload|admin|mixed] [duration_s]
#   bash lab/gns3/traffic_control.sh stop|status
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CMD="${1:-status}"
PROFILE="${2:-${DECA_TRAFFIC_PROFILE:-mixed}}"
DUR_IN="${3:-${DECA_TRAFFIC_DURATION:-0}}"
if [[ "$DUR_IN" == "0" || -z "$DUR_IN" ]]; then
  DUR=86400
else
  DUR="$DUR_IN"
fi

STATE="$ROOT/state/chaos_state.json"
TOS_TTC=136
TOS_PAYLOAD=128

cname() { docker ps --format '{{.Names}}' | grep -F "GNS3.$1." | head -1; }

apply_l3() {
  local IPA IPB NRSC SAC PE1 PE2 CORE
  IPA=$(cname IPERF-A); IPB=$(cname IPERF-B)
  NRSC=$(cname CE-NRSC); SAC=$(cname CE-SAC)
  PE1=$(cname PE1); PE2=$(cname PE2); CORE=$(cname CORE-N)
  [[ -n "$IPA" && -n "$IPB" && -n "$PE1" && -n "$NRSC" && -n "$SAC" && -n "$CORE" ]] \
    || { echo "GNS3 nodes not running (need IPERF-A/B, CE-NRSC/SAC, PE1/2, CORE-N)"; return 1; }

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

  # PE WAN rate 40mbit like Pi eth0; apply_sla_htb installs ToS + dport filters
  RATE=40mbit BEST_EFFORT=1 bash "$ROOT/apply_sla_htb.sh" >/tmp/gns3_htb_traffic.log 2>&1 || true
  echo "L3 + HTB ready (Pi twin RATE=40mbit)"
}

stop_traffic() {
  echo "[gns3-traffic] stop (Pi twin)"
  docker rm -f \
    gns3-iperf-srv-ttc gns3-iperf-srv-payload gns3-iperf-srv-admin \
    gns3-iperf-ttc gns3-iperf-payload gns3-iperf-admin \
    gns3-iperf-srv 2>/dev/null || true
  local IPA
  IPA=$(cname IPERF-A || true)
  if [[ -n "$IPA" ]]; then
    docker exec "$IPA" sh -c 'pkill -f iperf3 2>/dev/null || true' || true
  fi
  python3 - <<PY
import json, time
from pathlib import Path
p = Path("$STATE")
p.parent.mkdir(parents=True, exist_ok=True)
cur = {}
if p.exists():
    try: cur = json.loads(p.read_text())
    except Exception: cur = {}
cur.update({
    "util_gre_mbps": 2.5,
    "ce_util_mbps_gold": 4.0,
    "ce_util_mbps_bronze": 2.0,
    "fault_id": cur.get("fault_id") or "",
    "updated_unix": time.time(),
    "traffic_profile": "",
})
p.write_text(json.dumps(cur, indent=2) + "\n")
print("traffic stopped")
PY
}

start_traffic() {
  local profile="$1" dur="$2"
  local IPA IPB
  IPA=$(cname IPERF-A); IPB=$(cname IPERF-B)
  [[ -n "$IPA" && -n "$IPB" ]] || { echo "IPERF nodes missing"; return 1; }

  if ! docker image inspect networkstatic/iperf3 >/dev/null 2>&1; then
    echo "ERROR: networkstatic/iperf3 required (Pi twin — no nc/dd fallback)" >&2
    docker pull networkstatic/iperf3 || return 1
  fi

  stop_traffic >/dev/null 2>&1 || true
  apply_l3

  # Three servers like Pi (ports 5004 / 5006 / 5201)
  docker run -d --rm --name gns3-iperf-srv-ttc --network "container:$IPB" \
    networkstatic/iperf3 -s -p 5004 >/dev/null
  docker run -d --rm --name gns3-iperf-srv-payload --network "container:$IPB" \
    networkstatic/iperf3 -s -p 5006 >/dev/null
  docker run -d --rm --name gns3-iperf-srv-admin --network "container:$IPB" \
    networkstatic/iperf3 -s -p 5201 >/dev/null
  sleep 1

  echo "[gns3-traffic] Pi twin profile=$profile TT&C=0x88/1M Payload=0x80/50M Admin=TCP/20M"
  case "$profile" in
    ttc)
      docker run -d --rm --name gns3-iperf-ttc --network "container:$IPA" \
        networkstatic/iperf3 -u -b 1M -l 160 -p 5004 --tos "$TOS_TTC" -c 10.10.6.10 -t "$dur" >/dev/null
      ;;
    payload)
      docker run -d --rm --name gns3-iperf-payload --network "container:$IPA" \
        networkstatic/iperf3 -u -b 50M -l 1200 -p 5006 --tos "$TOS_PAYLOAD" -c 10.10.6.10 -t "$dur" >/dev/null
      ;;
    admin)
      docker run -d --rm --name gns3-iperf-admin --network "container:$IPA" \
        networkstatic/iperf3 -b 20M -p 5201 -c 10.10.6.10 -t "$dur" >/dev/null
      ;;
    mixed|*)
      docker run -d --rm --name gns3-iperf-ttc --network "container:$IPA" \
        networkstatic/iperf3 -u -b 1M -l 160 -p 5004 --tos "$TOS_TTC" -c 10.10.6.10 -t "$dur" >/dev/null
      docker run -d --rm --name gns3-iperf-payload --network "container:$IPA" \
        networkstatic/iperf3 -u -b 50M -l 1200 -p 5006 --tos "$TOS_PAYLOAD" -c 10.10.6.10 -t "$dur" >/dev/null
      docker run -d --rm --name gns3-iperf-admin --network "container:$IPA" \
        networkstatic/iperf3 -b 20M -p 5201 -c 10.10.6.10 -t "$dur" >/dev/null
      ;;
  esac

  python3 - <<PY
import json, time
from pathlib import Path
p = Path("$STATE")
p.parent.mkdir(parents=True, exist_ok=True)
cur = {}
if p.exists():
    try: cur = json.loads(p.read_text())
    except Exception: cur = {}
prof = "$profile"
# Overlay hint only — wire truth is iperf through HTB
util = {"ttc": 6.0, "payload": 45.0, "admin": 18.0, "mixed": 55.0}.get(prof, 40.0)
cur.update({
    "util_gre_mbps": util,
    "ce_util_mbps_gold": 8.0 if prof in ("ttc", "mixed") else 5.0,
    "ce_util_mbps_bronze": 3.0,
    "traffic_profile": prof,
    "updated_unix": time.time(),
})
p.write_text(json.dumps(cur, indent=2) + "\n")
print("started profile=%s duration=%ss (Pi twin iperf3+HTB)" % (prof, "$dur"))
PY
}

status_traffic() {
  echo "=== gns3 traffic (Pi twin) ==="
  docker ps --format '{{.Names}} {{.Status}}' | grep -E 'gns3-iperf' || echo none
  if [[ -f "$STATE" ]]; then
    python3 -c "import json; d=json.load(open('$STATE')); print('profile=', d.get('traffic_profile'), 'util_hint=', d.get('util_gre_mbps'))"
  fi
}

case "$CMD" in
  start) start_traffic "$PROFILE" "$DUR" ;;
  stop) stop_traffic ;;
  status) status_traffic ;;
  *) echo "usage: $0 start|stop|status [ttc|payload|admin|mixed] [duration_s]"; exit 2 ;;
esac
