#!/usr/bin/env bash
# Emergency reclaim when ~50GB root fills with /tmp/GNS3.* Wireshark temps.
# Safe for a live Pi campaign — only touches GNS3 captures + /tmp.
set -euo pipefail

GNS3_ROOT="${DECA_GNS3_ROOT:-/media/brain/Shaik's/gns3}"
API="${GNS3_API:-http://127.0.0.1:3080/v2}"

echo "=== before ==="
df -h / | tail -1
du -sch /tmp/GNS3.* 2>/dev/null | tail -1 || echo "no /tmp/GNS3.*"

if curl -sf -o /dev/null "$API/version" 2>/dev/null; then
  python3 - <<'PY'
import json, urllib.request, urllib.error, os
api = os.environ.get("GNS3_API", "http://127.0.0.1:3080/v2")
projects = json.load(urllib.request.urlopen(f"{api}/projects"))
opened = [p for p in projects if p.get("status") == "opened"]
stopped = 0
for p in opened:
    pid = p["project_id"]
    links = json.load(urllib.request.urlopen(f"{api}/projects/{pid}/links"))
    for link in links:
        if not link.get("capturing"):
            continue
        lid = link["link_id"]
        req = urllib.request.Request(
            f"{api}/projects/{pid}/links/{lid}/stop_capture",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            stopped += 1
            print("stopped", link.get("capture_file_name") or lid[:8])
        except urllib.error.HTTPError as e:
            if e.code not in (404, 409):
                print("fail", lid[:8], e.code)
print(f"captures_stopped={stopped}")
PY
else
  echo "gns3-server not up — skip capture stop"
fi

# Truncate open FDs first (frees blocks even while GUI holds the file), then unlink.
for f in /tmp/GNS3.*; do
  [[ -e "$f" ]] || continue
  : >"$f" 2>/dev/null || true
done
rm -f /tmp/GNS3.* 2>/dev/null || true

# Optional: rotate huge project pcaps on external (does not free root, keeps drive tidy).
if [[ "${1:-}" == "--purge-project-pcaps" ]]; then
  CAP="$GNS3_ROOT/projects/DECA/project-files/captures"
  if [[ -d "$CAP" ]]; then
    echo "purging $CAP …"
    find "$CAP" -type f -name '*.pcap' -size +10M -print -delete
  fi
fi

echo "=== after ==="
df -h / | tail -1
du -sch /tmp/GNS3.* 2>/dev/null | tail -1 || echo "no /tmp/GNS3.*"
echo
echo "Tip: restart GUI via: bash lab/gns3/start_gns3.sh --gui"
echo "     (sets TMPDIR to $GNS3_ROOT/tmp so temps stay off root)"
echo "Optional sudo reclaim: sudo journalctl --vacuum-size=200M && sudo apt-get clean"
echo "Optional Docker move:  bash lab/gns3/migrate_docker_to_external.sh --apply"
