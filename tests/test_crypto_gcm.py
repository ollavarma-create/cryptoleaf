
import pytest

from src.crypto_gcm import encrypt_gcm, decrypt_gcm


@pytest.mark.parametrize(
    "plaintext",
    [b"", b"Hello Cryptoleaf", bytes(range(256)) * 10],
)
def test_gcm_roundtrip(plaintext):
    encrypted = encrypt_gcm(plaintext, "qwerty")

    assert decrypt_gcm(encrypted, "qwerty") == plaintext


def test_gcm_wrong_password():
    encrypted = encrypt_gcm(b"Secret message", "correct")

    with pytest.raises(ValueError, match="Authentication failed"):
        decrypt_gcm(encrypted, "wrong")


def test_gcm_detects_corruption():
    encrypted = bytearray(encrypt_gcm(b"Secret message", "qwerty"))

    encrypted[28] ^= 0x01  # First ciphertext byte

    with pytest.raises(ValueError, match="Authentication failed"):
        decrypt_gcm(bytes(encrypted), "qwerty")


def test_gcm_rejects_empty_password():
    with pytest.raises(ValueError):
        encrypt_gcm(b"Secret", "")
