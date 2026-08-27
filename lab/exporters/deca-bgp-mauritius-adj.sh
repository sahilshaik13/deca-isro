#!/usr/bin/env bash
set -euo pipefail
up=0
st=$(sudo vtysh -c "show bgp vrf vrf-mission neighbors 10.10.3.1" 2>/dev/null | awk -F'= ' '/BGP state =/{print $2; exit}')
echo "$st" | grep -qi Established && up=1
printf "bgp_mauritius_adj_up value=%s\n" "${up}"
