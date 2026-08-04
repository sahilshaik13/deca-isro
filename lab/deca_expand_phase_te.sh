#!/usr/bin/env bash
# Phase TE — OSPF-TE + pathd SR-TE (FRR-native traffic engineering constructs).
# Fulfills PS13-O1.2 without RSVP-TE (unavailable in FRR 10.6).
# Does NOT touch models/fault_classifier/.
set -euo pipefail

echo "=== Phase TE: OSPF-TE link-params + pathd SR-TE policies ==="

need() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -T "$1" 'true' 2>/dev/null \
    || { echo "FAIL: cannot SSH $1"; exit 1; }
}
need station1; need station2; need station3

# Ensure pathd enabled on all stations
for H in station1 station2 station3; do
  ssh -T "$H" 'sudo bash -s' <<'EOF'
set -euo pipefail
if grep -q '^pathd=yes' /etc/frr/daemons 2>/dev/null; then
  :
else
  sed -i 's/^pathd=.*/pathd=yes/' /etc/frr/daemons
  systemctl restart frr
  sleep 3
fi
EOF
done

echo "=== PE1 (station1): TE attrs + SR-TE pe1-to-pe2 ==="
ssh -T station1 'sudo vtysh' <<'VTY'
configure terminal
interface gre-te-core
 mpls enable
 link-params
  metric 5
  max-bw 1e+08
  max-rsv-bw 8e+07
  admin-grp 0x1
  neighbor 10.50.1.2 as 65001
 exit
exit
interface eth0
 link-params
  metric 50
  max-bw 1e+09
  max-rsv-bw 8e+08
  admin-grp 0x2
 exit
exit
router ospf
 mpls-te on
 mpls-te router-address 10.1.1.1
 mpls-te export
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing prefix 10.1.1.1/32 index 1 no-php-flag
exit
segment-routing
 traffic-eng
  mpls-te on
  mpls-te import ospfv2
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

echo "=== PE2 (station2): TE attrs + SR-TE pe2-to-pe1 ==="
ssh -T station2 'sudo vtysh' <<'VTY'
configure terminal
interface gre-te-core
 mpls enable
 link-params
  metric 5
  max-bw 1e+08
  max-rsv-bw 8e+07
  admin-grp 0x1
  neighbor 10.50.2.2 as 65001
 exit
exit
interface eth0
 link-params
  metric 50
  max-bw 1e+09
  max-rsv-bw 8e+08
  admin-grp 0x2
 exit
exit
router ospf
 mpls-te on
 mpls-te router-address 10.1.2.1
 mpls-te export
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing prefix 10.1.2.1/32 index 2 no-php-flag
exit
segment-routing
 traffic-eng
  mpls-te on
  mpls-te import ospfv2
  segment-list SL-GRE
   index 10 mpls label 16003
   index 20 mpls label 16001
  exit
  segment-list SL-ETH
   index 10 mpls label 15010
  exit
  policy color 1 endpoint 10.1.1.1
   name pe2-to-pe1-te
   binding-sid 40002
   candidate-path preference 100 name via-gre explicit segment-list SL-GRE
   candidate-path preference 50 name via-eth explicit segment-list SL-ETH
  exit
 exit
exit
end
write memory
VTY

echo "=== CORE (station3): TE attrs + OSPF-SR (no PE policy) ==="
ssh -T station3 'sudo vtysh' <<'VTY'
configure terminal
interface gre-te-pe1
 mpls enable
 link-params
  metric 5
  max-bw 1e+08
  max-rsv-bw 8e+07
  admin-grp 0x1
  neighbor 10.50.1.1 as 65001
 exit
exit
interface gre-te-pe2
 mpls enable
 link-params
  metric 5
  max-bw 1e+08
  max-rsv-bw 8e+07
  admin-grp 0x1
  neighbor 10.50.2.1 as 65001
 exit
exit
interface eth0
 link-params
  metric 50
  max-bw 1e+09
  max-rsv-bw 8e+08
  admin-grp 0x2
 exit
exit
router ospf
 mpls-te on
 mpls-te router-address 10.1.3.1
 mpls-te export
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing prefix 10.1.3.1/32 index 3 no-php-flag
exit
segment-routing
 traffic-eng
  mpls-te on
  mpls-te import ospfv2
 exit
exit
end
write memory
VTY

sleep 5
echo "=== Smoke: TED + SR-TE policies ==="
ssh -T station1 'sudo vtysh -c "show pathd ted database verbose" | tail -8; sudo vtysh -c "show sr-te policy detail"; sudo vtysh -c "show mpls table 40001"'
ssh -T station2 'sudo vtysh -c "show sr-te policy detail"; sudo vtysh -c "show mpls table 40002"'

echo "=== Phase TE done (OSPF-TE + SR-TE; not RSVP-TE) ==="
echo "Verify: bash lab/deca_te_verify.sh"
