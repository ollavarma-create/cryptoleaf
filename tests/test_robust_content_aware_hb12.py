import numpy as np
import pytest
from PIL import Image
from tools.robust_content_aware_hb1 import select_positions
from tools.robust_content_aware_hb12 import (
    balanced_positions, balanced_scores, select_arm,
)


def image_with_edges():
    a = np.full((128, 128, 3), 120, dtype=np.uint8)
    a[32:64, 32:64] = np.random.default_rng(8).integers(
        35, 220, (32, 32, 3), dtype=np.uint8)
    return Image.fromarray(a, "RGB")


def test_balanced_deterministic_and_capacity_preserving():
    image = image_with_edges()
    a, meta = balanced_positions(image, 200)
    b, other = balanced_positions(image, 200)
    assert np.array_equal(a, b)
    assert meta == other
    assert len(a) == len(set(a.tolist())) == 200
    assert np.all((a >= 0) & (a < balanced_scores(image).size))


def test_quota_fallback_is_explicit():
    image = image_with_edges()
    a, meta = balanced_positions(image, 800, quota_fraction=.1)
    assert len(a) == 800
    assert meta["quota_fallback_count"] > 0
    assert meta["quota_initial"] + meta["quota_fallback_count"] == 800


def test_random_control_unchanged():
    image = image_with_edges()
    a, _ = select_arm(image, 100, "random", .5)
    assert np.array_equal(a, select_positions(image, 100, "random"))


def test_invalid_parameters():
    with pytest.raises(ValueError):
        balanced_positions(image_with_edges(), 100, quota_fraction=0)
    with pytest.raises(ValueError):
        balanced_positions(image_with_edges(), 1025)
