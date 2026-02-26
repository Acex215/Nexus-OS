#!/usr/bin/env python3
"""
NEXUS OS Flipper Zero Sub-GHz Bridge

Connects to Flipper Zero via USB serial and uses its Sub-GHz radio
for packet TX/RX at 433.92 MHz. Wraps the Flipper CLI interface.

The Flipper Zero CLI exposes Sub-GHz commands:
  subghz tx <hex_data> <frequency> <preset>
  subghz rx <frequency> <preset>

This bridge handles:
  - Serial connection management with auto-reconnect
  - KISS-framed packet TX/RX via rf_relay protocol
  - Receive buffer parsing for incoming packets
  - Rate limiting to stay within Sub-GHz duty cycle limits
"""

import glob
import logging
import os
import queue
import re
import threading
import time
from typing import Callable, Optional

try:
    import serial
except ImportError:
    serial = None  # Will fail gracefully if pyserial not installed

from rf_relay import (
    KISS_FEND, RFPacket, kiss_frame, kiss_unframe,
    PACKET_SIZE, MAGIC
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [flipper-bridge] %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Flipper Zero defaults
DEFAULT_FREQUENCY = 433920000  # 433.92 MHz
DEFAULT_PRESET = "FuriHalSubGhzPresetOok650Async"  # OOK modulation
SERIAL_BAUDRATE = 230400
SERIAL_TIMEOUT = 1.0

# Duty cycle: max 36 seconds per hour at 433 MHz (EU/US conservative)
MAX_TX_PER_MINUTE = 10
TX_COOLDOWN_SEC = 6.0  # minimum seconds between transmissions


def find_flipper_serial() -> Optional[str]:
    """Auto-detect Flipper Zero serial port."""
    # Flipper Zero typically shows as /dev/ttyACM*
    candidates = sorted(glob.glob('/dev/ttyACM*'))
    for port in candidates:
        try:
            s = serial.Serial(port, SERIAL_BAUDRATE, timeout=2)
            # Send empty line to get Flipper CLI prompt
            s.write(b'\r\n')
            time.sleep(0.5)
            resp = s.read(256)
            s.close()
            if b'>:' in resp or b'Flipper' in resp:
                logger.info(f"Found Flipper Zero at {port}")
                return port
        except (serial.SerialException, OSError):
            continue
    return None


class FlipperBridge:
    """Serial bridge to Flipper Zero Sub-GHz radio."""

    def __init__(self, port: Optional[str] = None,
                 frequency: int = DEFAULT_FREQUENCY,
                 on_receive: Optional[Callable[[RFPacket], None]] = None):
        self.port = port
        self.frequency = frequency
        self.on_receive = on_receive
        self.ser: Optional['serial.Serial'] = None
        self._running = False
        self._rx_thread: Optional[threading.Thread] = None
        self._tx_queue: queue.Queue = queue.Queue()
        self._tx_thread: Optional[threading.Thread] = None
        self._last_tx_time = 0.0
        self._tx_count_minute = 0
        self._tx_minute_start = 0.0
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        """Connect to Flipper Zero serial port."""
        if serial is None:
            logger.error("pyserial not installed. Run: pip install pyserial")
            return False

        if self.port is None:
            self.port = find_flipper_serial()
            if self.port is None:
                logger.warning("No Flipper Zero detected. Bridge in offline mode.")
                return False

        try:
            self.ser = serial.Serial(
                self.port,
                baudrate=SERIAL_BAUDRATE,
                timeout=SERIAL_TIMEOUT
            )
            # Wait for CLI to be ready
            time.sleep(1.0)
            self.ser.reset_input_buffer()

            # Send a newline and check for prompt
            self._send_cli(b'\r\n')
            time.sleep(0.3)
            resp = self.ser.read(512)

            if b'>:' in resp or b'Flipper' in resp or len(resp) > 0:
                self._connected = True
                logger.info(f"Connected to Flipper Zero on {self.port}")
                return True
            else:
                logger.warning(f"Device on {self.port} did not respond as Flipper Zero")
                self.ser.close()
                self.ser = None
                return False

        except serial.SerialException as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            return False

    def disconnect(self):
        """Disconnect from Flipper Zero."""
        self._running = False
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=3)
        if self._tx_thread and self._tx_thread.is_alive():
            self._tx_queue.put(None)  # poison pill
            self._tx_thread.join(timeout=3)
        if self.ser and self.ser.is_open:
            try:
                # Stop any active subghz session
                self._send_cli(b'subghz rx_stop\r\n')
                time.sleep(0.2)
                self.ser.close()
            except serial.SerialException:
                pass
        self._connected = False
        logger.info("Disconnected from Flipper Zero")

    def _send_cli(self, data: bytes):
        """Send raw bytes to Flipper CLI."""
        if self.ser and self.ser.is_open:
            self.ser.write(data)
            self.ser.flush()

    def _read_cli(self, timeout: float = 1.0) -> bytes:
        """Read response from Flipper CLI."""
        if not self.ser or not self.ser.is_open:
            return b''
        old_timeout = self.ser.timeout
        self.ser.timeout = timeout
        data = self.ser.read(4096)
        self.ser.timeout = old_timeout
        return data

    def transmit(self, packet: RFPacket) -> bool:
        """Queue a packet for transmission."""
        if not self._connected:
            logger.debug("Not connected, dropping TX packet")
            return False

        # Rate limiting
        now = time.time()
        if now - self._tx_minute_start > 60:
            self._tx_count_minute = 0
            self._tx_minute_start = now

        if self._tx_count_minute >= MAX_TX_PER_MINUTE:
            logger.warning("TX rate limit reached, dropping packet")
            return False

        self._tx_queue.put(packet)
        return True

    def _do_transmit(self, packet: RFPacket) -> bool:
        """Actually transmit a packet via Flipper Sub-GHz."""
        # Enforce cooldown
        now = time.time()
        elapsed = now - self._last_tx_time
        if elapsed < TX_COOLDOWN_SEC:
            time.sleep(TX_COOLDOWN_SEC - elapsed)

        # Encode packet and KISS-frame it
        raw = packet.encode()
        framed = kiss_frame(raw)
        hex_data = framed.hex()

        # Use Flipper Sub-GHz TX command
        # subghz tx_from_file is more reliable but requires file upload
        # For raw data, we use the RAW TX approach via CLI
        cmd = f'subghz tx {hex_data} {self.frequency}\r\n'
        logger.debug(f"TX: {packet} ({len(framed)} bytes framed)")

        with self._lock:
            self._send_cli(cmd.encode())
            time.sleep(0.1)
            resp = self._read_cli(timeout=2.0)

        self._last_tx_time = time.time()
        self._tx_count_minute += 1

        if b'error' in resp.lower() or b'Error' in resp:
            logger.error(f"TX error: {resp.decode(errors='replace')}")
            return False

        return True

    def _tx_loop(self):
        """TX thread: processes queued packets."""
        logger.info("TX loop started")
        while self._running:
            try:
                packet = self._tx_queue.get(timeout=1.0)
                if packet is None:
                    break
                self._do_transmit(packet)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"TX error: {e}")

    def _rx_loop(self):
        """RX thread: listens for incoming packets."""
        logger.info(f"RX loop started on {self.frequency} Hz")

        # Start Flipper Sub-GHz RX mode
        cmd = f'subghz rx {self.frequency}\r\n'
        with self._lock:
            self._send_cli(cmd.encode())

        rx_buffer = bytearray()

        while self._running:
            try:
                if not self.ser or not self.ser.is_open:
                    time.sleep(1)
                    continue

                with self._lock:
                    data = self.ser.read(256)

                if not data:
                    continue

                rx_buffer.extend(data)

                # Try to extract KISS frames from buffer
                while KISS_FEND in rx_buffer:
                    # Find frame boundaries
                    start = rx_buffer.index(KISS_FEND)
                    # Look for end delimiter
                    try:
                        end = rx_buffer.index(KISS_FEND, start + 1)
                    except ValueError:
                        break  # incomplete frame, wait for more data

                    frame_data = bytes(rx_buffer[start:end + 1])
                    rx_buffer = rx_buffer[end + 1:]

                    # Parse KISS frame
                    packets_raw = kiss_unframe(frame_data)
                    for raw in packets_raw:
                        pkt = RFPacket.decode(raw)
                        if pkt:
                            logger.debug(f"RX: {pkt}")
                            if self.on_receive:
                                try:
                                    self.on_receive(pkt)
                                except Exception as e:
                                    logger.error(f"RX callback error: {e}")

                # Prevent buffer from growing unbounded
                if len(rx_buffer) > 4096:
                    rx_buffer = rx_buffer[-1024:]

            except serial.SerialException as e:
                logger.error(f"RX serial error: {e}")
                self._connected = False
                time.sleep(5)
                # Try reconnect
                if self.connect():
                    cmd = f'subghz rx {self.frequency}\r\n'
                    with self._lock:
                        self._send_cli(cmd.encode())
            except Exception as e:
                logger.error(f"RX error: {e}")
                time.sleep(1)

    def start(self) -> bool:
        """Start TX/RX threads."""
        if not self._connected:
            if not self.connect():
                return False

        self._running = True

        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name='flipper-rx')
        self._rx_thread.start()

        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True, name='flipper-tx')
        self._tx_thread.start()

        logger.info("Flipper bridge started (TX + RX threads)")
        return True

    def stop(self):
        """Stop bridge."""
        self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tx_queue_size(self) -> int:
        return self._tx_queue.qsize()


class MockFlipperBridge(FlipperBridge):
    """Mock bridge for testing without hardware.

    Simulates TX/RX by looping packets back locally.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loopback_packets: list[RFPacket] = []

    def connect(self) -> bool:
        self._connected = True
        logger.info("MockFlipperBridge: connected (loopback mode)")
        return True

    def _do_transmit(self, packet: RFPacket) -> bool:
        logger.info(f"MockTX: {packet}")
        # Loopback: deliver to own RX callback
        self._loopback_packets.append(packet)
        if self.on_receive:
            self.on_receive(packet)
        return True

    def start(self) -> bool:
        self._connected = True
        self._running = True
        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True, name='mock-tx')
        self._tx_thread.start()
        logger.info("MockFlipperBridge started (loopback mode)")
        return True

    def disconnect(self):
        self._running = False
        if self._tx_thread and self._tx_thread.is_alive():
            self._tx_queue.put(None)
            self._tx_thread.join(timeout=3)
        self._connected = False
        logger.info("MockFlipperBridge disconnected")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='NEXUS Flipper Zero Sub-GHz Bridge')
    parser.add_argument('--port', help='Serial port (auto-detect if omitted)')
    parser.add_argument('--freq', type=int, default=DEFAULT_FREQUENCY, help='Frequency in Hz')
    parser.add_argument('--mock', action='store_true', help='Use mock bridge (no hardware)')
    parser.add_argument('--test-tx', action='store_true', help='Send a test heartbeat')
    args = parser.parse_args()

    def on_rx(pkt):
        print(f"  RX: {pkt}")

    if args.mock:
        bridge = MockFlipperBridge(on_receive=on_rx)
    else:
        bridge = FlipperBridge(port=args.port, frequency=args.freq, on_receive=on_rx)

    if not bridge.start():
        print("Failed to start bridge. Use --mock for testing without hardware.")
        exit(1)

    if args.test_tx:
        from rf_relay import make_heartbeat
        hb = make_heartbeat('0x817B0842B208B76A7665948F8D1A0592F9b1e958', 4, 12345)
        print(f"Sending test heartbeat: {hb}")
        bridge.transmit(hb)
        time.sleep(2)

    try:
        print("Bridge running. Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bridge.stop()
        print("Bridge stopped.")
