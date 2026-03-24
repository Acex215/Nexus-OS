#!/usr/bin/env python3
"""NEXUS OS — HID Controller

Host-side library for controlling the two Pi Pico 2 HID devices attached to
nexus-admin via USB serial.

Pico firmware protocol (CircuitPython code.py on each Pico):
  Keyboard (/dev/ttyACM*):  PING → PONG:keyboard
                             TYPE:<text> → OK / ERR:...
                             KEY:<K1>+<K2>+... → OK / ERR:...
  Mouse    (/dev/ttyACM*):  PING → PONG:mouse
                             MOVE:<x>,<y> → OK / ERR:...
                             CLICK:LEFT|RIGHT|MIDDLE → OK
                             SCROLL:<n> → OK

Auto-detection: on first import (or on explicit reinit()) this module scans
all /dev/ttyACM* ports, sends PING to each, and assigns keyboard/mouse by
the PONG:<role> response.

Public API:
    get_status()               → dict with port assignments and connectivity
    type_text(text)            → send TYPE:<text> to keyboard Pico
    press_key(*keys)           → send KEY:<k1>+<k2> to keyboard Pico
    move_mouse(x, y)           → send MOVE:<x>,<y> to mouse Pico
    click(button="LEFT")       → send CLICK:<button> to mouse Pico
    scroll(amount)             → send SCROLL:<amount> to mouse Pico
    reinit()                   → re-scan all ACM ports (useful after unplug)
"""

import glob
import logging
import time
from typing import Optional

import serial

log = logging.getLogger("hid_controller")

# ── Constants ──────────────────────────────────────────────────────────────────

BAUD       = 115200
CMD_DELAY  = 0.05   # seconds between commands
PING_WAIT  = 4.0    # seconds to wait for PONG after soft-reboot
OPEN_WAIT  = 1.0    # seconds after Serial() before sending (Pico needs ~1s to settle)
RETRY_WAIT = 2.0    # seconds before retry on first error


# ── Internal state ─────────────────────────────────────────────────────────────

_kbd_port: Optional[str]   = None
_mouse_port: Optional[str] = None
_initialized: bool         = False


def _open(port: str) -> serial.Serial:
    """Open a serial port to a CircuitPython Pico.

    DTR must remain at its default (asserted) so that CircuitPython's
    supervisor.runtime.serial_bytes_available returns True. The Pi Pico 2
    does not reset on DTR toggle, so no protection is needed.
    """
    return serial.Serial(port, baudrate=BAUD, timeout=3)


def _restart_code(port: str) -> None:
    """Send supervisor.reload() via CircuitPython REPL to start code.py."""
    try:
        s = _open(port)
        time.sleep(OPEN_WAIT)
        s.reset_input_buffer()
        s.write(b"import supervisor; supervisor.reload()\r\n")
        s.close()
        time.sleep(3.0)   # wait for usb_hid initialisation
    except Exception as exc:
        log.debug("_restart_code(%s): %s", port, exc)


def _ping(port: str) -> Optional[str]:
    """PING one port. Returns 'keyboard', 'mouse', or None.

    Reads all available bytes in a tight loop to handle the command echo
    ('PING') appearing on the same read as the response ('PONG:keyboard').
    """
    try:
        s = _open(port)
        time.sleep(OPEN_WAIT)
        s.reset_input_buffer()
        s.write(b"PING\r\n")
        # Read all data up to PING_WAIT and scan for PONG:
        buf = b""
        deadline = time.time() + PING_WAIT
        while time.time() < deadline:
            chunk = s.read(256)
            if chunk:
                buf += chunk
            text = buf.decode("utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("PONG:"):
                    s.close()
                    return line[5:]   # 'keyboard' or 'mouse'
            time.sleep(0.05)
        s.close()
        return None
    except Exception as exc:
        log.debug("_ping(%s): %s", port, exc)
        return None


def _detect() -> None:
    """Scan /dev/ttyACM* and assign keyboard/mouse ports."""
    global _kbd_port, _mouse_port, _initialized

    ports = sorted(glob.glob("/dev/ttyACM*"))
    if not ports:
        log.warning("hid_controller: no /dev/ttyACM* devices found")
        _initialized = True
        return

    for port in ports:
        role = _ping(port)
        if role is None:
            # Pico may be in REPL — try supervisor.reload() once
            log.debug("hid_controller: %s not responding, attempting reload", port)
            _restart_code(port)
            role = _ping(port)

        if role == "keyboard":
            _kbd_port = port
            log.info("hid_controller: keyboard → %s", port)
        elif role == "mouse":
            _mouse_port = port
            log.info("hid_controller: mouse    → %s", port)
        else:
            log.debug("hid_controller: %s — no PONG received", port)

    _initialized = True

    if not _kbd_port:
        log.warning("hid_controller: keyboard Pico not found")
    if not _mouse_port:
        log.warning("hid_controller: mouse Pico not found")


# Run auto-detection on import
_detect()


# ── Serial send helper ─────────────────────────────────────────────────────────

def _send(port: str, cmd: str) -> str:
    """Send a command string to a Pico and return the response line.

    Retries once if the first attempt fails or returns an unexpected response.
    Raises RuntimeError if the port is unavailable or both attempts fail.
    """
    raw = (cmd.strip() + "\r\n").encode()

    for attempt in (1, 2):
        try:
            s = _open(port)
            time.sleep(CMD_DELAY)
            s.reset_input_buffer()
            s.write(raw)
            resp = ""
            deadline = time.time() + 3
            while time.time() < deadline:
                line = s.readline().decode("utf-8", errors="replace").strip()
                # skip echo of the command itself
                if line and not line.startswith(cmd.split(":")[0]):
                    resp = line
                    break
            s.close()
            if resp:
                return resp
        except serial.SerialException as exc:
            if attempt == 2:
                raise RuntimeError(f"HID serial error on {port}: {exc}") from exc
            log.debug("_send attempt 1 failed (%s), retrying…", exc)
            time.sleep(RETRY_WAIT)

    raise RuntimeError(f"No response from Pico on {port} for command: {cmd!r}")


def _require_kbd() -> str:
    if not _kbd_port:
        raise RuntimeError("Keyboard Pico not detected. Run hid_controller.reinit().")
    return _kbd_port


def _require_mouse() -> str:
    if not _mouse_port:
        raise RuntimeError("Mouse Pico not detected. Run hid_controller.reinit().")
    return _mouse_port


# ── Public API ─────────────────────────────────────────────────────────────────

def reinit() -> None:
    """Re-scan ACM ports. Call this after reconnecting a Pico."""
    global _kbd_port, _mouse_port, _initialized
    _kbd_port = _mouse_port = None
    _initialized = False
    _detect()


def get_status() -> dict:
    """Return current port assignments and live connectivity for both devices."""
    kbd_ok   = False
    mouse_ok = False

    if _kbd_port:
        kbd_ok = (_ping(_kbd_port) == "keyboard")
    if _mouse_port:
        mouse_ok = (_ping(_mouse_port) == "mouse")

    return {
        "keyboard_port":  _kbd_port,
        "mouse_port":     _mouse_port,
        "keyboard_alive": kbd_ok,
        "mouse_alive":    mouse_ok,
    }


def type_text(text: str) -> str:
    """Type a string via the keyboard Pico.

    Returns 'OK' on success. Raises RuntimeError on failure.
    """
    port = _require_kbd()
    resp = _send(port, f"TYPE:{text}")
    if not resp.startswith("OK"):
        raise RuntimeError(f"type_text failed: {resp}")
    return resp


def press_key(*keys: str) -> str:
    """Press a key combination via the keyboard Pico.

    Example: press_key("CTRL", "C")  →  sends KEY:CTRL+C
    Returns 'OK' on success.
    """
    combo = "+".join(k.upper() for k in keys)
    port  = _require_kbd()
    resp  = _send(port, f"KEY:{combo}")
    if not resp.startswith("OK"):
        raise RuntimeError(f"press_key failed: {resp}")
    return resp


def move_mouse(x: int, y: int) -> str:
    """Move the mouse cursor by (x, y) pixels relative to current position."""
    port = _require_mouse()
    resp = _send(port, f"MOVE:{x},{y}")
    if not resp.startswith("OK"):
        raise RuntimeError(f"move_mouse failed: {resp}")
    return resp


def click(button: str = "LEFT") -> str:
    """Click a mouse button. button must be LEFT, RIGHT, or MIDDLE."""
    btn = button.upper()
    if btn not in ("LEFT", "RIGHT", "MIDDLE"):
        raise ValueError(f"Invalid button: {button!r}. Use LEFT, RIGHT, or MIDDLE.")
    port = _require_mouse()
    resp = _send(port, f"CLICK:{btn}")
    if not resp.startswith("OK"):
        raise RuntimeError(f"click failed: {resp}")
    return resp


def scroll(amount: int) -> str:
    """Scroll the mouse wheel. Positive = up, negative = down."""
    port = _require_mouse()
    resp = _send(port, f"SCROLL:{amount}")
    if not resp.startswith("OK"):
        raise RuntimeError(f"scroll failed: {resp}")
    return resp
