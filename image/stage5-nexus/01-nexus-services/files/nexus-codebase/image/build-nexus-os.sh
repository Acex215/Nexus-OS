#!/bin/bash
# Build NEXUS OS image using pi-gen
#
# Prerequisites:
# - Docker installed (pi-gen runs in Docker)
# - /opt/nexus codebase complete
# - Dashboard built (npm run build in /opt/nexus/dashboard)
#
# Output: /opt/nexus/image/pi-gen/deploy/NEXUS-OS-*.img.xz
#
# WARNING: This takes 30-90 minutes depending on hardware.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen"

echo "═══════════════════════════════════════════════════════"
echo "  NEXUS OS Image Builder"
echo "  Building from: ${PIGEN_DIR}"
echo "═══════════════════════════════════════════════════════"

# Ensure dashboard is built
if [ ! -f /opt/nexus/dashboard/dist/index.html ]; then
  echo "Building dashboard..."
  cd /opt/nexus/dashboard && npm run build
fi

# Copy NEXUS files to pi-gen stage5 for inclusion in image
echo "Copying NEXUS codebase to pi-gen stage5..."
STAGE5_FILES="${PIGEN_DIR}/stage5/01-nexus-services/files"
mkdir -p "${STAGE5_FILES}/nexus-codebase"
rsync -a --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
  /opt/nexus/ "${STAGE5_FILES}/nexus-codebase/"

# Build with Docker
cd "${PIGEN_DIR}"
echo "Starting pi-gen build (this will take a while)..."
./build-docker.sh

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Build complete!"
echo "  Image: ${PIGEN_DIR}/deploy/"
ls -lh "${PIGEN_DIR}/deploy/"*.img* 2>/dev/null
echo ""
echo "  Flash with: rpi-imager"
echo "  Or: dd if=NEXUS-OS-*.img of=/dev/sdX bs=4M"
echo "═══════════════════════════════════════════════════════"
