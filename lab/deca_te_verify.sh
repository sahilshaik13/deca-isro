#!/usr/bin/env bash
# Verify OSPF-TE TED + pathd SR-TE preferred/backup path switch (PS13-O1.2).
# Does not touch models/fault_classifier/.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVID_ROOT="$ROOT/data/rpi-net/te-verify"
EVID="$EVID_ROOT/deca-te-verify-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVID"

PASS=0
FAIL=0
pass() { echo "PASS: $*"; PASS=$((PASS + 1)); echo "PASS: $*" >>"$EVID/summary.txt"; }
fail() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); echo "FAIL: $*" >>"$EVID/summary.txt"; }

restore() {
  set +e
  ssh -T station1 'sudo vtysh' <<'VTY' >/dev/null 2>&1
configure terminal
segment-routing
 traffic-eng
  segment-list SL-GRE
   index 10 mpls label 16003
   index 20 mpls label 16002
  exit
  segment-list SL-ETH
   index 10 mpls label 15010
  exit
  policy color 1 endpoint 10.1.2.1
   name pe1-to-pe2-te
   binding-sid 40001
   candidate-path preference 100 name via-gre explicit segment-list SL-GRE
   candidate-path preference 50 name via-eth explicit segment-list SL-ETH
  exit
 exit
exit
end
write memory
VTY
}
trap restore EXIT

echo "=== evidence: $EVID ==="

# 1) TED present
TED=$(ssh -T station1 'sudo vtysh -c "show pathd ted database verbose"' 2>/dev/null || true)
echo "$TED" | tee "$EVID/ted.txt" >/dev/null
echo "$TED" | grep -qE "Total:[[:space:]]*[3-9] Vertices|Total:[[:space:]]*[1-9][0-9]+ Vertices" \
  && pass "pathd TED has >=3 vertices" || fail "pathd TED missing vertices"
echo "$TED" | grep -q "10.50.1.1" && pass "TED has GRE edge 10.50.1.1" || fail "TED missing GRE edge"

# 2) Preferred policy Active via GRE
POL=$(ssh -T station1 'sudo vtysh -c "show sr-te policy detail"' 2>/dev/null || true)
echo "$POL" | tee "$EVID/policy_preferred.txt"
echo "$POL" | grep -q "Status: Active" && pass "SR-TE policy Active" || fail "SR-TE policy not Active"
echo "$POL" | grep -q "via-gre" && pass "preferred candidate via-gre present" || fail "via-gre missing"
echo "$POL" | grep -q "via-eth" && pass "backup candidate via-eth present" || fail "via-eth missing"

BSID=$(ssh -T station1 'sudo vtysh -c "show mpls table 40001"' 2>/dev/null || true)
echo "$BSID" | tee "$EVID/bsid_preferred.txt"
echo "$BSID" | grep -q "gre-te-core" && pass "BSID 40001 nexthop gre-te-core" || fail "BSID not on gre-te-core"

# 3) Force backup: remove preferred candidate-path
ssh -T station1 'sudo vtysh -c "configure" -c "segment-routing" -c "traffic-eng" \
  -c "policy color 1 endpoint 10.1.2.1" \
  -c "no candidate-path preference 100" -c "exit" -c "end"' >/dev/null
sleep 2
POLB=$(ssh -T station1 'sudo vtysh -c "show sr-te policy detail"' 2>/dev/null || true)
echo "$POLB" | tee "$EVID/policy_backup.txt"
BSIDB=$(ssh -T station1 'sudo vtysh -c "show mpls table 40001"' 2>/dev/null || true)
echo "$BSIDB" | tee "$EVID/bsid_backup.txt"
echo "$POLB" | grep -q "via-eth" && echo "$POLB" | grep -q "Status: Active" \
  && pass "backup via-eth Active after preferred removed" \
  || fail "backup path did not activate"
echo "$BSIDB" | grep -q "eth0" && pass "BSID 40001 nexthop eth0 on backup" || fail "BSID not on eth0 after failover"

# 4) Restore preferred (trap also restores)
restore
trap - EXIT
sleep 2
POLR=$(ssh -T station1 'sudo vtysh -c "show sr-te policy detail"' 2>/dev/null || true)
echo "$POLR" | tee "$EVID/policy_restored.txt"
BSR=$(ssh -T station1 'sudo vtysh -c "show mpls table 40001"' 2>/dev/null || true)
echo "$BSR" | tee "$EVID/bsid_restored.txt"
echo "$POLR" | grep -q "via-gre" && echo "$BSR" | grep -q "gre-te-core" \
  && pass "preferred restored to gre-te-core" \
  || fail "preferred restore failed"

# 5) VPN still healthy
PING=$(ssh -T station1 'sudo ip netns exec ce-a ping -c 2 -W 2 10.100.2.1' 2>&1 || true)
echo "$PING" | tee "$EVID/vpn_ping.txt"
echo "$PING" | grep -q "1 received\|2 received" && pass "CE ping SAC via VPN" || fail "CE ping SAC failed"

{
  echo "pass=$PASS fail=$FAIL"
  echo "evidence=$EVID"
} | tee -a "$EVID/summary.txt"

echo "=== TE verify done: $PASS pass / $FAIL fail ==="
[[ "$FAIL" -eq 0 ]]
