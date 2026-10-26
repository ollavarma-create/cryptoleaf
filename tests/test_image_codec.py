# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – image codec tests
import logging
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.image_encoder import encode_image, capacity_bits, CapacityError
from src.image_decoder import decode_image, BadMagicError

logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_smooth_image(size: int, seed: int) -> np.ndarray:
    """Generate a smooth RGB image suitable for LSB and DWT tests.

    Heavily blurred to suppress high-frequency DWT content, which would
    otherwise require very large alpha values to get reliable SNR.
    """
    import cv2
    rng = np.random.default_rng(seed)
    arr = rng.integers(32, 224, (size, size, 3), dtype=np.uint8)
    return cv2.GaussianBlur(arr, (31, 31), 0)


def _make_jpeg_cover(width: int, height: int, seed: int) -> Image.Image:
    """Generate a moderately textured RGB PIL Image for block-luminance tests.

    Uses random pixels with a light Gaussian blur (kernel 5) to produce
    medium-frequency texture.  This is representative of natural photos and
    ensures JPEG quantisation at quality ≥ 75 preserves the centre-vs-edge-mean
    relationship used by Method B (bit error rate < 15 % per block, well within
    the correction capacity of Hamming(7,4) + 3× replication).

    Do NOT use heavily blurred or uniform images: blocks with near-zero AC
    energy put the embedded signal entirely in quantised-away high-frequency
    DCT components, causing very high bit error rates.
    """
    import cv2
    rng = np.random.default_rng(seed)
    arr = rng.integers(40, 216, (height, width, 3), dtype=np.uint8)
    return Image.fromarray(cv2.GaussianBlur(arr, (5, 5), 0), "RGB")


@pytest.fixture()
def small_cover(tmp_path: Path) -> Path:
    """1024×1024 smooth PNG cover image."""
    arr = _make_smooth_image(1024, seed=42)
    img = Image.fromarray(arr, "RGB")
    p = tmp_path / "cover.png"
    img.save(p, format="PNG")
    return p


@pytest.fixture()
def large_cover(tmp_path: Path) -> Path:
    """2048×2048 smooth PNG cover image."""
    arr = _make_smooth_image(2048, seed=99)
    img = Image.fromarray(arr, "RGB")
    p = tmp_path / "cover_large.png"
    img.save(p, format="PNG")
    return p


@pytest.fixture()
def jpeg_cover(tmp_path: Path) -> Path:
    """1024×1024 moderately textured JPEG cover image for Method B tests."""
    img = _make_jpeg_cover(1024, 1024, seed=7)
    p = tmp_path / "cover.jpg"
    img.save(p, format="JPEG", quality=95)
    return p


# ---------------------------------------------------------------------------
# Capacity tests
# ---------------------------------------------------------------------------

class TestCapacityBits:
    def test_lsb_returns_positive_int(self, small_cover: Path) -> None:
        cap = capacity_bits(small_cover)
        assert isinstance(cap, int)
        assert cap > 0

    def test_lsb_larger_image_has_more_capacity(
        self, small_cover: Path, large_cover: Path
    ) -> None:
        assert capacity_bits(large_cover) > capacity_bits(small_cover)

    def test_jpeg_returns_positive_int(self, jpeg_cover: Path) -> None:
        cap = capacity_bits(jpeg_cover, output_format="JPEG")
        assert isinstance(cap, int)
        assert cap > 0

    def test_jpeg_capacity_formula(self, jpeg_cover: Path) -> None:
        """1024×1024 → 128×128 = 16384 blocks → 16384*4//21 = 3121 bits."""
        cap = capacity_bits(jpeg_cover, output_format="JPEG")
        # For 1024×1024: (1024//8)² × 4 // 21 = 16384 × 4 // 21 = 3121
        assert cap == (1024 // 8) ** 2 * 4 // 21


# ---------------------------------------------------------------------------
# LSB tests (PNG / BMP / WEBP)
# ---------------------------------------------------------------------------

class TestCapacityError:
    def test_raises_on_oversized_payload(self, small_cover: Path) -> None:
        cap = capacity_bits(small_cover)
        giant_payload = bytes(cap)
        with pytest.raises(CapacityError):
            encode_image(small_cover, giant_payload, alpha=2.0)

    def test_small_payload_fits(self, small_cover: Path) -> None:
        stego = encode_image(small_cover, b"hello", alpha=2.0)
        assert stego is not None


class TestLsbRoundTrip:
    """Round-trip tests use alpha=2.0 (ignored for LSB) and smooth covers."""

    def test_plaintext_roundtrip(self, small_cover: Path) -> None:
        message = b"hello world"
        stego = encode_image(small_cover, message, password="", alpha=2.0)
        recovered = decode_image(stego, password="")
        assert recovered == message

    def test_encrypted_roundtrip(self, small_cover: Path) -> None:
        message = b"secret message 12345"
        password = "correct horse battery staple"
        stego = encode_image(small_cover, message, password=password, alpha=2.0)
        recovered = decode_image(stego, password=password)
        assert recovered == message

    def test_wrong_password_raises(self, small_cover: Path) -> None:
        message = b"sensitive data"
        stego = encode_image(small_cover, message, password="rightpassword", alpha=2.0)
        with pytest.raises(Exception):
            decode_image(stego, password="wrongpassword")

    def test_stego_image_same_dimensions(self, small_cover: Path) -> None:
        with Image.open(small_cover) as cover:
            w, h = cover.size
        stego = encode_image(small_cover, b"test", alpha=2.0)
        assert stego.size == (w, h)

    def test_various_payloads(self, small_cover: Path) -> None:
        for msg in (b"x", b"hello world", b"A" * 50):
            stego = encode_image(small_cover, msg, alpha=2.0)
            recovered = decode_image(stego)
            assert recovered == msg, f"Failed for payload len={len(msg)}"


# ---------------------------------------------------------------------------
# JPEG Method B tests (block-luminance)
# ---------------------------------------------------------------------------

class TestBlockLuminance:
    """Block-luminance (Method B) round-trip tests.

    Uses a smooth gradient cover image and the production encode/decode pair.
    Hamming(7,4) + 3× replication corrects ~20-30 % bit errors, so messages
    survive JPEG re-encoding at quality ≥ 70.
    """

    def test_encode_returns_pil_image(self, jpeg_cover: Path) -> None:
        stego = encode_image(jpeg_cover, b"hello", output_format="JPEG")
        assert isinstance(stego, Image.Image)

    def test_plaintext_roundtrip(self, jpeg_cover: Path) -> None:
        message = b"hello world"
        stego = encode_image(jpeg_cover, message, output_format="JPEG")
        recovered = decode_image(stego)
        assert recovered == message

    def test_encrypted_roundtrip(self, jpeg_cover: Path) -> None:
        message = b"secret message 12345"
        password = "correcthorsebatterystaple"
        stego = encode_image(jpeg_cover, message, password=password, output_format="JPEG")
        recovered = decode_image(stego, password=password)
        assert recovered == message

    def test_wrong_password_raises(self, jpeg_cover: Path) -> None:
        message = b"sensitive"
        stego = encode_image(jpeg_cover, message, password="right", output_format="JPEG")
        with pytest.raises(Exception):
            decode_image(stego, password="wrong")

    def test_same_dimensions_after_encode(self, jpeg_cover: Path) -> None:
        with Image.open(jpeg_cover) as cover:
            w, h = cover.size
        stego = encode_image(jpeg_cover, b"dim test", output_format="JPEG")
        assert stego.size == (w, h)

    def test_survives_jpeg_save_at_q85(self, jpeg_cover: Path, tmp_path: Path) -> None:
        """Payload survives a JPEG save at quality 85 (the standard save quality)."""
        message = b"survives jpeg q85"
        stego = encode_image(jpeg_cover, message, output_format="JPEG")

        saved = tmp_path / "stego.jpg"
        stego.save(saved, format="JPEG", quality=85)

        with Image.open(saved) as reloaded:
            recovered = decode_image(reloaded)
        assert recovered == message

    def test_survives_jpeg_save_at_q75(self, jpeg_cover: Path, tmp_path: Path) -> None:
        """Payload survives a second JPEG compression at quality 75."""
        message = b"survives q75"
        stego = encode_image(jpeg_cover, message, output_format="JPEG")

        saved = tmp_path / "stego.jpg"
        stego.save(saved, format="JPEG", quality=75)

        with Image.open(saved) as reloaded:
            recovered = decode_image(reloaded)
        assert recovered == message

    def test_raises_capacity_error_on_oversized_payload(
        self, jpeg_cover: Path
    ) -> None:
        cap_bits = capacity_bits(jpeg_cover, output_format="JPEG")
        giant = bytes(cap_bits)   # many more bytes than capacity allows
        with pytest.raises(CapacityError):
            encode_image(jpeg_cover, giant, output_format="JPEG")

    def test_bad_magic_on_plain_jpeg(self, jpeg_cover: Path) -> None:
        """A plain (non-stego) JPEG raises BadMagicError on decode."""
        with Image.open(jpeg_cover) as img:
            plain = img.convert("RGB")
        with pytest.raises((BadMagicError, Exception)):
            decode_image(plain)
