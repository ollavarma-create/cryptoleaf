"""Regression: blind robust extraction survives a 2x image enlargement."""
import io

import numpy as np
from PIL import Image

from src.robust_image import decode, encode


def test_blind_decode_after_2x_png_resize():
    # Deterministic, non-sensitive synthetic cover; no external fixtures.
    rng = np.random.default_rng(20261114)
    cover = Image.fromarray(
        rng.integers(0, 256, (480, 640, 3), dtype=np.uint8), "RGB"
    )
    payload = b"Cryptoleaf 2x resize regression"
    marked = encode(cover, payload)

    # Simulate a user exporting a 200%-scaled image as PNG.
    enlarged = marked.resize((1280, 960), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    enlarged.save(stream, format="PNG")
    stream.seek(0)
    with Image.open(stream) as received:
        result = decode(received)
    assert result.payload == payload
