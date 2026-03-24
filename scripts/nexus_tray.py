#!/usr/bin/env python3
"""
NEXUS OS System Tray Indicator
Shows cluster health and provides quick access to services.
"""

import threading
import time
import subprocess
import webbrowser
import json
import urllib.request
import urllib.error

from PIL import Image, ImageDraw
import pystray

GATEWAY = "http://localhost:8766"
POLL_INTERVAL = 30


class NexusTray:
    def __init__(self):
        self.healthy = False
        self.running = True
        self.icon = pystray.Icon(
            "nexus-os",
            icon=self._make_icon(False),
            title="NEXUS OS — checking...",
            menu=self._build_menu(),
        )

    def _make_icon(self, healthy):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = (0, 200, 100, 255) if healthy else (200, 50, 50, 255)
        draw.ellipse([8, 8, 56, 56], fill=color)
        # N letter in center
        draw.text((22, 14), "N", fill=(255, 255, 255, 255))
        return img

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Open Command Center", self._open_dashboard, default=True),
            pystray.MenuItem("Open AI Assistant", self._open_chat),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("System Status", self._show_status),
            pystray.MenuItem("Wallet", self._show_wallet),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Services", self._start_services),
            pystray.MenuItem("Stop Services", self._stop_services),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _api_get(self, path, timeout=5):
        try:
            req = urllib.request.Request(f"{GATEWAY}{path}")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None

    def _notify(self, title, body):
        try:
            subprocess.Popen(
                ["notify-send", title, body, "-i", "/usr/share/nexus-os/icons/nexus-app.png"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    def _open_dashboard(self, icon=None, item=None):
        webbrowser.open(f"{GATEWAY}/dashboard/")

    def _open_chat(self, icon=None, item=None):
        webbrowser.open(f"{GATEWAY}/chat/")

    def _show_status(self, icon=None, item=None):
        health = self._api_get("/api/health")
        if health:
            nodes = health.get("nodes", "?")
            block = health.get("block_height", "?")
            uptime = health.get("uptime", "?")
            self._notify(
                "NEXUS OS Status",
                f"Nodes: {nodes}\nBlock Height: {block}\nUptime: {uptime}",
            )
        else:
            self._notify("NEXUS OS Status", "Gateway unreachable. Services may be stopped.")

    def _show_wallet(self, icon=None, item=None):
        try:
            with open("/opt/nexus/config/device_identity.json", "r") as f:
                identity = json.load(f)
            addr = identity.get("address", "Unknown")
        except (FileNotFoundError, json.JSONDecodeError):
            addr = "Not configured"

        balances_text = ""
        if addr and addr != "Not configured":
            data = self._api_get(f"/api/tokens/balance/{addr}")
            if data and isinstance(data, dict):
                balances_text = "\n".join(f"  {k}: {v}" for k, v in data.items())

        body = f"Address: {addr}"
        if balances_text:
            body += f"\n\nBalances:\n{balances_text}"

        self._notify("NEXUS Wallet", body)

    def _start_services(self, icon=None, item=None):
        for svc in ["nexus-gateway", "nexus-dashboard-api", "nexus-node-agent"]:
            subprocess.Popen(
                ["sudo", "systemctl", "start", f"{svc}.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        self._notify("NEXUS OS", "Starting services...")

    def _stop_services(self, icon=None, item=None):
        for svc in ["nexus-node-agent", "nexus-dashboard-api", "nexus-gateway"]:
            subprocess.Popen(
                ["sudo", "systemctl", "stop", f"{svc}.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        self._notify("NEXUS OS", "Stopping services...")

    def _quit(self, icon=None, item=None):
        self.running = False
        self.icon.stop()

    def _poll_health(self):
        while self.running:
            health = self._api_get("/api/health", timeout=3)
            new_healthy = health is not None
            if new_healthy != self.healthy:
                self.healthy = new_healthy
                self.icon.icon = self._make_icon(self.healthy)
                if self.healthy:
                    self.icon.title = "NEXUS OS — healthy"
                else:
                    self.icon.title = "NEXUS OS — degraded"
            time.sleep(POLL_INTERVAL)

    def run(self):
        poll_thread = threading.Thread(target=self._poll_health, daemon=True)
        poll_thread.start()
        self.icon.run()


if __name__ == "__main__":
    NexusTray().run()
