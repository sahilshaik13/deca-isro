#!/usr/bin/env bash
# Keep GNS3 DECA nodes up while efficiency packs run (prevents loss=0 / refuse inject).
set -euo pipefail
PROJ=78f1223e-f45b-4f61-b131-8e103a8eaebb
LOG=/home/brain/deca-isro/data/deca/predictive/protocol_gns3/eff_pack_gns3_20260804T094436Z/logs/gns3_keepalive.log
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== keepalive start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
while true; do
  # stop when neither pack is running
  if ! pgrep -f 'run_efficiency_pack.sh' >/dev/null 2>&1 && \
     ! pgrep -f 'redo_eff_pack_best.sh' >/dev/null 2>&1; then
    echo "no packs — exit $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
  fi
  curl -sf -m5 -X POST "http://127.0.0.1:3080/v2/projects/$PROJ/open" >/dev/null || true
  if ! docker ps --format '{{.Names}}' | grep -qE 'GNS3\.PE1\.'; then
    echo "$(date -u +%H:%M:%SZ) PE1 down — restarting nodes"
    python3 - <<'PY' || true
import json, urllib.request
PROJ="78f1223e-f45b-4f61-b131-8e103a8eaebb"
base=f"http://127.0.0.1:3080/v2/projects/{PROJ}"
try:
    urllib.request.urlopen(urllib.request.Request(base+"/open", method="POST", data=b""), timeout=30)
except Exception:
    pass
nodes=json.load(urllib.request.urlopen(base+"/nodes"))
for n in nodes:
    if n["name"].startswith(("PE","CORE","CE-","IPERF")):
        try:
            urllib.request.urlopen(urllib.request.Request(base+f"/nodes/{n['node_id']}/start", method="POST", data=b""), timeout=60)
        except Exception:
            pass
print("restart attempted")
PY
  else
    echo "$(date -u +%H:%M:%SZ) PE1 ok"
  fi
  sleep 60
done
