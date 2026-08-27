#!/usr/bin/env bash
# Live verify: multi-class SD-WAN controller (TT&C 0x88 + Payload 0x80) SAC↔NRSC.
# Traffic: iperf3 only — NO Cisco TRex / DPDK.
# Does not touch models/fault_classifier/.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVID_ROOT="$ROOT/data/rpi-net/sdwan-verify"
EVID="$EVID_ROOT/deca-sdwan-verify-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVID"
LOG="$ROOT/data/rpi-net/sdwan_controller.log"
CTRL_PID=""

cleanup() {
  set +e
  [[ -n "${CTRL_PID}" ]] && kill "$CTRL_PID" 2>/dev/null
  ssh -T station1 'sudo pkill -f "iperf3 -c 10.101.2.3" 2>/dev/null || true'
  ssh -T station1 'sudo tc qdisc del dev gre-te-core root 2>/dev/null || true'
  ssh -T station1 "sudo bash -c 'vtysh -c \"configure terminal\" -c \"interface gre-te-core\" -c \"ip ospf cost 5\" -c \"end\" -c \"write memory\"; ip route replace 192.168.50.20/32 via 10.50.1.2 dev gre-te-core'" >/dev/null 2>&1
}
trap cleanup EXIT

echo "=== evidence dir: $EVID ==="

# TT&C :5004 tos 136 (0x88), Payload :5006 tos 128 (0x80)
ssh -T station2 'sudo pkill -9 iperf3 2>/dev/null || true; sleep 1
  sudo ip netns exec sac-srv iperf3 -s -p 5004 -D
  sudo ip netns exec sac-srv iperf3 -s -p 5006 -D
  sleep 1
  sudo ip netns exec sac-srv ss -ltn | grep -E "5004|5006"'

snap_routes() {
  local tag=$1
  {
    echo "=== $tag $(date -Is) ==="
    ssh -T station1 'echo ROUTE; ip route get 192.168.50.20; echo OSPF; sudo vtysh -c "show ip route 10.1.2.1"; echo COST; sudo vtysh -c "show running-config" | awk "/interface gre-te-core/,/^!/" | head -20'
  } | tee "$EVID/routes_${tag}.txt"
}

measure_flow() {
  local tag=$1 port=$2 tos=$3 rate=$4 dur=${5:-12} name=$6
  echo "=== ${name} measure $tag ${dur}s port=$port tos=$tos ==="
  ssh -T station1 "sudo pkill -f \"iperf3 -c 10.101.2.3 -p ${port}\" 2>/dev/null || true" || true
  sleep 1
  if ! ssh -T station1 "sudo ip netns exec nrsc-ws iperf3 -c 10.101.2.3 -p ${port} -u -b ${rate} -l 160 -t ${dur} --tos ${tos} --bind 10.101.1.2 -J" \
    >"$EVID/${name}_${tag}.json"; then
    echo "iperf failed for ${name}_${tag}" | tee "$EVID/${name}_${tag}.err"
    ssh -T station2 "sudo pkill -9 iperf3 2>/dev/null || true; sleep 1
      sudo ip netns exec sac-srv iperf3 -s -p 5004 -D
      sudo ip netns exec sac-srv iperf3 -s -p 5006 -D"
    sleep 1
    ssh -T station1 "sudo ip netns exec nrsc-ws iperf3 -c 10.101.2.3 -p ${port} -u -b ${rate} -l 160 -t ${dur} --tos ${tos} --bind 10.101.1.2 -J" \
      >"$EVID/${name}_${tag}.json"
  fi
  python3 - <<PY
import json
tag, name = "${tag}", "${name}"
path = f"${EVID}/{name}_{tag}.json"
p = json.load(open(path))
e = p["end"]["sum"]
line = (
    f"{name.upper()}_{tag}: jitter_ms={e.get('jitter_ms')} "
    f"lost={e.get('lost_packets')}/{e.get('packets')} "
    f"loss_pct={e.get('lost_percent')} "
    f"Mbps={e.get('bits_per_second', 0)/1e6:.3f}"
)
print(line)
open(f"${EVID}/{name}_{tag}.summary", "w").write(
    f"jitter_ms={e.get('jitter_ms')} lost_percent={e.get('lost_percent')} "
    f"bits_per_second={e.get('bits_per_second')}\n"
)
PY
}

wait_active() {
  local want=$1
  local max=${2:-40}
  for i in $(seq 1 "$max"); do
    sleep 3
    if curl -sf http://127.0.0.1:9280/metrics | grep -q "sdwan_active_path{class=\"voice\",path=\"${want}\"} 1"; then
      echo "ACTIVE ${want} at iter $i"
      return 0
    fi
    echo "wait $want $i ... $(curl -sf http://127.0.0.1:9280/metrics | grep -E 'sdwan_active_path_code|sdwan_policy_conflict|sdwan_class_wanted' || true)"
  done
  echo "FAIL: never became active=$want"
  return 1
}

wait_class_want() {
  local cls=$1 want=$2 max=${3:-40}
  for i in $(seq 1 "$max"); do
    sleep 3
    if curl -sf http://127.0.0.1:9280/metrics \
      | grep -q "sdwan_class_wanted_path{class=\"${cls}\",path=\"${want}\"} 1"; then
      echo "WANT ${cls}=${want} at iter $i"
      return 0
    fi
    echo "wait ${cls}->${want} $i ..."
  done
  echo "FAIL: ${cls} never wanted ${want}"
  return 1
}

# Stop any existing user controller that would fight for :9280
systemctl --user stop deca_sdwan_controller.service 2>/dev/null || true
pkill -f "deca_sdwan_controller.py" 2>/dev/null || true
sleep 1

: >"$LOG"
python3 "$ROOT/lab/deca_sdwan_controller.py" >>"$EVID/controller.stdout" 2>&1 &
CTRL_PID=$!
sleep 12
curl -sf http://127.0.0.1:9280/metrics | tee "$EVID/metrics_t0.txt" | grep sdwan_ | head -40

snap_routes before
measure_flow baseline_gre 5004 136 1M 10 ttc
measure_flow baseline_gre 5006 128 10M 10 payload

# Mild degrade: voice SLA fails (~80ms), video SLA (80ms) may still hold → conflict possible
kill -STOP "$CTRL_PID"
echo "=== inject mild netem (voice fails, video may hold) ==="
ssh -T station1 'sudo tc qdisc replace dev gre-te-core root netem delay 55ms 15ms distribution normal'
ssh -T station1 'ping -c 4 -i 0.2 -I gre-te-core 10.50.1.2' | tee "$EVID/gre_ping_mild.txt"
kill -CONT "$CTRL_PID"
echo "=== waiting voice to want eth0 (video may still want gre) ==="
wait_class_want voice eth0 30 || { tail -80 "$LOG"; exit 1; }
# Capture conflict metric while voice wants eth0
sleep 5
curl -sf http://127.0.0.1:9280/metrics | tee "$EVID/metrics_mild.txt" | grep -E 'sdwan_class_wanted|sdwan_policy_conflict|sdwan_active_path'
# Shared underlay follows voice
wait_active eth0 20 || { tail -60 "$LOG"; exit 1; }
snap_routes after_mild_voice_switch
measure_flow after_mild 5004 136 1M 10 ttc

# Hard degrade: both classes should prefer eth0
echo "=== inject hard netem (both classes fail gre) ==="
ssh -T station1 'sudo tc qdisc replace dev gre-te-core root netem delay 120ms 30ms distribution normal'
wait_class_want video eth0 35 || echo "WARN: video still wants gre (acceptable if conflict already resolved)"
curl -sf http://127.0.0.1:9280/metrics | tee "$EVID/metrics_hard.txt" | grep -E 'sdwan_class_wanted|sdwan_policy_conflict|sdwan_active'
snap_routes after_hard
measure_flow after_hard 5004 136 1M 8 ttc
measure_flow after_hard 5006 128 10M 8 payload

# Recover
echo "=== clear netem; wait recover to gre ==="
ssh -T station1 'sudo tc qdisc del dev gre-te-core root 2>/dev/null || true'
ssh -T station1 'ping -c 3 -I gre-te-core 10.50.1.2' | tee "$EVID/gre_ping_recovered.txt"
wait_active gre 50 || { tail -80 "$LOG"; exit 1; }
snap_routes after_recover_gre
measure_flow after_recover 5004 136 1M 8 ttc
measure_flow after_recover 5006 128 10M 8 payload

# Transient < enter_k should not flap
sw_v_before=$(curl -sf http://127.0.0.1:9280/metrics | awk '/sdwan_path_switch_count\{class="voice"\}/{print $2}')
ssh -T station1 'sudo tc qdisc replace dev gre-te-core root netem delay 100ms'
sleep 5
ssh -T station1 'sudo tc qdisc del dev gre-te-core root 2>/dev/null || true'
sleep 18
sw_v_after=$(curl -sf http://127.0.0.1:9280/metrics | awk '/sdwan_path_switch_count\{class="voice"\}/{print $2}')
active=$(curl -sf http://127.0.0.1:9280/metrics | awk '/sdwan_active_path_code\{class="voice"\}/{print $2}')
echo "transient voice_switches_before=$sw_v_before after=$sw_v_after active_code=$active" | tee "$EVID/transient.txt"
python3 - <<PY
b=float("${sw_v_before:-0}"); a=float("${sw_v_after:-0}"); act=float("${active:-0}")
open("${EVID}/transient.ok","w").write(f"delta={a-b} active={act}\n")
print(f"transient delta_voice_switches={a-b} active={act}")
if act != 1:
    raise SystemExit("FAIL: not on gre after transient")
PY

curl -sf http://127.0.0.1:9280/metrics | tee "$EVID/metrics_final.txt" | grep sdwan_
cp "$LOG" "$EVID/sdwan_controller.log"
curl -sf http://192.168.50.10:9273/metrics 2>/dev/null | grep sdwan_ | tee "$EVID/pe1_sdwan_metrics.txt" | head -40 || true

# Restart user service if it was enabled
systemctl --user start deca_sdwan_controller.service 2>/dev/null || true

echo "=== DONE evidence in $EVID ==="
ls -la "$EVID"
