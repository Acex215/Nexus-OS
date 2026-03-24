#!/bin/bash
# Runs on FIRST BOOT only

if [ ! -f /opt/nexus/config/node_identity.json ]; then
  echo "NEXUS OS First Boot — Generating device identity..."
  python3 /opt/nexus/scripts/first_boot_setup.py

  # Start node agent
  systemctl enable nexus-node-agent
  systemctl start nexus-node-agent
fi
