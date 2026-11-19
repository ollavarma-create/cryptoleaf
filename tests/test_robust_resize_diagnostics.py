"""Synthetic, deterministic tests for pre-FEC resize diagnostics."""
import numpy as np
from PIL import Image

from src import robust_image as robust
from src.robust_packet import pack
from tools import robust_resize_diagnostics as diag


def test_qim_error_counting_before_and_after_one_corrupted_header_bit(monkeypatch):
    packet = pack(b"x")
    expected = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    ll = np.zeros((64, 64), dtype=np.float64)
    positions = np.random.default_rng(robust.SEED).permutation(ll.size)
    repeated = np.repeat(expected, robust.REPEAT)
    ll.ravel()[positions[:len(repeated)]] = repeated * robust.DELTA

    monkeypatch.setattr(diag.pywt, "wavedec2", lambda *args, **kwargs: [ll])
    monkeypatch.setattr(
        robust, "_ycc",
        lambda _image: np.zeros((256, 256, 3), dtype=np.float64),
    )
    image = Image.new("RGB", (256, 256))
    clean = diag.bit_errors(image, packet)
    assert clean["repeated_qim_errors"] == 0
    assert clean["majority_bit_errors"] == 0
    assert clean["header_byte_errors"] == 0

    # Flip all nine repetitions of the first bit in the magic header.
    ll.ravel()[positions[:robust.REPEAT]] = (1 - expected[0]) * robust.DELTA
    corrupted = diag.bit_errors(image, packet)
    assert corrupted["repeated_qim_errors"] == robust.REPEAT
    assert corrupted["majority_bit_errors"] == 1
    assert corrupted["header_bit_errors"] == 1
    assert corrupted["header_byte_errors"] == 1
    assert corrupted["codeword_byte_errors"] == 0


def test_one_bit_length_repair_probe(monkeypatch):
    payload = b"test"
    packet = pack(payload)
    expected = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    ll = np.zeros((64, 64), dtype=np.float64)
    positions = np.random.default_rng(robust.SEED).permutation(ll.size)
    repeated = np.repeat(expected, robust.REPEAT)
    ll.ravel()[positions[:len(repeated)]] = repeated * robust.DELTA

    # Flip five of nine repetitions of the length field's least-significant
    # bit so majority voting produces a one-bit-invalid CLR1 length.
    bit_index = 6 * 8 - 1
    flip_positions = positions[
        bit_index * robust.REPEAT:bit_index * robust.REPEAT + 5
    ]
    ll.ravel()[flip_positions] = (1 - expected[bit_index]) * robust.DELTA

    monkeypatch.setattr(diag.pywt, "wavedec2", lambda *args, **kwargs: [ll])
    monkeypatch.setattr(
        robust, "_ycc",
        lambda _image: np.zeros((256, 256, 3), dtype=np.float64),
    )
    image = Image.new("RGB", (256, 256))
    result = diag.probe_one_bit_length_repair(image, image.size, payload)
    assert result.startswith("PASS:len=")
    assert "bit=0" in result


def test_diagnostic_excludes_amplified_diff_maps(tmp_path):
    valid = tmp_path / "s00-strength-0.000.png"
    diff = tmp_path / "s00-strength-0.000-vs-zero-diff.png"
    valid.touch()
    diff.touch()
    assert diag.encoded_strength_files(tmp_path) == [valid]
