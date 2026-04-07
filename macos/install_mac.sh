#!/usr/bin/env bash
# Cloudio macOS installer
# Usage: bash install_mac.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_LABEL="com.cloudio.app"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_LABEL.plist"
CONFIG_DIR="$HOME/.config/cloudio"

# ── Checks ────────────────────────────────────────────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
    echo "❌  This installer is for macOS only."
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "❌  python3 not found."
    echo "    Install it via Homebrew:  brew install python"
    exit 1
fi

PY="$(command -v python3)"
echo "✓  Python: $($PY --version)"

# ── Python dependencies ───────────────────────────────────────────────────

echo ""
echo "Installing Python dependencies (pyobjc)…"
"$PY" -m pip install --quiet --upgrade pyobjc-core pyobjc-framework-Cocoa

echo "✓  pyobjc installed"

# ── Config ────────────────────────────────────────────────────────────────

mkdir -p "$CONFIG_DIR"

if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
    cp "$REPO_DIR/config.example.json" "$CONFIG_DIR/config.json"
    echo "✓  Created $CONFIG_DIR/config.json (edit this with your server details)"
    echo "   Or use the in-app Configure… menu after launch."
else
    echo "✓  Config already exists at $CONFIG_DIR/config.json"
fi

# ── LaunchAgent (autostart on login) ─────────────────────────────────────

mkdir -p "$LAUNCH_AGENTS_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$SCRIPT_DIR/cloudio_mac.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/cloudio.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/cloudio.log</string>
</dict>
</plist>
EOF

echo "✓  LaunchAgent installed at $PLIST_PATH"

# Load it immediately (unload first in case a previous version was loaded)
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Cloudio is running!  Look for the cloud icon ☁  "
echo "  in your menu bar.                               "
echo ""
echo "  Next steps:                                     "
echo "  1. Click the icon → Configure… to set up your  "
echo "     server details.                              "
echo "  2. Drag any file onto the icon to upload it.    "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
