# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – AES-CBC encryption/decryption
#
# Ported from endecrypter.py (StegaMachine._aes_encrypt / _aes_decrypt).
# Do NOT rewrite the crypto logic – only adapt the interface to bytes.
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

"""AES-CBC encryption with PBKDF2-HMAC-SHA256 key derivation.

Wire format returned by encrypt():
    salt (16 bytes) | iv (16 bytes) | ciphertext (padded to AES block size)
"""

import logging
import os

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import pad, unpad

logger = logging.getLogger(__name__)

__all__ = ["encrypt", "decrypt"]

_PBKDF2_ITERATIONS = 200_000
_KEY_LEN = 32  # AES-256
_SALT_LEN = 16
_IV_LEN = 16


def encrypt(plaintext: bytes, password: str) -> bytes:
    """Encrypt *plaintext* with AES-CBC using a PBKDF2-derived key.

    Args:
        plaintext: Raw bytes to encrypt.
        password: Password string for key derivation.

    Returns:
        Bytes: salt(16) + iv(16) + ciphertext.
    """
    salt = os.urandom(_SALT_LEN)
    iv = os.urandom(_IV_LEN)
    key = PBKDF2(password, salt, dkLen=_KEY_LEN, count=_PBKDF2_ITERATIONS)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))
    logger.debug(
        "encrypt: %d plaintext bytes → %d ciphertext bytes",
        len(plaintext),
        len(ciphertext),
    )
    return salt + iv + ciphertext


def decrypt(data: bytes, password: str) -> bytes:
    """Decrypt *data* produced by encrypt().

    Args:
        data: Bytes in the format salt(16) + iv(16) + ciphertext.
        password: Password string used during encryption.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        ValueError: If decryption or unpadding fails (wrong password / corrupted data).
    """
    if len(data) < _SALT_LEN + _IV_LEN + AES.block_size:
        raise ValueError("Ciphertext too short to be valid.")

    salt = data[:_SALT_LEN]
    iv = data[_SALT_LEN: _SALT_LEN + _IV_LEN]
    ciphertext = data[_SALT_LEN + _IV_LEN:]

    key = PBKDF2(password, salt, dkLen=_KEY_LEN, count=_PBKDF2_ITERATIONS)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    try:
        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Decryption failed – wrong password or corrupted data: {exc}") from exc

    logger.debug(
        "decrypt: %d ciphertext bytes → %d plaintext bytes",
        len(ciphertext),
        len(plaintext),
    )
    return plaintext
