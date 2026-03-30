#!/bin/bash
# Install NEXUS systemd services for behavioral collection + daily epoch
set -e

SYSTEMD_DIR="/opt/nexus/config/systemd"

echo "Installing NEXUS systemd services..."

sudo cp "$SYSTEMD_DIR/nexus-collector.service" /etc/systemd/system/
sudo cp "$SYSTEMD_DIR/nexus-epoch.service" /etc/systemd/system/
sudo cp "$SYSTEMD_DIR/nexus-epoch.timer" /etc/systemd/system/

sudo systemctl daemon-reload

echo ""
echo "Services installed. Enable with:"
echo "  sudo systemctl enable --now nexus-collector"
echo "  sudo systemctl enable --now nexus-epoch.timer"
echo ""
echo "Grant consent first (creates the consent gate file):"
echo "  touch /opt/nexus/config/behavioral_consent_active"
echo ""
echo "Check status:"
echo "  systemctl status nexus-collector"
echo "  systemctl list-timers nexus-epoch.timer"
echo "  journalctl -u nexus-collector -f"
