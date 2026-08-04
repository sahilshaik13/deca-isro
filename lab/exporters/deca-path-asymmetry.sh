#!/usr/bin/env bash
set -euo pipefail
IF=${IFACE:-eth0}
tx=$(cat /sys/class/net/$IF/statistics/tx_bytes 2>/dev/null || echo 0)
rx=$(cat /sys/class/net/$IF/statistics/rx_bytes 2>/dev/null || echo 0)
python3 -c "tx=float('$tx'); rx=float('$rx'); den=tx+rx; ratio=(abs(tx-rx)/den if den>0 else 0.0); print(f'path_asymmetry_ratio value={ratio:.6f}')"
