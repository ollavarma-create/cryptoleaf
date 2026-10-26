# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – LSB audio steganography decoder
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

"""LSB audio steganography decoder.

Extracts payload from the least-significant bit of each PCM int16 sample (channel 0).
Mirrors encode_audio exactly in reverse.

Public API
----------
decode_audio(stego, password, chip_length) -> bytes

Pipeline
--------
stego audio
  → channel-0 samples as int16
  → extract LSBs
  → Phase 1: read RS-encoded header bits → RS-decode → validate STGA magic + version
  → read payload_len from header
  → Phase 2: read RS-encoded payload bits → RS-decode
  → crypto.decrypt()  (only if password given)
  → return plaintext bytes

Notes
-----
* chip_length is accepted for API compatibility but ignored.
* Input may be a file path, a float64 numpy array (converted to int16), or a tuple.
"""

import logging
import struct
from pathlib import Path

import numpy as np
import soundfile as sf
from .crypto import decrypt
from .error_correction import rs_encode, rs_decode

logger = logging.getLogger(__name__)

__all__ = ["decode_audio", "BadAudioMagicError"]

_MAGIC = b"\x53\x54\x47\x41"   # "STGA"
_HEADER_LEN = 32
_HEADER_VERSION = 4
_RS_NSYM = 64

# RS-encoded header is always a fixed size: 32 data + 64 parity = 96 bytes
_RS_HEADER_BYTES = len(rs_encode(bytes(_HEADER_LEN), nsym=_RS_NSYM))  # 96


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class BadAudioMagicError(ValueError):
    """Raised when the decoded header does not start with the STGA magic bytes."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _bits_to_bytes(bits: "list[int] | np.ndarray") -> bytes:
    """Convert a flat sequence of 0/1 bits (MSB-first) to bytes."""
    bits = list(bits)
    if len(bits) % 8 != 0:
        raise ValueError(f"bit count {len(bits)} must be a multiple of 8")
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | int(bits[i + j])
        out.append(byte)
    return bytes(out)


def _load_ch0_int16(
    stego: "str | Path | np.ndarray | tuple",
) -> "tuple[np.ndarray, int]":
    """Return (channel-0 int16 array, samplerate) from various input types.

    Accepted forms:
      * str / Path                   – read from file via soundfile (int16)
      * np.ndarray float64 (N,) or (N,C) – multiply by 32767 → int16
      * tuple (np.ndarray, int)      – (data, samplerate), data converted to int16
    """
    if isinstance(stego, (str, Path)):
        data, sr = sf.read(stego, dtype="int16", always_2d=True)
        return data[:, 0], sr

    if isinstance(stego, tuple):
        arr = np.asarray(stego[0])
        sr = int(stego[1])
    else:
        arr = np.asarray(stego)
        sr = 44100

    if arr.ndim == 1:
        arr = arr[:, np.newaxis]

    # Convert float → int16 if needed
    if arr.dtype.kind == "f":
        arr = np.round(arr * 32768.0).clip(-32768, 32767).astype(np.int16)
    else:
        arr = arr.astype(np.int16)

    return arr[:, 0], sr


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decode_audio(
    stego: "str | Path | np.ndarray | tuple",
    password: str = "",
    chip_length: int = 4096,
) -> bytes:
    """Extract a hidden payload from a stego audio object.

    Mirrors encode_audio exactly in reverse:
      1. Load stego audio; extract channel-0 as int16.
      2. Extract all LSBs.
      3. Phase 1: read first _RS_HEADER_BYTES*8 bits → bytes → RS-decode → validate.
      4. Read payload_len from header bytes 4-7.
      5. Phase 2: read next rs_payload_bytes*8 bits → bytes → RS-decode.
      6. If password given, AES-decrypt the payload.
      7. Return plaintext bytes.

    Args:
        stego: Stego audio as a file path (str/Path), a 1-D or 2-D numpy
            array, or a (np.ndarray, samplerate) tuple as returned by
            encode_audio.
        password: Password used during encoding (empty string = no encryption).
        chip_length: Accepted for API compatibility; ignored.

    Returns:
        The original plaintext payload bytes.

    Raises:
        BadAudioMagicError: Header magic is not STGA or version is wrong.
        ReedSolomonError: RS parity check fails – data too corrupted to recover.
        ValueError: Decryption fails – wrong password or corrupted ciphertext.
    """
    if isinstance(stego, (str, Path)):
        logger.info("decode_audio: opening '%s'", stego)

    # Step 1: load channel 0 as int16
    ch0, samplerate = _load_ch0_int16(stego)
    logger.debug("decode_audio: channel-0 shape %s  samplerate=%d", ch0.shape, samplerate)

    # Step 2: extract all LSBs at once
    lsbs = (ch0 & np.int16(1)).astype(np.uint8)

    # Step 3: Phase 1 – extract and decode RS-protected header
    n_header_bits = _RS_HEADER_BYTES * 8   # 768 bits
    if len(lsbs) < n_header_bits:
        raise BadAudioMagicError(
            "Audio file is too short to contain a valid STGA header."
        )

    header_rs_bytes = _bits_to_bytes(lsbs[:n_header_bits])
    header_bytes = rs_decode(header_rs_bytes, nsym=_RS_NSYM)

    if header_bytes[:4] != _MAGIC:
        raise BadAudioMagicError(
            f"STGA magic not found – got {header_bytes[:4]!r}. "
            "Audio may not contain a hidden payload, or data is too corrupted."
        )

    version = header_bytes[8]
    if version != _HEADER_VERSION:
        raise BadAudioMagicError(
            f"Unsupported header version {version} (expected {_HEADER_VERSION}). "
            "File may have been encoded with a different version of Cryptoleaf."
        )

    payload_len = struct.unpack_from(">I", header_bytes, 4)[0]
    logger.debug("decode_audio: payload_len=%d bytes", payload_len)

    # Step 5: Phase 2 – extract and decode RS-protected payload
    rs_payload_bytes = len(rs_encode(bytes(payload_len), nsym=_RS_NSYM))
    n_payload_bits = rs_payload_bytes * 8
    payload_offset = n_header_bits

    if len(lsbs) < payload_offset + n_payload_bits:
        raise ValueError(
            f"Audio too short: need {payload_offset + n_payload_bits} bits "
            f"but only {len(lsbs)} available."
        )

    payload_rs_bytes = _bits_to_bytes(lsbs[payload_offset : payload_offset + n_payload_bits])
    encrypted_payload = rs_decode(payload_rs_bytes, nsym=_RS_NSYM)

    # Step 6: optional decryption
    if password:
        plaintext = decrypt(encrypted_payload, password)
        logger.info("decode_audio: decrypted %d bytes", len(plaintext))
    else:
        plaintext = encrypted_payload
        logger.info("decode_audio: recovered %d bytes (no encryption)", len(plaintext))

    return plaintext


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Cryptoleaf audio steganography decoder (LSB)"
    )
    parser.add_argument("stego", help="Stego audio file (WAV or FLAC)")
    parser.add_argument("--password", default="", help="Decryption password (must match encoder)")
    args = parser.parse_args()

    stego_path = Path(args.stego)
    print(f"Decoding: {stego_path}")

    try:
        plaintext = decode_audio(stego_path, password=args.password)
        message = plaintext.decode("utf-8")
        print(f"Decoded message: {message!r}")
    except BadAudioMagicError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
