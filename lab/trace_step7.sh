#!/bin/bash
echo "--- TRACING TRAFFIC FROM CE-A ---"

# 1. Start a tcpdump in the background inside the namespace
# We look for ICMP traffic going to the remote IP
echo "Starting capture on veth-cea-pe (CE-A to PE)..."
ssh -t station1 'sudo ip netns exec ce-a timeout 10 tcpdump -ni veth-cea-pe icmp' &
PID=$!

sleep 2

# 2. Trigger the ping
echo "Triggering ping to 10.100.2.1..."
ssh -t station1 'sudo ip netns exec ce-a ping -c 3 10.100.2.1'

sleep 2
kill $PID 2>/dev/null
echo "--- Capture Complete ---"
