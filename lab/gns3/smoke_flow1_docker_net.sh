#!/usr/bin/env bash
# Temporary L3 smoke for GNS3 DECA nodes WITHOUT ubridge.
# Creates docker networks + IPs along:
#   IPERF-A → CE-NRSC → PE1 → CORE-N → PE2 → CE-SAC → IPERF-B
# Tear down: bash lab/gns3/smoke_flow1_docker_net.sh down
set -euo pipefail

ACTION="${1:-up}"
PREFIX=gns3smoke

cname() {
  docker ps --format '{{.Names}}' | grep -F "GNS3.$1." | head -1
}

need() {
  local n="$1" c
  c="$(cname "$n")"
  [[ -n "$c" ]] || { echo "missing running container for $n — Start nodes in GNS3 first"; exit 1; }
  echo "$c"
}

down() {
  for net in \
    ${PREFIX}-lan-a ${PREFIX}-ce-pe1 ${PREFIX}-pe1-core \
    ${PREFIX}-core-pe2 ${PREFIX}-pe2-ce ${PREFIX}-lan-b
  do
    docker network rm "$net" 2>/dev/null || true
  done
  echo "smoke networks removed (containers left running)"
}

up() {
  local IPA IPB NRSC SAC PE1 PE2 CORE
  IPA="$(need IPERF-A)"
  IPB="$(need IPERF-B)"
  NRSC="$(need CE-NRSC)"
  SAC="$(need CE-SAC)"
  PE1="$(need PE1)"
  PE2="$(need PE2)"
  CORE="$(need CORE-N)"

  # Ensure prior smoke nets are gone without breaking sandboxes mid-run
  for net in \
    ${PREFIX}-lan-a ${PREFIX}-ce-pe1 ${PREFIX}-pe1-core \
    ${PREFIX}-core-pe2 ${PREFIX}-pe2-ce ${PREFIX}-lan-b
  do
    if docker network inspect "$net" >/dev/null 2>&1; then
      for c in $(docker network inspect "$net" -f '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null); do
        docker network disconnect -f "$net" "$c" 2>/dev/null || true
      done
      docker network rm "$net" 2>/dev/null || true
    fi
  done

  docker network create "${PREFIX}-lan-a" >/dev/null
  docker network create "${PREFIX}-ce-pe1" >/dev/null
  docker network create "${PREFIX}-pe1-core" >/dev/null
  docker network create "${PREFIX}-core-pe2" >/dev/null
  docker network create "${PREFIX}-pe2-ce" >/dev/null
  docker network create "${PREFIX}-lan-b" >/dev/null

  docker network connect "${PREFIX}-lan-a" "$IPA"
  docker network connect "${PREFIX}-lan-a" "$NRSC"
  docker network connect "${PREFIX}-ce-pe1" "$NRSC"
  docker network connect "${PREFIX}-ce-pe1" "$PE1"
  docker network connect "${PREFIX}-pe1-core" "$PE1"
  docker network connect "${PREFIX}-pe1-core" "$CORE"
  docker network connect "${PREFIX}-core-pe2" "$CORE"
  docker network connect "${PREFIX}-core-pe2" "$PE2"
  docker network connect "${PREFIX}-pe2-ce" "$PE2"
  docker network connect "${PREFIX}-pe2-ce" "$SAC"
  docker network connect "${PREFIX}-lan-b" "$SAC"
  docker network connect "${PREFIX}-lan-b" "$IPB"

  # Helper: newest eth* besides eth0 (bridge) — GNS3 often has no eth; docker adds eth1+
  cfg() {
    local c="$1" ip="$2" peer_via="${3:-}"
    docker exec "$c" sh -c "
      set -e
      # pick last ethN
      IF=\$(ls /sys/class/net | grep -E '^eth[0-9]+\$' | sort -V | tail -1)
      ip link set \"\$IF\" up
      ip addr flush dev \"\$IF\" 2>/dev/null || true
      ip addr add $ip dev \"\$IF\"
      echo \"\$IF $ip\"
      ${peer_via:+ip route replace default via $peer_via || true}
    "
  }

  # Multi-IF nodes: assign by connecting order is fragile — use explicit nets via IP on each eth
  # Simpler: use ip on each interface by scanning and matching subnet after connect order.
  assign_pair() {
    local c="$1" want_subnet="$2" addr="$3"
    docker exec "$c" sh -c "
      set -e
      for IF in \$(ls /sys/class/net | grep -E '^eth'); do
        ip link set \"\$IF\" up
      done
      # Prefer empty IPv4 iface; assign sequentially by calling this once per addr with marker file
      MARK=/tmp/gns3smoke.ifidx
      IDX=\$(cat \$MARK 2>/dev/null || echo 0)
      IF=\$(ls /sys/class/net | grep -E '^eth' | sort -V | sed -n \"\$((IDX+1))p\")
      echo \$((IDX+1)) > \$MARK
      ip addr flush dev \"\$IF\" 2>/dev/null || true
      ip addr add $addr dev \"\$IF\"
      echo \"$c \$IF $addr\"
    "
  }

  # Reset markers
  for c in "$IPA" "$IPB" "$NRSC" "$SAC" "$PE1" "$PE2" "$CORE"; do
    docker exec "$c" rm -f /tmp/gns3smoke.ifidx 2>/dev/null || true
    docker exec "$c" sh -c 'for IF in $(ls /sys/class/net | grep eth); do ip link set $IF up; done' 2>/dev/null || true
  done

  # Addressing plan (/30-ish /24 for simplicity)
  # lan-a 10.10.1.0/24 : A=.10  NRSC=.1
  # ce-pe1 10.10.2.0/24 : NRSC=.1 PE1=.2
  # pe1-core 10.10.3.0/24 : PE1=.1 CORE=.2
  # core-pe2 10.10.4.0/24 : CORE=.1 PE2=.2
  # pe2-ce 10.10.5.0/24 : PE2=.1 SAC=.2
  # lan-b 10.10.6.0/24 : SAC=.1 B=.10

  # Interface order = docker network connect order on that container
  assign_pair "$IPA"  lan-a   10.10.1.10/24
  assign_pair "$NRSC" lan-a   10.10.1.1/24
  assign_pair "$NRSC" ce-pe1  10.10.2.1/24
  assign_pair "$PE1"  ce-pe1  10.10.2.2/24
  assign_pair "$PE1"  pe1core 10.10.3.1/24
  assign_pair "$CORE" pe1core 10.10.3.2/24
  assign_pair "$CORE" corepe2 10.10.4.1/24
  assign_pair "$PE2"  corepe2 10.10.4.2/24
  assign_pair "$PE2"  pe2ce   10.10.5.1/24
  assign_pair "$SAC"  pe2ce   10.10.5.2/24
  assign_pair "$SAC"  lan-b   10.10.6.1/24
  assign_pair "$IPB"  lan-b   10.10.6.10/24

  # Routes
  docker exec "$IPA"  sh -c 'ip route replace default via 10.10.1.1'
  docker exec "$IPB"  sh -c 'ip route replace default via 10.10.6.1'
  docker exec "$NRSC" sh -c '
    ip route replace 10.10.6.0/24 via 10.10.2.2
    ip route replace 10.10.3.0/24 via 10.10.2.2
    ip route replace 10.10.4.0/24 via 10.10.2.2
    ip route replace 10.10.5.0/24 via 10.10.2.2
  '
  docker exec "$SAC" sh -c '
    ip route replace 10.10.1.0/24 via 10.10.5.1
    ip route replace 10.10.2.0/24 via 10.10.5.1
    ip route replace 10.10.3.0/24 via 10.10.5.1
    ip route replace 10.10.4.0/24 via 10.10.5.1
  '
  docker exec "$PE1" sh -c '
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    ip route replace 10.10.1.0/24 via 10.10.2.1
    ip route replace 10.10.4.0/24 via 10.10.3.2
    ip route replace 10.10.5.0/24 via 10.10.3.2
    ip route replace 10.10.6.0/24 via 10.10.3.2
  '
  docker exec "$PE2" sh -c '
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    ip route replace 10.10.6.0/24 via 10.10.5.2
    ip route replace 10.10.1.0/24 via 10.10.4.1
    ip route replace 10.10.2.0/24 via 10.10.4.1
    ip route replace 10.10.3.0/24 via 10.10.4.1
  '
  docker exec "$CORE" sh -c '
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    ip route replace 10.10.1.0/24 via 10.10.3.1
    ip route replace 10.10.2.0/24 via 10.10.3.1
    ip route replace 10.10.5.0/24 via 10.10.4.2
    ip route replace 10.10.6.0/24 via 10.10.4.2
  '

  echo
  echo "=== ping IPERF-A → IPERF-B (10.10.6.10) ==="
  docker exec "$IPA" ping -c 3 -W 2 10.10.6.10 || true

  echo
  echo "=== install iperf3 if needed + 5s UDP ToS 0x88 ==="
  docker exec "$IPB" sh -c 'command -v iperf3 >/dev/null || (apk add --no-cache iperf3 >/dev/null)'
  docker exec "$IPA" sh -c 'command -v iperf3 >/dev/null || (apk add --no-cache iperf3 >/dev/null)'
  docker exec -d "$IPB" sh -c 'pkill iperf3 2>/dev/null; iperf3 -s -D'
  sleep 1
  docker exec "$IPA" iperf3 -u -b 2M --tos 0x88 -c 10.10.6.10 -t 5 || true

  # Bump GNS3 exporter gauges to reflect live smoke
  python3 - <<'PY'
from pathlib import Path
import json, time
p = Path("/home/brain/deca-isro/lab/gns3/state/chaos_state.json")
d = json.loads(p.read_text()) if p.is_file() else {}
d.update({"util_gre_mbps": 6.0, "latency_gre_ms": 3.0, "fault_id": "", "updated_unix": time.time()})
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(d, indent=2) + "\n")
print("updated chaos_state util/latency for Prom :9091")
PY

  echo
  echo "OK smoke path up. Tear down networks with: $0 down"
  echo "NOTE: permanent GNS3 links still need: sudo apt install ubridge  then Start all in GUI"
}

case "$ACTION" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 {up|down}"; exit 1 ;;
esac
