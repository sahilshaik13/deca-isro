#!/bin/bash
echo "--- STEP 7 DEEP DIAGNOSTIC: CE-A to CE-B Data Plane ---"

# 1. Verify Namespaces Exist
echo -n "[1/4] Checking Namespaces: "
ssh -q station1 'ip netns list' | grep -q "ce-a" && echo -n "CE-A (OK) " || echo -n "CE-A (MISSING) "
ssh -q station2 'ip netns list' | grep -q "ce-b" && echo "CE-B (OK)" || echo "CE-B (MISSING)"

# 2. Check Interface status inside the namespaces
echo -n "[2/4] Checking veth interfaces: "
ssh -q station1 'sudo ip netns exec ce-a ip link show veth-cea-pe' &>/dev/null && echo -n "CE-A Link (UP) " || echo -n "CE-A Link (DOWN) "
ssh -q station2 'sudo ip netns exec ce-b ip link show veth-ceb-pe' &>/dev/null && echo "CE-B Link (UP)"

# 3. Check if Routes exist in the VRF
echo -n "[3/4] Checking VRF Routing (Station 1): "
ssh -q station1 'sudo ip route show vrf vrf-mission | grep "10.10.1.0"' &>/dev/null && echo "Route Exists (OK)" || echo "Route MISSING (FAIL)"

# 4. Execute Detailed Ping
echo -e "[4/4] Executing ICMP Data Plane Probe..."
ssh -t station1 'sudo ip netns exec ce-a ping -c 3 10.100.2.1'

echo "--- Diagnostic Complete ---"
