# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – Reed-Solomon error correction wrapper
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Thin wrapper around reedsolo.RSCodec.

Uses RSCodec(64) by default: 64 parity bytes per 255-byte block, corrects up
to 32 byte errors per block (~34 % overhead).  The higher parity overhead is
needed for MP3 robustness: after a 128 kbps MP3 round-trip the typical byte
error rate is ~17–18 per block, which exceeds the 16-byte capacity of nsym=32.
"""

import logging
from reedsolo import RSCodec, ReedSolomonError

logger = logging.getLogger(__name__)

__all__ = ["rs_encode", "rs_decode", "ReedSolomonError", "hamming_encode", "hamming_decode"]


def rs_encode(data: bytes, nsym: int = 64) -> bytes:
    """Encode *data* with Reed-Solomon parity bytes.

    Args:
        data: Raw bytes to protect.
        nsym: Number of parity bytes per 255-byte block (default 64).

    Returns:
        Encoded bytes (data + parity interleaved by block).
    """
    codec = RSCodec(nsym)
    encoded = bytes(codec.encode(data))
    logger.debug("RS encode: %d bytes → %d bytes (nsym=%d)", len(data), len(encoded), nsym)
    return encoded


def hamming_encode(bits: list[int]) -> list[int]:
    """Hamming(7,4) encoder: every 4 data bits → 7-bit codeword.

    Codeword layout (1-indexed positions):
      pos 1 (p1): parity of positions 1,3,5,7 → p1 = d1⊕d2⊕d4
      pos 2 (p2): parity of positions 2,3,6,7 → p2 = d1⊕d3⊕d4
      pos 3 (d1): first data bit
      pos 4 (p3): parity of positions 4,5,6,7 → p3 = d2⊕d3⊕d4
      pos 5 (d2): second data bit
      pos 6 (d3): third data bit
      pos 7 (d4): fourth data bit

    Input is padded with zeros to the next multiple of 4 if needed.

    Args:
        bits: List of 0/1 integers to encode.

    Returns:
        List of 0/1 integers (length = ceil(len(bits)/4) * 7).
    """
    remainder = len(bits) % 4
    if remainder:
        bits = bits + [0] * (4 - remainder)

    out: list[int] = []
    for i in range(0, len(bits), 4):
        d1, d2, d3, d4 = bits[i], bits[i + 1], bits[i + 2], bits[i + 3]
        p1 = d1 ^ d2 ^ d4
        p2 = d1 ^ d3 ^ d4
        p3 = d2 ^ d3 ^ d4
        out.extend([p1, p2, d1, p3, d2, d3, d4])

    logger.debug("hamming_encode: %d bits → %d bits", len(bits), len(out))
    return out


def hamming_decode(bits: list[int]) -> list[int]:
    """Hamming(7,4) decoder with single-bit error correction.

    Each 7-bit codeword is decoded to 4 data bits.  If the syndrome
    indicates a single-bit error, that bit is flipped before extraction.

    Args:
        bits: List of 0/1 integers (length must be a multiple of 7).

    Returns:
        List of 0/1 data bits (length = len(bits) // 7 * 4).

    Raises:
        ValueError: If len(bits) is not a multiple of 7.
    """
    if len(bits) % 7 != 0:
        raise ValueError(
            f"hamming_decode: bit count {len(bits)} must be a multiple of 7"
        )

    out: list[int] = []
    errors_corrected = 0
    for i in range(0, len(bits), 7):
        cw = list(bits[i : i + 7])
        # Syndrome: s1*1 + s2*2 + s3*4 gives the 1-indexed error position (0 = no error)
        s1 = cw[0] ^ cw[2] ^ cw[4] ^ cw[6]  # covers positions 1,3,5,7
        s2 = cw[1] ^ cw[2] ^ cw[5] ^ cw[6]  # covers positions 2,3,6,7
        s3 = cw[3] ^ cw[4] ^ cw[5] ^ cw[6]  # covers positions 4,5,6,7
        err = s1 + 2 * s2 + 4 * s3
        if err:
            cw[err - 1] ^= 1
            errors_corrected += 1
        # Data bits are at 0-indexed positions 2 (d1), 4 (d2), 5 (d3), 6 (d4)
        out.extend([cw[2], cw[4], cw[5], cw[6]])

    if errors_corrected:
        logger.debug("hamming_decode: corrected %d single-bit errors", errors_corrected)
    return out


def rs_decode(data: bytes, nsym: int = 64) -> bytes:
    """Decode and error-correct *data* using Reed-Solomon.

    Args:
        data: Encoded bytes (as returned by rs_encode).
        nsym: Must match the value used during encoding (default 64).

    Returns:
        Original data bytes with errors corrected.

    Raises:
        ReedSolomonError: If errors exceed the correction capacity.
    """
    codec = RSCodec(nsym)
    decoded_tuple = codec.decode(data)
    # reedsolo.decode() returns (decoded, decoded_msgecc, errata_pos)
    decoded = bytes(decoded_tuple[0])
    logger.debug("RS decode: %d bytes → %d bytes (nsym=%d)", len(data), len(decoded), nsym)
    return decoded
