#!/bin/bash
while true; do
    # 1. Clean the slate: Kill stuck servers and start a fresh one on station2
    ssh -T station2 'sudo pkill iperf3; sudo ip netns exec ce-b iperf3 -s -D'
    sleep 2
    
    # 2. Blast data from station1 for 60 seconds
    ssh -T station1 'sudo ip netns exec ce-a iperf3 -c 10.100.2.1 -t 60 -M 1300'
    
    # 3. Breathe and repeat
    sleep 5
done
