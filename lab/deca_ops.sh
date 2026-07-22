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
    svc=$(ssh_sudo "$h" 'systemctl is-enabled frr strongswan-starter chrony deca-ns.service 2>/dev/null' | tr '\n' ' ')
    ns=$(ssh -q "$h" 'sudo ip netns list 2>/dev/null' | wc -l)
    [[ "$svc" == *enabled* ]] && pass "$h services: $svc" || warn "$h services: $svc"
    [ "$ns" -le 1 ] && pass "$h namespaces clean ($ns)" || warn "$h namespaces: $ns present (check for dupes)"
  done
  svc3=$(ssh_sudo station3 'systemctl is-enabled frr chrony 2>/dev/null' | tr '\n' ' ')
  [[ "$svc3" == *enabled* ]] && pass "station3 services: $svc3" || warn "station3 services: $svc3"

  log "\n[4] OSPF / MPLS / BGP (station1)"
  ospf=$(ssh_sudo station1 'vtysh -c "show ip ospf neighbor"' | grep -c Full)
  [ "$ospf" -ge 1 ] && pass "OSPF: $ospf full adjacency" || fail "OSPF: no full adjacency"

  mpls=$(ssh_sudo station1 'vtysh -c "show mpls table"' | grep -c LDP)
  [ "$mpls" -ge 1 ] && pass "MPLS/LDP labels populated" || fail "MPLS/LDP labels missing"

  bgp=$(ssh_sudo station1 'vtysh -c "show ip bgp summary"' | grep "10.1.3.1")
  [ -n "$bgp" ] && pass "BGP peer 10.1.3.1: $bgp" || fail "BGP peer 10.1.3.1 not established"

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
  log "\n=== DECA heal: restarting failed services ==="

  for h in station1 station2; do
    log "--- $h ---"
    ssh_sudo "$h" '
      systemctl reset-failed
      systemctl is-active --quiet deca-ns.service || systemctl restart deca-ns.service
      sleep 2
      systemctl is-active --quiet frr || systemctl restart frr
      systemctl is-active --quiet strongswan-starter || systemctl restart strongswan-starter
      systemctl is-active --quiet telegraf || systemctl restart telegraf
    '
  done

  log "--- station3 ---"
  ssh_sudo station3 '
    systemctl reset-failed
    systemctl is-active --quiet frr || systemctl restart frr
    systemctl is-active --quiet telegraf || systemctl restart telegraf
  '

  sleep 3
  log "\nHeal pass complete — re-running check\n"
  run_check
}

# ---------------------------------------------------------------------------
# INSTALL-BOOT — from apply_boot_fix.sh: enable namespace service on boot
# ---------------------------------------------------------------------------
run_install_boot() {
  need_password
  log "\n=== Installing boot-autostart service (station1, station2) ==="

  for h in station1 station2; do
    log "Updating $h..."
    ssh_sudo "$h" '
      mkdir -p /usr/local/bin
      [ -f /etc/rc.local ] && mv /etc/rc.local /usr/local/bin/setup_namespaces.sh
      chmod +x /usr/local/bin/setup_namespaces.sh
      cat > /etc/systemd/system/deca-namespaces.service << EOT
[Unit]
Description=DECA CE Namespaces and iPerf Server
After=network-online.target frr.service systemd-networkd.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/setup_namespaces.sh
ExecStartPost=/usr/bin/systemctl restart frr

[Install]
WantedBy=multi-user.target
EOT
      systemctl daemon-reload
      systemctl enable --now deca-namespaces.service
    '
    log "$h updated."
  done

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
