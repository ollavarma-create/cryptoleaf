# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – image steganography decoder
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

"""Image steganography decoder – LSB / DWT+spread-spectrum / block-luminance.

decode_image() tries methods in sequence until one succeeds:
  1. LSB        (STGL magic) – PNG/BMP/WEBP produced by this tool.
  2. DWT+SS     (STG2 magic) – JPEG produced by an older version of this tool.
  3. Block-lum. (STGB magic) – JPEG produced by Method B (current version).

Public API
----------
decode_image(stego, password, chip_length) -> bytes
"""

import hashlib
import logging
import struct
from pathlib import Path

import numpy as np
import pywt
from PIL import Image

from reedsolo import ReedSolomonError

from .crypto import decrypt
from .error_correction import rs_encode, rs_decode, hamming_decode

logger = logging.getLogger(__name__)

__all__ = ["decode_image", "BadMagicError"]

# DWT+SS magic: "STG2" (legacy – produced by older versions of this tool)
_MAGIC = b"\x53\x54\x47\x32"
# LSB magic: "STGL"
_LSB_MAGIC = b"\x53\x54\x47\x4c"
# Block-luminance magic: "STGB"
_BLOCK_MAGIC = b"\x53\x54\x47\x42"

_HEADER_LEN = 32
_DEFAULT_CHIP_LENGTH = 64
_WAVELET = "db1"
_DWT_LEVEL = 2

# Block-luminance constants (must match image_encoder._BLOCKS_PER_BYTE)
_BLOCK_SIZE = 8
_BLOCKS_PER_BYTE = 42    # 8 bits × (7/4 Hamming) × 3 replication
_HEADER_BLOCKS = _HEADER_LEN * _BLOCKS_PER_BYTE   # = 1344


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class BadMagicError(ValueError):
    """Raised when no recognised magic bytes are found in the stego image."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _bits_to_bytes(bits: list[int]) -> bytes:
    """Convert a flat list of 0/1 bits (MSB-first) to bytes."""
    if len(bits) % 8 != 0:
        raise ValueError(f"bit count {len(bits)} must be a multiple of 8")
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        out.append(byte)
    return bytes(out)


def _decrypt_if_needed(data: bytes, password: str, method: str) -> bytes:
    """Optionally AES-decrypt *data* and log the result."""
    if password:
        plaintext = decrypt(data, password)
        logger.info("decode_image [%s]: decrypted %d bytes", method, len(plaintext))
    else:
        plaintext = data
        logger.info(
            "decode_image [%s]: recovered %d bytes (no encryption)", method, len(plaintext)
        )
    return plaintext


# ---------------------------------------------------------------------------
# LSB decoder
# ---------------------------------------------------------------------------

def _decode_image_lsb(img: Image.Image, password: str) -> bytes:
    """Extract a payload embedded with the LSB method (STGL magic).

    Reads bits from the LSB of every RGB channel byte in raster order.

    Args:
        img: RGB stego image.
        password: AES password (empty = no decryption).

    Returns:
        Plaintext payload bytes.

    Raises:
        BadMagicError: STGL magic not found – image was not LSB-encoded.
        ReedSolomonError: RS parity check fails.
        ValueError: Decryption fails (wrong password).
    """
    flat = np.array(img.convert("RGB"), dtype=np.uint8).flatten()

    # Extract and decode header
    rs_header_len = len(rs_encode(bytes(_HEADER_LEN)))
    n_header_bits = rs_header_len * 8
    header_rs_bytes = _bits_to_bytes((flat[:n_header_bits] & 1).tolist())
    logger.debug(
        "decode_image [LSB]: first 16 bytes of raw header RS: %s",
        header_rs_bytes[:16].hex(),
    )
    header_bytes = rs_decode(header_rs_bytes)

    if header_bytes[:4] != _LSB_MAGIC:
        raise BadMagicError(
            f"STGL magic not found – got {header_bytes[:4]!r}."
        )

    payload_len = struct.unpack_from(">I", header_bytes, 4)[0]
    logger.debug("decode_image [LSB]: payload_len=%d bytes", payload_len)

    # Extract and decode payload (immediately after header bits in the flat array)
    rs_payload_len = len(rs_encode(bytes(payload_len)))
    n_payload_bits = rs_payload_len * 8
    payload_bits = (flat[n_header_bits: n_header_bits + n_payload_bits] & 1).tolist()
    payload_rs_bytes = _bits_to_bytes(payload_bits)
    encrypted_payload = rs_decode(payload_rs_bytes)

    return _decrypt_if_needed(encrypted_payload, password, "LSB")


# ---------------------------------------------------------------------------
# DWT + spread-spectrum decoder
# ---------------------------------------------------------------------------

def _build_prng(password: str) -> np.random.Generator:
    """Seed a numpy Generator from SHA-256 of *password*.

    Must produce an identical sequence to image_encoder._build_prng.
    Uses seed 0 when *password* is empty.
    """
    if not password:
        logger.debug("_build_prng: seed=0 (no password)")
        return np.random.default_rng(0)
    digest = hashlib.sha256(password.encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    logger.debug("_build_prng: seed=%d (password supplied)", seed)
    return np.random.default_rng(seed)


def _spread_extract(
    flat: np.ndarray,
    n_bits: int,
    rng: np.random.Generator,
    chip_length: int,
) -> list[int]:
    """Extract *n_bits* from *flat* using the same PRNG sequence as the encoder.

    Args:
        flat: Combined cH2+cV2 coefficient array (read-only).
        n_bits: How many bits to extract.
        rng: Seeded PRNG (state advanced in-place; must match encoder state).
        chip_length: Spread-spectrum chip length.

    Returns:
        List of 0/1 integers (MSB first).
    """
    bits: list[int] = []
    n = len(flat)
    for _ in range(n_bits):
        indices = rng.integers(0, n, size=chip_length)
        chip_seq = rng.choice([-1.0, 1.0], size=chip_length)
        correlation = np.sum(flat[indices] * chip_seq)
        bits.append(1 if correlation > 0 else 0)
    return bits


def _decode_image_dwt(
    img: Image.Image,
    password: str,
    chip_length: int,
) -> bytes:
    """Extract a payload embedded with the DWT+spread-spectrum method (STG2 magic).

    Args:
        img: RGB stego image.
        password: AES password (empty = no decryption).
        chip_length: Spread-spectrum chip length (must match encoder).

    Returns:
        Plaintext payload bytes.

    Raises:
        BadMagicError: STG2 magic not found.
        ReedSolomonError: RS parity check fails.
        ValueError: Decryption fails (wrong password).
    """
    # Y luma channel
    ycbcr = img.convert("YCbCr")
    Y = np.array(ycbcr, dtype=np.float64)[:, :, 0]
    logger.debug("decode_image [DWT]: Y channel shape %s", Y.shape)

    # Level-2 DWT
    coeffs = pywt.wavedec2(Y, wavelet=_WAVELET, level=_DWT_LEVEL)
    _, (cH2, cV2, _), _ = coeffs
    logger.debug("decode_image [DWT]: cH2 %s cV2 %s", cH2.shape, cV2.shape)

    combined_flat = np.concatenate([cH2.flatten(), cV2.flatten()])

    rng = _build_prng(password)
    logger.debug(
        "decode_image [DWT]: chip_length=%d wavelet=%s level=%d",
        chip_length, _WAVELET, _DWT_LEVEL,
    )

    # Extract and decode header
    rs_header_len = len(rs_encode(bytes(_HEADER_LEN)))
    n_header_bits = rs_header_len * 8
    logger.debug("decode_image [DWT]: extracting %d header bits", n_header_bits)

    header_bits = _spread_extract(combined_flat, n_header_bits, rng, chip_length)
    header_rs_bytes = _bits_to_bytes(header_bits)
    logger.debug(
        "decode_image [DWT]: first 16 bytes of raw header RS: %s",
        header_rs_bytes[:16].hex(),
    )
    header_bytes = rs_decode(header_rs_bytes)

    if header_bytes[:4] != _MAGIC:
        raise BadMagicError(
            f"STG2 magic not found – got {header_bytes[:4]!r}. "
            "Image may not contain a hidden payload, or data is too corrupted."
        )

    payload_len = struct.unpack_from(">I", header_bytes, 4)[0]
    logger.debug("decode_image [DWT]: payload_len=%d bytes", payload_len)

    # Extract and decode payload
    rs_payload_len = len(rs_encode(bytes(payload_len)))
    n_payload_bits = rs_payload_len * 8
    logger.debug("decode_image [DWT]: extracting %d payload bits", n_payload_bits)

    payload_bits = _spread_extract(combined_flat, n_payload_bits, rng, chip_length)
    payload_rs_bytes = _bits_to_bytes(payload_bits)
    encrypted_payload = rs_decode(payload_rs_bytes)

    return _decrypt_if_needed(encrypted_payload, password, "DWT")


# ---------------------------------------------------------------------------
# Block-luminance decoder (JPEG Method B)
# ---------------------------------------------------------------------------

def _extract_block_raw_bits(img: Image.Image) -> list[int]:
    """Extract one raw bit per 8×8 block from the Y luma channel.

    Decision rule: centre_pixel > edge_mean → 1, else → 0.
    Blocks are visited in raster order (left-to-right, top-to-bottom).

    Args:
        img: PIL Image (any mode; converted to YCbCr internally).

    Returns:
        List of 0/1 integers, one per available 8×8 block.
    """
    ycbcr = np.array(img.convert("YCbCr"), dtype=np.float64)
    h, w = ycbcr.shape[:2]
    bs = _BLOCK_SIZE
    cy = cx = bs // 2
    mask = np.ones((bs, bs), dtype=bool)
    mask[cy, cx] = False

    bits: list[int] = []
    # Start from the second row of blocks (y=bs) – must match encoder which
    # skips the first row to avoid JPEG quantisation corruption of magic bytes.
    for y in range(bs, h - bs + 1, bs):
        for x in range(0, w - bs + 1, bs):
            block = ycbcr[y : y + bs, x : x + bs, 0]
            centre = block[cy, cx]
            edge_mean = block[mask].mean()
            bits.append(1 if centre > edge_mean else 0)
    return bits


def _majority_vote(bits: list[int]) -> list[int]:
    """Reduce a 3× replicated bit stream to one bit per triplet (majority vote).

    Args:
        bits: List of 0/1 integers (length must be a multiple of 3).

    Returns:
        List of 0/1 integers (length = len(bits) // 3).

    Raises:
        ValueError: If len(bits) is not a multiple of 3.
    """
    if len(bits) % 3 != 0:
        raise ValueError(
            f"_majority_vote: bit count {len(bits)} must be a multiple of 3"
        )
    out: list[int] = []
    for i in range(0, len(bits), 3):
        out.append(1 if (bits[i] + bits[i + 1] + bits[i + 2]) >= 2 else 0)
    return out


def _decode_image_block(img: Image.Image, password: str) -> bytes:
    """Extract a payload embedded with Method B (block-luminance, STGB magic).

    Two-pass decoding:
      Pass 1 – header: read first 1344 raw bits, vote, Hamming-decode
               → 32-byte STGB header, parse payload_len.
      Pass 2 – payload: read next payload_len × 42 raw bits, vote,
               Hamming-decode → encrypted payload bytes.

    Args:
        img: PIL Image (any mode).
        password: AES password (empty = no decryption).

    Returns:
        Plaintext payload bytes.

    Raises:
        BadMagicError: STGB magic not found.
        ValueError: Decryption fails (wrong password or corrupted data).
    """
    raw_bits = _extract_block_raw_bits(img)
    logger.debug("decode_image [Block]: extracted %d raw bits from blocks", len(raw_bits))

    # --- Pass 1: decode header ---
    if len(raw_bits) < _HEADER_BLOCKS:
        raise BadMagicError(
            f"Image too small for block-luminance header: "
            f"need {_HEADER_BLOCKS} blocks, got {len(raw_bits)}."
        )
    header_voted = _majority_vote(raw_bits[:_HEADER_BLOCKS])   # → 448 bits
    header_bits = hamming_decode(header_voted)                   # → 256 bits
    header_bytes = _bits_to_bytes(header_bits)

    logger.debug(
        "decode_image [Block]: header raw first 16 hex: %s", header_bytes[:16].hex()
    )

    if header_bytes[:4] != _BLOCK_MAGIC:
        raise BadMagicError(
            f"STGB magic not found – got {header_bytes[:4]!r}. "
            "Image was not encoded with Method B."
        )

    payload_len = struct.unpack_from(">I", header_bytes, 4)[0]
    logger.debug("decode_image [Block]: payload_len=%d bytes", payload_len)

    # --- Pass 2: decode payload ---
    payload_raw_count = payload_len * _BLOCKS_PER_BYTE   # payload_len × 42
    start = _HEADER_BLOCKS
    end = start + payload_raw_count
    if len(raw_bits) < end:
        raise BadMagicError(
            f"Stego image too small to hold declared payload of {payload_len} bytes "
            f"(need {end} blocks, have {len(raw_bits)})."
        )
    payload_voted = _majority_vote(raw_bits[start:end])   # → payload_len × 14 bits
    payload_bits = hamming_decode(payload_voted)           # → payload_len × 8 bits
    encrypted_payload = _bits_to_bytes(payload_bits)

    return _decrypt_if_needed(encrypted_payload, password, "Block")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decode_image(
    stego: "str | Path | Image.Image",
    password: str = "",
    chip_length: int = _DEFAULT_CHIP_LENGTH,
) -> bytes:
    """Extract a hidden payload from a stego image.

    Tries three methods in sequence until one succeeds:
      1. LSB        (STGL magic) – fast, for PNG/BMP/WEBP.
      2. DWT+SS     (STG2 magic) – backward compat for older JPEG embeds.
      3. Block-lum. (STGB magic) – current JPEG Method B.

    Args:
        stego: File path to the stego image, or an already-opened PIL Image.
        password: Password used during encoding (empty string for no encryption).
        chip_length: Spread-spectrum chip length (DWT path only).

    Returns:
        The original plaintext payload bytes.

    Raises:
        BadMagicError: No recognised magic found – not a stego image produced
            by this tool, or data is too corrupted to recover.
        ReedSolomonError: RS parity check fails (LSB or DWT paths).
        ValueError: Decryption fails – wrong password or corrupted ciphertext.
    """
    # Load image once; all decoders work from a PIL Image
    if isinstance(stego, (str, Path)):
        logger.info("decode_image: opening '%s'", stego)
        with Image.open(stego) as img:
            img = img.convert("RGB")
    else:
        img = stego.convert("RGB")

    # 1. Try LSB (lossless PNG/BMP/WEBP).
    # Catch ReedSolomonError: random LSBs in a JPEG produce undecodable RS
    # codewords before we even check the magic bytes.
    try:
        return _decode_image_lsb(img, password)
    except (BadMagicError, ReedSolomonError) as exc:
        logger.debug("decode_image: LSB failed (%s), trying DWT", type(exc).__name__)

    # 2. Try DWT+spread-spectrum (legacy JPEG embeds with STG2 magic).
    try:
        return _decode_image_dwt(img, password, chip_length)
    except (BadMagicError, ReedSolomonError) as exc:
        logger.debug("decode_image: DWT failed (%s), trying block-luminance", type(exc).__name__)

    # 3. Try block-luminance Method B (current JPEG path, STGB magic).
    return _decode_image_block(img, password)
