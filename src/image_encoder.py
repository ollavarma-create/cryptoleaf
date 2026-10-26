# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – image steganography encoder
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

"""Image steganography encoder – hybrid LSB / block-luminance.

Method selection
----------------
* **PNG, BMP, WEBP** (lossless) → LSB (Least Significant Bit).
  One bit hidden per RGB channel byte in raster order.
  ~100 % reliable round-trip; capacity ≈ width × height × 3 bits.
* **JPEG** (lossy) → Method B: block-based luminance (8×8 blocks, YCbCr space).
  Each 8×8 block carries one bit by shifting the centre pixel relative to
  the edge-pixel mean.  Hamming(7,4) + 3× replication provide error
  correction so the payload survives JPEG re-encoding at quality ≥ 70.

Public API
----------
encode_image(cover_path, payload, password, alpha, output_format) -> PIL.Image
capacity_bits(cover_path, chip_length, output_format) -> int
"""

import logging
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from .crypto import encrypt
from .error_correction import rs_encode, hamming_encode

logger = logging.getLogger(__name__)

__all__ = ["encode_image", "capacity_bits", "CapacityError", "FallbackToPNGWarning"]

# LSB header magic: "STGL"
_LSB_MAGIC = b"\x53\x54\x47\x4c"
# Block-luminance header magic: "STGB"
_BLOCK_MAGIC = b"\x53\x54\x47\x42"

_HEADER_VERSION = 2
_HEADER_LEN = 32          # bytes, before RS/Hamming encoding

# Lossless formats → LSB method
_LOSSLESS_FORMATS = frozenset({"PNG", "BMP", "WEBP"})

# Block-luminance constants (JPEG path)
# strength=50: empirically sufficient for JPEG q75+ survival while remaining
# imperceptible after JPEG's own quantisation spreads the impulse across the block.
_DEFAULT_BLOCK_STRENGTH = 50
_BLOCK_SIZE = 8
# Overhead factor: 8 bits/byte × (7/4 Hamming expansion) × 3 replication = 42 blocks/byte
_BLOCKS_PER_BYTE = 42
# Raw blocks needed to embed the fixed 32-byte header
_HEADER_BLOCKS = _HEADER_LEN * _BLOCKS_PER_BYTE   # = 1344


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class CapacityError(ValueError):
    """Raised when the payload exceeds the cover image's capacity."""


class FallbackToPNGWarning(UserWarning):
    """Issued when JPEG capacity is insufficient and encoding falls back to PNG."""


# ---------------------------------------------------------------------------
# Shared private helpers
# ---------------------------------------------------------------------------

def _build_header(magic: bytes, payload_len: int) -> bytes:
    """Build the 32-byte steganography header.

    Layout (big-endian):
      bytes 0-3  : magic (b'STGB' or b'STGL')
      bytes 4-7  : uint32 payload length (post-encryption, pre error-correction)
      byte  8    : uint8  version = 2
      bytes 9-31 : zero-filled reserved

    Args:
        magic: 4-byte magic bytes identifying the embedding method.
        payload_len: Length of payload bytes (after encryption).

    Returns:
        32-byte header.
    """
    header = bytearray(_HEADER_LEN)
    header[0:4] = magic
    struct.pack_into(">I", header, 4, payload_len)
    header[8] = _HEADER_VERSION
    return bytes(header)


def _bits_from_bytes(data: bytes) -> list[int]:
    """Convert bytes to a list of 0/1 integer bits (MSB first)."""
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


# ---------------------------------------------------------------------------
# LSB helpers
# ---------------------------------------------------------------------------

def _lsb_embed(img: Image.Image, bits: list[int]) -> Image.Image:
    """Embed *bits* into the LSB of RGB channel bytes in raster order.

    Args:
        img: Cover PIL Image (converted to RGB internally).
        bits: List of 0/1 integers to embed.

    Returns:
        New PIL RGB Image with bits embedded.

    Raises:
        CapacityError: If len(bits) exceeds total channel count.
    """
    arr = np.array(img.convert("RGB"), dtype=np.uint8)
    flat = arr.flatten()
    n = len(bits)
    if n > len(flat):
        raise CapacityError(
            f"Payload too large: need {n} bits but image has only {len(flat)} "
            "LSB positions. Use a larger cover image."
        )
    flat[:n] = (flat[:n] & np.uint8(0xFE)) | np.array(bits, dtype=np.uint8)
    return Image.fromarray(flat.reshape(arr.shape), mode="RGB")


def _encode_image_lsb(
    cover_path: Path,
    payload: bytes,
    password: str,
    output_format: str,
) -> Image.Image:
    """LSB embedding pipeline for lossless formats (PNG, BMP, WEBP).

    Pipeline:
      1. Optionally encrypt payload.
      2. RS-encode payload.
      3. Build 32-byte STGL header and RS-encode it.
      4. Embed all bits via LSB into RGB channel bytes.
      5. Return PIL Image.

    Args:
        cover_path: Path to the cover image.
        payload: Plaintext bytes to hide.
        password: AES password; empty string = no encryption.
        output_format: "PNG", "BMP", or "WEBP".

    Returns:
        PIL RGB Image with hidden payload.

    Raises:
        CapacityError: If payload + header exceed image LSB capacity.
    """
    logger.info(
        "encode_image [LSB]: cover='%s' payload=%d bytes fmt=%s encrypted=%s",
        cover_path.name, len(payload), output_format, bool(password),
    )

    encrypted_payload = encrypt(payload, password) if password else payload
    payload_len = len(encrypted_payload)

    rs_payload = rs_encode(encrypted_payload)
    logger.debug("encode_image [LSB]: RS-encoded payload: %d bytes.", len(rs_payload))

    header = _build_header(_LSB_MAGIC, payload_len)
    rs_header = rs_encode(header)
    logger.debug("encode_image [LSB]: RS-encoded header: %d bytes.", len(rs_header))

    all_bytes = rs_header + rs_payload
    bits = _bits_from_bytes(all_bytes)
    logger.debug(
        "encode_image [LSB]: %d bits to embed; first 16 bytes hex: %s",
        len(bits), all_bytes[:16].hex(),
    )

    with Image.open(cover_path) as img:
        cover = img.copy()

    stego = _lsb_embed(cover, bits)
    logger.info(
        "encode_image [LSB]: done, stego image %dx%d.", stego.width, stego.height
    )
    return stego


# ---------------------------------------------------------------------------
# Block-luminance helpers (JPEG Method B)
# ---------------------------------------------------------------------------

def _replicate3(bits: list[int]) -> list[int]:
    """Repeat each bit 3 times: [b0, b1, …] → [b0, b0, b0, b1, b1, b1, …].

    Args:
        bits: Input list of 0/1 integers.

    Returns:
        List of length 3 × len(bits).
    """
    out: list[int] = []
    for b in bits:
        out.extend([b, b, b])
    return out


def _embed_block_luminance(
    ycbcr_arr: np.ndarray,
    bits: list[int],
    strength: int,
) -> np.ndarray:
    """Embed one bit per 8×8 block by shifting the centre pixel vs edge mean.

    For bit=1: centre_Y = clip(edge_mean + strength, 0, 255)
    For bit=0: centre_Y = clip(edge_mean - strength, 0, 255)

    The decoder recovers bits as (centre_Y > edge_mean) → 1, else 0.
    Using edge_mean as the reference point (not the original centre value)
    guarantees correct extraction regardless of the block's original luma.

    Args:
        ycbcr_arr: HxWx3 uint8 array in YCbCr colour space (modified in place).
        bits: Encoded bits to embed (one per 8×8 block, in raster order).
        strength: Luma shift magnitude (default 25).

    Returns:
        Modified ycbcr_arr (same object, modified in place).
    """
    h, w = ycbcr_arr.shape[:2]
    bs = _BLOCK_SIZE
    cy = cx = bs // 2        # centre pixel inside block: (4, 4)
    bit_idx = 0

    # Start from the second row of blocks (y=bs) – the first row (y=0..7) is
    # particularly vulnerable to JPEG quantisation and consistently corrupts the
    # first magic byte even at quality 85.  The decoder skips the same row.
    for y in range(bs, h - bs + 1, bs):
        for x in range(0, w - bs + 1, bs):
            if bit_idx >= len(bits):
                return ycbcr_arr
            block_y = ycbcr_arr[y : y + bs, x : x + bs, 0].astype(np.int16)
            # Edge mean: all pixels except centre
            mask = np.ones((bs, bs), dtype=bool)
            mask[cy, cx] = False
            edge_mean = float(block_y[mask].mean())
            shift = strength if bits[bit_idx] else -strength
            block_y[cy, cx] = int(np.clip(edge_mean + shift, 0, 255))
            ycbcr_arr[y : y + bs, x : x + bs, 0] = block_y.astype(np.uint8)
            bit_idx += 1

    return ycbcr_arr


def _encode_image_block(
    cover_path: Path,
    payload: bytes,
    password: str,
    strength: int = _DEFAULT_BLOCK_STRENGTH,
) -> Image.Image:
    """Block-luminance (Method B) pipeline for JPEG output.

    Pipeline:
      1. Optionally encrypt payload.
      2. Build 32-byte STGB header.
      3. Concatenate header + encrypted payload → bits.
      4. Apply Hamming(7,4) encoding.
      5. Apply 3× replication.
      6. Check capacity; raise CapacityError if insufficient.
      7. Embed one bit per 8×8 block in Y channel.
      8. Return PIL RGB Image (save as JPEG q85 is the caller's responsibility).

    Error correction: Hamming(7,4) + 3× replication (no Reed-Solomon).

    Args:
        cover_path: Path to the cover image.
        payload: Plaintext bytes to hide.
        password: AES password; empty string = no encryption.
        strength: Luma shift magnitude per block (default 25).

    Returns:
        PIL RGB Image with hidden payload.

    Raises:
        CapacityError: If payload + header exceed block-luminance capacity.
    """
    logger.info(
        "encode_image [Block]: cover='%s' payload=%d bytes strength=%d encrypted=%s",
        cover_path.name, len(payload), strength, bool(password),
    )

    encrypted_payload = encrypt(payload, password) if password else payload
    payload_len = len(encrypted_payload)

    header = _build_header(_BLOCK_MAGIC, payload_len)
    full_data = header + encrypted_payload            # 32 + payload_len bytes
    raw_bits = _bits_from_bytes(full_data)            # (32 + payload_len) * 8 bits

    hamming_bits = hamming_encode(raw_bits)           # * 7/4 expansion
    encoded_bits = _replicate3(hamming_bits)          # * 3 replication

    n_bits_needed = len(encoded_bits)
    logger.debug(
        "encode_image [Block]: %d data bytes → %d encoded bits (%.1f× overhead)",
        len(full_data), n_bits_needed, n_bits_needed / (len(full_data) * 8),
    )

    with Image.open(cover_path) as img:
        orig_img = img.copy()

    w, h = orig_img.size
    # Usable blocks: subtract the entire first row (row 0) that is always skipped
    n_blocks = (w // _BLOCK_SIZE) * (max(0, h // _BLOCK_SIZE - 1))
    if n_bits_needed > n_blocks:
        # Compute usable bytes for the error message
        usable_bytes = max(0, n_blocks * 4 // 21 // 8 - _HEADER_LEN)
        raise CapacityError(
            f"Payload too large: need {n_bits_needed} blocks but cover image "
            f"({w}×{h}) provides only {n_blocks}. "
            f"Maximum message size: ~{usable_bytes} bytes."
        )

    ycbcr_arr = np.array(orig_img.convert("YCbCr"), dtype=np.uint8)
    ycbcr_arr = _embed_block_luminance(ycbcr_arr, encoded_bits, strength)
    stego_img = Image.fromarray(ycbcr_arr, mode="YCbCr").convert("RGB")

    logger.info(
        "encode_image [Block]: done, stego image %dx%d.", stego_img.width, stego_img.height
    )
    return stego_img


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capacity_bits(
    cover_path: str | Path,
    chip_length: int = 64,
    output_format: str = "PNG",
) -> int:
    """Return the embeddable bit capacity for a given cover image and format.

    For lossless formats (PNG, BMP, WEBP): capacity = width × height × 3
    (one LSB per RGB channel byte).

    For JPEG (Method B): capacity = (w//8 × h//8) × 4 // 21
    (usable bits after Hamming(7,4) + 3× replication overhead).
    The returned value includes the 32-byte header; subtract 32 bytes to get
    the net message capacity.

    Args:
        cover_path: Path to the cover image.
        chip_length: Unused (kept for API compatibility).
        output_format: Target output format string.

    Returns:
        Number of bits that can be embedded (including header overhead).
    """
    output_format = output_format.upper()
    with Image.open(cover_path) as img:
        w, h = img.width, img.height
        if output_format in _LOSSLESS_FORMATS:
            n_bits = w * h * 3
            logger.debug(
                "capacity_bits [LSB]: %dx%d×3 → %d bits", w, h, n_bits,
            )
            return n_bits

    # JPEG – Method B block count (first row always skipped)
    n_blocks = (w // _BLOCK_SIZE) * (max(0, h // _BLOCK_SIZE - 1))
    n_bits = n_blocks * 4 // 21
    logger.debug(
        "capacity_bits [Block]: %dx%d → %d usable blocks (first row skipped) → %d bits",
        w, h, n_blocks, n_bits,
    )
    return n_bits


def encode_image(
    cover_path: str | Path,
    payload: bytes,
    password: str = "",
    alpha: float = 1.0,
    output_format: str = "PNG",
) -> "tuple[Image.Image, str]":
    """Embed *payload* into the cover image.

    Dispatches to the appropriate method based on *output_format*:

    * PNG / BMP / WEBP → LSB embedding (reliable, high-capacity, lossless only).
    * JPEG             → Method B: block-based luminance (8×8 blocks, YCbCr).
                         Survives JPEG re-encoding at quality ≥ 70.
                         *alpha* is ignored for this path.
                         If the image is too small for Method B, automatically
                         falls back to LSB/PNG and returns "PNG" as the format.

    Args:
        cover_path: Path to the cover image file.
        payload: Plaintext bytes to hide.
        password: Optional AES-CBC password. Must never appear in logs.
        alpha: Embedding strength (unused for JPEG/Method B).
        output_format: Target format string ("PNG", "JPEG", "BMP", "WEBP").

    Returns:
        ``(PIL Image, actual_output_format)`` – actual format may differ from
        *output_format* when JPEG falls back to PNG.

    Raises:
        CapacityError: Payload exceeds image capacity for the chosen method
            (only raised for lossless formats; JPEG falls back to PNG instead).
        ValueError: Unsupported format.
    """
    import warnings

    cover_path = Path(cover_path)
    output_format = output_format.upper()

    if output_format in _LOSSLESS_FORMATS:
        return _encode_image_lsb(cover_path, payload, password, output_format), output_format

    # JPEG path – Method B block luminance; fall back to LSB/PNG if too small
    try:
        return _encode_image_block(cover_path, payload, password), "JPEG"
    except CapacityError as exc:
        logger.warning(
            "encode_image: JPEG capacity exceeded (%s); falling back to LSB/PNG.", exc
        )
        warnings.warn(
            f"JPEG image too small for payload – saved as PNG instead. ({exc})",
            FallbackToPNGWarning,
            stacklevel=2,
        )
        return _encode_image_lsb(cover_path, payload, password, "PNG"), "PNG"
