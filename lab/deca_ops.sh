#!/bin/bash
# deca_ops.sh — unified DECA lab operations: check | heal | install-boot | all
# Replaces: check_stations.sh, check_step7.sh, deca_diagnostic.sh, deca-heal-telemetry.sh, apply_boot_fix.sh
set -uo pipefail

STATIONS=(station1 station2 station3)
RESULTS=()   # collected "LABEL: PASS/FAIL/WARN" lines for the final summary

log()  { echo -e "$1"; }
pass() { RESULTS+=("PASS  $1"); log "  [PASS] $1"; }
fail() { RESULTS+=("FAIL  $1"); log "  [FAIL] $1"; }
warn() { RESULTS+=("WARN  $1"); log "  [WARN] $1"; }

need_password() {
  if [ -z "${DECA_SUDO_PW:-}" ]; then
    echo -n "Enter the sudo password for the stations: "
    read -rs DECA_SUDO_PW
    echo ""
  fi
}

ssh_sudo() {  # ssh_sudo <host> <remote command string>
  local host="$1" cmd="$2"
  echo "$DECA_SUDO_PW" | ssh -q -o ConnectTimeout=5 "$host" "sudo -S bash -c '$cmd'" 2>/dev/null
}

# ---------------------------------------------------------------------------
# CHECK — merges deca_diagnostic.sh + check_stations.sh + check_step7.sh
# ---------------------------------------------------------------------------
run_check() {
  need_password
  log "\n=========================================="
  log "          DECA LAB — HEALTH CHECK"
  log "=========================================="

  log "\n[1] Layer 3 reachability"
  for i in "${!STATIONS[@]}"; do
    ip="192.168.50.$(( (i+1)*10 ))"
    ping -c1 -W1 "$ip" &>/dev/null && pass "${STATIONS[$i]} ($ip) reachable" || fail "${STATIONS[$i]} ($ip) unreachable"
  done

  log "\n[2] NTP sync"
  for h in "${STATIONS[@]}"; do
    out=$(ssh -q -o ConnectTimeout=5 "$h" 'chronyc tracking 2>/dev/null | grep "System time"')
    [ -n "$out" ] && pass "$h NTP: $out" || warn "$h NTP: no data"
  done

  log "\n[3] Service enablement + namespace guard"
  for h in station1 station2; do
    if [ "$h" = station1 ]; then
      svc=$(ssh_sudo "$h" 'systemctl is-enabled frr strongswan-starter chrony telegraf deca-ns.service deca-ns-mauritius.service deca-mauritius-bgp.service deca-vrf-up.service deca-expansion-boot.service deca-watchdog.service 2>/dev/null' | tr '\n' ' ')
      ns=$(ssh -q "$h" 'sudo ip netns list 2>/dev/null' | wc -l)
      [[ "$svc" == *enabled* ]] && pass "$h services: $svc" || warn "$h services: $svc"
      # PE1: ce-a, ce-mauritius, nrsc-ws/srv, mau-ws/srv (≥6)
      [ "$ns" -ge 6 ] && pass "$h namespaces OK ($ns; NRSC+Mauritius+site hosts)" \
        || warn "$h namespaces: $ns (expect ≥6: ce-a, ce-mauritius, nrsc-*, mau-*)"
    else
      svc=$(ssh_sudo "$h" 'systemctl is-enabled frr strongswan-starter chrony telegraf deca-ns.service deca-vrf-up.service deca-expansion-boot.service deca-watchdog.service 2>/dev/null' | tr '\n' ' ')
      ns=$(ssh -q "$h" 'sudo ip netns list 2>/dev/null' | wc -l)
      [[ "$svc" == *enabled* ]] && pass "$h services: $svc" || warn "$h services: $svc"
      # PE2: ce-b, ce-mcf, sac-ws/srv, mcf-ws/srv (≥6)
      [ "$ns" -ge 6 ] && pass "$h namespaces OK ($ns; SAC+MCF+site hosts)" \
        || warn "$h namespaces: $ns (expect ≥6: ce-b, ce-mcf, sac-*, mcf-*)"
    fi
  done
  svc3=$(ssh_sudo station3 'systemctl is-enabled frr chrony telegraf deca-expansion-boot.service deca-watchdog.service 2>/dev/null' | tr '\n' ' ')
  [[ "$svc3" == *enabled* ]] && pass "station3 services: $svc3" || warn "station3 services: $svc3"

  log "\n[3a] Site inventory"
  log "  CORE Hub          station3                 lo 10.1.3.1"
  log "  SAC Datacenter    station2/ce-b            10.10.2.0/30  LAN 10.101.2.0/29  CE-lo 10.100.2.1"
  log "  NRSC Branch       station1/ce-a            10.10.1.0/30  LAN 10.101.1.0/29  CE-lo 10.100.1.1"
  log "  Mauritius Distant station1/ce-mauritius    10.10.3.0/30  LAN 10.101.3.0/29  CE-lo 10.100.3.1 (~200ms)"
  log "  MCF Regional      station2/ce-mcf          10.10.4.0/30  LAN 10.101.4.0/29  CE-lo 10.100.4.1"
  for pair in \
    "station1:nrsc-ws:10.101.1.2" "station1:nrsc-srv:10.101.1.3" \
    "station1:mau-ws:10.101.3.2" "station2:sac-ws:10.101.2.2" \
    "station2:sac-srv:10.101.2.3" "station2:mcf-ws:10.101.4.2"; do
    IFS=: read -r h ns ip <<<"$pair"
    got=$(ssh_sudo "$h" "ip netns exec $ns ip -br addr" 2>/dev/null | grep -o "$ip" || true)
    [ -n "$got" ] && pass "$h $ns has $ip" || fail "$h $ns missing $ip"
  done

  log "\n[3b] Expansion boot artifacts (VRF / GRE / HTB)"
  vrf1=$(ssh_sudo station1 'ip -br link show type vrf | grep -c UP || true')
  gre1=$(ssh -q station1 'ip tunnel show 2>/dev/null | grep -c gre-te || true')
  gre3=$(ssh -q station3 'ip tunnel show 2>/dev/null | grep -c gre-te || true')
  htb1=$(ssh_sudo station1 'tc qdisc show dev eth0 | grep -c "htb 1:" || true')
  [ "${vrf1:-0}" -ge 1 ] && pass "station1 VRF UP ($vrf1)" || fail "station1 VRF not UP"
  [ "${gre1:-0}" -ge 1 ] && pass "station1 GRE TE present" || fail "station1 GRE TE missing (run install-boot)"
  [ "${gre3:-0}" -ge 2 ] && pass "station3 GRE TE present ($gre3)" || warn "station3 GRE TE count=$gre3 (expect 2)"
  [ "${htb1:-0}" -ge 1 ] && pass "station1 HTB QoS on eth0" || warn "station1 HTB missing (expansion-boot will restore)"

  log "\n[4] OSPF / MPLS / BGP VPNv4 (station1)"
  ospf=$(ssh_sudo station1 'vtysh -c "show ip ospf neighbor"' | grep -c Full)
  [ "$ospf" -ge 1 ] && pass "OSPF: $ospf full adjacency" || fail "OSPF: no full adjacency"

  mpls=$(ssh_sudo station1 'vtysh -c "show mpls table"' | grep -cE 'BGP|LDP')
  [ "$mpls" -ge 1 ] && pass "MPLS labels populated ($mpls)" || fail "MPLS labels missing"

  vpn=$(ssh_sudo station1 'vtysh -c "show bgp ipv4 vpn summary"' | grep "10.1.3.1" || true)
  # Established line: PfxRcd is column 10
  pfx=$(echo "$vpn" | awk '{print $10}')
  if [ -n "$vpn" ] && [ "${pfx:-0}" -gt 0 ] 2>/dev/null; then
    pass "BGP ipv4 vpn peer OK (PfxRcd=$pfx): $vpn"
  else
    fail "BGP ipv4 vpn: expected PfxRcd>0 (got: ${vpn:-missing})"
  fi
  b_routes=$(ssh_sudo station1 'vtysh -c "show ip route vrf vrf-mission"' | grep -cE '^B' || true)
  [ "${b_routes:-0}" -ge 4 ] && pass "VRF mission has $b_routes BGP routes" \
    || warn "VRF mission BGP routes=$b_routes (expect ≥4 remote prefixes)"

  log "\n[5] IPsec overlay (station1)"
  ipsec_state=$(ssh_sudo station1 'ipsec status' | grep -c ESTABLISHED)
  [ "$ipsec_state" -ge 1 ] && pass "IPsec: $ipsec_state ESTABLISHED" || fail "IPsec: no ESTABLISHED SA"

  log "\n[6] CE-A -> CE-B data plane (deep check)"
  nsA=$(ssh -q station1 'ip netns list 2>/dev/null' | grep -c ce-a)
  nsB=$(ssh -q station2 'ip netns list 2>/dev/null' | grep -c ce-b)
  [ "$nsA" -ge 1 ] && pass "ce-a namespace present" || fail "ce-a namespace missing"
  [ "$nsB" -ge 1 ] && pass "ce-b namespace present" || fail "ce-b namespace missing"

  route=$(ssh_sudo station1 'ip route show vrf vrf-mission | grep "10.10.1.0"')
  [ -n "$route" ] && pass "VRF route to 10.10.1.0 present" || fail "VRF route to 10.10.1.0 MISSING"

  ping_out=$(ssh_sudo station1 'ip netns exec ce-a ping -c 3 -W 2 10.100.2.1')
  loss=$(echo "$ping_out" | grep -oP '\d+(?=% packet loss)')
  if [ -n "$loss" ] && [ "$loss" -lt 100 ]; then
    pass "VPN dataplane ce-a -> 10.100.2.1 (${loss}% loss)"
  else
    fail "VPN dataplane ce-a -> 10.100.2.1 unreachable"
  fi

  log "\n[6b] Site-LAN + Mauritius + MCF reachability"
  nsM=$(ssh -q station1 'ip netns list 2>/dev/null' | grep -c ce-mauritius)
  if [ "$nsM" -ge 1 ]; then
    pass "ce-mauritius namespace present"
    mau=$(ssh_sudo station1 'ip netns exec ce-mauritius ping -c 3 -W 3 10.100.2.1')
    mau_rtt=$(echo "$mau" | awk -F'/' '/rtt|round-trip/{print $5}')
    mau_loss=$(echo "$mau" | grep -oP '\d+(?=% packet loss)')
    if [ -n "$mau_loss" ] && [ "$mau_loss" -lt 100 ]; then
      pass "Mauritius -> SAC reachable (avg_rtt_ms=${mau_rtt:-?}; expect ~150-250)"
    else
      fail "Mauritius -> SAC unreachable"
    fi
    bgp_m=$(ssh_sudo station1 'vtysh -c "show bgp vrf vrf-mission summary"' | grep "10.10.3.1" || true)
    [ -n "$bgp_m" ] && pass "Mauritius BGP peer: $bgp_m" || fail "Mauritius BGP peer 10.10.3.1 missing"
  else
    fail "ce-mauritius namespace missing (run lab/deca_expand_phase_a.sh)"
  fi
  ns_mcf=$(ssh -q station2 'ip netns list 2>/dev/null' | grep -c ce-mcf)
  [ "$ns_mcf" -ge 1 ] && pass "ce-mcf namespace present" || fail "ce-mcf missing (run lab/deca_expand_phase_g.sh)"
  for probe in \
    "station1:nrsc-ws:10.101.2.2:NRSC-ws→SAC-ws" \
    "station2:mcf-ws:10.101.1.2:MCF-ws→NRSC-ws" \
    "station1:mau-ws:10.101.2.2:Mauritius-ws→SAC-ws"; do
    IFS=: read -r h ns dest label <<<"$probe"
    wait=2; [[ "$label" == Mauritius* ]] && wait=3
    out=$(ssh_sudo "$h" "ip netns exec $ns ping -c 2 -W $wait $dest")
    loss=$(echo "$out" | grep -oP '\d+(?=% packet loss)')
    rtt=$(echo "$out" | awk -F'/' '/rtt|round-trip/{print $5}')
    if [ -n "${loss:-}" ] && [ "$loss" -lt 100 ]; then
      pass "$label (rtt=${rtt:-?}ms loss=${loss}%)"
    else
      fail "$label unreachable"
    fi
  done

  log "\n[7] Telemetry pipeline"
  up=0
  for i in "${!STATIONS[@]}"; do
    ip="192.168.50.$(( (i+1)*10 ))"
    if curl -sf --max-time 3 "http://$ip:9273/metrics" >/dev/null; then
      pass "Telegraf $ip:9273 up"; up=$((up+1))
    else
      fail "Telegraf $ip:9273 down"
    fi
  done

  exp=$(ssh -q station1 'curl -sf --max-time 3 localhost:9273/metrics' | grep -cE '^(ospf_adj_up_value|path_asymmetry_ratio_value|bgp_mauritius_adj_up_value|ipsec_sa_age_s_value)' || true)
  [ "${exp:-0}" -ge 3 ] && pass "station1 expansion exporters present ($exp series)" \
    || warn "station1 expansion exporters sparse ($exp) — run lab/deca_install_expansion_boot.sh"

  if curl -sf --max-time 3 http://localhost:9090/-/ready >/dev/null; then
    scraped=$(curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"up"' | wc -l)
    pass "Prometheus ready, $scraped/${#STATIONS[@]} targets healthy"
  else
    fail "Prometheus not ready on :9090"
  fi

  print_summary
}

# ---------------------------------------------------------------------------
# HEAL — from deca-heal-telemetry.sh: restart failed services, then re-check
# ---------------------------------------------------------------------------
run_heal() {
  need_password
  log "\n=== DECA heal: restarting failed services + expansion boot ==="

  for h in station1 station2; do
    log "--- $h ---"
    ssh_sudo "$h" '
      systemctl reset-failed
      systemctl is-active --quiet deca-ns.service || systemctl restart deca-ns.service
      systemctl start deca-vrf-up.service 2>/dev/null || true
      systemctl start deca-ns-mauritius.service 2>/dev/null || true
      systemctl start deca-mauritius-bgp.service 2>/dev/null || true
      sleep 2
      systemctl is-active --quiet frr || systemctl restart frr
      systemctl is-active --quiet strongswan-starter || systemctl restart strongswan-starter
      systemctl is-active --quiet telegraf || systemctl restart telegraf
      /usr/local/bin/deca-expansion-boot.sh 2>/dev/null || true
    '
  done

  log "--- station3 ---"
  ssh_sudo station3 '
    systemctl reset-failed
    systemctl is-active --quiet frr || systemctl restart frr
    systemctl is-active --quiet telegraf || systemctl restart telegraf
    /usr/local/bin/deca-expansion-boot.sh 2>/dev/null || true
  '

  sleep 3
  log "\nHeal pass complete — re-running check\n"
  run_check
}

# ---------------------------------------------------------------------------
# INSTALL-BOOT — enable sticky expansion + base namespaces for cold power-on
# ---------------------------------------------------------------------------
run_install_boot() {
  need_password
  log "\n=== Installing boot-autostart (namespaces + network expansion) ==="

  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  if [[ -x "$ROOT/lab/deca_install_expansion_boot.sh" ]]; then
    log "Running lab/deca_install_expansion_boot.sh ..."
    bash "$ROOT/lab/deca_install_expansion_boot.sh" || warn "expansion boot install reported errors"
  else
    fail "lab/deca_install_expansion_boot.sh missing"
  fi

  for h in station1 station2; do
    log "Ensuring base units enabled on $h..."
    ssh_sudo "$h" '
      systemctl enable frr strongswan-starter chrony telegraf deca-ns.service deca-watchdog.service deca-expansion-boot.service deca-vrf-up.service 2>/dev/null || true
    '
  done
  ssh_sudo station1 'systemctl enable deca-ns-mauritius.service deca-mauritius-bgp.service 2>/dev/null || true'
  ssh_sudo station3 'systemctl enable frr chrony telegraf deca-watchdog.service deca-expansion-boot.service 2>/dev/null || true'

  log "\nBoot fix applied. Running check...\n"
  run_check
}

print_summary() {
  local total=${#RESULTS[@]} passed=0 failed=0 warned=0
  for r in "${RESULTS[@]}"; do
    case "$r" in
      PASS*) passed=$((passed+1)) ;;
      FAIL*) failed=$((failed+1)) ;;
      WARN*) warned=$((warned+1)) ;;
    esac
  done
  log "\n=========================================="
  log "  SUMMARY: $passed/$total pass, $warned warn, $failed fail"
  log "=========================================="
  if [ "$failed" -gt 0 ]; then
    log "Failed items:"
    printf '  %s\n' "${RESULTS[@]}" | grep FAIL
    log "\nRun: ./deca_ops.sh heal"
  fi
}

# ---------------------------------------------------------------------------
case "${1:-check}" in
  check)        run_check ;;
  heal)         run_heal ;;
  install-boot) run_install_boot ;;
  all)          run_install_boot; run_heal ;;
  *) echo "Usage: $0 {check|heal|install-boot|all}"; exit 1 ;;
esac
