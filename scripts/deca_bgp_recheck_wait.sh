#!/usr/bin/env bash
# Wait for BGP+VRF re-check, verify gates, archive, print grade.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
RID="${1:-$(cat /tmp/deca_bgp_recheck_run_id 2>/dev/null)}"
[[ -n "$RID" ]] || { echo "usage: $0 <run_id>"; exit 1; }

echo "[recheck] waiting for ${RID}..."
for _ in $(seq 1 200); do
  [[ -f "data/rpi-net/live/${RID}/scorecard.json" ]] && break
  sleep 15
done
[[ -f "data/rpi-net/live/${RID}/scorecard.json" ]] || { echo "timeout"; exit 1; }

FEED="data/rpi-net/live/${RID}/operator_feed.log"
echo "[recheck] gates:"
grep -E 'cross-host echo|vrf origin-lock' "$FEED" | head -2

mkdir -p "data/rpi-net/blind-tests/${RID}"
cp -a "data/rpi-net/live/${RID}/." "data/rpi-net/blind-tests/${RID}/"

python3 scripts/deca_blind_scorecard.py --run-id "${RID}" --no-prom 2>&1 | tail -25

python3 - "$RID" <<'PY'
import json, sys
from pathlib import Path
rid = sys.argv[1]
sc = json.loads(Path(f"data/rpi-net/live/{rid}/scorecard.json").read_text())
s = sc.get("summary", {})
decls = [json.loads(l) for l in Path(f"data/rpi-net/live/{rid}/declarations.jsonl").read_text().splitlines() if l.strip()]
s1_vrf = [d for d in decls if d.get("host") == "station1" and d.get("event") == "confirmed_raise" and d.get("confirmed") == "vrf_leakage"]
vrf_held = sum(1 for d in decls if d.get("vrf_origin_suppressed"))
echo_held = sum(1 for d in decls if d.get("cross_host_echo_suppressed"))
spur = sc.get("spurious_false_alarms")
spur_n = len(spur) if isinstance(spur, list) else spur
print(f"\n[recheck] SUMMARY detect={s.get('detected')}/{s.get('circumstances_created')} "
      f"class_acc={s.get('class_accuracy')} spur={spur_n} "
      f"s1_vrf_confirms={len(s1_vrf)} vrf_held={vrf_held} echo_held={echo_held}")
for e in sc.get("events") or []:
    print(f"  {e.get('fault_type')} @{e.get('host')} det={e.get('detected')} pred={e.get('predicted_class')}")
Path("/tmp/deca_bgp_recheck_done").write_text(rid + "\n")
PY
