#!/usr/bin/env bash
# ==============================================================================
# AdGuard Controller: Uninstaller
# Cleans up systemd user service, CLI tool, and desktop integration
# ==============================================================================

set -euo pipefail

echo "🗑️  Uninstalling AdGuard DNS Controller..."

# 1. Stop and disable service
if systemctl --user is-active adguard-controller.service >/dev/null 2>&1; then
  echo "• Stopping systemd user service..."
  systemctl --user stop adguard-controller.service || true
  systemctl --user disable adguard-controller.service || true
fi

# 2. Remove service unit
rm -f "${HOME}/.config/systemd/user/adguard-controller.service"
systemctl --user daemon-reload || true

# 3. Remove CLI client
rm -f "${HOME}/.local/bin/adguard-dns"

# 4. Remove desktop entries
rm -f "${HOME}/.local/share/applications/adguard-controller.desktop"
rm -f "${HOME}/Desktop/adguard-controller.desktop"

echo "✅ AdGuard Controller uninstalled."
echo "Note: Configuration directory was preserved at: ${HOME}/.config/adguard-controller/"
echo "      To remove it completely, run: rm -rf ~/.config/adguard-controller"
