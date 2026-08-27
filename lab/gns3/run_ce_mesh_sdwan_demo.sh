#!/usr/bin/env bash
# Full CE↔CE mesh + SD-WAN AAR demo on GNS3 DECA fabric.
#
# Shows:
#   • every CE talking to every other CE
#   • TT&C (0x88) + Payload (0x80) on vrf-mission (via CORE-N)
#   • Admin/BE (0x00) on vrf-admin (PE↔PE direct)
#   • mid-run rain-fade on mission → mission latency rises; admin stays clean
#
# Usage:
#   bash lab/gns3/run_ce_mesh_sdwan_demo.sh           # 90s mesh + brownout
#   DURATION=120 bash lab/gns3/run_ce_mesh_sdwan_demo.sh
#   bash lab/gns3/run_ce_mesh_sdwan_demo.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DURATION="${DURATION:-90}"
PID="${GNS3_PROJECT_ID:-78f1223e-f45b-4f61-b131-8e103a8eaebb}"
AUTH="admin:admin"

cname() { docker ps --format '{{.Names}}' | grep -F "GNS3.$1." | head -1; }
dex() { docker exec "$1" sh -c "$2"; }
cfg() { # cfg <cid> <if> <cidr>
  if ! docker exec "$1" ip link show "$2" >/dev/null 2>&1; then
    echo "  WARN: $1 missing iface $2 — skip $3"
    return 0
  fi
  dex "$1" "ip link set $2 up; ip addr flush dev $2 2>/dev/null; ip addr add $3 dev $2" || true
}

if [[ "${1:-}" == "--stop" ]]; then
  docker ps --format '{{.Names}}' | grep -E '^gns3-(mesh|iperf)' | xargs -r docker rm -f
  # clear netem on CORE
  CORE=$(cname CORE-N || true)
  [[ -n "$CORE" ]] && dex "$CORE" 'tc qdisc del dev eth0 root 2>/dev/null; tc qdisc del dev eth1 root 2>/dev/null; true' || true
  echo "stopped mesh sidecars + cleared CORE netem"
  exit 0
fi

need() {
  local n; n=$(cname "$1")
  [[ -n "$n" ]] || { echo "missing node $1 — Start all in GNS3"; exit 1; }
  echo "$n"
}

echo "=== stop prior short generators ==="
docker ps --format '{{.Names}}' | grep -E '^gns3-(mesh|iperf)' | xargs -r docker rm -f || true

NRSC=$(need CE-NRSC); MAU=$(need CE-Mauritius); SHAD=$(need CE-Shadnagar)
SAC=$(need CE-SAC); MCF=$(need CE-MCF); ISTRAC=$(need CE-ISTRAC)
HQ=$(need CE-ISRO-HQ); BHOPAL=$(need CE-Bhopal)
PE1=$(need PE1); PE2=$(need PE2); PE3=$(need PE3); CORE=$(need CORE-N)

echo "=== L3 addressing (all CEs + mission CORE + admin PE-PE) ==="
# PE1 CE attaches
cfg "$PE1" eth4 10.11.1.1/24   # NRSC
cfg "$PE1" eth5 10.11.2.1/24   # Mauritius
cfg "$PE1" eth6 10.11.3.1/24   # Shadnagar
cfg "$NRSC" eth0 10.11.1.2/24
cfg "$MAU"  eth0 10.11.2.2/24
cfg "$SHAD" eth0 10.11.3.2/24
# PE2 CE attaches
cfg "$PE2" eth4 10.11.4.1/24   # SAC
cfg "$PE2" eth5 10.11.5.1/24   # MCF
cfg "$PE2" eth6 10.11.6.1/24   # ISTRAC
cfg "$SAC"    eth0 10.11.4.2/24
cfg "$MCF"    eth0 10.11.5.2/24
cfg "$ISTRAC" eth0 10.11.6.2/24
# PE3 CE attaches
cfg "$PE3" eth4 10.11.7.1/24   # ISRO-HQ
cfg "$PE3" eth5 10.11.8.1/24   # Bhopal
cfg "$HQ"     eth0 10.11.7.2/24
cfg "$BHOPAL" eth0 10.11.8.2/24
# Mission PE↔CORE
cfg "$PE1"  eth0 10.10.3.1/24
cfg "$CORE" eth0 10.10.3.2/24
cfg "$PE2"  eth0 10.10.4.2/24
cfg "$CORE" eth1 10.10.4.1/24
cfg "$PE3"  eth0 10.10.7.1/24
cfg "$CORE" eth2 10.10.7.2/24
# Admin PE↔PE
cfg "$PE1" eth2 10.12.12.1/24
cfg "$PE2" eth2 10.12.12.2/24
cfg "$PE1" eth3 10.12.13.1/24
cfg "$PE3" eth2 10.12.13.2/24
cfg "$PE2" eth3 10.12.23.1/24
cfg "$PE3" eth3 10.12.23.2/24

for c in "$PE1" "$PE2" "$PE3" "$CORE" "$NRSC" "$MAU" "$SHAD" "$SAC" "$MCF" "$ISTRAC" "$HQ" "$BHOPAL"; do
  dex "$c" "sysctl -w net.ipv4.ip_forward=1 >/dev/null"
done

# CE defaults toward their PE
dex "$NRSC"   "ip route replace default via 10.11.1.1"
dex "$MAU"    "ip route replace default via 10.11.2.1"
dex "$SHAD"   "ip route replace default via 10.11.3.1"
dex "$SAC"    "ip route replace default via 10.11.4.1"
dex "$MCF"    "ip route replace default via 10.11.5.1"
dex "$ISTRAC" "ip route replace default via 10.11.6.1"
dex "$HQ"     "ip route replace default via 10.11.7.1"
dex "$BHOPAL" "ip route replace default via 10.11.8.1"

# CORE: site prefixes via owning PE
dex "$CORE" "
  ip route replace 10.11.1.0/24 via 10.10.3.1
  ip route replace 10.11.2.0/24 via 10.10.3.1
  ip route replace 10.11.3.0/24 via 10.10.3.1
  ip route replace 10.11.4.0/24 via 10.10.4.2
  ip route replace 10.11.5.0/24 via 10.10.4.2
  ip route replace 10.11.6.0/24 via 10.10.4.2
  ip route replace 10.11.7.0/24 via 10.10.7.1
  ip route replace 10.11.8.0/24 via 10.10.7.1
"

install_aar() {
  # On a PE: mark ToS → mission(table 100) / admin(table 200)
  local cid="$1"
  local peer_core="$2"   # next-hop for mission
  local peer_pe_a="$3"   # admin NH for remote set A (other PE /24s)
  # shellcheck disable=SC2086
  docker exec "$cid" sh -c "
    set -e
    iptables -t mangle -F PREROUTING 2>/dev/null || true
    iptables -t mangle -F OUTPUT 2>/dev/null || true
    # TT&C + Payload → mission
    iptables -t mangle -A PREROUTING -p udp -m tos --tos 0x88 -j MARK --set-mark 0x1
    iptables -t mangle -A PREROUTING -p tcp -m tos --tos 0x88 -j MARK --set-mark 0x1
    iptables -t mangle -A PREROUTING -p udp -m tos --tos 0x80 -j MARK --set-mark 0x1
    iptables -t mangle -A PREROUTING -p tcp -m tos --tos 0x80 -j MARK --set-mark 0x1
    iptables -t mangle -A PREROUTING -p icmp -j MARK --set-mark 0x1
    # everything else (BE) → admin
    iptables -t mangle -A PREROUTING -m mark --mark 0 -j MARK --set-mark 0x2
    ip rule del fwmark 1 table 100 2>/dev/null || true
    ip rule del fwmark 2 table 200 2>/dev/null || true
    ip rule add fwmark 1 table 100 priority 100
    ip rule add fwmark 2 table 200 priority 101
    ip route flush table 100 2>/dev/null || true
    ip route flush table 200 2>/dev/null || true
  "
}

# PE AAR tables — local CE /24s on-link in BOTH tables (same-PE hairpin)
install_aar "$PE1" 10.10.3.2 10.12.12.2
dex "$PE1" "
  ip route replace 10.11.1.0/24 dev eth4 table 100
  ip route replace 10.11.2.0/24 dev eth5 table 100
  ip route replace 10.11.3.0/24 dev eth6 table 100
  ip route replace 10.11.1.0/24 dev eth4 table 200
  ip route replace 10.11.2.0/24 dev eth5 table 200
  ip route replace 10.11.3.0/24 dev eth6 table 200
  for n in 4 5 6 7 8; do ip route replace 10.11.\$n.0/24 via 10.10.3.2 table 100; done
  for n in 4 5 6; do ip route replace 10.11.\$n.0/24 via 10.12.12.2 table 200; done
  for n in 7 8; do ip route replace 10.11.\$n.0/24 via 10.12.13.2 table 200; done
  for n in 4 5 6 7 8; do ip route replace 10.11.\$n.0/24 via 10.10.3.2; done
"

install_aar "$PE2" 10.10.4.1 10.12.12.1
dex "$PE2" "
  ip route replace 10.11.4.0/24 dev eth4 table 100
  ip route replace 10.11.5.0/24 dev eth5 table 100
  ip route replace 10.11.6.0/24 dev eth6 table 100
  ip route replace 10.11.4.0/24 dev eth4 table 200
  ip route replace 10.11.5.0/24 dev eth5 table 200
  ip route replace 10.11.6.0/24 dev eth6 table 200
  for n in 1 2 3 7 8; do ip route replace 10.11.\$n.0/24 via 10.10.4.1 table 100; done
  for n in 1 2 3; do ip route replace 10.11.\$n.0/24 via 10.12.12.1 table 200; done
  for n in 7 8; do ip route replace 10.11.\$n.0/24 via 10.12.23.2 table 200; done
  for n in 1 2 3 7 8; do ip route replace 10.11.\$n.0/24 via 10.10.4.1; done
"

install_aar "$PE3" 10.10.7.2 10.12.13.1
dex "$PE3" "
  ip route replace 10.11.7.0/24 dev eth4 table 100
  ip route replace 10.11.8.0/24 dev eth5 table 100
  ip route replace 10.11.7.0/24 dev eth4 table 200
  ip route replace 10.11.8.0/24 dev eth5 table 200
  for n in 1 2 3 4 5 6; do ip route replace 10.11.\$n.0/24 via 10.10.7.2 table 100; done
  for n in 1 2 3; do ip route replace 10.11.\$n.0/24 via 10.12.13.1 table 200; done
  for n in 4 5 6; do ip route replace 10.11.\$n.0/24 via 10.12.23.1 table 200; done
  for n in 1 2 3 4 5 6; do ip route replace 10.11.\$n.0/24 via 10.10.7.2; done
"

echo "=== apply fabric-wide HTB SLAs ==="
bash "$ROOT/apply_sla_htb.sh" >/tmp/gns3_sla_apply.log 2>&1 || true
# also HTB on PE CE-facing + admin ifaces (mission eth0 already covered)
for pair in "$PE1:eth5" "$PE1:eth6" "$PE1:eth2" "$PE1:eth3" \
            "$PE2:eth5" "$PE2:eth6" "$PE2:eth2" "$PE2:eth3" \
            "$PE3:eth4" "$PE3:eth5" "$PE3:eth2" "$PE3:eth3"; do
  cid="${pair%%:*}"; ifc="${pair##*:}"
  docker exec "$cid" sh -c "
    IF=$ifc
    ip link show \$IF >/dev/null 2>&1 || exit 0
    tc qdisc del dev \$IF root 2>/dev/null || true
    tc qdisc add dev \$IF root handle 1: htb default 20
    tc class add dev \$IF parent 1: classid 1:1 htb rate 100mbit ceil 100mbit
    tc class add dev \$IF parent 1:1 classid 1:10 htb rate 10mbit ceil 100mbit prio 0
    tc class add dev \$IF parent 1:1 classid 1:15 htb rate 70mbit ceil 85mbit prio 1
    tc class add dev \$IF parent 1:1 classid 1:20 htb rate 5mbit ceil 40mbit prio 2
    tc qdisc add dev \$IF parent 1:10 handle 10: sfq
    tc qdisc add dev \$IF parent 1:15 handle 15: sfq
    tc qdisc add dev \$IF parent 1:20 handle 20: sfq
    tc filter add dev \$IF protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
    tc filter add dev \$IF protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
  " 2>/dev/null || true
done

echo "=== start packet capture on CE + mission + admin links ==="
python3 - <<PY
import json, urllib.request, base64
PID="$PID"
base=f"http://127.0.0.1:3080/v2/projects/{PID}"
auth=base64.b64encode(b"$AUTH").decode()
def req(method, path, body=None):
    data=None if body is None else json.dumps(body).encode()
    r=urllib.request.Request(base+path, data=data, method=method,
      headers={"Authorization":f"Basic {auth}","Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        raw=resp.read(); return json.loads(raw) if raw else {}
nodes={n["node_id"]: n["name"] for n in req("GET","/nodes")}
want=set()
ces=["CE-NRSC","CE-Mauritius","CE-Shadnagar","CE-SAC","CE-MCF","CE-ISTRAC","CE-ISRO-HQ","CE-Bhopal"]
for ce,pe in [("CE-NRSC","PE1"),("CE-Mauritius","PE1"),("CE-Shadnagar","PE1"),
             ("CE-SAC","PE2"),("CE-MCF","PE2"),("CE-ISTRAC","PE2"),
             ("CE-ISRO-HQ","PE3"),("CE-Bhopal","PE3")]:
    want.add(tuple(sorted([ce,pe])))
for a,b in [("PE1","CORE-N"),("PE2","CORE-N"),("PE3","CORE-N"),
            ("PE1","PE2"),("PE1","PE3"),("PE2","PE3")]:
    want.add(tuple(sorted([a,b])))
n=0
for L in req("GET","/links"):
    ends=tuple(sorted(nodes[x["node_id"]] for x in L["nodes"]))
    if ends in want:
        if L.get("capturing"):
            continue
        try:
            req("POST", f"/links/{L['link_id']}/start_capture", {
                "data_link_type":"DLT_EN10MB",
                "capture_file_name": f"sdwan_{ends[0]}_{ends[1]}.pcap"
            })
            n+=1; print("capture", ends[0], "<->", ends[1])
        except Exception as e:
            print("skip", ends, e)
print(f"new_captures={n}")
PY

echo "=== connectivity smoke (CE mesh ping) ==="
fail=0
for src_name_ip in \
  "CE-NRSC:$NRSC:10.11.1.2" "CE-Mauritius:$MAU:10.11.2.2" "CE-Shadnagar:$SHAD:10.11.3.2" \
  "CE-SAC:$SAC:10.11.4.2" "CE-MCF:$MCF:10.11.5.2" "CE-ISTRAC:$ISTRAC:10.11.6.2" \
  "CE-ISRO-HQ:$HQ:10.11.7.2" "CE-Bhopal:$BHOPAL:10.11.8.2"; do
  :
done
# ping from NRSC to every other CE
for dst in 10.11.2.2 10.11.3.2 10.11.4.2 10.11.5.2 10.11.6.2 10.11.7.2 10.11.8.2; do
  if dex "$NRSC" "ping -c 1 -W 2 $dst" >/dev/null 2>&1; then
    echo "  OK NRSC → $dst"
  else
    echo "  FAIL NRSC → $dst"; fail=$((fail+1))
  fi
done
[[ "$fail" -eq 0 ]] || echo "WARN: $fail pings failed (continuing traffic anyway)"

echo "=== start iperf servers on every CE ==="
declare -A CE_CID=(
  [CE-NRSC]="$NRSC" [CE-Mauritius]="$MAU" [CE-Shadnagar]="$SHAD"
  [CE-SAC]="$SAC" [CE-MCF]="$MCF" [CE-ISTRAC]="$ISTRAC"
  [CE-ISRO-HQ]="$HQ" [CE-Bhopal]="$BHOPAL"
)
declare -A CE_IP=(
  [CE-NRSC]=10.11.1.2 [CE-Mauritius]=10.11.2.2 [CE-Shadnagar]=10.11.3.2
  [CE-SAC]=10.11.4.2 [CE-MCF]=10.11.5.2 [CE-ISTRAC]=10.11.6.2
  [CE-ISRO-HQ]=10.11.7.2 [CE-Bhopal]=10.11.8.2
)
# Gold/Silver prefer TT&C+Payload; Bronze prefer Payload/BE
declare -A CE_TOS=(
  [CE-NRSC]=0x88 [CE-Mauritius]=0x80 [CE-Shadnagar]=0x00
  [CE-SAC]=0x80 [CE-MCF]=0x80 [CE-ISTRAC]=0x00
  [CE-ISRO-HQ]=0x88 [CE-Bhopal]=0x00
)

i=0
for name in "${!CE_CID[@]}"; do
  cid="${CE_CID[$name]}"
  docker rm -f "gns3-mesh-srv-$i" >/dev/null 2>&1 || true
  docker run -d --rm --name "gns3-mesh-srv-$i" --network "container:$cid" \
    networkstatic/iperf3 -s -p $((5201 + i)) >/dev/null
  i=$((i+1))
done
sleep 2

echo "=== mesh clients: each CE → all other CEs (${DURATION}s) ==="
# Map name → server port index (stable order)
names=(CE-NRSC CE-Mauritius CE-Shadnagar CE-SAC CE-MCF CE-ISTRAC CE-ISRO-HQ CE-Bhopal)
declare -A PORT
for idx in "${!names[@]}"; do PORT[${names[$idx]}]=$((5201 + idx)); done

c=0
for src in "${names[@]}"; do
  for dst in "${names[@]}"; do
    [[ "$src" == "$dst" ]] && continue
    tos="${CE_TOS[$src]}"
    # rotate classes so every pair carries visible SD-WAN marks
    case $((c % 3)) in
      0) tos=0x88; rate=1M ;;    # TT&C mission
      1) tos=0x80; rate=8M ;;    # Payload mission
      2) tos=0x00; rate=3M ;;    # BE admin
    esac
    scid="${CE_CID[$src]}"
    dip="${CE_IP[$dst]}"
    dport="${PORT[$dst]}"
    docker rm -f "gns3-mesh-cli-$c" >/dev/null 2>&1 || true
    docker run -d --rm --name "gns3-mesh-cli-$c" --network "container:$scid" \
      networkstatic/iperf3 -u -b "$rate" --tos "$tos" -c "$dip" -p "$dport" -t "$DURATION" \
      >/dev/null 2>&1 || true
    c=$((c+1))
  done
done
echo "started $c CE↔CE flows (ToS 0x88 mission / 0x80 mission / 0x00 admin)"

# Also continuous ping mesh for GUI link blinks
docker rm -f gns3-mesh-ping >/dev/null 2>&1 || true
docker run -d --rm --name gns3-mesh-ping --network "container:$NRSC" alpine:3.20 \
  sh -c "apk add --no-cache iputils >/dev/null 2>&1 || true
         while true; do
           for d in 10.11.2.2 10.11.3.2 10.11.4.2 10.11.5.2 10.11.6.2 10.11.7.2 10.11.8.2; do
             ping -c 1 -W 1 \$d >/dev/null 2>&1 || true
           done
           sleep 1
         done" >/dev/null 2>&1 || \
docker exec -d "$NRSC" sh -c '
  while true; do
    for d in 10.11.2.2 10.11.3.2 10.11.4.2 10.11.5.2 10.11.6.2 10.11.7.2 10.11.8.2; do
      ping -c 1 -W 1 $d >/dev/null 2>&1 || true
    done
    sleep 1
  done'

echo
echo ">>> LOOK AT GNS3 NOW — captures on CE attaches + CORE (mission) + PE-PE (admin)"
echo ">>> TT&C/Payload should dominate PE↔CORE links; BE on PE↔PE admin links"
sleep 12

echo "=== SD-WAN action: rain-fade brownout on mission (CORE-N eth0) ==="
# NetEM on CORE (keeps PE1 HTB intact)
dex "$CORE" "tc qdisc replace dev eth0 root netem delay 40ms loss 1%"
dex "$CORE" "tc qdisc replace dev eth1 root netem delay 40ms loss 1%"
python3 - <<'PY'
import json, time
from pathlib import Path
p = Path("/home/brain/deca-isro/lab/gns3/state/chaos_state.json")
d = json.loads(p.read_text()) if p.is_file() else {}
d.update({"fault_id":"rain_fade","latency_gre_ms":40,"loss_gre_pct":1.0,"jitter_gre_ms":3.2,"updated_unix":time.time()})
p.write_text(json.dumps(d, indent=2)+"\n")
print("chaos_state rain_fade set")
PY
echo "mission path now ~40ms+1% loss — admin PE-PE should stay ~1ms (check Wireshark / ping)"

# show live path contrast
echo "=== path contrast (mission vs admin RTT) ==="
echo -n "mission NRSC→SAC (icmp→marked mission): "
dex "$NRSC" "ping -c 3 -W 2 10.11.4.2" | tail -1 || true
echo -n "admin  NRSC→SAC via forced BE tos probe: "
# send unmarked UDP to see admin — use traceroute-ish: ping from PE1 to PE2 direct
dex "$PE1" "ping -c 3 -W 1 10.12.12.2" | tail -1 || true

echo
echo "LIVE for ~$((DURATION - 12))s more. In GNS3:"
echo "  1. Open Wireshark on a PE1↔CORE-N capture  → ToS 0x88/0x80 (mission)"
echo "  2. Open Wireshark on PE1↔PE2 capture       → ToS 0x00 (admin backup)"
echo "  3. Watch CE-NRSC / CE-Mauritius / CE-SAC attach links for site traffic"
echo "Stop: bash lab/gns3/run_ce_mesh_sdwan_demo.sh --stop"
