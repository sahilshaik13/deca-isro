#!/usr/bin/env bash
# install_edge.sh — deploy softflowd + Telegraf→Kafka pipeline on a PE.
# Usage: bash lab/telemetry-pipeline/install_edge.sh station1
set -euo pipefail

HOST="${1:?usage: $0 station1|station2}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PIPE="$ROOT/lab/telemetry-pipeline"
ADV="${KAFKA_ADVERTISED_HOST:-}"
if [[ -z "$ADV" ]]; then
  ADV="$(ip -4 -br addr show 2>/dev/null | awk '/192\.168\.50\./ {print $3}' | head -1 | cut -d/ -f1 || true)"
fi
ADV="${ADV:-192.168.50.1}"

echo "=== Deploy telemetry edge → $HOST (Kafka ${ADV}:9092) ==="

ssh -T "$HOST" 'mkdir -p /tmp/deca-telemetry'
scp -q "$PIPE/telegraf.conf" "$HOST:/tmp/deca-telemetry/telegraf.conf"
scp -q "$PIPE/setup_softflowd.sh" "$HOST:/tmp/deca-telemetry/setup_softflowd.sh"
scp -q "$PIPE/scripts/sdwan_tunnel_stats.sh" "$HOST:/tmp/deca-telemetry/sdwan_tunnel_stats.sh"
scp -q "$PIPE/rsyslog-deca-frr.conf" "$HOST:/tmp/deca-telemetry/rsyslog-deca-frr.conf"
scp -q "$PIPE/snmpd.deca.conf" "$HOST:/tmp/deca-telemetry/snmpd.deca.conf"

# shellcheck disable=SC2029
ssh -T "$HOST" "sudo ADV='${ADV}' bash -s" <<'EOS'
set -euo pipefail
ADV="${ADV:?}"

# --- Telegraf edge config (Kafka broker + unprivileged syslog port) ---
# Pi telegraf user cannot bind :514 → use :5514
python3 - <<PY
from pathlib import Path
adv = """${ADV}"""
t = Path("/tmp/deca-telemetry/telegraf.conf").read_text()
t = t.replace("192.168.50.1:9092", f"{adv}:9092")
t = t.replace('server = "udp://:514"', 'server = "udp://:5514"')
# Telegraf 1.21 on jammy: inputs.netflow exists; if missing, comment handled at runtime
Path("/tmp/deca-telegraf-kafka.conf").write_text(t)
print("brokers ->", adv + ":9092", "| syslog udp://:5514")
PY

install -d /etc/telegraf/telegraf.d
install -m 0644 /tmp/deca-telegraf-kafka.conf /etc/telegraf/telegraf.d/deca-kafka-pipeline.conf
install -m 0755 /tmp/deca-telemetry/sdwan_tunnel_stats.sh /usr/local/bin/sdwan_tunnel_stats.sh

# Telegraf (_telegraf) must read softflowctl + write dump dir
install -d -o root -g _telegraf -m 1775 /var/lib/deca-softflowd
echo "_telegraf ALL=(root) NOPASSWD: /usr/sbin/softflowctl" >/etc/sudoers.d/deca-telegraf-softflowctl
chmod 440 /etc/sudoers.d/deca-telegraf-softflowctl
visudo -cf /etc/sudoers.d/deca-telegraf-softflowctl >/dev/null

# --- softflowd → 127.0.0.1:2055 ---
bash /tmp/deca-telemetry/setup_softflowd.sh install
systemctl is-active --quiet deca-softflowd.service \
  || { echo "FAIL deca-softflowd"; systemctl status deca-softflowd --no-pager; exit 1; }

# --- rsyslog FRR → Telegraf :5514 ---
sed 's/port="514"/port="5514"/' /tmp/deca-telemetry/rsyslog-deca-frr.conf \
  > /etc/rsyslog.d/30-deca-frr.conf
systemctl restart rsyslog || true

# --- snmpd (required for inputs.snmp; do not soft-skip) ---
if ! dpkg -l snmpd 2>/dev/null | grep -q '^ii'; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y snmpd snmp
fi
install -d /etc/snmp
install -m 0644 /tmp/deca-telemetry/snmpd.deca.conf /etc/snmp/snmpd.conf
systemctl enable snmpd
systemctl restart snmpd
sleep 1
if ! systemctl is-active --quiet snmpd; then
  echo "FAIL snmpd"; journalctl -u snmpd -n 40 --no-pager; exit 1
fi
# quick localhost walk (numeric OID; MIBs not required)
if command -v snmpget >/dev/null; then
  snmpget -v2c -c deca-lab 127.0.0.1 1.3.6.1.2.1.1.1.0 >/dev/null \
    || { echo "FAIL: snmpd not answering on 127.0.0.1:161"; exit 1; }
fi

systemctl restart telegraf
sleep 2
if systemctl is-active --quiet telegraf; then
  echo "OK telegraf active"
else
  echo "FAIL telegraf"; journalctl -u telegraf -n 40 --no-pager; exit 1
fi

ss -ulnp | grep -E ':(5514|2055)\b' || echo "WARN: UDP 5514/2055 not shown yet"
pgrep -af softflowd || echo "WARN: softflowd not running"
grep -E 'brokers|topic' /etc/telegraf/telegraf.d/deca-kafka-pipeline.conf | head -5
EOS

echo "=== Edge deploy done on $HOST ==="
