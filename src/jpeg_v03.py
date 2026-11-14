
"""Cryptoleaf JPEG v0.3 format header."""

import struct
import zlib

MAGIC = b"STGC"
VERSION = 3
HEADER_SIZE = 32
RS_NSYM = 64


# JPEG block-luminance parameters
BLOCK_SIZE = 8
BLOCKS_PER_BYTE = 42
RS_DATA_BYTES = 255 - RS_NSYM
GCM_OVERHEAD = 44  # salt + nonce + authentication tag


def encoded_payload_size(message_len: int) -> int:
    """Exact RS-encoded size of an AES-GCM message."""
    if message_len < 0:
        raise ValueError("Negative message length")

    encrypted_len = message_len + GCM_OVERHEAD
    rs_blocks = (encrypted_len + RS_DATA_BYTES - 1) // RS_DATA_BYTES

    return encrypted_len + rs_blocks * RS_NSYM


def required_blocks(message_len: int) -> int:
    """JPEG luminance blocks required for a v0.3 message."""
    return (HEADER_SIZE + encoded_payload_size(message_len)) * BLOCKS_PER_BYTE


def available_blocks(width: int, height: int) -> int:
    """Count usable 8x8 blocks, skipping the first block row."""
    if width < 0 or height < 0:
        raise ValueError("Negative image dimensions")

    columns = width // BLOCK_SIZE
    rows = max(0, height // BLOCK_SIZE - 1)

    return columns * rows


def message_fits(width: int, height: int, message_len: int) -> bool:
    """Whether the message fits in a JPEG cover image."""
    return required_blocks(message_len) <= available_blocks(width, height)


def max_message_size(width: int, height: int) -> int:
    """Maximum plaintext bytes fitting the image geometrically."""
    capacity_bytes = available_blocks(width, height) // BLOCKS_PER_BYTE
    payload_capacity = capacity_bytes - HEADER_SIZE

    if payload_capacity < GCM_OVERHEAD + RS_NSYM:
        return 0

    # Binary search handles the RS block boundaries exactly.
    low, high = 0, payload_capacity

    while low < high:
        mid = (low + high + 1) // 2

        if encoded_payload_size(mid) <= payload_capacity:
            low = mid
        else:
            high = mid - 1

    return low



def _header_crc(header: bytes) -> int:
    """Calculate CRC32 excluding the checksum field."""
    return zlib.crc32(header[:10] + header[14:32]) & 0xFFFFFFFF



def build_header(encoded_payload_len: int) -> bytes:
    """Build a JPEG v0.3 header."""
    if not 0 <= encoded_payload_len <= 0xFFFFFFFF:
        raise ValueError("Invalid encoded payload length")

    header = bytearray(HEADER_SIZE)
    header[:4] = MAGIC
    struct.pack_into(">I", header, 4, encoded_payload_len)
    header[8] = VERSION
    header[9] = RS_NSYM
    struct.pack_into(">I", header, 10, _header_crc(header))
    return bytes(header)



def parse_header(data: bytes) -> int:
    """Validate header and return RS-encoded payload length."""
    if len(data) != HEADER_SIZE:
        raise ValueError("Invalid JPEG v0.3 header size")

    stored_crc = struct.unpack_from(">I", data, 10)[0]
    if stored_crc != _header_crc(data):
        raise ValueError("JPEG v0.3 header CRC mismatch")

    if data[:4] != MAGIC:
        raise ValueError("Invalid JPEG v0.3 magic")
    if data[8] != VERSION:
        raise ValueError("Unsupported JPEG v0.3 version")
    if data[9] != RS_NSYM:
        raise ValueError("Unsupported Reed-Solomon configuration")
    if any(data[14:]):
        raise ValueError("Nonzero reserved header bytes")

    return struct.unpack_from(">I", data, 4)[0]



from .error_correction import rs_encode, rs_decode


def encode_payload(data: bytes) -> bytes:
    """Add Reed-Solomon protection to the encrypted payload."""
    return rs_encode(data, nsym=RS_NSYM)


def decode_payload(data: bytes) -> bytes:
    """Recover the encrypted payload using Reed-Solomon."""
    return rs_decode(data, nsym=RS_NSYM)


from .crypto_gcm import encrypt_gcm, decrypt_gcm


def prepare_payload(plaintext: bytes, password: str) -> bytes:
    """Encrypt and RS-protect a JPEG v0.3 message."""
    encrypted = encrypt_gcm(plaintext, password)
    return encode_payload(encrypted)


def recover_payload(encoded: bytes, password: str) -> bytes:
    """RS-correct, authenticate and decrypt a JPEG v0.3 message."""
    encrypted = decode_payload(encoded)
    return decrypt_gcm(encrypted, password)
