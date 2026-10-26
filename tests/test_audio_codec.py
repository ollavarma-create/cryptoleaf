# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – audio codec tests (LSB method, header version 4)
#
# Note on test parameters:
#   The encoder uses LSB embedding: 1 bit per int16 PCM sample in channel 0.
#   alpha and chip_length are accepted for API compatibility but ignored.
#   Capacity = n_samples (one bit per sample).
#
#   With 10-second mono audio at 44100 Hz:
#     capacity = 441000 bits = 55125 bytes
#   RS-encoded header (32 bytes, nsym=64): 96 bytes = 768 bits (fixed)

import logging
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.audio_encoder import encode_audio, capacity_bits_audio, AudioCapacityError
from src.audio_decoder import decode_audio, BadAudioMagicError

logging.basicConfig(level=logging.WARNING)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SR = 44100           # samples per second
_CHIP_LENGTH = 128    # chip length for tests (smaller than default 4096 for speed)


def _make_sine_audio(seconds: float, seed: int = 0) -> np.ndarray:
    """Generate a smooth mono float64 audio signal (mix of low-frequency sines).

    The signal has meaningful amplitude so adaptive alpha scaling works normally.
    Spread-spectrum SNR scales with alpha / sqrt(chip_length) and is independent
    of specific signal content for the correlation test.
    """
    n = int(seconds * _SR)
    t = np.linspace(0, seconds, n, endpoint=False)
    rng = np.random.default_rng(seed)
    freqs = rng.integers(100, 1000, size=4)
    signal = sum(np.sin(2 * np.pi * f * t) for f in freqs)
    signal = signal / np.max(np.abs(signal)) * 0.7
    return signal.astype(np.float64)


@pytest.fixture()
def mono_cover(tmp_path: Path) -> Path:
    """10-second mono sine WAV (capacity = 3445 bits at chip_length=128)."""
    signal = _make_sine_audio(10.0, seed=1)
    p = tmp_path / "cover_mono.wav"
    sf.write(p, signal, _SR, subtype="PCM_16")
    return p


@pytest.fixture()
def stereo_cover(tmp_path: Path) -> Path:
    """10-second stereo sine WAV (embed in ch-0 only)."""
    ch0 = _make_sine_audio(10.0, seed=2)
    ch1 = _make_sine_audio(10.0, seed=3)
    stereo = np.column_stack([ch0, ch1])
    p = tmp_path / "cover_stereo.wav"
    sf.write(p, stereo, _SR, subtype="PCM_16")
    return p


@pytest.fixture()
def long_cover(tmp_path: Path) -> Path:
    """30-second mono sine WAV (larger capacity for oversized-payload test)."""
    signal = _make_sine_audio(30.0, seed=4)
    p = tmp_path / "cover_long.wav"
    sf.write(p, signal, _SR, subtype="PCM_16")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCapacityBitsAudio:
    def test_returns_positive_int(self, mono_cover: Path) -> None:
        cap = capacity_bits_audio(mono_cover, chip_length=_CHIP_LENGTH)
        assert isinstance(cap, int)
        assert cap > 0

    def test_longer_audio_has_more_capacity(
        self, mono_cover: Path, long_cover: Path
    ) -> None:
        assert (
            capacity_bits_audio(long_cover, chip_length=_CHIP_LENGTH)
            > capacity_bits_audio(mono_cover, chip_length=_CHIP_LENGTH)
        )

    def test_capacity_equals_sample_count(self, mono_cover: Path) -> None:
        """LSB capacity = n_samples; chip_length param is ignored."""
        import soundfile as sf
        info = sf.info(mono_cover)
        expected = info.frames
        assert capacity_bits_audio(mono_cover) == expected
        # chip_length is accepted but ignored
        assert capacity_bits_audio(mono_cover, chip_length=128) == expected
        assert capacity_bits_audio(mono_cover, chip_length=4096) == expected


class TestAudioCapacityError:
    def test_raises_on_oversized_payload(self, mono_cover: Path) -> None:
        cap = capacity_bits_audio(mono_cover, chip_length=_CHIP_LENGTH)
        # cap is in bits; using cap bytes is always too large after RS overhead
        giant = bytes(cap)
        with pytest.raises(AudioCapacityError):
            encode_audio(mono_cover, giant, chip_length=_CHIP_LENGTH)

    def test_small_payload_fits(self, mono_cover: Path) -> None:
        stego, sr = encode_audio(mono_cover, b"hello", chip_length=_CHIP_LENGTH)
        assert stego is not None
        assert sr == _SR


class TestAudioRoundTrip:
    """Round-trip tests for the LSB codec.

    LSB embedding is lossless through WAV PCM_16: exactly 1 bit is modified
    per sample (the least significant bit), so recovery is always exact.
    alpha and chip_length parameters are accepted but ignored.
    """

    def test_plaintext_roundtrip(self, mono_cover: Path) -> None:
        message = b"hello world"
        stego, sr = encode_audio(mono_cover, message, chip_length=_CHIP_LENGTH)
        recovered = decode_audio((stego, sr), chip_length=_CHIP_LENGTH)
        assert recovered == message

    def test_encrypted_roundtrip(self, mono_cover: Path) -> None:
        message = b"secret audio message"
        password = "correct horse battery staple"
        stego, sr = encode_audio(
            mono_cover, message, password=password, chip_length=_CHIP_LENGTH
        )
        recovered = decode_audio((stego, sr), password=password, chip_length=_CHIP_LENGTH)
        assert recovered == message

    def test_wrong_password_raises(self, mono_cover: Path) -> None:
        message = b"sensitive data"
        stego, sr = encode_audio(
            mono_cover, message, password="rightpassword", chip_length=_CHIP_LENGTH
        )
        with pytest.raises(Exception):
            decode_audio((stego, sr), password="wrongpassword", chip_length=_CHIP_LENGTH)

    def test_output_same_length(self, mono_cover: Path) -> None:
        original, _ = sf.read(mono_cover, dtype="float64", always_2d=True)
        stego, _ = encode_audio(mono_cover, b"test", chip_length=_CHIP_LENGTH)
        assert stego.shape == original.shape

    def test_various_payloads(self, mono_cover: Path) -> None:
        for msg in (b"x", b"hello world", b"A" * 50):
            stego, sr = encode_audio(mono_cover, msg, chip_length=_CHIP_LENGTH)
            recovered = decode_audio((stego, sr), chip_length=_CHIP_LENGTH)
            assert recovered == msg, f"Failed for payload len={len(msg)}"

    def test_stereo_channel1_unchanged(self, stereo_cover: Path) -> None:
        """Only channel 0 should be modified; channel 1 must be bit-exact."""
        original, _ = sf.read(stereo_cover, dtype="float64", always_2d=True)
        stego, _ = encode_audio(
            stereo_cover, b"stereo test", chip_length=_CHIP_LENGTH
        )
        np.testing.assert_array_equal(
            stego[:, 1], original[:, 1],
            err_msg="Channel 1 was unexpectedly modified by the encoder.",
        )

    def test_decode_from_file(self, mono_cover: Path, tmp_path: Path) -> None:
        """Encoder output saved to WAV PCM_16 and decoded from file path."""
        message = b"file path decode"
        stego, sr = encode_audio(mono_cover, message, chip_length=_CHIP_LENGTH)
        stego_path = tmp_path / "stego.wav"
        sf.write(stego_path, stego, sr, subtype="PCM_16")
        recovered = decode_audio(stego_path, chip_length=_CHIP_LENGTH)
        assert recovered == message


class TestFlacSurvival:
    """FLAC is lossless; LSB embedding survives PCM_24 round-trip exactly.

    The encoder outputs float64 / 32768.0.  sf.write to FLAC PCM_24 stores
    24-bit samples; sf.read dtype=int16 recovers the original int16 values
    preserving LSBs exactly.
    """

    def test_flac_roundtrip(self, mono_cover: Path, tmp_path: Path) -> None:
        message = b"hello flac world"
        stego, sr = encode_audio(mono_cover, message, chip_length=_CHIP_LENGTH)
        flac_path = tmp_path / "stego.flac"
        sf.write(flac_path, stego, sr, format="FLAC", subtype="PCM_24")
        recovered = decode_audio(flac_path, chip_length=_CHIP_LENGTH)
        assert recovered == message


class TestBadMagicError:
    def test_raises_on_plain_audio(self, mono_cover: Path) -> None:
        """Decoding an unmodified cover raises an error (bad magic or RS failure)."""
        with pytest.raises(Exception):
            decode_audio(mono_cover, chip_length=_CHIP_LENGTH)
