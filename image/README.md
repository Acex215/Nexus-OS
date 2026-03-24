# NEXUS OS Image Builder

Build a flashable Raspberry Pi image with the full NEXUS OS stack.

## Prerequisites

- Raspberry Pi 4, Pi 400, Pi 5, or Pi 500 (arm64)
- Docker installed on the build machine
- `/opt/nexus` codebase complete
- Dashboard built (`npm run build` in `/opt/nexus/dashboard`)

## Build

```bash
git clone https://github.com/Acex215/Nexus-OS.git
cd Nexus-OS/image
sudo ./build-nexus-os.sh
```

Build takes 30-90 minutes. Output: `pi-gen/deploy/NEXUS-OS-*.img.xz`

## Flash

Option A — Raspberry Pi Imager:
1. Open Raspberry Pi Imager
2. Choose OS → Use custom → select the `.img.xz` file
3. Choose storage → select your SD card
4. Write

Option B — Command line:
```bash
xzcat NEXUS-OS-1.0.img.xz | sudo dd of=/dev/sdX bs=4M status=progress
sync
```

## First Boot

1. Insert SD card and power on the Pi
2. First-boot setup runs automatically (generates wallet, inits blockchain + IPFS)
3. Desktop loads with the NEXUS first-boot GUI wizard
4. Choose node role (Host or Client) and configure network
5. Open Command Center from the desktop menu or taskbar

## What's Included

- **Blockchain**: Geth (Clique PoA) + smart contracts
- **Storage**: IPFS private cluster (Kubo)
- **AI Inference**: Local LLM support
- **Dashboard**: Web-based Command Center at `http://localhost:8766/dashboard/`
- **AI Assistant**: Chat interface at `http://localhost:8766/chat/`
- **CLI**: `nexus-cli` for terminal management
- **System Tray**: Status indicator with quick actions
- **Desktop**: LXDE with NEXUS branding, dark theme

## Pi Imager Custom Repository

To list NEXUS OS in Raspberry Pi Imager as a custom OS:

```
https://venture-verse.org/nexus-os-imager.json
```

Add this URL in Pi Imager under Settings → Custom OS.

## Default Credentials

- User: `nexus`
- Password: `nexus`
- SSH: enabled

Change the password on first login.
