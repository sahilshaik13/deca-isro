#!/usr/bin/env bash
# Heal pathd crash-on-boot (FRR 10.6): traffic-eng policy block in frr.conf can
# abort pathd during vtysh_read. Strip TE from conf, restart pathd/frr, then
# re-apply via ensure_te / deca_expand_phase_te.sh.
#
# Usage (on a PE/CORE host as root):
#   bash lab/deca_pathd_boot_heal.sh
# From brain:
#   for H in station1 station2 station3; do scp lab/deca_pathd_boot_heal.sh $H:/tmp/; ssh $H 'sudo bash /tmp/deca_pathd_boot_heal.sh'; done
#   bash lab/deca_expand_phase_te.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root"; exit 1
fi

cp -a /etc/frr/frr.conf "/etc/frr/frr.conf.bak.pathdheal.$(date +%Y%m%d%H%M%S)"
python3 - <<'PY'
from pathlib import Path
p = Path("/etc/frr/frr.conf")
lines = p.read_text().splitlines(True)
out = []
i = 0
n = len(lines)
while i < n:
    line = lines[i]
    if line.rstrip("\n") == "segment-routing" and i + 1 < n and lines[i + 1].startswith(" traffic-eng"):
        i += 1
        while i < n:
            l = lines[i]
            if l.rstrip("\n") == "exit" and not l.startswith(" "):
                i += 1
                if i < n and lines[i].rstrip("\n") == "!":
                    out.append(lines[i]); i += 1
                break
            if l.rstrip("\n") == "!":
                out.append(l); i += 1
                break
            i += 1
        continue
    out.append(line)
    i += 1
p.write_text("".join(out))
print("stripped top-level segment-routing/traffic-eng from frr.conf")
PY

# Ensure pathd enabled
sed -i 's/^pathd=.*/pathd=yes/' /etc/frr/daemons
systemctl restart frr
sleep 4
vtysh -c "show daemon" || true
pgrep -a pathd || { echo "pathd still down"; journalctl -u frr -n 40 --no-pager; exit 1; }
echo "pathd up — next: re-apply TE with bash lab/deca_expand_phase_te.sh (from brain)"
