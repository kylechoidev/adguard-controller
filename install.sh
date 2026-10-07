#!/usr/bin/env bash
# ==============================================================================
# AdGuard Controller: One-Click Installer for Linux
# Sets up systemd user service, CLI tool, and desktop integration
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/adguard-controller"
SERVICE_DIR="${HOME}/.config/systemd/user"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons"

echo "🛡️  Installing AdGuard DNS Controller..."
echo "──────────────────────────────────────────────"

# 1. Dependency Checks
echo "[1/6] Checking dependencies..."
for cmd in python3 curl systemctl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ Error: Required tool '$cmd' is not installed." >&2
    exit 1
  fi
done

if ! command -v dnscrypt-proxy >/dev/null 2>&1; then
  echo "⚠️  dnscrypt-proxy is not installed."
  echo "   To install on Ubuntu/Debian/Mint, run: sudo apt install -y dnscrypt-proxy"
fi

# 2. Config Directory
echo "[2/6] Setting up configuration..."
mkdir -p "$CONFIG_DIR"
if [ ! -f "${CONFIG_DIR}/config.json" ]; then
  if [ -f "${SCRIPT_DIR}/config.example.json" ]; then
    cp "${SCRIPT_DIR}/config.example.json" "${CONFIG_DIR}/config.json"
    echo "   Created default config at: ${CONFIG_DIR}/config.json"
  fi
else
  echo "   Preserving existing config at: ${CONFIG_DIR}/config.json"
fi

# 3. CLI Client
echo "[3/6] Installing CLI tool..."
mkdir -p "$BIN_DIR"
cp "${SCRIPT_DIR}/bin/adguard-dns" "${BIN_DIR}/adguard-dns"
chmod +x "${BIN_DIR}/adguard-dns"

# 4. Desktop Integration & Icon
echo "[4/6] Installing desktop shortcuts..."
mkdir -p "$ICON_DIR" "$APP_DIR"
if [ -f "${SCRIPT_DIR}/static/adguard.png" ]; then
  cp "${SCRIPT_DIR}/static/adguard.png" "${ICON_DIR}/adguard.png"
fi

# Generate desktop file pointing to this installation
cat > "${APP_DIR}/adguard-controller.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=AdGuard Controller
Comment=Gentle Laptop DNS Controller for VPS AdGuard Blocker
Exec=chromium --app=http://127.0.0.1:5350 --class=AdGuardController --name=AdGuardController --window-size=720,620 --no-first-run --no-default-browser-check
Icon=adguard
Terminal=false
Categories=Network;System;Security;Settings;
StartupNotify=true
StartupWMClass=127.0.0.1.AdGuardController
EOF
chmod +x "${APP_DIR}/adguard-controller.desktop"

# 5. Systemd User Service
echo "[5/6] Registering systemd user service..."
mkdir -p "$SERVICE_DIR"
cat > "${SERVICE_DIR}/adguard-controller.service" << EOF
[Unit]
Description=AdGuard Home Laptop DNS Controller
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${SCRIPT_DIR}/backend/controller.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable adguard-controller.service
systemctl --user restart adguard-controller.service

# 6. Verification
echo "[6/6] Verifying local daemon..."
sleep 2
if systemctl --user is-active adguard-controller.service >/dev/null 2>&1; then
  echo "✅ AdGuard Controller is running successfully!"
else
  echo "⚠️ Service did not start cleanly. Check logs with: journalctl --user -u adguard-controller -n 20"
fi

echo "──────────────────────────────────────────────"
echo "🎉 Installation Complete!"
echo "• Web App:   http://127.0.0.1:5350"
echo "• CLI Tool:  adguard-dns [status|toggle|enable|disable|test]"
echo "• Settings:  ${CONFIG_DIR}/config.json"
