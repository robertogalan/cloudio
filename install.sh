#!/bin/bash
# Cloudio installer for Linux Mint
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing Cloudio..."

# Install system dependencies
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 \
    openssh-client \
    sshpass

# Make main script executable
chmod +x "$SCRIPT_DIR/cloudio.py"

# Lock down config file permissions if it exists (contains credentials)
if [ -f "$SCRIPT_DIR/config.json" ]; then
    chmod 600 "$SCRIPT_DIR/config.json"
fi

# Set up autostart
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/cloudio.desktop <<EOF
[Desktop Entry]
Name=Cloudio
Comment=Cloud file upload tray app
Exec=python3 ${SCRIPT_DIR}/cloudio.py
Icon=${SCRIPT_DIR}/assets/cloud.svg
Type=Application
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

echo ""
echo "Cloudio installed!"
echo "  Configure:    cp ${SCRIPT_DIR}/config.example.json ${SCRIPT_DIR}/config.json"
echo "                chmod 600 ${SCRIPT_DIR}/config.json   # keep credentials private"
echo "                \$EDITOR ${SCRIPT_DIR}/config.json"
echo "  Start now:    python3 ${SCRIPT_DIR}/cloudio.py"
echo "  Auto-starts on login."
