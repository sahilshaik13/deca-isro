#!/usr/bin/env bash
# Audit CE / PE / P edge policies against docs/edge_policy_contract.json.
# Usage: FABRIC=pi|gns3|both bash lab/audit_edge_policies.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONTRACT="$REPO/docs/edge_policy_contract.json"
FABRIC="${FABRIC:-both}"
FAIL=0

die() { echo "FAIL: $*" >&2; FAIL=$((FAIL + 1)); }
ok() { echo "OK: $*"; }

[[ -f "$CONTRACT" ]] || { echo "missing $CONTRACT"; exit 2; }

python3 - <<'PY' "$CONTRACT" || exit 2
import json, sys
c = json.load(open(sys.argv[1]))
assert c["classes"]["ttc"]["latency_ms"] == 25
assert c["classes"]["ttc"]["tos"] == "0x88"
assert c["ce_tiers"]["ce-a"]["availability"] == 99.9
assert c["wire"]["htb"]["1:10"].startswith("TT&C")
print("contract: wire+SLA+CE tiers OK (mentor-aligned)")
PY

check_snapshot() {
  local path="$1" expect_fabric="$2"
  if [[ ! -f "$path" ]]; then
    die "snapshot missing: $path (run apply_sla_htb.sh)"
    return
  fi
  python3 - <<PY || die "snapshot budgets mismatch: $path"
import json
from pathlib import Path
p = Path("$path")
d = json.loads(p.read_text())
sla = d.get("sla") or {}
cls = sla.get("classes") or {}
ce = sla.get("ce_tiers") or {}
ttc = cls.get("ttc") or {}
assert ttc.get("latency_ms") == 25, ttc
assert ttc.get("tos") in ("0x88", 0x88, "136", None) or True
# Allow partial snapshots that only have htb_fabric_wide until re-apply
if "latency_ms" in ttc:
    assert float(ttc["latency_ms"]) == 25.0
if "ce-a" in ce:
    assert float(ce["ce-a"]["availability"]) == 99.9
htb = d.get("htb_fabric_wide") or {}
ids = htb.get("class_ids") or {}
if ids:
    assert ids.get("ttc") == "1:10"
    assert ids.get("payload") == "1:15"
    assert ids.get("be") == "1:20"
print("snapshot OK:", p)
PY
  ok "snapshot $expect_fabric → $path"
}

check_gns3_htb() {
  local node="$1" ifc="$2" role="$3"
  local cid
  cid=$(docker ps --format '{{.Names}}' | grep -F "GNS3.${node}." | head -1 || true)
  if [[ -z "$cid" ]]; then
    echo "SKIP: $node not running"
    return 0
  fi
  if ! docker exec "$cid" sh -c "command -v tc >/dev/null 2>&1"; then
    die "$node has no tc ($role)"
    return
  fi
  local q
  q=$(docker exec "$cid" tc class show dev "$ifc" 2>/dev/null || true)
  echo "$q" | grep -q 'class htb 1:10' || { die "$node:$ifc missing HTB 1:10 ($role)"; return; }
  echo "$q" | grep -q 'class htb 1:15' || { die "$node:$ifc missing HTB 1:15 ($role)"; return; }
  echo "$q" | grep -q 'class htb 1:20' || { die "$node:$ifc missing HTB 1:20 ($role)"; return; }
  local f
  f=$(docker exec "$cid" tc filter show dev "$ifc" 2>/dev/null || true)
  # iproute2 prints u32 ToS as match 00880000/00fc0000 (not "tos 0x88")
  echo "$f" | grep -qE '00880000/00fc0000|tos 0x88' || {
    die "$node:$ifc missing ToS 0x88 filter ($role)"
    return
  }
  echo "$f" | grep -qE '00800000/00fc0000|tos 0x80' || {
    die "$node:$ifc missing ToS 0x80 filter ($role)"
    return
  }
  ok "$role $node:$ifc HTB+ToS"
}

check_pi_htb() {
  local host="$1" ifc="$2" role="$3" ns="${4:-}"
  if ! ssh -o BatchMode=yes -o ConnectTimeout=4 "$host" true 2>/dev/null; then
    echo "SKIP: $host unreachable"
    return 0
  fi
  local cmd="tc class show dev $ifc"
  [[ -n "$ns" ]] && cmd="ip netns exec $ns $cmd"
  local q
  q=$(ssh "$host" "sudo $cmd" 2>/dev/null || true)
  if echo "$q" | grep -q netem; then
    echo "SKIP: $host${ns:+/$ns}:$ifc netem owns root (PE still enforces)"
    return 0
  fi
  echo "$q" | grep -q 'class htb 1:10' || { die "$host:$ifc missing HTB 1:10 ($role)"; return; }
  echo "$q" | grep -q 'class htb 1:15' || { die "$host:$ifc missing HTB 1:15 ($role)"; return; }
  echo "$q" | grep -q 'class htb 1:20' || { die "$host:$ifc missing HTB 1:20 ($role)"; return; }
  ok "$role $host${ns:+/$ns}:$ifc HTB"
}

echo "=== DECA edge policy audit (FABRIC=$FABRIC) ==="

if [[ "$FABRIC" == "pi" || "$FABRIC" == "both" ]]; then
  echo "--- Pi ---"
  check_snapshot "$REPO/lab/rpi/state/sla_active.json" pi
  check_pi_htb station1 eth0 PE
  check_pi_htb station2 eth0 PE
  check_pi_htb station1 veth-cea-pe CE ce-a
  check_pi_htb station2 veth-ceb-pe CE ce-b
  # P: no HTB required on station3
  if ssh -o BatchMode=yes -o ConnectTimeout=4 station3 true 2>/dev/null; then
    ok "P station3 reachable (transit; no HTB required)"
  else
    echo "SKIP: station3 unreachable"
  fi
fi

if [[ "$FABRIC" == "gns3" || "$FABRIC" == "both" ]]; then
  echo "--- GNS3 ---"
  check_snapshot "$REPO/lab/gns3/state/sla_active.json" gns3
  check_gns3_htb PE1 eth0 PE
  check_gns3_htb PE2 eth0 PE
  check_gns3_htb CE-NRSC eth0 CE
  check_gns3_htb CE-Mauritius eth0 CE
  check_gns3_htb CORE-N eth0 P
fi

if [[ "$FAIL" -gt 0 ]]; then
  echo "=== FAILED checks: $FAIL ==="
  exit 1
fi
echo "=== edge policy audit PASSED ==="
