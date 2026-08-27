#!/usr/bin/env bash
# Install GNS3 (server + GUI) into a venv on the external drive — not on root.
set -euo pipefail

if [[ -n "${DECA_GNS3_ROOT:-}" ]]; then
  GNS3_ROOT="$DECA_GNS3_ROOT"
else
  GNS3_ROOT="/media/brain/Shaik's/gns3"
fi

DRIVE="$(dirname "$GNS3_ROOT")"
[[ -d "$DRIVE" ]] || { echo "ERROR: drive not mounted: $DRIVE" >&2; exit 1; }

bash "$(dirname "$0")/ensure_storage.sh"

VENV="$GNS3_ROOT/venv"
CONF_DIR="$GNS3_ROOT/configs"
CONF="$CONF_DIR/gns3_server.conf"
PIP_CACHE="$GNS3_ROOT/.pip-cache"
export PIP_CACHE_DIR="$PIP_CACHE"
mkdir -p "$PIP_CACHE"

PYTHON="${DECA_GNS3_PYTHON:-python3}"
echo "==> Creating venv at $VENV"
"$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip setuptools wheel

# Pin a known-good 2.2.x pair for Ubuntu 22.04 (PyQt6 via pip).
GNS3_VER="${DECA_GNS3_VERSION:-2.2.61}"
echo "==> Installing gns3-server/gui==$GNS3_VER + PyQt5 (this takes a few minutes)"
python -m pip install "PyQt5" "sip" "gns3-server==${GNS3_VER}" "gns3-gui==${GNS3_VER}"

# Server config — all heavy paths on external drive
cat > "$CONF" <<EOF
[Server]
host = 127.0.0.1
port = 3080
local = True
images_path = $GNS3_ROOT/images
projects_path = $GNS3_ROOT/projects
appliances_path = $GNS3_ROOT/appliances
symbols_path = $GNS3_ROOT/symbols
configs_path = $GNS3_ROOT/configs
report_errors = True
auth = False

[Qemu]
enable_kvm = True
require_kvm = False
EOF

# GUI prefs hint (operator may also set Edit → Preferences)
cat > "$CONF_DIR/gns3_gui.ini.snippet" <<EOF
# Point GNS3 GUI local server at:
#   Host: 127.0.0.1  Port: 3080
#   Config: $CONF
# Or launch via: lab/gns3/start_gns3.sh
EOF

WRAPPER="$GNS3_ROOT/bin"
mkdir -p "$WRAPPER"
cat > "$WRAPPER/gns3-server" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/gns3server" --config "$CONF" "\$@"
EOF
cat > "$WRAPPER/gns3" <<EOF
#!/usr/bin/env bash
# Prefer local server already configured via $CONF
export PATH="$VENV/bin:\$PATH"
exec "$VENV/bin/gns3" "\$@"
EOF
chmod +x "$WRAPPER/gns3-server" "$WRAPPER/gns3"

# Symlink helpers into repo lab/gns3 for convenience (thin)
REPO_BIN="$(cd "$(dirname "$0")" && pwd)"
ln -sfn "$WRAPPER/gns3-server" "$REPO_BIN/gns3-server"
ln -sfn "$WRAPPER/gns3" "$REPO_BIN/gns3"

echo
echo "OK GNS3 $GNS3_VER installed under $GNS3_ROOT"
echo "   server wrapper: $WRAPPER/gns3-server"
echo "   gui wrapper:    $WRAPPER/gns3"
echo "   config:         $CONF"
"$VENV/bin/gns3server" --version || true
"$VENV/bin/gns3" --version || true
echo
echo "Next: bash lab/gns3/start_gns3.sh   # starts server (GUI needs DISPLAY)"
