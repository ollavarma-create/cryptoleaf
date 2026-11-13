
"""Cryptoleaf JPEG v0.3 format header."""

import struct

MAGIC = b"STGC"
VERSION = 3
HEADER_SIZE = 32
RS_NSYM = 64


def build_header(encoded_payload_len: int) -> bytes:
    """Build a JPEG v0.3 header."""
    if not 0 <= encoded_payload_len <= 0xFFFFFFFF:
        raise ValueError("Invalid encoded payload length")

    header = bytearray(HEADER_SIZE)
    header[:4] = MAGIC
    struct.pack_into(">I", header, 4, encoded_payload_len)
    header[8] = VERSION
    header[9] = RS_NSYM
    return bytes(header)


def parse_header(data: bytes) -> int:
    """Validate header and return RS-encoded payload length."""
    if len(data) != HEADER_SIZE:
        raise ValueError("Invalid JPEG v0.3 header size")
    if data[:4] != MAGIC:
        raise ValueError("Invalid JPEG v0.3 magic")
    if data[8] != VERSION:
        raise ValueError("Unsupported JPEG v0.3 version")
    if data[9] != RS_NSYM:
        raise ValueError("Unsupported Reed-Solomon configuration")
    if any(data[10:]):
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
