import numpy as np
import pytest
from PIL import Image
from tools.robust_content_aware_hb25 import capped_positions


def test_deterministic_unique_and_cap():
    pixels = np.random.default_rng(25).integers(30, 225, (256, 256, 3), dtype=np.uint8)
    im = Image.fromarray(pixels)
    for factor in (None, 1.5, 2., 3.):
        a, info = capped_positions(im, 200, factor, tile=8)
        b, _ = capped_positions(im, 200, factor, tile=8)
        assert a is not None
        assert np.array_equal(a, b)
        assert len(np.unique(a)) == 200
        assert info["max_positions_per_tile"] <= info["cap_positions_per_tile"]


def test_flat_image_skipped_not_forced():
    im = Image.new("RGB", (128, 128), "white")
    for factor in (None, 1.5):
        positions, info = capped_positions(im, 50, factor)
        assert positions is None
        assert info["reason"] == "INSUFFICIENT_TEXTURE"


def test_invalid_caps():
    im = Image.new("RGB", (64, 64))
    for factor, tile in ((1., 8), (0., 8), (float("nan"), 8), (2., 0)):
        with pytest.raises(ValueError):
            capped_positions(im, 10, factor, tile)
