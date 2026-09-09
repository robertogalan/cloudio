#!/bin/bash
# Cloudio installer for Linux (Debian/Ubuntu/Mint, Arch, Fedora)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing Cloudio..."

# --- System dependencies -----------------------------------------------------
# Package names differ per distro; detect the package manager and map them.
install_deps() {
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq \
            python3-gi \
            python3-gi-cairo \
            gir1.2-gtk-3.0 \
            gir1.2-ayatanaappindicator3-0.1 \
            openssh-client \
            sshpass
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm \
            python-gobject \
            python-cairo \
            gtk3 \
            libayatana-appindicator \
            openssh \
            sshpass
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y \
            python3-gobject \
            gtk3 \
            libayatana-appindicator-gtk3 \
            openssh-clients \
            sshpass
    else
        echo "No supported package manager found (apt-get, pacman, dnf)."
        echo "Install these yourself, then re-run:"
        echo "  Python GTK3 bindings, GTK3, libayatana-appindicator, ssh/scp, sshpass"
        exit 1
    fi
}

install_deps

# Make the entry points executable
chmod +x "$SCRIPT_DIR/cloudio.py" "$SCRIPT_DIR/bin/cloudio"

# --- CLI on PATH -------------------------------------------------------------
# Symlinked rather than copied so `git pull` updates the command too.
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
ln -sfn "$SCRIPT_DIR/bin/cloudio" "$BIN_DIR/cloudio"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Note: $BIN_DIR is not on your PATH; add it to use 'cloudio' directly." ;;
esac

# Lock down config file permissions if it exists (contains credentials)
if [ -f "$SCRIPT_DIR/config.json" ]; then
    chmod 600 "$SCRIPT_DIR/config.json"
fi

# --- Autostart ---------------------------------------------------------------
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
echo "  Upload:       cloudio file.png"
echo "  Start tray:   cloudio --tray"

# Hyprland ignores XDG autostart; it needs an entry in its own config.
if [ "$XDG_CURRENT_DESKTOP" = "Hyprland" ]; then
    echo ""
    echo "  Hyprland does not read ~/.config/autostart. Add this to"
    echo "  ~/.config/hypr/autostart.lua instead:"
    echo "    o.launch_on_start(\"python3 ${SCRIPT_DIR}/cloudio.py\")"
else
    echo "  Auto-starts on login."
fi
