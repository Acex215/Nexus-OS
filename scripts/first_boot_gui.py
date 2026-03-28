#!/usr/bin/env python3
"""
NEXUS OS First Boot GUI Wizard
Runs once on first desktop login to guide the user through setup.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import json
import webbrowser

FLAG_FILE = "/opt/nexus/config/.first_boot_gui_complete"
CONFIG_FILE = "/opt/nexus/config/node_config.json"
WALLET_DIR = "/opt/nexus/blockchain/keystore"


class FirstBootWizard:
    def __init__(self):
        if os.path.exists(FLAG_FILE):
            raise SystemExit("First boot GUI already completed.")

        self.root = tk.Tk()
        self.root.title("NEXUS OS Setup")
        self.root.geometry("700x500")
        self.root.resizable(False, False)
        self.root.configure(bg="#0f1423")

        self.wallet_address = ""
        self.private_key = ""
        self.node_role = tk.StringVar(value="client")
        self.gateway_url = tk.StringVar(value="")
        self.behavioral_enabled = tk.BooleanVar(value=False)

        self.current_step = 0
        self.steps = [
            self.step_welcome,
            self.step_identity,
            self.step_role,
            self.step_network,
            self.step_behavioral,
            self.step_complete,
        ]

        self.content_frame = tk.Frame(self.root, bg="#0f1423")
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)

        self.nav_frame = tk.Frame(self.root, bg="#0f1423")
        self.nav_frame.pack(fill=tk.X, padx=40, pady=(0, 20))

        self._load_wallet()
        self._show_step()
        self.root.mainloop()

    def _load_wallet(self):
        """Load wallet address and key from first-boot setup output."""
        config_path = "/opt/nexus/config/device_identity.json"
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
            self.wallet_address = data.get("address", "Not yet generated")
            self.private_key = data.get("private_key", "")
        else:
            self.wallet_address = "Pending — run first-boot setup"
            self.private_key = ""

    def _clear_frame(self, frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def _make_label(self, parent, text, size=14, color="#e0e0e0", bold=False):
        weight = "bold" if bold else "normal"
        label = tk.Label(
            parent, text=text, bg="#0f1423", fg=color,
            font=("DejaVu Sans", size, weight), wraplength=620, justify=tk.LEFT,
        )
        return label

    def _make_button(self, parent, text, command, primary=False):
        bg = "#00c8dc" if primary else "#2a3050"
        fg = "#0f1423" if primary else "#e0e0e0"
        btn = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            font=("DejaVu Sans", 12, "bold"), relief=tk.FLAT,
            padx=20, pady=8, cursor="hand2",
        )
        return btn

    def _show_step(self):
        self._clear_frame(self.content_frame)
        self._clear_frame(self.nav_frame)
        self.steps[self.current_step]()

    def _next_step(self):
        self.current_step += 1
        if self.current_step < len(self.steps):
            self._show_step()

    def _prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self._show_step()

    def _add_nav_buttons(self, show_back=True, next_text="Next", next_cmd=None):
        if show_back and self.current_step > 0:
            back_btn = self._make_button(self.nav_frame, "Back", self._prev_step)
            back_btn.pack(side=tk.LEFT)

        cmd = next_cmd if next_cmd else self._next_step
        next_btn = self._make_button(self.nav_frame, next_text, cmd, primary=True)
        next_btn.pack(side=tk.RIGHT)

    # --- Step 1: Welcome ---
    def step_welcome(self):
        f = self.content_frame

        spacer = tk.Frame(f, bg="#0f1423", height=40)
        spacer.pack()

        title = self._make_label(f, "NEXUS OS", size=36, color="#00c8dc", bold=True)
        title.pack(pady=(20, 10))

        subtitle = self._make_label(
            f, "Your Data. Your Hardware. Your Rules.",
            size=16, color="#6478a0",
        )
        subtitle.pack(pady=(0, 30))

        desc = self._make_label(
            f,
            "Welcome to NEXUS OS. This wizard will set up your device identity, "
            "choose your node role, and connect you to the network.\n\n"
            "This takes about 30 seconds.",
            size=12, color="#a0a8c0",
        )
        desc.pack(pady=10)

        self._add_nav_buttons(show_back=False, next_text="Get Started")

    # --- Step 2: Device Identity ---
    def step_identity(self):
        f = self.content_frame

        title = self._make_label(f, "Device Identity", size=24, color="#00c8dc", bold=True)
        title.pack(pady=(10, 20))

        desc = self._make_label(
            f, "Your device identity has been generated. This is your unique "
            "address on the NEXUS network.",
            size=12, color="#a0a8c0",
        )
        desc.pack(pady=(0, 20))

        addr_label = self._make_label(f, "Wallet Address:", size=11, color="#6478a0")
        addr_label.pack(anchor=tk.W)

        addr_frame = tk.Frame(f, bg="#1a2040", padx=10, pady=10)
        addr_frame.pack(fill=tk.X, pady=(5, 15))

        addr_text = tk.Label(
            addr_frame, text=self.wallet_address, bg="#1a2040", fg="#00c8dc",
            font=("DejaVu Sans Mono", 13), anchor=tk.W,
        )
        addr_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        copy_btn = tk.Button(
            addr_frame, text="Copy", bg="#2a3050", fg="#e0e0e0",
            font=("DejaVu Sans", 10), relief=tk.FLAT, cursor="hand2",
            command=lambda: self._copy_to_clipboard(self.wallet_address),
        )
        copy_btn.pack(side=tk.RIGHT)

        # Private key section
        warn = self._make_label(
            f, "Save your private key — it will not be shown again.",
            size=11, color="#ff6b6b", bold=True,
        )
        warn.pack(pady=(5, 10))

        self.pk_frame = tk.Frame(f, bg="#0f1423")
        self.pk_frame.pack(fill=tk.X)

        self.pk_revealed = False
        self.pk_button = self._make_button(
            self.pk_frame, "Show Private Key", self._reveal_private_key,
        )
        self.pk_button.pack(anchor=tk.W)

        self._add_nav_buttons()

    def _reveal_private_key(self):
        if self.pk_revealed:
            return
        self.pk_revealed = True
        self.pk_button.destroy()

        if not self.private_key:
            lbl = self._make_label(
                self.pk_frame, "Private key not available. Check device_identity.json.",
                size=11, color="#ff6b6b",
            )
            lbl.pack(anchor=tk.W)
            return

        pk_box = tk.Frame(self.pk_frame, bg="#2a1010", padx=10, pady=10)
        pk_box.pack(fill=tk.X, pady=5)

        pk_text = tk.Label(
            pk_box, text=self.private_key, bg="#2a1010", fg="#ff6b6b",
            font=("DejaVu Sans Mono", 10), anchor=tk.W,
        )
        pk_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        copy_btn = tk.Button(
            pk_box, text="Copy", bg="#2a3050", fg="#e0e0e0",
            font=("DejaVu Sans", 10), relief=tk.FLAT, cursor="hand2",
            command=lambda: self._copy_to_clipboard(self.private_key),
        )
        copy_btn.pack(side=tk.RIGHT)

    def _copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # --- Step 3: Node Role ---
    def step_role(self):
        f = self.content_frame

        title = self._make_label(f, "Choose Your Node Role", size=24, color="#00c8dc", bold=True)
        title.pack(pady=(10, 20))

        # Host Node option
        host_frame = tk.Frame(f, bg="#1a2040", padx=15, pady=15)
        host_frame.pack(fill=tk.X, pady=5)

        host_rb = tk.Radiobutton(
            host_frame, text="Host Node (Full Cluster)",
            variable=self.node_role, value="host",
            bg="#1a2040", fg="#e0e0e0", selectcolor="#2a3050",
            font=("DejaVu Sans", 13, "bold"), anchor=tk.W,
            activebackground="#1a2040", activeforeground="#00c8dc",
        )
        host_rb.pack(anchor=tk.W)

        host_desc = tk.Label(
            host_frame,
            text="Run blockchain validator, IPFS storage, and AI inference. "
                 "Requires dedicated hardware and stable network.",
            bg="#1a2040", fg="#6478a0", font=("DejaVu Sans", 10),
            wraplength=580, justify=tk.LEFT,
        )
        host_desc.pack(anchor=tk.W, padx=(25, 0), pady=(5, 0))

        # Client Node option
        client_frame = tk.Frame(f, bg="#1a2040", padx=15, pady=15)
        client_frame.pack(fill=tk.X, pady=5)

        client_rb = tk.Radiobutton(
            client_frame, text="Client Node (Join Network)",
            variable=self.node_role, value="client",
            bg="#1a2040", fg="#e0e0e0", selectcolor="#2a3050",
            font=("DejaVu Sans", 13, "bold"), anchor=tk.W,
            activebackground="#1a2040", activeforeground="#00c8dc",
        )
        client_rb.pack(anchor=tk.W)

        client_desc = tk.Label(
            client_frame,
            text="Connect to an existing NEXUS cluster. Contribute storage and "
                 "compute, earn tokens. Recommended for most users.",
            bg="#1a2040", fg="#6478a0", font=("DejaVu Sans", 10),
            wraplength=580, justify=tk.LEFT,
        )
        client_desc.pack(anchor=tk.W, padx=(25, 0), pady=(5, 0))

        self._add_nav_buttons()

    # --- Step 4: Network Configuration ---
    def step_network(self):
        f = self.content_frame

        title = self._make_label(f, "Network Configuration", size=24, color="#00c8dc", bold=True)
        title.pack(pady=(10, 20))

        role = self.node_role.get()

        if role == "host":
            desc = self._make_label(
                f, "As a Host Node, your device will run the full NEXUS stack. "
                "The gateway URL is set to localhost.",
                size=12, color="#a0a8c0",
            )
            desc.pack(pady=(0, 15))

            self.gateway_url.set("http://localhost:8766")

            gw_frame = tk.Frame(f, bg="#1a2040", padx=10, pady=10)
            gw_frame.pack(fill=tk.X, pady=5)

            gw_label = tk.Label(
                gw_frame, text="Gateway: http://localhost:8766",
                bg="#1a2040", fg="#00c8dc", font=("DejaVu Sans Mono", 12),
            )
            gw_label.pack(anchor=tk.W)
        else:
            desc = self._make_label(
                f, "Enter the Gateway URL of the NEXUS cluster you want to join, "
                "or use auto-discovery to find one on your local network.",
                size=12, color="#a0a8c0",
            )
            desc.pack(pady=(0, 15))

            entry_label = self._make_label(f, "Gateway URL:", size=11, color="#6478a0")
            entry_label.pack(anchor=tk.W, pady=(10, 5))

            entry_frame = tk.Frame(f, bg="#1a2040", padx=10, pady=10)
            entry_frame.pack(fill=tk.X, pady=(0, 10))

            entry = tk.Entry(
                entry_frame, textvariable=self.gateway_url,
                bg="#0f1423", fg="#e0e0e0", insertbackground="#00c8dc",
                font=("DejaVu Sans Mono", 12), relief=tk.FLAT,
            )
            entry.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 10))

            discover_btn = tk.Button(
                entry_frame, text="Auto-discover", bg="#2a3050", fg="#e0e0e0",
                font=("DejaVu Sans", 10), relief=tk.FLAT, cursor="hand2",
                command=self._auto_discover,
            )
            discover_btn.pack(side=tk.RIGHT)

            self.discover_status = self._make_label(f, "", size=10, color="#6478a0")
            self.discover_status.pack(anchor=tk.W)

        self._add_nav_buttons(next_cmd=self._finish_setup)

    def _auto_discover(self):
        self.discover_status.configure(text="Searching for NEXUS gateways...")
        self.root.update()
        try:
            from zeroconf import Zeroconf, ServiceBrowser
            import socket
            import time

            found = []

            class Listener:
                def add_service(self, zc, type_, name):
                    info = zc.get_service_info(type_, name)
                    if info:
                        addr = socket.inet_ntoa(info.addresses[0])
                        port = info.port
                        found.append(f"http://{addr}:{port}")

                def remove_service(self, zc, type_, name):
                    pass

                def update_service(self, zc, type_, name):
                    pass

            zc = Zeroconf()
            ServiceBrowser(zc, "_nexus-gateway._tcp.local.", Listener())
            time.sleep(3)
            zc.close()

            if found:
                self.gateway_url.set(found[0])
                self.discover_status.configure(
                    text=f"Found {len(found)} gateway(s). Using: {found[0]}",
                    fg="#00c8dc",
                )
            else:
                self.discover_status.configure(
                    text="No gateways found. Enter the URL manually.",
                    fg="#ff6b6b",
                )
        except Exception as e:
            self.discover_status.configure(
                text=f"Discovery failed: {e}", fg="#ff6b6b",
            )

    def _finish_setup(self):
        """Save configuration and proceed to completion."""
        config = {
            "node_role": self.node_role.get(),
            "gateway_url": self.gateway_url.get(),
            "wallet_address": self.wallet_address,
        }

        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        self._next_step()

    # --- Step 5: Behavioral Intelligence (Optional) ---
    def step_behavioral(self):
        f = self.content_frame

        title = self._make_label(
            f, "Behavioral Intelligence (Optional)",
            size=24, color="#00c8dc", bold=True,
        )
        title.pack(pady=(10, 15))

        intro = self._make_label(
            f,
            "NEXUS can record your device interactions to train a "
            "privacy-preserving AI model. This is completely optional.",
            size=12, color="#a0a8c0",
        )
        intro.pack(pady=(0, 10))

        # What's recorded
        recorded_label = self._make_label(f, "WHAT'S RECORDED:", size=11, color="#e0e0e0", bold=True)
        recorded_label.pack(anchor=tk.W, pady=(5, 2))
        recorded_desc = self._make_label(
            f,
            "Every action you take on this device \u2014 keystrokes, clicks, "
            "URLs visited, app usage, files opened, messages, system state, "
            "location, weather, audio controls, and more \u2014 is recorded as "
            "a blockchain transaction on YOUR private chain.",
            size=10, color="#a0a8c0",
        )
        recorded_desc.pack(anchor=tk.W, padx=(15, 0), pady=(0, 8))

        # What the network sees
        network_label = self._make_label(f, "WHAT THE NETWORK SEES:", size=11, color="#e0e0e0", bold=True)
        network_label.pack(anchor=tk.W, pady=(5, 2))
        network_desc = self._make_label(
            f,
            "A 32-byte hash. Nothing else. The network cannot reconstruct "
            "any individual action from this hash.",
            size=10, color="#a0a8c0",
        )
        network_desc.pack(anchor=tk.W, padx=(15, 0), pady=(0, 8))

        # What you control
        control_label = self._make_label(f, "WHAT YOU CONTROL:", size=11, color="#e0e0e0", bold=True)
        control_label.pack(anchor=tk.W, pady=(5, 2))
        control_desc = self._make_label(
            f,
            "\u2022 Enable or disable at any time in NEXUS Monitor\n"
            "\u2022 Per-channel control (disable individual channels)\n"
            "\u2022 Emergency stop button (instant halt + data destruction)\n"
            "\u2022 Full audit trail of every pipeline event on-chain",
            size=10, color="#a0a8c0",
        )
        control_desc.pack(anchor=tk.W, padx=(15, 0), pady=(0, 8))

        cost_label = self._make_label(
            f, "TOKEN COST: 10 ECT per day for collection.",
            size=10, color="#6478a0",
        )
        cost_label.pack(anchor=tk.W, pady=(0, 5))

        change_label = self._make_label(
            f, "You can change this at any time in NEXUS Settings.",
            size=10, color="#6478a0",
        )
        change_label.pack(anchor=tk.W, pady=(0, 15))

        # Toggle
        toggle_frame = tk.Frame(f, bg="#1a2040", padx=15, pady=12)
        toggle_frame.pack(fill=tk.X, pady=5)

        toggle_cb = tk.Checkbutton(
            toggle_frame, text="Enable Behavioral Collection",
            variable=self.behavioral_enabled,
            bg="#1a2040", fg="#e0e0e0", selectcolor="#2a3050",
            font=("DejaVu Sans", 13, "bold"), anchor=tk.W,
            activebackground="#1a2040", activeforeground="#00c8dc",
        )
        toggle_cb.pack(anchor=tk.W)

        off_label = tk.Label(
            toggle_frame, text="Default: OFF",
            bg="#1a2040", fg="#6478a0", font=("DejaVu Sans", 10),
        )
        off_label.pack(anchor=tk.W, padx=(25, 0))

        self._add_nav_buttons(next_cmd=self._finish_behavioral)

    def _finish_behavioral(self):
        """Apply behavioral consent choice and proceed."""
        if self.behavioral_enabled.get():
            import time as _time

            # Create local consent file
            consent_dir = "/opt/nexus/config"
            os.makedirs(consent_dir, exist_ok=True)
            consent_path = os.path.join(consent_dir, "behavioral_consent_active")
            with open(consent_path, "w") as f:
                json.dump({
                    "granted_at": int(_time.time()),
                    "wallet": self.wallet_address,
                    "source": "first_boot_wizard",
                }, f, indent=2)

            # Try on-chain consent grant (non-blocking, best-effort)
            try:
                import sys
                sys.path.insert(0, '/opt/nexus')
                sys.path.insert(0, '/opt/nexus-distro')
                from libnexus.behavioral_client import BehavioralClient
                client = BehavioralClient()
                client.grant_consent()
            except Exception:
                pass  # Chain may not be reachable yet; consent file is enough

            # Enable the systemd service
            try:
                subprocess.run(
                    ["sudo", "systemctl", "enable", "nexus-behavioral"],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass

        self._next_step()

    # --- Step 6: Complete ---
    def step_complete(self):
        f = self.content_frame

        spacer = tk.Frame(f, bg="#0f1423", height=30)
        spacer.pack()

        title = self._make_label(f, "Setup Complete", size=28, color="#00c8dc", bold=True)
        title.pack(pady=(10, 20))

        role_text = "Host Node" if self.node_role.get() == "host" else "Client Node"
        summary = self._make_label(
            f,
            f"Role: {role_text}\n"
            f"Wallet: {self.wallet_address}\n"
            f"Gateway: {self.gateway_url.get() or 'Not configured'}",
            size=12, color="#a0a8c0",
        )
        summary.pack(pady=(0, 30))

        ready = self._make_label(
            f, "NEXUS OS is ready. Click below to open the Command Center.",
            size=13, color="#e0e0e0",
        )
        ready.pack(pady=(0, 20))

        open_btn = self._make_button(
            f, "Open Command Center", self._open_dashboard, primary=True,
        )
        open_btn.pack(pady=10)

    def _open_dashboard(self):
        gateway = self.gateway_url.get() or "http://localhost:8766"
        webbrowser.open(f"{gateway}/dashboard/")

        # Mark wizard as complete
        os.makedirs(os.path.dirname(FLAG_FILE), exist_ok=True)
        with open(FLAG_FILE, "w") as f:
            f.write("complete\n")

        self.root.destroy()


if __name__ == "__main__":
    FirstBootWizard()
