#!/bin/bash
# DECA Network Master Diagnostic — run via: check stations
# Shows PE health + full multi-site inventory (CORE / SAC / NRSC / Mauritius / MCF).
set -uo pipefail

echo -e "\n=========================================="
echo "      DECA NETWORK MASTER DIAGNOSTIC      "
echo "=========================================="

PASSWORD="${DECA_SUDO_PW:-}"
# Lab Pis usually have NOPASSWD for brain; only prompt if needed.
need_pw=0
for H in station1 station2 station3; do
  if ! ssh -q -o BatchMode=yes -o ConnectTimeout=5 "$H" 'sudo -n true' 2>/dev/null; then
    need_pw=1
    break
  fi
done
if [ "$need_pw" -eq 1 ] && [ -z "$PASSWORD" ]; then
  echo -n "Enter the sudo password for the stations: "
  read -rs PASSWORD
  echo ""
elif [ "$need_pw" -eq 0 ]; then
  echo "(using passwordless sudo on stations)"
fi

# Run a remote command under sudo. $2 must be a single shell string (quoted by caller).
ssh_sudo() {
  local host="$1"
  local cmd="$2"
  local q
  q=$(printf '%q' "$cmd")
  if ssh -q -o ConnectTimeout=8 "$host" 'sudo -n true' 2>/dev/null; then
    ssh -q -o ConnectTimeout=8 "$host" "sudo -n bash -c $q" 2>/dev/null
  else
    # shellcheck disable=SC2029
    echo "$PASSWORD" | ssh -q -o ConnectTimeout=8 "$host" "sudo -S bash -c $q" 2>/dev/null
  fi
}

ping_ns() {
  local host="$1" ns="$2" dest="$3" label="$4" wait="${5:-2}"
  local out rtt loss
  out=$(ssh_sudo "$host" "ip netns exec $ns ping -c 2 -W $wait $dest") || true
  loss=$(echo "$out" | grep -oP '\d+(?=% packet loss)' | head -1)
  rtt=$(echo "$out" | awk -F'/' '/rtt|round-trip/{print $5}')
  if [ -n "${loss:-}" ] && [ "$loss" -lt 100 ]; then
    printf "  %-36s OK  avg_rtt=%sms  loss=%s%%\n" "$label" "${rtt:-?}" "$loss"
  else
    printf "  %-36s FAIL\n" "$label"
  fi
}

echo -e "\n[1/10] Layer 3 reachability (lab LAN)"
for H in 10 20 30; do
  ping -c 1 -W 1 "192.168.50.$H" &>/dev/null \
    && echo "  station$((H/10)) (192.168.50.$H): UP" \
    || echo "  station$((H/10)) (192.168.50.$H): DOWN"
done

echo -e "\n[2/10] Site map (roles / attachments / site LANs)"
cat <<'EOF'
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ Site              Role              Host / CE        Attach / CE-lo      │
  │                   Site LAN /29                       Hosts               │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ CORE              Hub / P-backbone  station3         eth0 .30            │
  │                                     lo 10.1.3.1                          │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ SAC, Ahmedabad    Datacenter        station2 / ce-b  10.10.2.0/30        │
  │                                     CE-lo 10.100.2.1                     │
  │                   10.101.2.0/29                      sac-ws .2  sac-srv .3│
  ├──────────────────────────────────────────────────────────────────────────┤
  │ NRSC, Hyderabad   Branch            station1 / ce-a  10.10.1.0/30        │
  │                                     CE-lo 10.100.1.1                     │
  │                   10.101.1.0/29                      nrsc-ws .2 nrsc-srv .3│
  ├──────────────────────────────────────────────────────────────────────────┤
  │ Mauritius         Distant branch    station1 /       10.10.3.0/30        │
  │                                     ce-mauritius     CE-lo 10.100.3.1    │
  │                   10.101.3.0/29                      mau-ws .2  mau-srv .3│
  │                   (netem ~200ms RTT to SAC)                              │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ MCF, Hassan       Regional branch   station2 / ce-mcf 10.10.4.0/30       │
  │                                     CE-lo 10.100.4.1                     │
  │                   10.101.4.0/29                      mcf-ws .2  mcf-srv .3│
  └──────────────────────────────────────────────────────────────────────────┘
EOF

echo -e "\n[3/10] Live namespaces + addressing"
echo "  --- station1 (PE1: NRSC + Mauritius) ---"
ssh_sudo station1 'ip netns list' | sed 's/^/  /'
for ns in ce-a ce-mauritius nrsc-ws nrsc-srv mau-ws mau-srv; do
  addr=$(ssh_sudo station1 "ip netns exec $ns ip -br addr" 2>/dev/null \
    | awk '!/lo|DOWN|UNKNOWN.*127/ && /UP|UNKNOWN/ {print $1,$3}' | head -2 | tr '\n' '; ')
  printf "    %-14s %s\n" "$ns" "${addr:-MISSING}"
done
echo "  --- station2 (PE2: SAC + MCF) ---"
ssh_sudo station2 'ip netns list' | sed 's/^/  /'
for ns in ce-b ce-mcf sac-ws sac-srv mcf-ws mcf-srv; do
  addr=$(ssh_sudo station2 "ip netns exec $ns ip -br addr" 2>/dev/null \
    | awk '!/lo|DOWN|UNKNOWN.*127/ && /UP|UNKNOWN/ {print $1,$3}' | head -2 | tr '\n' '; ')
  printf "    %-14s %s\n" "$ns" "${addr:-MISSING}"
done
echo "  --- station3 (CORE) ---"
ssh -q station3 'hostname; ip -br addr show eth0 | head -1; ip tunnel show 2>/dev/null | grep gre-te || echo "no gre-te"' | sed 's/^/  /'

echo -e "\n[4/10] NTP sync"
for H in station1 station2 station3; do
  echo -n "  $H: "
  ssh -q "$H" 'chronyc tracking 2>/dev/null | grep "System time"' \
    | awk '{print $4, $5, $6, $7}' || echo "no data"
done

echo -e "\n[5/10] OSPF / BGP / MPLS (PE1)"
ospf_lines=$(ssh_sudo station1 'vtysh -c "show ip ospf neighbor"' | grep "Full" || true)
if [ -n "$ospf_lines" ]; then
  echo "$ospf_lines" | awk '{print "  OSPF neighbor " $1 " is " $3}'
else
  echo "  OSPF: no Full adjacencies"
fi
# FRR 10: VPNv4 is "ipv4 vpn". Unicast NoNeg toward CORE is intentional.
vpn=$(ssh_sudo station1 'vtysh -c "show bgp ipv4 vpn summary"' | grep "10.1.3.1" || true)
if [ -n "$vpn" ]; then
  echo "  BGP ipv4 vpn peer: $vpn"
  pfx=$(echo "$vpn" | awk '{print $10}')
  if [ "${pfx:-0}" -gt 0 ] 2>/dev/null; then
    echo "  VPNv4 prefixes received from RR: $pfx (native L3VPN)"
  else
    echo "  VPNv4 PfxRcd=0 — check RD/RT 65001:100 and LDP on gre-te-*"
  fi
else
  echo "  BGP ipv4 vpn: peer 10.1.3.1 missing"
fi
bcount=$(ssh_sudo station1 'vtysh -c "show ip route vrf vrf-mission"' | grep -cE '^B' || true)
echo "  VRF vrf-mission BGP routes: ${bcount:-0}"
if ssh_sudo station1 'vtysh -c "show mpls table"' | grep -qE 'LDP|BGP'; then
  echo "  MPLS labels: ACTIVE"
else
  echo "  MPLS labels: check (BGP VPN may still use service labels)"
fi

echo -e "\n[6/10] IPsec SD-WAN overlay + preferred underlay"
# Prefer swanctl (copy_dscp path); fall back to stroke ipsec status
sas=$(ssh_sudo station1 'swanctl --list-sas 2>/dev/null' || true)
if echo "$sas" | grep -q ESTABLISHED; then
  echo "$sas" | grep ESTABLISHED | sed 's/^/  IPsec /'
elif ssh_sudo station1 'ipsec status' | grep -q ESTABLISHED; then
  ssh_sudo station1 'ipsec status' | grep ESTABLISHED | sed 's/^/  IPsec /'
else
  echo "  IPsec: no ESTABLISHED SA (site pings may still work via BGP+MPLS)"
fi
echo -n "  PE2 underlay (192.168.50.20): "
ssh -q station1 'ip route get 192.168.50.20 2>/dev/null' | head -1 | sed 's/^/ /'
if curl -sf --max-time 2 http://192.168.50.10:9273/metrics 2>/dev/null \
  | grep -q 'sdwan_active_path_value{class="voice",host="station1",path="gre"} 1'; then
  echo "  SD-WAN controller voice path: gre-te-core"
elif curl -sf --max-time 2 http://192.168.50.10:9273/metrics 2>/dev/null \
  | grep -q 'sdwan_active_path_value{class="voice",host="station1",path="eth0"} 1'; then
  echo "  SD-WAN controller voice path: eth0"
else
  echo "  SD-WAN controller metrics: not present (daemon down or not scraped)"
fi

echo -e "\n[7/10] Site reachability (CE-lo + site-LAN hosts)"
ping_ns station1 ce-a         10.100.2.1 "NRSC CE-lo → SAC CE-lo"
ping_ns station1 nrsc-ws      10.101.2.2 "NRSC-ws → SAC-ws"
ping_ns station1 nrsc-ws      10.101.2.3 "NRSC-ws → SAC-srv"
ping_ns station2 mcf-ws       10.101.1.2 "MCF-ws → NRSC-ws"
ping_ns station2 mcf-ws       10.100.1.1 "MCF-ws → NRSC CE-lo"
ping_ns station1 ce-mauritius 10.100.2.1 "Mauritius CE-lo → SAC CE-lo" 3
ping_ns station1 mau-ws       10.101.2.2 "Mauritius-ws → SAC-ws" 3

echo -e "\n[8/10] Mauritius BGP + MCF presence"
mau=$(ssh_sudo station1 'vtysh -c "show bgp vrf vrf-mission summary"' | grep "10.10.3.1" || true)
if [ -n "$mau" ]; then
  echo "  Mauritius BGP: $mau"
else
  echo "  Mauritius BGP peer 10.10.3.1: MISSING"
fi
ssh_sudo station2 'ip netns list' | grep -q ce-mcf \
  && echo "  ce-mcf: PRESENT" || echo "  ce-mcf: MISSING"
ssh_sudo station1 'ip netns list' | grep -q ce-mauritius \
  && echo "  ce-mauritius: PRESENT" || echo "  ce-mauritius: MISSING"

echo -e "\n[9/10] Expansion / QoS quick checks"
for H in station1 station2 station3; do
  gre=$(ssh -q "$H" 'ip tunnel show 2>/dev/null | grep -c gre-te || true')
  echo "  $H gre-te tunnels: ${gre:-0}"
done
ssh -q station1 'tc qdisc show dev eth0 2>/dev/null | head -2' | sed 's/^/  PE1 eth0: /'
ssh -q station2 'tc qdisc show dev eth0 2>/dev/null | head -2' | sed 's/^/  PE2 eth0: /'

echo -e "\n[10/10] Telemetry / Prometheus"
up=0
for ip in 192.168.50.10 192.168.50.20 192.168.50.30; do
  if curl -sf --max-time 3 "http://$ip:9273/metrics" >/dev/null; then
    echo "  Telegraf $ip:9273 UP"; up=$((up+1))
  else
    echo "  Telegraf $ip:9273 DOWN"
  fi
done
if curl -sf --max-time 3 http://localhost:9090/-/ready >/dev/null; then
  scraped=$(curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"up"' | wc -l)
  err=$(curl -s http://localhost:9090/api/v1/targets | grep -o 'out of bounds' | head -1 || true)
  echo "  Prometheus ready; scrape targets healthy: $scraped (Telegraf endpoints up: $up/3)"
  if [ -n "$err" ] || [ "${scraped:-0}" -eq 0 ]; then
    echo "  WARN: scrape 'out of bounds' — wipe TSDB: sudo bash scripts/deca_fix_prom_vpn.sh"
  fi
else
  echo "  Prometheus: not ready on :9090"
fi

echo -e "\n=========================================="
echo "           DIAGNOSTIC COMPLETE            "
echo "==========================================\n"
