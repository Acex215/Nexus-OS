"""
NEXUS OS Sub-GHz RF Relay Protocol

Adapted from SatNOGS KISS framing for low-bandwidth peer-to-peer
communication over Flipper Zero Sub-GHz radio (433.92 MHz).

Packet format (64 bytes max):
  [4B magic "NXUS"] [20B sender wallet] [20B recipient wallet]
  [1B msg_type] [1B seq_num] [18B payload]

For larger messages, payloads are fragmented:
  Fragment header in payload[0:2]: [1B frag_index] [1B frag_total]
  Fragment data: payload[2:18] = 16 bytes per fragment

KISS framing (from SatNOGS) wraps packets for serial transport:
  0xC0 <escaped_packet_bytes> 0xC0
  Escape: 0xC0 -> 0xDB 0xDC, 0xDB -> 0xDB 0xDD
"""

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

# Constants
MAGIC = b'NXUS'
PACKET_SIZE = 64
WALLET_SIZE = 20
PAYLOAD_SIZE = 18
FRAG_PAYLOAD_SIZE = 16  # payload minus 2-byte fragment header

# KISS framing bytes
KISS_FEND = 0xC0
KISS_FESC = 0xDB
KISS_TFEND = 0xDC
KISS_TFESC = 0xDD


class MsgType(IntEnum):
    HEARTBEAT = 0x01
    ALERT = 0x02
    DATA = 0x03
    ACK = 0x04
    PEER_ANNOUNCE = 0x05
    FRAG_DATA = 0x06  # fragmented data packet


@dataclass
class RFPacket:
    sender: bytes      # 20 bytes (truncated wallet address)
    recipient: bytes   # 20 bytes (truncated wallet address, 0x00*20 = broadcast)
    msg_type: MsgType
    seq_num: int       # 0-255
    payload: bytes     # up to 18 bytes

    def encode(self) -> bytes:
        """Encode packet to 64-byte wire format."""
        if len(self.sender) != WALLET_SIZE:
            raise ValueError(f"Sender must be {WALLET_SIZE} bytes")
        if len(self.recipient) != WALLET_SIZE:
            raise ValueError(f"Recipient must be {WALLET_SIZE} bytes")
        if len(self.payload) > PAYLOAD_SIZE:
            raise ValueError(f"Payload max {PAYLOAD_SIZE} bytes, got {len(self.payload)}")

        # Pad payload to exact size
        padded_payload = self.payload.ljust(PAYLOAD_SIZE, b'\x00')

        packet = (
            MAGIC
            + self.sender
            + self.recipient
            + struct.pack('BB', self.msg_type, self.seq_num)
            + padded_payload
        )
        assert len(packet) == PACKET_SIZE
        return packet

    @classmethod
    def decode(cls, data: bytes) -> Optional['RFPacket']:
        """Decode 64-byte wire format to packet. Returns None if invalid."""
        if len(data) != PACKET_SIZE:
            return None
        if data[:4] != MAGIC:
            return None

        sender = data[4:24]
        recipient = data[24:44]
        msg_type, seq_num = struct.unpack('BB', data[44:46])
        payload = data[46:64]

        try:
            msg_type = MsgType(msg_type)
        except ValueError:
            return None

        return cls(
            sender=sender,
            recipient=recipient,
            msg_type=msg_type,
            seq_num=seq_num,
            payload=payload
        )

    def __repr__(self):
        return (f"RFPacket(type={self.msg_type.name}, seq={self.seq_num}, "
                f"sender={self.sender[:4].hex()}..., payload={len(self.payload.rstrip(b'\\x00'))}B)")


# === KISS Framing (adapted from SatNOGS) ===

def kiss_escape(data: bytes) -> bytes:
    """Escape special bytes for KISS framing."""
    out = bytearray()
    for b in data:
        if b == KISS_FEND:
            out.extend([KISS_FESC, KISS_TFEND])
        elif b == KISS_FESC:
            out.extend([KISS_FESC, KISS_TFESC])
        else:
            out.append(b)
    return bytes(out)


def kiss_unescape(data: bytes) -> bytes:
    """Unescape KISS-framed data."""
    return (data
            .replace(bytes([KISS_FESC, KISS_TFEND]), bytes([KISS_FEND]))
            .replace(bytes([KISS_FESC, KISS_TFESC]), bytes([KISS_FESC])))


def kiss_frame(packet_bytes: bytes) -> bytes:
    """Wrap packet in KISS frame for serial transport."""
    return bytes([KISS_FEND]) + kiss_escape(packet_bytes) + bytes([KISS_FEND])


def kiss_unframe(data: bytes) -> list[bytes]:
    """Extract packets from KISS-framed serial data."""
    frames = []
    for chunk in data.split(bytes([KISS_FEND])):
        if len(chunk) == 0:
            continue
        unescaped = kiss_unescape(chunk)
        if len(unescaped) == PACKET_SIZE and unescaped[:4] == MAGIC:
            frames.append(unescaped)
    return frames


# === Wallet address helpers ===

def wallet_to_bytes(wallet_hex: str) -> bytes:
    """Convert '0x...' wallet address to 20 bytes."""
    addr = wallet_hex.lower().replace('0x', '')
    return bytes.fromhex(addr.ljust(40, '0'))[:WALLET_SIZE]


def bytes_to_wallet(data: bytes) -> str:
    """Convert 20 bytes back to '0x...' wallet address."""
    return '0x' + data.hex()


BROADCAST_ADDR = b'\x00' * WALLET_SIZE


# === Message fragmentation ===

def fragment_message(sender: bytes, recipient: bytes, data: bytes,
                     msg_type: MsgType = MsgType.FRAG_DATA,
                     start_seq: int = 0) -> list[RFPacket]:
    """Fragment a large message into multiple 64-byte RF packets."""
    frag_count = (len(data) + FRAG_PAYLOAD_SIZE - 1) // FRAG_PAYLOAD_SIZE
    if frag_count > 255:
        raise ValueError(f"Message too large: {len(data)} bytes, max {255 * FRAG_PAYLOAD_SIZE}")

    packets = []
    for i in range(frag_count):
        chunk = data[i * FRAG_PAYLOAD_SIZE:(i + 1) * FRAG_PAYLOAD_SIZE]
        # Fragment header: [index, total]
        payload = struct.pack('BB', i, frag_count) + chunk
        packets.append(RFPacket(
            sender=sender,
            recipient=recipient,
            msg_type=msg_type,
            seq_num=(start_seq + i) % 256,
            payload=payload
        ))
    return packets


def reassemble_message(packets: list[RFPacket]) -> Optional[bytes]:
    """Reassemble fragmented packets into original message."""
    if not packets:
        return None

    # Parse fragment headers
    fragments = {}
    total = None
    for pkt in packets:
        if len(pkt.payload) < 2:
            continue
        frag_idx, frag_total = struct.unpack('BB', pkt.payload[:2])
        if total is None:
            total = frag_total
        elif frag_total != total:
            return None  # inconsistent fragment count
        fragments[frag_idx] = pkt.payload[2:]

    if total is None or len(fragments) != total:
        return None  # missing fragments

    return b''.join(fragments[i] for i in range(total))


# === Heartbeat / Alert helpers ===

def make_heartbeat(sender_wallet: str, node_num: int, block_height: int) -> RFPacket:
    """Create a heartbeat packet broadcasting node status."""
    payload = struct.pack('>BHI', node_num, 0, block_height)  # node, reserved, block
    return RFPacket(
        sender=wallet_to_bytes(sender_wallet),
        recipient=BROADCAST_ADDR,
        msg_type=MsgType.HEARTBEAT,
        seq_num=0,
        payload=payload
    )


def make_alert(sender_wallet: str, alert_code: int, message: str) -> RFPacket:
    """Create an alert packet (truncated to 16 bytes after code)."""
    msg_bytes = message.encode('utf-8')[:16]
    payload = struct.pack('>H', alert_code) + msg_bytes
    return RFPacket(
        sender=wallet_to_bytes(sender_wallet),
        recipient=BROADCAST_ADDR,
        msg_type=MsgType.ALERT,
        seq_num=0,
        payload=payload
    )


# Alert codes
ALERT_NODE_DOWN = 0x0001
ALERT_CHAIN_STALL = 0x0002
ALERT_STORAGE_FULL = 0x0003
ALERT_SECURITY = 0x0004
