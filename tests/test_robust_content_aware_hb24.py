import numpy as np
from PIL import Image
from tools.robust_content_aware_hb24 import positions_for


def test_deterministic_and_unique():
    pixels = np.random.default_rng(24).integers(30, 220, (192, 256, 3), dtype=np.uint8)
    image = Image.fromarray(pixels)
    for tile in (None, 8, 16, 32):
        a, info = positions_for(image, 120, tile)
        b, _ = positions_for(image, 120, tile)
        assert np.array_equal(a, b)
        assert len(np.unique(a)) == 120
        assert info["eligible"] >= 120


def test_spreading_changes_map():
    pixels = np.random.default_rng(42).integers(20, 235, (256, 256, 3), dtype=np.uint8)
    image = Image.fromarray(pixels)
    base, _ = positions_for(image, 250, None)
    spread, _ = positions_for(image, 250, 8)
    assert not np.array_equal(base, spread)


def test_capacity_skip():
    image = Image.new("RGB", (128, 128), "white")
    positions, info = positions_for(image, 50, 8)
    assert positions is None
    assert info["reason"] == "INSUFFICIENT_TEXTURE"
