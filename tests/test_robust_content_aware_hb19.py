import numpy as np
import pytest
from PIL import Image
from tools.robust_content_aware_hb19 import SCALES, down_up


def test_scales_monotone_and_baseline():
    assert SCALES[0] == 1.0
    assert all(a > b for a, b in zip(SCALES, SCALES[1:]))
    im = Image.fromarray(np.random.default_rng(9).integers(
        0, 256, (72, 112, 3), dtype=np.uint8))
    out = down_up(im, 1.0)
    assert out.size == im.size
    assert np.array_equal(np.asarray(out), np.asarray(im))


def test_lanczos_down_up_returns_original_dimensions():
    im = Image.fromarray(np.random.default_rng(9).integers(
        0, 256, (72, 112, 3), dtype=np.uint8))
    for scale in SCALES[1:]:
        out = down_up(im, scale)
        assert out.size == im.size
        assert out.mode == "RGB"


def test_invalid_scale_rejected():
    im = Image.new("RGB", (64, 64))
    for scale in (0, -1, 1.01):
        with pytest.raises(ValueError):
            down_up(im, scale)
