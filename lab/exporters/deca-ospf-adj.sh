#!/usr/bin/env bash
set -euo pipefail
n=$(sudo vtysh -c "show ip ospf neighbor" 2>/dev/null | awk 'NR>1 && $3 ~ /Full/ {c++} END{print c+0}')
printf "ospf_adj_up,neighbor=aggregate value=%s\n" "${n:-0}"
