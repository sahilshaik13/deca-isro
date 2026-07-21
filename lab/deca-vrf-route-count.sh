#!/usr/bin/env bash
# FRR per-VRF route counts for Telegraf inputs.exec (Influx line protocol).
# Install: sudo install -m 0755 lab/deca-vrf-route-count.sh /usr/local/bin/
set -euo pipefail

count_routes() {
  local vrf="$1"
  # Telegraf's exec plugin runs as the unprivileged `_telegraf` user; the FRR
  # vty socket is root/frrvty-only, so this needs the sudoers NOPASSWD drop-in
  # installed alongside this script (see lab/deca-deploy.sh Tier 5 section).
  #
  # Counts the BGP table, not the RIB/FIB: a leaked VPNv4 import via
  # `rt vpn import` shows up in `show bgp vrf <vrf> ipv4 unicast` immediately,
  # but in this lab's topology the imported prefixes' next hops don't resolve
  # across the VRF boundary, so they never get selected/installed into the RIB
  # (`show ip route vrf <vrf> summary` stays 0 even with a live leak --
  # verified 2026-07-20). The BGP table is the real, reliable signal of the
  # wrong-RT-import fault; footer line is "Displayed N routes and M total
  # paths" (or "No BGP prefixes displayed, 0 exist" when empty).
  sudo vtysh -c "show bgp vrf ${vrf} ipv4 unicast" 2>/dev/null \
    | awk '/^Displayed/ { print $2; exit } /^No BGP prefixes/ { print 0; exit }'
}

emit() {
  local vrf="$1" val
  val="$(count_routes "${vrf}")"
  val="${val:-0}"
  printf 'vrf_route_count,vrf=%s value=%s\n' "${vrf}" "${val}"
}

# NB: the deployed VRF is named "vrf-admin" (see `show vrf`), not "ADMIN".
# `inject_vrf_leakage()` historically targeted a phantom "ADMIN" BGP-VRF
# instance that zebra never bound to any real VRF -- fixed alongside this
# exporter (docs/TIER5_VRF_ROUTE_COUNT.md).
emit vrf-admin
emit vrf-mission
