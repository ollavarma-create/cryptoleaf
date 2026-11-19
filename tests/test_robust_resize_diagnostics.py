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
