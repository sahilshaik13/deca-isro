#!/bin/bash
echo -e "\n=========================================="
echo "      DECA NETWORK MASTER DIAGNOSTIC      "
echo "=========================================="

# Prompt securely for the station password once
echo -n "Enter the sudo password for the stations: "
read -s PASSWORD
echo ""

echo -e "\n[1/8] Checking Layer 3 Reachability..."
for H in 10 20 30; do 
    ping -c 1 -W 1 192.168.50.$H &> /dev/null && echo "  Station $(($H/10)) (192.168.50.$H): UP" || echo "  Station $(($H/10)): DOWN"
done

echo -e "\n[2/8] Checking NTP Microsecond Sync..."
for H in station1 station2 station3; do 
    echo -n "  $H: "
    ssh -q $H 'chronyc tracking | grep "System time"' | awk '{print $4, $5, $6, $7}'
done

echo -e "\n[3/8] Checking OSPF Adjacencies..."
echo "$PASSWORD" | ssh -q station1 'sudo -S vtysh -c "show ip ospf neighbor"' 2>/dev/null | grep "Full" | awk '{print "  Neighbor " $1 " is " $3}'

echo -e "\n[4/8] Checking BGP VPNv4 Sessions..."
echo "$PASSWORD" | ssh -q station1 'sudo -S vtysh -c "show ip bgp summary"' 2>/dev/null | grep "10.1.3.1" | awk '{print "  BGP Peer " $1 " - Uptime: " $9 " - State: " $10}'

echo -e "\n[5/8] Checking MPLS Label Table (LDP)..."
echo "$PASSWORD" | ssh -q station1 'sudo -S vtysh -c "show mpls table"' 2>/dev/null | grep "LDP" > /dev/null && echo "  LDP Labels: ACTIVE & POPULATED" || echo "  LDP Labels: MISSING"

echo -e "\n[6/8] Checking IPSec SD-WAN Overlay..."
echo "$PASSWORD" | ssh -q station1 'sudo -S ipsec status' 2>/dev/null | grep "ESTABLISHED" | sed 's/^/  /'

echo -e "\n[7/8] Checking CE-A to CE-B VPN Data Plane (Ping over MPLS)..."
echo "$PASSWORD" | ssh -q station1 'sudo -S ip netns exec ce-a ping -c 2 10.100.2.1' 2>/dev/null | grep "time=" | awk '{print "  VPN Path " $7, $8}'

echo -e "\n[8/8] Checking Telemetry / Prometheus Endpoints..."
HEALTHY_TARGETS=$(curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"up"' | wc -l)
echo "  Active Telegraf/pmacct endpoints scraped: $HEALTHY_TARGETS / 3"

echo -e "\n=========================================="
echo "           DIAGNOSTIC COMPLETE            "
echo "==========================================\n"
