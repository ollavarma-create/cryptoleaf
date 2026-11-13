
"""Authenticated AES-256-GCM encryption for Cryptoleaf JPEG v0.3."""

import os

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2

SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
KEY_LEN = 32
PBKDF2_ITERATIONS = 200_000

# Bind the ciphertext to the new JPEG format.
AAD = b"Cryptoleaf:STGC:v3"


def _derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise ValueError("A non-empty password is required")

    return PBKDF2(
        password,
        salt,
        dkLen=KEY_LEN,
        count=PBKDF2_ITERATIONS,
        hmac_hash_module=SHA256,
    )


def encrypt_gcm(plaintext: bytes, password: str) -> bytes:
    """Return salt | nonce | ciphertext | authentication tag."""
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive_key(password, salt)

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=TAG_LEN)
    cipher.update(AAD)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    return salt + nonce + ciphertext + tag


def decrypt_gcm(data: bytes, password: str) -> bytes:
    """Verify authentication and decrypt the v0.3 payload."""
    minimum_length = SALT_LEN + NONCE_LEN + TAG_LEN
    if len(data) < minimum_length:
        raise ValueError("AES-GCM payload is too short")

    salt = data[:SALT_LEN]
    nonce = data[SALT_LEN:SALT_LEN + NONCE_LEN]
    ciphertext = data[SALT_LEN + NONCE_LEN:-TAG_LEN]
    tag = data[-TAG_LEN:]

    key = _derive_key(password, salt)

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=TAG_LEN)
    cipher.update(AAD)

    try:
        return cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError as exc:
        raise ValueError(
            "Authentication failed: wrong password or corrupted data"
        ) from exc
