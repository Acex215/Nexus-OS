#!/usr/bin/env python3
"""NEXUS OS Mesh Discovery Service — find peers on the local network.

Discovery layers (in priority order):
  1. mDNS (zeroconf) — works on LAN without internet
  2. ARP scan + port probe — fallback if mDNS unavailable
  3. BLE advertisement — future (placeholder)
  4. 433MHz Sub-GHz beacon — future (placeholder)

Publishes this node as _nexus._tcp.local. and browses for other NEXUS
nodes. Maintains a discovered_peers dict and optionally notifies the
Gateway when new peers appear.

Usage:
    python3 mesh_discovery.py
    python3 mesh_discovery.py --port 8766 --gateway-notify
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mesh-discovery] %(levelname)s %(message)s",
)
log = logging.getLogger("mesh_discovery")

try:
    from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False
    log.warning("zeroconf not installed — mDNS disabled (pip install zeroconf)")

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    sys.path.insert(0, "/opt/nexus")
    from libnexus.kernel import NexusKernel
    HAS_KERNEL = True
except ImportError:
    HAS_KERNEL = False
    log.warning("libnexus.kernel not importable — on-chain peer registration disabled")

# ── Constants ────────────────────────────────────────────────────────────────

SERVICE_TYPE = "_nexus._tcp.local."
SCAN_INTERVAL = 60        # seconds between discovery sweeps
PEER_STALE_AFTER = 300    # seconds before a peer is considered stale
IDENTITY_FILE = Path("/opt/nexus/config/node_identity.json")
PEERS_FILE = Path("/opt/nexus/config/discovered_peers.json")
GATEWAY_URL = "http://localhost:8766"

# Subnet to ARP-scan when mDNS is unavailable
ARP_SCAN_SUBNETS = ["10.0.20.0/24", "10.0.10.0/24"]
NEXUS_PROBE_PORT = 8766


# ── Identity ─────────────────────────────────────────────────────────────────

def _load_identity() -> dict:
    """Load wallet and capabilities from node_identity.json."""
    if IDENTITY_FILE.exists():
        try:
            return json.loads(IDENTITY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"wallet": "", "capabilities": {}}


def _get_local_ip() -> str:
    """Best-effort local IP detection via UDP socket trick."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.0.20.3", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ── Peer store ───────────────────────────────────────────────────────────────

class PeerStore:
    """Thread-safe store for discovered NEXUS peers."""

    def __init__(self):
        self.peers: dict[str, dict] = {}  # wallet → {ip, port, capabilities, last_seen, source}
        self.on_new_peer = None  # async callback(wallet, ip, port, capabilities)

    def update(self, wallet: str, ip: str, port: int,
               capabilities: str = "", source: str = "mdns"):
        is_new = wallet not in self.peers
        self.peers[wallet] = {
            "ip": ip,
            "port": port,
            "capabilities": capabilities,
            "last_seen": time.time(),
            "source": source,
        }
        if is_new:
            log.info("Discovered NEXUS peer: %s at %s:%d [%s]",
                     wallet[:10] + "..." if len(wallet) > 10 else wallet,
                     ip, port, source)
            if self.on_new_peer is not None:
                asyncio.get_event_loop().create_task(
                    self.on_new_peer(wallet, ip, port, capabilities))
        return is_new

    def remove_stale(self, max_age: float = PEER_STALE_AFTER) -> list[str]:
        now = time.time()
        stale = [w for w, p in self.peers.items() if now - p["last_seen"] > max_age]
        for w in stale:
            log.info("Peer stale, removing: %s", w[:10])
            del self.peers[w]
        return stale

    def save(self, path: Path = PEERS_FILE):
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {}
        for w, p in self.peers.items():
            serializable[w] = {**p, "last_seen_iso": datetime.fromtimestamp(
                p["last_seen"], tz=timezone.utc).isoformat()}
        path.write_text(json.dumps(serializable, indent=2))

    def as_list(self) -> list[dict]:
        return [{"wallet": w, **p} for w, p in self.peers.items()]


# ── Layer 1: mDNS (zeroconf) ────────────────────────────────────────────────

class NexusMDNSListener:
    """Zeroconf service browser listener — called on peer add/remove."""

    def __init__(self, store: PeerStore, my_wallet: str):
        self.store = store
        self.my_wallet = my_wallet

    def add_service(self, zc: "Zeroconf", service_type: str, name: str):
        info = zc.get_service_info(service_type, name)
        if not info:
            return
        self._process_info(info)

    def update_service(self, zc: "Zeroconf", service_type: str, name: str):
        info = zc.get_service_info(service_type, name)
        if not info:
            return
        self._process_info(info)

    def remove_service(self, zc: "Zeroconf", service_type: str, name: str):
        log.debug("mDNS service removed: %s", name)

    def _process_info(self, info: "ServiceInfo"):
        props = {}
        if info.properties:
            for k, v in info.properties.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else str(v)
                props[key] = val

        wallet = props.get("wallet", "")
        if not wallet or wallet == self.my_wallet:
            return

        addresses = info.parsed_scoped_addresses()
        if not addresses:
            return
        ip = addresses[0]
        port = info.port or NEXUS_PROBE_PORT
        capabilities = props.get("capabilities", "")

        self.store.update(wallet, ip, port, capabilities, source="mdns")


def _publish_mdns(zc: "Zeroconf", wallet: str, port: int,
                  capabilities: str, local_ip: str) -> "ServiceInfo":
    """Register this node as a _nexus._tcp service via mDNS."""
    hostname_safe = socket.gethostname().replace(".", "-")
    service_name = f"nexus-{hostname_safe}.{SERVICE_TYPE}"

    info = ServiceInfo(
        SERVICE_TYPE,
        service_name,
        addresses=[socket.inet_aton(local_ip)],
        port=port,
        properties={
            "wallet": wallet,
            "capabilities": capabilities,
            "hostname": socket.gethostname(),
        },
    )
    zc.register_service(info)
    log.info("mDNS published: %s on %s:%d", service_name, local_ip, port)
    return info


# ── Layer 2: ARP scan + port probe ──────────────────────────────────────────

async def _arp_scan_fallback(store: PeerStore, my_wallet: str):
    """Scan local subnets for hosts with NEXUS_PROBE_PORT open."""
    log.info("ARP scan fallback: probing subnets %s for port %d",
             ARP_SCAN_SUBNETS, NEXUS_PROBE_PORT)

    live_hosts = set()
    for subnet in ARP_SCAN_SUBNETS:
        try:
            proc = await asyncio.create_subprocess_exec(
                "arp", "-n",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            for line in stdout.decode().splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0][0].isdigit():
                    ip = parts[0]
                    # Check if IP is in our target subnet (simple /24 check)
                    subnet_prefix = subnet.rsplit(".", 1)[0]
                    if ip.startswith(subnet_prefix.rsplit(".", 1)[0]):
                        live_hosts.add(ip)
        except Exception as exc:
            log.debug("ARP scan error for %s: %s", subnet, exc)

    # Also try a ping sweep to populate the ARP table first
    for subnet in ARP_SCAN_SUBNETS:
        prefix = subnet.rsplit(".", 1)[0]
        tasks = []
        for i in range(1, 255):
            ip = f"{prefix}.{i}"
            tasks.append(_probe_port(ip, NEXUS_PROBE_PORT))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for ip_idx, result in enumerate(results):
            if result is True:
                ip = f"{prefix}.{ip_idx + 1}"
                live_hosts.add(ip)

    for ip in live_hosts:
        if await _probe_port(ip, NEXUS_PROBE_PORT):
            # We found a NEXUS node, but we don't know its wallet yet.
            # Use IP as a temporary identifier; the real wallet will be
            # resolved when the node registers with the Gateway.
            wallet_placeholder = f"unknown-{ip}"
            store.update(wallet_placeholder, ip, NEXUS_PROBE_PORT,
                         capabilities="", source="arp-scan")


async def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


# ── Layer 3: BLE (placeholder) ───────────────────────────────────────────────

async def _ble_advertise(wallet: str, capabilities: str):
    """Placeholder: BLE advertisement for NEXUS node discovery.

    Will use bleak library to advertise a BLE service with:
      - Service UUID: custom NEXUS UUID
      - Characteristic: wallet address + capabilities
    Requires: Pi with Bluetooth, bleak library
    """
    log.debug("BLE discovery: not yet implemented")


# ── Layer 4: Sub-GHz 433MHz (placeholder) ────────────────────────────────────

async def _subghz_beacon(wallet: str, capabilities: str):
    """Placeholder: 433MHz beacon via Flipper Zero bridge.

    Will use FlipperBridge from rf_relay.py to broadcast a compact
    discovery packet every SCAN_INTERVAL seconds. Packet format:
      [MAGIC:2][WALLET_HASH:4][CAPS_BITMAP:1][PORT:2]
    Requires: Flipper Zero connected via USB serial
    """
    log.debug("Sub-GHz beacon: not yet implemented")


# ── Gateway notification ─────────────────────────────────────────────────────

async def _notify_gateway(peer: dict):
    """POST newly discovered peer to the Gateway's peer notification endpoint."""
    if not HAS_AIOHTTP:
        return
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            async with session.post(
                f"{GATEWAY_URL}/peer_discovered",
                json=peer,
            ) as resp:
                if resp.status < 300:
                    log.debug("Gateway notified about peer %s", peer.get("wallet", "?")[:10])
    except Exception as exc:
        log.debug("Gateway notification failed: %s", exc)


# ── On-chain registration ────────────────────────────────────────────────────

def _get_kernel() -> "NexusKernel | None":
    """Lazy-init a NexusKernel instance for on-chain calls."""
    if not HAS_KERNEL:
        return None
    if not hasattr(_get_kernel, "_instance"):
        identity = _load_identity()
        wallet = identity.get("wallet", "")
        if not wallet:
            log.warning("No wallet in identity — on-chain registration disabled")
            _get_kernel._instance = None
        else:
            try:
                _get_kernel._instance = NexusKernel(wallet=wallet)
                log.info("NexusKernel connected for on-chain peer registration")
            except Exception as exc:
                log.warning("NexusKernel init failed: %s — on-chain registration disabled", exc)
                _get_kernel._instance = None
    return _get_kernel._instance


async def _register_peer_onchain(wallet: str, ip: str, port: int,
                                  capabilities: str):
    """Register a newly-discovered peer in MeshRegistry if not already on-chain."""
    kernel = _get_kernel()
    if kernel is None:
        return

    loop = asyncio.get_running_loop()
    try:
        # Check if peer already registered (read is cheap)
        existing = await loop.run_in_executor(None, kernel.get_peer, wallet)
        if existing.get("active") and existing.get("ip") == ip:
            log.debug("Peer %s already on-chain at %s", wallet[:10], ip)
            return

        caps_list = [c.strip() for c in capabilities.split(",") if c.strip()]
        receipt = await loop.run_in_executor(
            None, kernel.register_peer, wallet, ip, port, caps_list
        )
        log.info("Registered peer %s on-chain — tx %s block %d",
                 wallet[:10], receipt["tx_hash"][:12], receipt["block"])
    except Exception as exc:
        log.debug("On-chain peer registration failed for %s: %s", wallet[:10], exc)


# ── Main service ─────────────────────────────────────────────────────────────

class MeshDiscoveryService:
    """Async service that publishes this node and discovers peers."""

    def __init__(self, port: int, gateway_notify: bool = False):
        self.port = port
        self.gateway_notify = gateway_notify
        self.store = PeerStore()
        self._shutdown = asyncio.Event()

        identity = _load_identity()
        self.wallet = identity.get("wallet", "")
        caps = identity.get("capabilities", {})
        if isinstance(caps, dict):
            self.capabilities = ",".join(k for k, v in caps.items() if v) if caps else "compute"
        elif isinstance(caps, list):
            self.capabilities = ",".join(caps) if caps else "compute"
        else:
            self.capabilities = str(caps) or "compute"

        self.local_ip = _get_local_ip()
        self.store.on_new_peer = _register_peer_onchain
        self._zc: "Zeroconf | None" = None
        self._browser: "ServiceBrowser | None" = None
        self._service_info: "ServiceInfo | None" = None

    async def run(self):
        log.info("Mesh Discovery starting — wallet=%s ip=%s port=%d",
                 (self.wallet[:10] + "...") if self.wallet else "none",
                 self.local_ip, self.port)
        log.info("Capabilities: %s", self.capabilities)
        log.info("Discovery layers: %s",
                 ", ".join(filter(None, [
                     "mDNS" if HAS_ZEROCONF else None,
                     "ARP-scan",
                     "BLE (future)",
                     "Sub-GHz (future)",
                 ])))

        # Start mDNS if available
        if HAS_ZEROCONF:
            self._start_mdns()

        # Main discovery loop
        try:
            while not self._shutdown.is_set():
                await self._discovery_sweep()
                self.store.remove_stale()
                self.store.save()

                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._shutdown.wait()),
                        timeout=SCAN_INTERVAL,
                    )
                    break
                except asyncio.TimeoutError:
                    pass
        finally:
            self._stop_mdns()
            self.store.save()
            log.info("Mesh Discovery stopped. %d peers known.", len(self.store.peers))

    async def _discovery_sweep(self):
        """Run one round of all discovery layers."""
        # mDNS is handled by the ServiceBrowser callback (continuous)
        # so we only need to run fallback layers here.

        if not HAS_ZEROCONF:
            await _arp_scan_fallback(self.store, self.wallet)

        # Placeholders for future layers
        await _ble_advertise(self.wallet, self.capabilities)
        await _subghz_beacon(self.wallet, self.capabilities)

        # Notify Gateway about any new peers
        if self.gateway_notify:
            for peer_data in self.store.as_list():
                if time.time() - peer_data["last_seen"] < SCAN_INTERVAL + 5:
                    await _notify_gateway(peer_data)

        peer_count = len(self.store.peers)
        if peer_count > 0:
            log.info("Discovery sweep complete: %d peer(s) known", peer_count)

    def _start_mdns(self):
        """Initialize zeroconf: publish our service and start browsing."""
        if not HAS_ZEROCONF:
            return
        try:
            self._zc = Zeroconf(ip_version=IPVersion.V4Only)
            self._service_info = _publish_mdns(
                self._zc, self.wallet, self.port,
                self.capabilities, self.local_ip,
            )
            listener = NexusMDNSListener(self.store, self.wallet)
            self._browser = ServiceBrowser(self._zc, SERVICE_TYPE, listener)
            log.info("mDNS browser started for %s", SERVICE_TYPE)
        except Exception as exc:
            log.warning("mDNS startup failed: %s — falling back to ARP scan", exc)
            self._zc = None

    def _stop_mdns(self):
        """Clean up zeroconf resources."""
        if self._zc:
            try:
                if self._service_info:
                    self._zc.unregister_service(self._service_info)
                if self._browser:
                    self._browser.cancel()
                self._zc.close()
            except Exception as exc:
                log.debug("mDNS cleanup error: %s", exc)
            self._zc = None

    def request_shutdown(self):
        log.info("Shutdown requested.")
        self._shutdown.set()


# ── Entry point ──────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NEXUS Mesh Discovery Service — mDNS + fallback peer discovery",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--port", type=int,
        default=int(os.environ.get("NEXUS_DISCOVERY_PORT", "8766")),
        help="Port to advertise (env: NEXUS_DISCOVERY_PORT)",
    )
    p.add_argument(
        "--gateway-notify", action="store_true", default=False,
        help="POST discovered peers to the Gateway",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args()


async def main():
    args = _parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    svc = MeshDiscoveryService(
        port=args.port,
        gateway_notify=args.gateway_notify,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, svc.request_shutdown)

    await svc.run()


if __name__ == "__main__":
    asyncio.run(main())
