#!/usr/bin/env python3
"""NEXUS OS First-Boot Setup — generate device cryptographic identity.

Run once on a fresh NEXUS client node. Creates an Ethereum wallet,
saves the keystore, and attempts to register with MeshRegistry on-chain.

Usage:
    python3 /opt/nexus/scripts/first_boot_setup.py
"""
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
from pathlib import Path

KEYSTORE_DIR = Path("/opt/nexus/blockchain/keystore")
PASSWORD_FILE = Path("/opt/nexus/blockchain/password.txt")
CONFIG_DIR = Path("/opt/nexus/config")
IDENTITY_FILE = CONFIG_DIR / "node_identity.json"
PENDING_REG_FILE = CONFIG_DIR / "pending_registration.json"

GATEWAY_RPC = "http://10.0.20.3:8545"


# ── Step 1: Check if wallet already exists ───────────────────────────

def wallet_exists() -> bool:
    if not KEYSTORE_DIR.exists():
        return False
    keyfiles = [f for f in KEYSTORE_DIR.iterdir() if f.is_file() and f.name.startswith("UTC")]
    return len(keyfiles) > 0


# ── Step 2 & 3: Generate wallet and save keystore ───────────────────

def generate_wallet() -> dict:
    from eth_account import Account

    account = Account.create()
    password = secrets.token_urlsafe(32)

    # Encrypt and save keystore
    encrypted = Account.encrypt(account.key, password)

    KEYSTORE_DIR.mkdir(parents=True, exist_ok=True)

    # Keystore filename follows Geth convention
    import time
    ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    addr_hex = account.address.lower().replace("0x", "")
    keystore_path = KEYSTORE_DIR / f"UTC--{ts}.000000000Z--{addr_hex}"

    with open(keystore_path, "w") as f:
        json.dump(encrypted, f)
    os.chmod(keystore_path, 0o600)

    # Save password (chmod 600)
    with open(PASSWORD_FILE, "w") as f:
        f.write(password + "\n")
    os.chmod(PASSWORD_FILE, 0o600)

    return {
        "address": account.address,
        "private_key": account.key.hex(),
        "keystore_path": str(keystore_path),
    }


# ── Step 4: Display identity ────────────────────────────────────────

def display_identity(wallet_info: dict):
    print()
    print("=" * 51)
    print("  NEXUS OS -- Device Identity Generated")
    print("=" * 51)
    print(f"  Wallet Address: {wallet_info['address']}")
    print(f"  Private Key: {wallet_info['private_key']}")
    print()
    print("  WARNING: SAVE YOUR PRIVATE KEY NOW")
    print("  It will NOT be shown again.")
    print("  This key IS your device identity.")
    print("=" * 51)
    print()


# ── Auto-detect capabilities ────────────────────────────────────────

def detect_capabilities() -> dict:
    caps = {
        "hostname": socket.gethostname(),
        "arch": platform.machine(),
        "cpu_count": os.cpu_count() or 1,
        "memory_gb": 0,
        "storage_gb": 0,
        "ai_tops": 0,
        "has_wifi": False,
    }

    # Memory
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    caps["memory_gb"] = round(kb / (1024 * 1024))
                    break
    except Exception:
        pass

    # Root disk
    try:
        st = os.statvfs("/")
        caps["storage_gb"] = round(st.f_blocks * st.f_frsize / (1024 ** 3))
    except Exception:
        pass

    # Hailo AI accelerator
    if Path("/dev/hailo0").exists():
        try:
            result = subprocess.run(
                ["hailortcli", "fw-control", "identify"],
                capture_output=True, text=True, timeout=5,
            )
            if "HAILO-10" in result.stdout.upper():
                caps["ai_tops"] = 40
            elif "HAILO-8" in result.stdout.upper():
                caps["ai_tops"] = 26
        except Exception:
            caps["ai_tops"] = 26  # Safe default for Pi with Hailo

    # WiFi (for mesh)
    try:
        caps["has_wifi"] = Path("/sys/class/net/wlan0").exists()
    except Exception:
        pass

    return caps


# ── Step 5: Register with MeshRegistry ──────────────────────────────

def try_register(address: str, caps: dict) -> bool:
    """Attempt on-chain registration via NexusKernel. Returns True on success."""
    try:
        sys.path.insert(0, "/opt/nexus")
        from libnexus import NexusKernel

        k = NexusKernel(rpc_url=GATEWAY_RPC, wallet=address)

        # Check connectivity
        block = k.get_block_number()
        print(f"  Blockchain reachable (block {block})")

        # Register node specs
        result = k.register_node(
            caps["hostname"],
            caps["cpu_count"],
            caps["memory_gb"],
            caps["storage_gb"],
            caps["ai_tops"],
        )
        print(f"  Registered in block {result['block']}")
        print(f"  TX: {result['tx_hash']}")
        return True

    except Exception as exc:
        print(f"  Registration failed: {exc}")
        return False


def save_pending_registration(address: str, caps: dict):
    """Save registration request for later when network is available."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    pending = {
        "wallet": address,
        "hostname": caps["hostname"],
        "cpu": caps["cpu_count"],
        "memory_gb": caps["memory_gb"],
        "storage_gb": caps["storage_gb"],
        "ai_tops": caps["ai_tops"],
        "gateway_rpc": GATEWAY_RPC,
    }
    with open(PENDING_REG_FILE, "w") as f:
        json.dump(pending, f, indent=2)
    print(f"  Saved pending registration to {PENDING_REG_FILE}")
    print("  Will auto-register when network connectivity is established.")


# ── Step 6: Write node_identity.json ────────────────────────────────

def save_identity(address: str, registered: bool, caps: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    identity = {
        "wallet": address,
        "registered": registered,
        "capabilities": caps,
    }
    with open(IDENTITY_FILE, "w") as f:
        json.dump(identity, f, indent=2)
    os.chmod(IDENTITY_FILE, 0o644)
    print(f"  Identity saved to {IDENTITY_FILE}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("\nNEXUS OS First-Boot Setup")
    print("=" * 40)

    # Step 1
    if wallet_exists():
        print("Wallet already initialized.")
        if IDENTITY_FILE.exists():
            identity = json.loads(IDENTITY_FILE.read_text())
            print(f"  Address: {identity.get('wallet', 'unknown')}")
        print("Nothing to do. Exiting.")
        sys.exit(0)

    # Steps 2 & 3
    print("\nGenerating device wallet...")
    wallet_info = generate_wallet()
    print(f"  Keystore: {wallet_info['keystore_path']}")
    print(f"  Password: {PASSWORD_FILE} (chmod 600)")

    # Step 4
    display_identity(wallet_info)

    # Auto-detect capabilities
    print("Detecting hardware capabilities...")
    caps = detect_capabilities()
    print(f"  Host   : {caps['hostname']}")
    print(f"  Arch   : {caps['arch']}")
    print(f"  CPU    : {caps['cpu_count']} cores")
    print(f"  Memory : {caps['memory_gb']} GB")
    print(f"  Storage: {caps['storage_gb']} GB")
    print(f"  AI     : {caps['ai_tops']} TOPS")
    print(f"  WiFi   : {'yes' if caps['has_wifi'] else 'no'}")

    # Step 5
    print("\nAttempting on-chain registration...")
    registered = try_register(wallet_info["address"], caps)
    if not registered:
        save_pending_registration(wallet_info["address"], caps)

    # Step 6
    print("\nSaving node identity...")
    save_identity(wallet_info["address"], registered, caps)

    print("\nFirst-boot setup complete.\n")


if __name__ == "__main__":
    main()
