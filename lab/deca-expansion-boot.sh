#!/usr/bin/env bash
# deca-expansion-boot.sh — runs ON a Pi at boot (and from watchdog/heal).
# Restores network-expansion state that does not survive reboot by itself:
#   VRF UP, GRE TE tunnels, HTB QoS classes, Mauritius CE/BGP, policy rules.
# Idempotent; always exits 0 so systemd WantedBy does not fail the boot chain.
# Does not touch models/fault_classifier/.
set +e

HOST="$(hostname -s 2>/dev/null || hostname | cut -d. -f1)"
log() { echo "[deca-expansion-boot $HOST] $*"; }

vrf_up() {
  ip link set vrf-mission up 2>/dev/null
  ip link set vrf-admin up 2>/dev/null
}

ensure_gre() {
  local name="$1" remote="$2" local_ip="$3" addr="$4"
  if ! ip link show "$name" &>/dev/null; then
    ip tunnel del "$name" 2>/dev/null
    ip tunnel add "$name" mode gre remote "$remote" local "$local_ip" ttl 64
    ip addr add "$addr" dev "$name" 2>/dev/null
    ip link set "$name" up
    sysctl -w "net.ipv4.conf.${name}.forwarding=1" >/dev/null 2>&1
    log "created GRE $name ($addr → $remote)"
  else
    ip link set "$name" up 2>/dev/null
    ip addr show dev "$name" 2>/dev/null | grep -q "${addr%/*}" \
      || ip addr add "$addr" dev "$name" 2>/dev/null
  fi
}

ensure_htb() {
  # PS13 aerospace QoS: TT&C 0x88 → 1:10 LLQ; Payload 0x80 → 1:15 (~70% + RED);
  # Admin/BE → 1:20. Prefer lab/deca_htb_qos.sh when present on the Pi.
  local IF=eth0
  if [[ -x /usr/local/bin/deca_htb_qos.sh ]]; then
    FORCE=0 IF="$IF" /usr/local/bin/deca_htb_qos.sh && return 0
  fi
  if [[ -x /opt/deca/deca_htb_qos.sh ]]; then
    FORCE=0 IF="$IF" /opt/deca/deca_htb_qos.sh && return 0
  fi
  # Inline fallback (same marks as lab/deca_htb_qos.sh)
  if tc qdisc show dev "$IF" 2>/dev/null | grep -q 'qdisc htb 1:'; then
    if tc filter show dev "$IF" 2>/dev/null | grep -q 'tos 80'; then
      return 0
    fi
  fi
  tc qdisc del dev "$IF" root 2>/dev/null
  tc qdisc add dev "$IF" root handle 1: htb default 20
  tc class add dev "$IF" parent 1: classid 1:1 htb rate 40mbit ceil 40mbit
  tc class add dev "$IF" parent 1:1 classid 1:10 htb rate 2mbit ceil 40mbit prio 1
  tc class add dev "$IF" parent 1:1 classid 1:15 htb rate 28mbit ceil 34mbit prio 2
  tc class add dev "$IF" parent 1:1 classid 1:20 htb rate 5mbit ceil 24mbit prio 5
  tc qdisc add dev "$IF" parent 1:10 handle 10: sfq perturb 10
  tc qdisc add dev "$IF" parent 1:15 handle 15: red \
    limit 500000 min 350000 max 425000 avpkt 1000 burst 40 probability 0.2 ecn 2>/dev/null \
    || tc qdisc add dev "$IF" parent 1:15 handle 15: sfq perturb 10
  tc qdisc add dev "$IF" parent 1:20 handle 20: sfq perturb 10
  tc filter add dev "$IF" protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10 2>/dev/null
  tc filter add dev "$IF" protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15 2>/dev/null
  tc filter add dev "$IF" protocol ip parent 1:0 prio 3 u32 match ip tos 0xb8 0xfc flowid 1:10 2>/dev/null
  tc filter add dev "$IF" protocol ip parent 1:0 prio 4 u32 match ip dport 5004 0xffff flowid 1:10 2>/dev/null
  tc filter add dev "$IF" protocol ip parent 1:0 prio 5 u32 match ip dport 5006 0xffff flowid 1:15 2>/dev/null
  log "HTB PS13 QoS on $IF (TT&C 0x88 / Payload 0x80 / BE)"
}

ensure_rule() {
  # $1 = destination prefix e.g. 10.100.3.1/32 — match with or without mask
  local to="$1" prio="$2"
  local bare="${to%/*}"
  if ip rule 2>/dev/null | grep -E "to ${bare}(/32)?[[:space:]]" >/dev/null; then
    return 0
  fi
  ip rule add to "$to" lookup 100 priority "$prio" 2>/dev/null \
    || ip rule add to "$bare" lookup 100 priority "$prio" 2>/dev/null \
    || true
}

# Re-assert OSPF-TE / pathd SR-TE constructs if FRR came up without them
# (config normally persists in /etc/frr/frr.conf; this is a heal safety-net).
ensure_te() {
  command -v vtysh >/dev/null 2>&1 || return 0
  case "$HOST" in
    station1)
      vtysh -c "configure terminal" \
        -c "router ospf" -c "mpls-te on" -c "mpls-te router-address 10.1.1.1" \
        -c "mpls-te export" -c "segment-routing on" \
        -c "segment-routing global-block 16000 23999" \
        -c "segment-routing prefix 10.1.1.1/32 index 1 no-php-flag" -c "exit" \
        -c "segment-routing" -c "traffic-eng" \
        -c "mpls-te on" -c "mpls-te import ospfv2" -c "exit" -c "exit" \
        -c "end" >/dev/null 2>&1 || true
      if ! vtysh -c "show sr-te policy" 2>/dev/null | grep -q "10.1.2.1"; then
        vtysh -c "configure terminal" -c "segment-routing" -c "traffic-eng" \
          -c "segment-list SL-GRE" -c "index 10 mpls label 16003" \
          -c "index 20 mpls label 16002" -c "exit" \
          -c "segment-list SL-ETH" -c "index 10 mpls label 15010" -c "exit" \
          -c "policy color 1 endpoint 10.1.2.1" -c "name pe1-to-pe2-te" \
          -c "binding-sid 40001" \
          -c "candidate-path preference 100 name via-gre explicit segment-list SL-GRE" \
          -c "candidate-path preference 50 name via-eth explicit segment-list SL-ETH" \
          -c "exit" -c "exit" -c "exit" -c "end" >/dev/null 2>&1 || true
        log "SR-TE pe1-to-pe2-te reapplied"
      fi
      ;;
    station2)
      vtysh -c "configure terminal" \
        -c "router ospf" -c "mpls-te on" -c "mpls-te router-address 10.1.2.1" \
        -c "mpls-te export" -c "segment-routing on" \
        -c "segment-routing global-block 16000 23999" \
        -c "segment-routing prefix 10.1.2.1/32 index 2 no-php-flag" -c "exit" \
        -c "segment-routing" -c "traffic-eng" \
        -c "mpls-te on" -c "mpls-te import ospfv2" -c "exit" -c "exit" \
        -c "end" >/dev/null 2>&1 || true
      if ! vtysh -c "show sr-te policy" 2>/dev/null | grep -q "10.1.1.1"; then
        vtysh -c "configure terminal" -c "segment-routing" -c "traffic-eng" \
          -c "segment-list SL-GRE" -c "index 10 mpls label 16003" \
          -c "index 20 mpls label 16001" -c "exit" \
          -c "segment-list SL-ETH" -c "index 10 mpls label 15010" -c "exit" \
          -c "policy color 1 endpoint 10.1.1.1" -c "name pe2-to-pe1-te" \
          -c "binding-sid 40002" \
          -c "candidate-path preference 100 name via-gre explicit segment-list SL-GRE" \
          -c "candidate-path preference 50 name via-eth explicit segment-list SL-ETH" \
          -c "exit" -c "exit" -c "exit" -c "end" >/dev/null 2>&1 || true
        log "SR-TE pe2-to-pe1-te reapplied"
      fi
      ;;
    station3)
      vtysh -c "configure terminal" \
        -c "router ospf" -c "mpls-te on" -c "mpls-te router-address 10.1.3.1" \
        -c "mpls-te export" -c "segment-routing on" \
        -c "segment-routing global-block 16000 23999" \
        -c "segment-routing prefix 10.1.3.1/32 index 3 no-php-flag" -c "exit" \
        -c "segment-routing" -c "traffic-eng" \
        -c "mpls-te on" -c "mpls-te import ospfv2" -c "exit" -c "exit" \
        -c "end" >/dev/null 2>&1 || true
      ;;
  esac
}

# MPLS must be enabled on the GRE TE path — OSPF prefers gre-te-*; without
# LDP/MPLS on GRE, BGP VPNv4 imports stay invalid and VRF RIB has no B routes.
ensure_mpls_gre() {
  local ifc
  for ifc in gre-te-core gre-te-pe1 gre-te-pe2; do
    [ -d "/sys/class/net/$ifc" ] || continue
    sysctl -w "net.mpls.conf.${ifc}.input=1" >/dev/null 2>&1 || true
  done
  if command -v vtysh >/dev/null 2>&1; then
    case "$HOST" in
      station1|station2)
        vtysh -c "configure terminal" \
          -c "interface gre-te-core" -c "mpls enable" -c "exit" \
          -c "mpls ldp" -c "address-family ipv4" \
          -c "interface gre-te-core" -c "exit" -c "exit-address-family" -c "exit" \
          -c "end" >/dev/null 2>&1 || true
        ;;
      station3)
        vtysh -c "configure terminal" \
          -c "interface gre-te-pe1" -c "mpls enable" -c "exit" \
          -c "interface gre-te-pe2" -c "mpls enable" -c "exit" \
          -c "mpls ldp" -c "address-family ipv4" \
          -c "interface gre-te-pe1" -c "exit" \
          -c "interface gre-te-pe2" -c "exit" -c "exit-address-family" -c "exit" \
          -c "end" >/dev/null 2>&1 || true
        ;;
    esac
  fi
}

# Site-LAN helper (Phase G): br-lan + ws/srv host netns inside each CE
ensure_site_lan() {
  # $1=ce-ns $2=tag $3=lan/cidr $4=gw $5=ws $6=srv
  if [ -x /usr/local/bin/deca-site-lan.sh ]; then
    /usr/local/bin/deca-site-lan.sh "$1" "$2" "$3" "$4" "$5" "$6" >/dev/null 2>&1 \
      && log "site-lan $2 ok" || log "site-lan $2 skipped/failed"
  fi
}

case "$HOST" in
  station1)
    vrf_up
    ensure_gre gre-te-core 192.168.50.30 192.168.50.10 10.50.1.1/30
    ensure_mpls_gre
    ensure_te
    ensure_htb
    ensure_rule 10.100.1.1/32 980
    ensure_rule 10.100.3.1/32 994
    ensure_rule 10.10.1.0/30 980
    ensure_rule 10.10.3.0/30 980
    ensure_rule 10.101.1.0/29 980
    ensure_rule 10.101.2.0/29 980
    ensure_rule 10.101.3.0/29 980
    ensure_rule 10.101.4.0/29 980
    ensure_rule 10.100.4.1/32 980
    ensure_rule 10.10.4.0/30 980
    systemctl start deca-ns-mauritius.service 2>/dev/null
    systemctl start deca-mauritius-bgp.service 2>/dev/null
    ip route replace 10.100.3.1/32 via 10.10.3.1 dev veth-pe-cem table 100 2>/dev/null
    ensure_site_lan ce-a nrsc 10.101.1.0/29 10.101.1.1 10.101.1.2 10.101.1.3
    ensure_site_lan ce-mauritius mau 10.101.3.0/29 10.101.3.1 10.101.3.2 10.101.3.3
    systemctl start deca-swanctl-up.service 2>/dev/null || /usr/local/bin/deca-swanctl-up.sh 2>/dev/null || true
    ;;
  station2)
    vrf_up
    ensure_gre gre-te-core 192.168.50.30 192.168.50.20 10.50.2.1/30
    ensure_mpls_gre
    ensure_te
    ensure_htb
    ensure_rule 10.100.3.1/32 994
    ensure_rule 10.100.1.1/32 999
    ensure_rule 10.100.2.1/32 980
    ensure_rule 10.10.2.0/30 980
    ensure_rule 10.101.1.0/29 980
    ensure_rule 10.101.2.0/29 980
    ensure_rule 10.101.3.0/29 980
    ensure_rule 10.101.4.0/29 980
    ensure_rule 10.100.4.1/32 980
    ensure_rule 10.10.4.0/30 980
    systemctl start deca-ns-mcf.service 2>/dev/null
    ensure_site_lan ce-b sac 10.101.2.0/29 10.101.2.1 10.101.2.2 10.101.2.3
    ensure_site_lan ce-mcf mcf 10.101.4.0/29 10.101.4.1 10.101.4.2 10.101.4.3
    systemctl start deca-swanctl-up.service 2>/dev/null || /usr/local/bin/deca-swanctl-up.sh 2>/dev/null || true
    ;;
  station3)
    sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1
    ensure_gre gre-te-pe1 192.168.50.10 192.168.50.30 10.50.1.2/30
    ensure_gre gre-te-pe2 192.168.50.20 192.168.50.30 10.50.2.2/30
    ensure_mpls_gre
    ensure_te
    ;;
  *)
    log "unknown host — no expansion actions"
    exit 0
    ;;
esac

systemctl is-active --quiet telegraf || systemctl restart telegraf

# Station-ready latch for brain campaign pause/resume (power-outage recovery).
# Brain polls ping + :9273; this file proves expansion-boot + telegraf finished.
mkdir -p /run/deca
date -u +%Y-%m-%dT%H:%M:%SZ > /run/deca/station-ready
# Optional Prom textfile (if telegraf file plugin watches /run/deca)
cat > /run/deca/station_ready.prom <<EOF
# HELP deca_station_ready 1 after expansion-boot + telegraf on this Pi
# TYPE deca_station_ready gauge
deca_station_ready{host="$HOST"} 1
EOF

log "done (station-ready)"
exit 0
