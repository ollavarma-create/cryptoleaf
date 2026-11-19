"""Regression tests for backward-compatible CLR1 magic/length-bit recovery.

Synthetic LL2 coefficients isolate the decoder logic from image-specific
Fourier/DWT distortion. Full resize robustness still needs user-side tests.
"""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from src.robust_packet import pack


@pytest.fixture
def encoded_ll(monkeypatch):
    payload = b"header length repair test"
    packet = pack(payload)
    bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    ll = np.zeros((64, 64), dtype=np.float64)
    positions = np.random.default_rng(robust.SEED).permutation(ll.size)
    repeated = np.repeat(bits, robust.REPEAT)
    ll.ravel()[positions[:len(repeated)]] = repeated * robust.DELTA

    monkeypatch.setattr(
        robust.pywt, "wavedec2", lambda *args, **kwargs: [ll]
    )
    monkeypatch.setattr(
        robust, "_ycc",
        lambda _image: np.zeros((256, 256, 3), dtype=np.float64),
    )

    def corrupt(bit_index: int, repeats: int = 5):
        indexes = positions[
            bit_index * robust.REPEAT:bit_index * robust.REPEAT + repeats
        ]
        ll.ravel()[indexes] = (1 - bits[bit_index]) * robust.DELTA

    return Image.new("RGB", (256, 256)), payload, corrupt


def test_unchanged_valid_packet_fast_path(encoded_ll):
    image, payload, _ = encoded_ll
    assert robust.decode_at_size(image, image.size) == payload


def test_repair_invalid_length_high_byte_bit_11(encoded_ll):
    image, payload, corrupt = encoded_ll
    # CLR1 16-bit big-endian length: bit 11 is index 36 of full header.
    corrupt(32 + (15 - 11))
    assert robust.decode_at_size(image, image.size) == payload


def test_repair_plausible_but_wrong_length_low_bit(encoded_ll):
    image, payload, corrupt = encoded_ll
    # A wrong length may still be 12..255; failed RS/CRC must trigger repair.
    corrupt(47)
    assert robust.decode_at_size(image, image.size) == payload


def test_repair_length_and_one_codeword_byte(encoded_ll):
    image, payload, corrupt = encoded_ll
    corrupt(36)
    corrupt(48)
    assert robust.decode_at_size(image, image.size) == payload


def test_repair_one_corrupted_magic_bit(encoded_ll):
    image, payload, corrupt = encoded_ll
    corrupt(0)
    assert robust.decode_at_size(image, image.size) == payload


def test_repair_magic_bit_and_two_codeword_bytes(encoded_ll):
    image, payload, corrupt = encoded_ll
    corrupt(0)
    corrupt(48)
    corrupt(56)
    assert robust.decode_at_size(image, image.size) == payload


def test_repair_one_magic_and_one_length_bit(encoded_ll):
    image, payload, corrupt = encoded_ll
    corrupt(0)
    corrupt(36)
    assert robust.decode_at_size(image, image.size) == payload


def test_does_not_accept_two_corrupted_magic_bits(encoded_ll):
    image, _, corrupt = encoded_ll
    corrupt(0)
    corrupt(1)
    with pytest.raises(ValueError, match="Invalid CLR1 header"):
        robust.decode_at_size(image, image.size)


def test_does_not_accept_magic_repair_with_five_bad_codeword_bytes(encoded_ll):
    image, _, corrupt = encoded_ll
    corrupt(0)
    for index in (48, 56, 64, 72, 80):
        corrupt(index)
    with pytest.raises(ValueError):
        robust.decode_at_size(image, image.size)


def test_does_not_accept_two_length_bit_errors(encoded_ll):
    image, _, corrupt = encoded_ll
    corrupt(36)
    corrupt(37)
    with pytest.raises(ValueError, match="Invalid CLR1 length"):
        robust.decode_at_size(image, image.size)
