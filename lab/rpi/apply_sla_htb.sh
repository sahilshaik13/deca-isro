#!/usr/bin/env bash
# Apply Pi AAR / PS13 HTB on PE stations + CE netns WAN ifaces.
# Budgets: lab/rpi/SLA.md (TT&C≤25ms · Payload≤80ms · Gold 99.9%).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
HTB_LOCAL="$REPO/lab/deca_htb_qos.sh"
FORCE="${FORCE:-1}"

ssh_ok() {
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$1" true 2>/dev/null
}

ensure_remote_htb() {
  local host="$1"
  ssh "$host" "test -x /usr/local/bin/deca_htb_qos.sh" 2>/dev/null && return 0
  scp -q "$HTB_LOCAL" "$host:/tmp/deca_htb_qos.sh"
  ssh "$host" "sudo install -m 0755 /tmp/deca_htb_qos.sh /usr/local/bin/deca_htb_qos.sh"
}

apply_host_if() {
  local host="$1" ifc="$2" rate="$3"
  echo "[$host] IF=$ifc RATE=$rate"
  ssh "$host" "sudo env FORCE=$FORCE IF=$ifc RATE=$rate /usr/local/bin/deca_htb_qos.sh" \
    && echo "  ok $host:$ifc" || echo "  FAIL $host:$ifc"
}

apply_ns_if() {
  local host="$1" ns="$2" ifc="$3" rate="$4"
  # Do not clobber NetEM (rain-fade / bronze delay) if it owns the root qdisc.
  if ssh "$host" "sudo ip netns exec $ns tc qdisc show dev $ifc 2>/dev/null | grep -q netem"; then
    echo "[$host/$ns] skip $ifc (netem present — PE HTB still enforces)"
    return 0
  fi
  echo "[$host/$ns] IF=$ifc RATE=$rate"
  ssh "$host" "sudo ip netns exec $ns env FORCE=$FORCE IF=$ifc RATE=$rate /usr/local/bin/deca_htb_qos.sh" \
    && echo "  ok $host/$ns:$ifc" || echo "  FAIL $host/$ns:$ifc"
}

APPLIED=()
echo "=== Pi fabric-wide PS13 HTB (TT&C 0x88 → 1:10 · Payload 0x80 → 1:15 · BE → 1:20) ==="

for h in station1 station2; do
  if ! ssh_ok "$h"; then
    echo "[$h] unreachable — skip"
    continue
  fi
  ensure_remote_htb "$h"
  apply_host_if "$h" eth0 40mbit
  APPLIED+=("$h:eth0")
done

if ssh_ok station1; then
  apply_ns_if station1 ce-a veth-cea-pe 40mbit && APPLIED+=("ce-a:veth-cea-pe")
  apply_ns_if station1 ce-mauritius veth-cem-pe 20mbit && APPLIED+=("ce-mauritius:veth-cem-pe")
fi
if ssh_ok station2; then
  apply_ns_if station2 ce-b veth-ceb-pe 40mbit && APPLIED+=("ce-b:veth-ceb-pe")
  apply_ns_if station2 ce-mcf veth-cemcf-pe 20mbit && APPLIED+=("ce-mcf:veth-cemcf-pe")
fi

mkdir -p "$ROOT/state"
python3 - <<PY
import json, time
from pathlib import Path
repo = Path("$REPO")
contract_path = repo / "docs" / "edge_policy_contract.json"
contract = json.loads(contract_path.read_text()) if contract_path.exists() else {}
fab = (contract.get("fabrics") or {}).get("pi") or {}
p = Path("$ROOT/state/sla_active.json")
doc = {
  "active_fabric": "pi",
  "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "sla": {
    "fabric": "pi",
    "label": fab.get("label", "Pi live SLAs (production-like / mentor-aligned)"),
    "classes": contract.get("classes") or {
      "ttc": {"latency_ms": 25, "jitter_ms": 5, "loss_pct": 0.1, "tos": "0x88"},
      "payload": {"latency_ms": 80, "jitter_ms": 15, "loss_pct": 2.0, "tos": "0x80"},
      "admin": {"tos": "0x00"},
    },
    "ce_tiers": {
      k: {"site": v["site"], "tier": v["tier"], "availability": v["availability"]}
      for k, v in (contract.get("ce_tiers") or {}).items()
    } or {
      "ce-a": {"site": "NRSC", "tier": "Gold", "availability": 99.9},
      "ce-b": {"site": "SAC", "tier": "Silver", "availability": 99.5},
      "ce-mauritius": {"site": "Mauritius", "tier": "Bronze", "availability": 90.0},
      "ce-mcf": {"site": "MCF", "tier": "Bronze", "availability": 90.0},
    },
    "chaos": fab.get("chaos", ["iperf3", "netem", "stress-ng", "bgp_soft_clear"]),
  },
  "wire": contract.get("wire") or {
    "ttc_tos": "0x88", "payload_tos": "0x80", "admin_tos": "0x00",
    "htb": {"1:10": "TT&C LLQ", "1:15": "Payload ~70%", "1:20": "BE scavenger"},
  },
  "layers": contract.get("layers") or {},
  "htb_fabric_wide": {
    "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "class_ids": {"ttc": "1:10", "payload": "1:15", "be": "1:20"},
    "interfaces": """${APPLIED[*]}""".split(),
    "prom": "http://127.0.0.1:9090",
    "edge_roles": {
      "pe": ["station1", "station2"],
      "ce": ["ce-a", "ce-b", "ce-mauritius", "ce-mcf"],
      "p": ["station3"],
    },
  },
}
p.write_text(json.dumps(doc, indent=2) + "\n")
print(f"wrote {p} ifaces={len(doc['htb_fabric_wide']['interfaces'])}")
PY

echo "OK — see lab/rpi/SLA.md · docs/EDGE_POLICY_LAYERS.md · capture Prom must be :9090"
echo "     audit: bash lab/audit_edge_policies.sh"
