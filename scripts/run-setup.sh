#!/bin/bash
#
# NEXUS OS - Run setup.d scripts in order
# This script is executed once during initial system setup
#
set -e

LOG_FILE="/var/log/nexus-setup.log"
SETUP_DIR="/opt/nexus/setup.d"

log() {
    echo "[NEXUS Setup $(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

error() {
    echo "[NEXUS ERROR $(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}" >&2
}

# Create log directory if needed
mkdir -p "$(dirname ${LOG_FILE})"

log "========================================="
log "NEXUS OS Initial Setup Starting"
log "========================================="

# Ensure directories exist
mkdir -p /opt/nexus/{blockchain,scripts,network,backup,logs,run,tmp}
mkdir -p /opt/nexus/blockchain/{data,keystore,config}
mkdir -p /var/lib/nexus
mkdir -p /etc/nexus

# Check if setup.d directory exists
if [ ! -d "${SETUP_DIR}" ]; then
    log "Setup directory not found: ${SETUP_DIR}"
    log "Looking for alternative locations..."

    # Try alternative locations
    for alt_dir in "/home/user/Nexus-OS/setup.d" "/root/Nexus-OS/setup.d"; do
        if [ -d "${alt_dir}" ]; then
            log "Found setup.d at ${alt_dir}, copying..."
            mkdir -p "${SETUP_DIR}"
            cp -r "${alt_dir}/"* "${SETUP_DIR}/"
            chmod +x "${SETUP_DIR}/"*
            break
        fi
    done
fi

if [ ! -d "${SETUP_DIR}" ]; then
    error "No setup.d directory found. Skipping setup."
    exit 0
fi

# Count scripts
SCRIPT_COUNT=$(find "${SETUP_DIR}" -type f -executable 2>/dev/null | wc -l)
log "Found ${SCRIPT_COUNT} setup scripts"

# Run scripts in sorted order (by filename)
COUNTER=0
for script in $(find "${SETUP_DIR}" -type f -executable 2>/dev/null | sort); do
    COUNTER=$((COUNTER + 1))
    SCRIPT_NAME=$(basename "${script}")

    log "[$COUNTER/$SCRIPT_COUNT] Running: ${SCRIPT_NAME}"

    if bash "${script}" >> "${LOG_FILE}" 2>&1; then
        log "[$COUNTER/$SCRIPT_COUNT] Completed: ${SCRIPT_NAME}"
    else
        EXIT_CODE=$?
        error "[$COUNTER/$SCRIPT_COUNT] Failed: ${SCRIPT_NAME} (exit code: ${EXIT_CODE})"
        # Continue with other scripts even if one fails
    fi
done

log "========================================="
log "NEXUS OS Initial Setup Complete"
log "========================================="
