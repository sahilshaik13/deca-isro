#!/bin/bash
echo "--- DECA Topology Health Check ---"
echo "Waiting 30s for full convergence before diagnostics..."; sleep 30
for H in s1 s2 s3; do
  echo "[Checking $H]"
  ssh -T $H 'hostname; uptime; ip addr show eth0 | grep inet'
done

echo -e "\n--- Service Enablement Check ---"
ssh -T s1 'sudo systemctl is-enabled frr strongswan-starter chrony deca-ns.service'
ssh -T s2 'sudo systemctl is-enabled frr strongswan-starter chrony deca-ns.service'
ssh -T s3 'sudo systemctl is-enabled frr chrony'

echo -e "\n--- Duplicate Namespace Guard ---"
ssh -T s1 'sudo ip netns list'
ssh -T s2 'sudo ip netns list'

echo -e "\n--- OSPF Adjacency Check (Station 1) ---"
ssh -T s1 'sudo vtysh -c "show ip ospf neighbor"'

echo -e "\n--- MPLS Label Table (Station 1) ---"
ssh -T s1 'sudo vtysh -c "show mpls table"'

echo -e "\n--- IPSec Tunnel State (Station 1) ---"
ssh -T s1 'sudo ipsec status'

echo -e "\n--- VPN Reachability (CE-A to CE-B) ---"
ssh -T s1 'sudo ip netns exec ce-a ping -c 2 10.100.2.1 | grep "packets transmitted"'
