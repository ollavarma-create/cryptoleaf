# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – LSB audio steganography encoder
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

"""LSB audio steganography encoder.

Embeds payload in the least-significant bit of each PCM int16 sample (channel 0).
Reed-Solomon protects both the header and the payload.

Public API
----------
encode_audio(cover_path, payload, password, alpha, chip_length) -> (np.ndarray, int)
capacity_bits_audio(cover_path, chip_length) -> int

Pipeline
--------
raw bytes
  → crypto.encrypt()            (only if password given)
  → error_correction.rs_encode()
  → prepend 32-byte STGA header → rs_encode header
  → embed bit stream in LSB of int16 channel-0 samples
  → return (stego_float64, samplerate)

Notes
-----
* alpha and chip_length are accepted for API compatibility but ignored.
* Only channel 0 carries the payload; all other channels are left intact.
* Output is returned as float64 in [-1, 1] (divided by 32767) for sf.write.
* Header version 4 identifies this LSB method.
"""

import logging
import struct
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from .crypto import encrypt
from .error_correction import rs_encode

logger = logging.getLogger(__name__)

__all__ = ["encode_audio", "capacity_bits_audio", "AudioCapacityError"]

_MAGIC = b"\x53\x54\x47\x41"   # "STGA"
_HEADER_VERSION = 4              # 4 = LSB method
_HEADER_LEN = 32
_RS_NSYM = 64                    # parity bytes per RS block


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class AudioCapacityError(ValueError):
    """Raised when the payload exceeds the cover audio's bit capacity."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_header(payload_len: int, samplerate: int) -> bytes:
    """Build the 32-byte STGA header.

    Layout (big-endian):
      bytes 0-3  : magic b'STGA'
      bytes 4-7  : uint32 payload length (post-encryption, pre-RS)
      byte  8    : uint8  version = 4
      bytes 9-12 : uint32 samplerate
      bytes 13-31: zero-filled reserved
    """
    header = bytearray(_HEADER_LEN)
    header[0:4] = _MAGIC
    struct.pack_into(">I", header, 4, payload_len)
    header[8] = _HEADER_VERSION
    struct.pack_into(">I", header, 9, samplerate)
    return bytes(header)


def _bits_from_bytes(data: bytes) -> list[int]:
    """Convert bytes to a list of 0/1 integer bits (MSB first)."""
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capacity_bits_audio(
    cover_path: "str | Path",
    chip_length: int = 4096,
) -> int:
    """Return the usable bit capacity for a given cover audio file.

    Capacity = number of samples in channel 0 (1 bit per sample, LSB).

    Args:
        cover_path: Path to the cover audio file.
        chip_length: Accepted for API compatibility; ignored.

    Returns:
        Number of bits that can be embedded.
    """
    data, _ = sf.read(cover_path, dtype="int16", always_2d=True)
    n_bits = len(data)
    logger.debug("capacity_bits_audio: n_samples=%d → %d bits", n_bits, n_bits)
    return n_bits


def encode_audio(
    cover_path: "str | Path",
    payload: bytes,
    password: str = "",
    alpha: Optional[float] = None,
    chip_length: Optional[int] = None,
) -> "tuple[np.ndarray, int]":
    """Embed *payload* into the cover audio using LSB steganography.

    Processing pipeline:
      1. Load cover audio as int16; extract channel 0.
      2. Optionally encrypt payload with AES-CBC (crypto.encrypt).
      3. Reed-Solomon encode the (possibly encrypted) payload.
      4. Build 32-byte STGA header (version 4, with samplerate) and RS-encode it.
      5. Assemble header + payload bit stream.
      6. Check bit capacity (raises AudioCapacityError if insufficient).
      7. Embed bits in LSB of int16 channel-0 samples.
      8. Return (stego_float64, samplerate).

    Args:
        cover_path: Path to the cover audio file (WAV or FLAC).
        payload: Plaintext bytes to hide.
        password: Optional password for AES-CBC encryption.
        alpha: Accepted for API compatibility; ignored.
        chip_length: Accepted for API compatibility; ignored.

    Returns:
        Tuple ``(stego_data, samplerate)`` where *stego_data* is a float64
        numpy array of the same shape as the cover audio, values in [-1, 1].

    Raises:
        AudioCapacityError: If the encoded payload exceeds audio capacity.
    """
    cover_path = Path(cover_path)

    # Step 1: load cover audio as int16
    data, samplerate = sf.read(cover_path, dtype="int16", always_2d=True)
    ch0 = data[:, 0].copy()
    n_audio = len(ch0)

    logger.info(
        "encode_audio: cover='%s' payload=%d bytes samplerate=%d encrypted=%s",
        cover_path.name, len(payload), samplerate, bool(password),
    )

    # Step 2: optional encryption
    encrypted_payload = encrypt(payload, password) if password else payload
    payload_len = len(encrypted_payload)

    # Step 3: RS-encode payload
    rs_payload = rs_encode(encrypted_payload, nsym=_RS_NSYM)
    logger.debug("RS-encoded payload: %d bytes.", len(rs_payload))

    # Step 4: build and RS-encode header
    header = _build_header(payload_len, samplerate)
    rs_header = rs_encode(header, nsym=_RS_NSYM)
    logger.debug("RS-encoded header: %d bytes.", len(rs_header))

    # Step 5: assemble bit stream (header first, then payload)
    bits = _bits_from_bytes(rs_header + rs_payload)
    n_bits_needed = len(bits)
    logger.debug("Total bits to embed: %d (capacity: %d).", n_bits_needed, n_audio)

    # Step 6: capacity check
    if n_bits_needed > n_audio:
        raise AudioCapacityError(
            f"Payload too large: need {n_bits_needed} bits but cover capacity is "
            f"{n_audio} bits. Reduce payload or use a longer cover audio file."
        )

    # Step 7: embed LSBs
    bits_arr = np.array(bits, dtype=np.int16)
    ch0[:n_bits_needed] = (ch0[:n_bits_needed] & np.int16(-2)) | bits_arr

    # Step 8: replace channel 0 and return as float64
    stego = data.copy()
    stego[:, 0] = ch0
    stego_float = stego.astype(np.float64) / 32768.0

    logger.info(
        "encode_audio: done, %d samples %d-channel at %d Hz.",
        stego.shape[0], stego.shape[1], samplerate,
    )
    return stego_float, samplerate


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    _DEFAULT_MESSAGE = "The Little Brown Fox Jumped Over The Lazy Dog 1234567890 Times"

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Cryptoleaf audio steganography encoder (LSB)"
    )
    parser.add_argument("cover", help="Cover audio file (WAV or FLAC)")
    parser.add_argument(
        "--message",
        default=_DEFAULT_MESSAGE,
        help=f"Message to embed (default: '{_DEFAULT_MESSAGE}')",
    )
    parser.add_argument("--password", default="", help="AES-CBC encryption password (optional)")
    args = parser.parse_args()

    cover_path = Path(args.cover)
    out_wav = cover_path.parent / f"enc_{cover_path.stem}.wav"

    print(f"Message : {args.message!r}")
    print(f"Cover   : {cover_path}")
    print(f"Output  : {out_wav}")

    stego_data, sr = encode_audio(
        cover_path,
        args.message.encode("utf-8"),
        password=args.password,
    )

    sf.write(str(out_wav), stego_data, sr, subtype="PCM_16")
    print(f"Wrote WAV: {out_wav}")
