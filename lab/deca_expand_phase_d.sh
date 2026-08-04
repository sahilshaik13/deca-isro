#!/usr/bin/env bash
# Phase D — Tier-5-pattern missing telemetry exporters.
# Does NOT touch models/fault_classifier/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== Phase D: Tier-5 telemetry exporters ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2; need station3

# Local exporter scripts (copied to stations)
mkdir -p "$ROOT/lab/exporters"
cat > "$ROOT/lab/exporters/deca-syslog-err-count.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cnt=$(journalctl --since "60 sec ago" -p warning..alert -q -o cat 2>/dev/null | wc -l | tr -d ' ')
printf "syslog_err_count value=%s\n" "${cnt:-0}"
SH

cat > "$ROOT/lab/exporters/deca-netflow-flow-count.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
flows=0
if command -v conntrack >/dev/null 2>&1; then
  flows=$(conntrack -C 2>/dev/null || echo 0)
elif [[ -r /proc/net/nf_conntrack ]]; then
  flows=$(wc -l </proc/net/nf_conntrack | tr -d ' ')
else
  flows=$(ss -tan state established 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
fi
printf "netflow_flow_count value=%s\n" "${flows:-0}"
SH

cat > "$ROOT/lab/exporters/deca-path-asymmetry.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
IF=${IFACE:-eth0}
tx=$(cat /sys/class/net/$IF/statistics/tx_bytes 2>/dev/null || echo 0)
rx=$(cat /sys/class/net/$IF/statistics/rx_bytes 2>/dev/null || echo 0)
python3 -c "tx=float('$tx'); rx=float('$rx'); den=tx+rx; ratio=(abs(tx-rx)/den if den>0 else 0.0); print(f'path_asymmetry_ratio value={ratio:.6f}')"
SH

cat > "$ROOT/lab/exporters/deca-ospf-adj.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
n=$(sudo vtysh -c "show ip ospf neighbor" 2>/dev/null | awk 'NR>1 && $3 ~ /Full/ {c++} END{print c+0}')
printf "ospf_adj_up,neighbor=aggregate value=%s\n" "${n:-0}"
SH

cat > "$ROOT/lab/exporters/deca-bgp-mauritius-adj.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
up=0
st=$(sudo vtysh -c "show bgp vrf vrf-mission neighbors 10.10.3.1" 2>/dev/null | awk -F'= ' '/BGP state =/{print $2; exit}')
echo "$st" | grep -qi Established && up=1
printf "bgp_mauritius_adj_up value=%s\n" "${up}"
SH

cat > "$ROOT/lab/exporters/deca-ipsec-rekey.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=$(sudo ipsec statusall 2>/dev/null || sudo ipsec status 2>/dev/null || true)
age=0
if echo "$out" | grep -q 'ESTABLISHED'; then
  line=$(echo "$out" | grep ESTABLISHED | head -1)
  if echo "$line" | grep -qoE '[0-9]+ seconds ago'; then
    age=$(echo "$line" | grep -oE '[0-9]+ seconds ago' | awk '{print $1}')
  elif echo "$line" | grep -qoE '[0-9]+ minutes ago'; then
    age=$(echo "$line" | grep -oE '[0-9]+ minutes ago' | awk '{print $1*60}')
  elif echo "$line" | grep -qoE '[0-9]+ hours ago'; then
    age=$(echo "$line" | grep -oE '[0-9]+ hours ago' | awk '{print $1*3600}')
  fi
fi
nsa=$(echo "$out" | grep -c 'INSTALLED, TUNNEL' || true)
printf "ipsec_sa_age_s value=%s\n" "${age:-0}"
printf "ipsec_child_sa_count value=%s\n" "${nsa:-0}"
SH

chmod +x "$ROOT/lab/exporters/"*.sh

deploy_host() {
  local H=$1
  echo "=== Deploy exporters → $H ==="
  scp -q "$ROOT/lab/exporters/"*.sh "$H:/tmp/"
  ssh -T "$H" "sudo bash -s" <<REMOTE
set -euo pipefail
install -m 0755 /tmp/deca-*.sh /usr/local/bin/
mkdir -p /etc/telegraf/telegraf.d

# sudoers for vtysh/ipsec where needed
HOST=\$(hostname | cut -d. -f1)
if [ "\$HOST" = station1 ]; then
  cat >/etc/sudoers.d/92-telegraf-phase-d <<'S'
_telegraf ALL=(root) NOPASSWD: /usr/bin/vtysh -c show ip ospf neighbor, /usr/bin/vtysh -c show bgp vrf vrf-mission neighbors 10.10.3.1, /usr/sbin/ipsec statusall, /usr/sbin/ipsec status
S
elif [ "\$HOST" = station2 ]; then
  cat >/etc/sudoers.d/92-telegraf-phase-d <<'S'
_telegraf ALL=(root) NOPASSWD: /usr/bin/vtysh -c show ip ospf neighbor, /usr/sbin/ipsec statusall, /usr/sbin/ipsec status
S
else
  cat >/etc/sudoers.d/92-telegraf-phase-d <<'S'
_telegraf ALL=(root) NOPASSWD: /usr/bin/vtysh -c show ip ospf neighbor
S
fi
chmod 0440 /etc/sudoers.d/92-telegraf-phase-d
visudo -cf /etc/sudoers.d/92-telegraf-phase-d

cat >/etc/telegraf/telegraf.d/deca-phase-d-common.conf <<'EOF'
[[inputs.exec]]
  commands = ["/usr/local/bin/deca-syslog-err-count.sh"]
  timeout = "5s"
  interval = "10s"
  data_format = "influx"
  name_override = "syslog_err_count"

[[inputs.exec]]
  commands = ["/usr/local/bin/deca-netflow-flow-count.sh"]
  timeout = "4s"
  interval = "10s"
  data_format = "influx"
  name_override = "netflow_flow_count"

[[inputs.exec]]
  commands = ["/usr/local/bin/deca-path-asymmetry.sh"]
  timeout = "3s"
  interval = "10s"
  data_format = "influx"
  name_override = "path_asymmetry_ratio"

[[inputs.exec]]
  commands = ["/usr/local/bin/deca-ospf-adj.sh"]
  timeout = "5s"
  interval = "10s"
  data_format = "influx"
  name_override = "ospf_adj_up"
EOF

if [ "\$HOST" = station1 ]; then
  cat >/etc/telegraf/telegraf.d/deca-phase-d-pe1.conf <<'EOF'
[[inputs.exec]]
  commands = ["/usr/local/bin/deca-bgp-mauritius-adj.sh"]
  timeout = "5s"
  interval = "10s"
  data_format = "influx"
  name_override = "bgp_mauritius_adj_up"

[[inputs.exec]]
  commands = ["/usr/local/bin/deca-ipsec-rekey.sh"]
  timeout = "5s"
  interval = "15s"
  data_format = "influx"
EOF
fi
if [ "\$HOST" = station2 ]; then
  cat >/etc/telegraf/telegraf.d/deca-phase-d-pe2.conf <<'EOF'
[[inputs.exec]]
  commands = ["/usr/local/bin/deca-ipsec-rekey.sh"]
  timeout = "5s"
  interval = "15s"
  data_format = "influx"
EOF
fi

systemctl restart telegraf
sleep 1
systemctl is-active telegraf
REMOTE
}

deploy_host station1
deploy_host station2
deploy_host station3

echo "=== BEFORE (direct telegraf) ==="
sleep 12
for H in station1 station2 station3; do
  echo "-- $H --"
  ssh -T "$H" 'curl -s localhost:9273/metrics' | grep -E '^(syslog_err_count|netflow_flow_count|ospf_adj_up|bgp_mauritius|ipsec_|path_asymmetry)' | head -40 || true
done

if [[ "${SKIP_SMOKE:-0}" == "1" ]]; then
  echo "=== SKIP_SMOKE=1 — skipping inject/clear smoke ==="
  echo "=== Phase D install done ==="
  exit 0
fi

echo "=== Smoke inject/clear ==="
ssh -T station1 'sudo logger -p user.warning deca-phase-d-smoke-test
sudo vtysh -c "clear bgp vrf vrf-mission 10.10.3.1 soft" 2>/dev/null || true
sudo ipsec down deca-sdwan 2>/dev/null || true
sleep 1
sudo ipsec up deca-sdwan 2>/dev/null || true
sleep 4
sudo ipsec status | head -12
sudo vtysh -c "show bgp vrf vrf-mission neighbors 10.10.3.1" | grep "BGP state" || true
# manual exporter run as proof
sudo -u _telegraf /usr/local/bin/deca-syslog-err-count.sh || /usr/local/bin/deca-syslog-err-count.sh
sudo -u _telegraf /usr/local/bin/deca-bgp-mauritius-adj.sh || sudo /usr/local/bin/deca-bgp-mauritius-adj.sh
sudo -u _telegraf /usr/local/bin/deca-ipsec-rekey.sh || sudo /usr/local/bin/deca-ipsec-rekey.sh
sudo -u _telegraf /usr/local/bin/deca-ospf-adj.sh || sudo /usr/local/bin/deca-ospf-adj.sh
sudo -u _telegraf /usr/local/bin/deca-path-asymmetry.sh || /usr/local/bin/deca-path-asymmetry.sh
sudo -u _telegraf /usr/local/bin/deca-netflow-flow-count.sh || /usr/local/bin/deca-netflow-flow-count.sh
'

sleep 15
echo "=== AFTER ==="
for H in station1 station2; do
  echo "-- $H --"
  ssh -T "$H" 'curl -s localhost:9273/metrics' | grep -E '^(syslog_err_count|netflow_flow_count|ospf_adj_up|bgp_mauritius|ipsec_|path_asymmetry)' | head -40 || true
done

echo "=== Prom queries ==="
for q in syslog_err_count_value netflow_flow_count_value ospf_adj_up_value bgp_mauritius_adj_up_value ipsec_sa_age_s_value path_asymmetry_ratio_value; do
  echo -n "$q: "
  curl -sg "http://127.0.0.1:9090/api/v1/query?query=$q" | python3 -c 'import sys,json; d=json.load(sys.stdin); r=d.get("data",{}).get("result",[]); print(len(r), "series", [x["value"][1] for x in r[:3]])'
done

echo "=== Phase D done ==="
