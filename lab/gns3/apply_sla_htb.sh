#!/usr/bin/env bash
# Apply GNS3 AAR / PS13 HTB on every PE, CE, and CORE node (not just PE1).
# Same class IDs as Pi: 1:10 TT&C (0x88) · 1:15 Payload (0x80) · 1:20 BE.
# Requires: ubridge + DECA nodes started; fabric should be gns3.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
# Pi twin default WAN rate (lab/deca_htb_qos.sh); CORE may still use NODE_RATE
RATE="${RATE:-40mbit}"
FORCE="${FORCE:-1}"

cname() { docker ps --format '{{.Names}}' | grep -F "GNS3.$1." | head -1; }

# DECA-CE Alpine image has no iproute2/tc (apk mirror often blocked).
# Seed tc + musl libs from a running FRR PE once per apply.
ensure_tc_on_ces() {
  local pe bundle=/tmp/deca-gns3-tc-bundle.tar
  pe=$(cname PE1 || true)
  [[ -n "$pe" ]] || return 0
  if ! docker exec "$pe" sh -c 'command -v tc >/dev/null'; then
    echo "[warn] PE1 has no tc — cannot seed CEs"
    return 0
  fi
  docker exec "$pe" sh -c 'tar -C / -cf - \
    sbin/tc \
    usr/lib/libelf-0.186.so usr/lib/libelf.so.1 \
    usr/lib/libmnl.so.0.2.0 usr/lib/libmnl.so.0 \
    usr/lib/libcap.so.2.64 usr/lib/libcap.so.2 \
    usr/lib/libxtables.so.12.6.0 usr/lib/libxtables.so.12' >"$bundle"
  for ce in $(docker ps --format '{{.Names}}' | grep 'GNS3.CE-' || true); do
    if docker exec "$ce" sh -c 'command -v tc >/dev/null 2>&1'; then
      continue
    fi
    docker cp "$bundle" "$ce:/tmp/tc-bundle.tar" >/dev/null
    docker exec "$ce" sh -c 'tar -C / -xf /tmp/tc-bundle.tar && chmod +x /sbin/tc' \
      && echo "[seed] tc → $ce" || echo "[warn] tc seed failed: $ce"
  done
}

# PS13 HTB leaf — twin of lab/deca_htb_qos.sh (RED on 1:15 + dport 5004/5006).
apply_htb() {
  local cid="$1" ifc="$2" rate="${3:-$RATE}"
  docker exec "$cid" sh -c "
set -e
IF='$ifc'
RATE='$rate'
FORCE='$FORCE'
RATE_NUM=\${RATE%mbit}; RATE_NUM=\${RATE_NUM%Mbit}; RATE_NUM=\${RATE_NUM%M}
PAY_RATE=\$(awk -v r=\"\$RATE_NUM\" 'BEGIN{printf \"%.0fmbit\", r*0.70}')
PAY_CEIL=\$(awk -v r=\"\$RATE_NUM\" 'BEGIN{printf \"%.0fmbit\", r*0.85}')
BE_CEIL=\$(awk -v r=\"\$RATE_NUM\" 'BEGIN{printf \"%.0fmbit\", r*0.60}')
if [ \"\$FORCE\" != 1 ] && tc qdisc show dev \"\$IF\" 2>/dev/null | grep -q 'qdisc htb 1:'; then
  if tc filter show dev \"\$IF\" 2>/dev/null | grep -q 'tos 80'; then
    echo \"  skip \$IF (PS13 htb present)\"
    exit 0
  fi
fi
ip link show \"\$IF\" >/dev/null 2>&1 || { echo \"  miss \$IF\"; exit 0; }
ip link set \"\$IF\" up 2>/dev/null || true
tc qdisc del dev \"\$IF\" root 2>/dev/null || true
tc qdisc add dev \"\$IF\" root handle 1: htb default 20
tc class add dev \"\$IF\" parent 1: classid 1:1 htb rate \"\$RATE\" ceil \"\$RATE\"
tc class add dev \"\$IF\" parent 1:1 classid 1:10 htb rate 2mbit ceil \"\$RATE\" prio 1
tc class add dev \"\$IF\" parent 1:1 classid 1:15 htb rate \"\$PAY_RATE\" ceil \"\$PAY_CEIL\" prio 2
tc class add dev \"\$IF\" parent 1:1 classid 1:20 htb rate 5mbit ceil \"\$BE_CEIL\" prio 5
tc qdisc add dev \"\$IF\" parent 1:10 handle 10: sfq perturb 10
tc qdisc add dev \"\$IF\" parent 1:15 handle 15: red limit 500000 min 350000 max 425000 avpkt 1000 burst 40 probability 0.2 ecn 2>/dev/null \
  || tc qdisc add dev \"\$IF\" parent 1:15 handle 15: sfq perturb 10
tc qdisc add dev \"\$IF\" parent 1:20 handle 20: sfq perturb 10
tc filter add dev \"\$IF\" protocol ip parent 1:0 prio 1 u32 match ip tos 0x88 0xfc flowid 1:10
tc filter add dev \"\$IF\" protocol ip parent 1:0 prio 2 u32 match ip tos 0x80 0xfc flowid 1:15
tc filter add dev \"\$IF\" protocol ip parent 1:0 prio 3 u32 match ip tos 0xb8 0xfc flowid 1:10
tc filter add dev \"\$IF\" protocol ip parent 1:0 prio 4 u32 match ip dport 5004 0xffff flowid 1:10
tc filter add dev \"\$IF\" protocol ip parent 1:0 prio 5 u32 match ip dport 5006 0xffff flowid 1:15
echo \"  ok \$IF rate=\$RATE classes=1:10/1:15/1:20 + RED/dport (Pi twin)\"
" 2>&1 | sed "s/^/  /"
}

# Known Flow-1 path ifaces.
# HTB only on PE + CE (QoS edge). CORE/P must NOT get HTB — NetEM rain/loss
# applies on CORE-N eth0 (Pi twin of gre-te-core underlay). P preserves DSCP.
declare -A NODE_IFACES=(
  [PE1]="eth0 eth4"          # CORE + CE-NRSC
  [PE2]="eth0 eth4"          # CORE + CE-SAC
  [PE3]="eth0 eth1 eth2"     # CORE + vrf-admin + CE stubs
  [CE-NRSC]="eth0"           # WAN Gold
  [CE-SAC]="eth0"            # WAN Silver
  [CE-Mauritius]="eth0"      # WAN Bronze
  [CE-MCF]="eth0"
  [CE-Shadnagar]="eth0"
  [CE-ISTRAC]="eth0"
  [CE-ISRO-HQ]="eth0"
  [CE-Bhopal]="eth0"
)

# PE WAN = Pi eth0 40mbit
declare -A NODE_RATE=(
  [CE-NRSC]="40mbit"
  [CE-SAC]="40mbit"
  [CE-Mauritius]="40mbit"
  [CE-MCF]="40mbit"
  [CE-Shadnagar]="40mbit"
  [CE-ISTRAC]="40mbit"
  [CE-ISRO-HQ]="40mbit"
  [CE-Bhopal]="40mbit"
  [PE1]="40mbit"
  [PE2]="40mbit"
  [PE3]="40mbit"
)

APPLIED=0
MISSING=0
FAILED=0
REPORT=()

echo "=== GNS3 edge HTB (PE+CE only; CORE/P left clear for NetEM underlay) ==="
ensure_tc_on_ces
# Strip any prior HTB on CORE so NetEM rain/loss can attach (Pi gre-te twin)
for node in CORE-N CORE-S; do
  cid=$(cname "$node" || true)
  [[ -z "$cid" ]] && continue
  for ifc in eth0 eth1; do
    docker exec "$cid" sh -c \
      "tc qdisc show dev $ifc 2>/dev/null | grep -q 'qdisc htb' && tc qdisc del dev $ifc root 2>/dev/null || true" \
      >/dev/null 2>&1 || true
  done
  echo "[$node] HTB cleared (P transit — NetEM underlay ready)"
done
for node in PE1 PE2 PE3 \
            CE-NRSC CE-SAC CE-Mauritius CE-MCF CE-Shadnagar \
            CE-ISTRAC CE-ISRO-HQ CE-Bhopal; do
  cid=$(cname "$node" || true)
  if [[ -z "$cid" ]]; then
    echo "[$node] not running — skip"
    MISSING=$((MISSING + 1))
    continue
  fi
  ifaces="${NODE_IFACES[$node]:-eth0}"
  rate="${NODE_RATE[$node]:-$RATE}"
  echo "[$node] $cid  ifaces=[$ifaces] rate=$rate"
  for ifc in $ifaces; do
    if apply_htb "$cid" "$ifc" "$rate"; then
      APPLIED=$((APPLIED + 1))
      REPORT+=("$node:$ifc")
    else
      FAILED=$((FAILED + 1))
      echo "  FAIL $node:$ifc"
    fi
  done
done

# Persist coverage + aligned SLA snapshot next to sla_active.json
mkdir -p "$ROOT/state"
python3 - <<PY
import json, time
from pathlib import Path
repo = Path("$ROOT").resolve().parents[1]
contract_path = repo / "docs" / "edge_policy_contract.json"
contract = json.loads(contract_path.read_text()) if contract_path.exists() else {}
fab = (contract.get("fabrics") or {}).get("gns3") or {}
p = Path("$ROOT/state/sla_active.json")
base = {
    "active_fabric": "gns3",
    "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "sla": {
        "fabric": "gns3",
        "label": fab.get("label", "GNS3 sim SLAs (aligned to Pi / mentor)"),
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
        "ttc_tos": "0x88",
        "payload_tos": "0x80",
        "admin_tos": "0x00",
        "htb": {"1:10": "TT&C LLQ", "1:15": "Payload ~70%", "1:20": "BE scavenger"},
    },
    "layers": contract.get("layers") or {},
}
base["htb_fabric_wide"] = {
    "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "class_ids": {"ttc": "1:10", "payload": "1:15", "be": "1:20"},
    "tos": {"ttc": "0x88", "payload": "0x80", "be": "0x00"},
    "interfaces": """${REPORT[*]}""".split(),
    "nodes_missing": $MISSING,
    "iface_failed": $FAILED,
    "iface_count": $APPLIED,
    "edge_roles": {
        "pe": ["PE1", "PE2", "PE3"],
        "ce": ["CE-NRSC", "CE-SAC", "CE-Mauritius", "CE-MCF",
               "CE-Shadnagar", "CE-ISTRAC", "CE-ISRO-HQ", "CE-Bhopal"],
        "p": ["CORE-N", "CORE-S"],
    },
}
p.write_text(json.dumps(base, indent=2) + "\n")
print(f"wrote {p} htb interfaces={base['htb_fabric_wide']['iface_count']} failed={base['htb_fabric_wide']['iface_failed']}")
PY

echo "OK — HTB on $APPLIED iface(s); failed=$FAILED; not-running=$MISSING"
echo "     budgets: lab/gns3/SLA.md (aligned TT&C≤25ms · Payload≤80ms · Gold 99.9%)"
echo "     layers:  docs/EDGE_POLICY_LAYERS.md · audit: bash lab/audit_edge_policies.sh"
# BEST_EFFORT=1 (campaign default path): never fail the caller on partial HTB
if [[ "${BEST_EFFORT:-0}" == "1" ]]; then
  exit 0
fi
[[ "$FAILED" -eq 0 ]]
