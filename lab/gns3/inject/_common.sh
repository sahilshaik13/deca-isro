#!/usr/bin/env bash
# Shared helpers for GNS3 chaos — twin of Pi (iperf3 + NetEM + stress-ng + BGP soft-clear).
# NetEM must NOT wipe PE HTB: apply on mission underlay peer (CORE-N eth0) or GRE.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
if [[ -n "${DECA_GNS3_ROOT:-}" ]]; then
  GNS3_ROOT="$DECA_GNS3_ROOT"
else
  GNS3_ROOT="/media/brain/Shaik's/gns3"
fi
STATE="${DECA_GNS3_CHAOS_STATE:-$REPO_ROOT/lab/gns3/state/chaos_state.json}"
EXPORTER_PY="$REPO_ROOT/lab/gns3/exporters/gns3_path_exporter.py"
REQUIRE_LIVE="${DECA_REQUIRE_LIVE:-1}"
# Pi twin: soft-clear neighbor = CORE on PE1↔CORE-N (see traffic_control addressing)
BGP_NEIGHBOR="${DECA_GNS3_BGP_NEIGHBOR:-10.10.3.2}"

mkdir -p "$(dirname "$STATE")" "$REPO_ROOT/lab/gns3/state"

patch_state() {
  python3 - "$STATE" "$@" <<'PY'
import json, sys, time
path = sys.argv[1]
cur = {}
try:
    cur = json.loads(open(path).read())
except Exception:
    pass
for arg in sys.argv[2:]:
    if "=" not in arg:
        continue
    k, _, v = arg.partition("=")
    try:
        if v.replace(".", "", 1).isdigit() or (v[:1] == "-" and v[1:].replace(".", "", 1).isdigit()):
            cur[k] = float(v)
        else:
            cur[k] = v
    except Exception:
        cur[k] = v
cur["updated_unix"] = time.time()
open(path, "w").write(json.dumps(cur, indent=2) + "\n")
print(path)
PY
}

find_pe1_container() {
  docker ps --format '{{.ID}} {{.Names}}' 2>/dev/null | awk '/PE1|pe1/ {print $1; exit}'
}

find_core_n_container() {
  docker ps --format '{{.ID}} {{.Names}}' 2>/dev/null | awk '/CORE-N|core-n/ {print $1; exit}'
}

cname() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -F "GNS3.$1." | head -1
}

ensure_exporter() {
  if curl -sf -o /dev/null "http://127.0.0.1:9275/metrics" 2>/dev/null; then
    return 0
  fi
  nohup python3 "$EXPORTER_PY" >"$REPO_ROOT/lab/gns3/state/exporter.log" 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -sf -o /dev/null "http://127.0.0.1:9275/metrics" 2>/dev/null && return 0
    sleep 0.3
  done
  echo "WARN: gns3 exporter not reachable on :9275" >&2
}

require_pe1() {
  local cid
  cid="$(find_pe1_container || true)"
  if [[ -n "$cid" ]]; then
    echo "$cid"
    return 0
  fi
  if [[ "$REQUIRE_LIVE" == "1" ]]; then
    echo "ERROR: no running PE1 — refuse inject (set DECA_REQUIRE_LIVE=0 to override)" >&2
    return 1
  fi
  echo "WARN: no PE1" >&2
  return 0
}

# Resolve NetEM target like Pi gre-te-core: delay the mission underlay WITHOUT wiping PE HTB.
# Prefer: (1) GRE on PE1 if present and not HTB
#         (2) CORE-N eth0/eth1 WITHOUT HTB (P transit — must stay clear of HTB)
# Never: PE1 eth0 with HTB (QoS shaper).
netem_target() {
  local pe core gre ifc
  pe="$(find_pe1_container || true)"
  core="$(find_core_n_container || true)"
  if [[ -n "$pe" ]]; then
    gre="$(
      docker exec "$pe" sh -c \
        "ip -br link 2>/dev/null | awk '\$1 ~ /^(gre|gretap|tun)/ { gsub(/@.*/,\"\",\$1); print \$1; exit }'" \
        2>/dev/null || true
    )"
    if [[ -n "${gre:-}" ]]; then
      if ! docker exec "$pe" sh -c "tc qdisc show dev $gre 2>/dev/null | grep -q 'qdisc htb'"; then
        echo "$pe $gre"
        return 0
      fi
    fi
  fi
  if [[ -n "$core" ]]; then
    for ifc in eth0 eth1; do
      # Auto-clear mistaken HTB on P so NetEM can attach (edge QoS stays on PE)
      if docker exec "$core" sh -c "tc qdisc show dev $ifc 2>/dev/null | grep -q 'qdisc htb'"; then
        echo "WARN: stripping HTB from CORE $ifc (P must not shape; NetEM needs root)" >&2
        docker exec "$core" sh -c "tc qdisc del dev $ifc root 2>/dev/null || true" || true
      fi
      if docker exec "$core" sh -c "ip link show $ifc >/dev/null 2>&1"; then
        echo "$core $ifc"
        return 0
      fi
    done
  fi
  if [[ -n "$pe" ]]; then
    if ! docker exec "$pe" sh -c "tc qdisc show dev eth0 2>/dev/null | grep -q 'qdisc htb'"; then
      echo "$pe eth0"
      return 0
    fi
  fi
  return 1
}

apply_netem_pe1() {
  local spec=$1
  local cid dev
  if ! read -r cid dev < <(netem_target); then
    if [[ "$REQUIRE_LIVE" == "1" ]]; then
      echo "ERROR: no NetEM target (need PE1 GRE or CORE-N eth0)" >&2
      return 1
    fi
    echo "netem: no target — state-only"
    return 0
  fi
  if [[ "$spec" == "clear" ]]; then
    docker exec "$cid" sh -c "tc qdisc del dev $dev root 2>/dev/null || true" || true
    echo "netem cleared $cid:$dev"
    return 0
  fi
  # Refuse to clobber HTB root on PE (Pi keeps HTB on eth0, NetEM on gre/CORE)
  if docker exec "$cid" sh -c "tc qdisc show dev $dev 2>/dev/null | grep -q 'qdisc htb'"; then
    echo "ERROR: $cid:$dev has HTB — refusing NetEM root-replace (would wipe QoS)" >&2
    return 1
  fi
  docker exec "$cid" sh -c "tc qdisc replace dev $dev root netem $spec" || {
    echo "WARN: tc netem failed on $cid:$dev" >&2
    return 1
  }
  echo "netem $cid:$dev → $spec (PE HTB preserved)"
}
