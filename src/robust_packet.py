"""Versioned RS8 transport packet for Cryptoleaf's experimental robust image mode.

This module only handles framing and error correction. It does NOT implement
Fourier synchronization, DWT embedding, encryption, or image I/O.

Wire format: b'CLR1' | uint16 big-endian RS codeword length |
             RS8(payload | CRC32(payload)).

The checksum is inside the RS codeword, so it is checked *after* correction.
This is a new format; it is not compatible with the research DWT1 wrapper.
"""

import zlib

from reedsolo import RSCodec, ReedSolomonError

MAGIC = b"CLR1"
PARITY = 8
MAX_CODEWORD = 255  # reedsolo's default GF(256) codeword limit
MAX_PAYLOAD = MAX_CODEWORD - PARITY - 4
HEADER_BYTES = 6


def pack(payload: bytes) -> bytes:
    """Encode bytes into a versioned, checksum-protected RS8 codeword."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large: maximum {MAX_PAYLOAD} bytes")
    protected = payload + zlib.crc32(payload).to_bytes(4, "big")
    codeword = bytes(RSCodec(PARITY).encode(protected))
    return MAGIC + len(codeword).to_bytes(2, "big") + codeword


def unpack(packet: bytes) -> bytes:
    """Correct up to four erroneous RS symbols and validate CRC32.

    A failed check is always reported as ValueError; callers must never
    treat a partially corrected codeword as a valid payload.
    """
    if not isinstance(packet, bytes):
        raise TypeError("packet must be bytes")
    if len(packet) < HEADER_BYTES or packet[:4] != MAGIC:
        raise ValueError("invalid robust packet magic")
    length = int.from_bytes(packet[4:6], "big")
    if length < PARITY + 4 or length > MAX_CODEWORD:
        raise ValueError("invalid robust packet length")
    if len(packet) != HEADER_BYTES + length:
        raise ValueError("truncated or trailing robust packet data")
    try:
        corrected, _, _ = RSCodec(PARITY).decode(packet[HEADER_BYTES:])
    except (ReedSolomonError, ValueError, IndexError) as exc:
        raise ValueError("RS8 correction failed") from exc
    corrected = bytes(corrected)
    if len(corrected) < 4:
        raise ValueError("corrected payload too short")
    payload, checksum = corrected[:-4], corrected[-4:]
    if zlib.crc32(payload) != int.from_bytes(checksum, "big"):
        raise ValueError("robust packet checksum mismatch")
    return payload
