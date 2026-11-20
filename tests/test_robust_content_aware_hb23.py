import numpy as np
import pytest
from PIL import Image
from tools.robust_content_aware_hb23 import ranked_positions


def test_strict_skips_and_fill_preserves_capacity():
    image = Image.new("RGB", (128, 128), "white")
    strict, info = ranked_positions(image, 50, "strict", 5.)
    assert strict is None
    assert info["reason"] == "INSUFFICIENT_ELIGIBLE"
    fill, info = ranked_positions(image, 50, "fill", 5.)
    assert len(fill) == 50
    assert np.unique(fill).size == 50
    assert info["fallback"] == 50
    assert info["selected_saturated_fraction"] == 1.


def test_determinism_and_nested_thresholds():
    rng = np.random.default_rng(22)
    image = Image.fromarray(rng.integers(10, 245, (128, 128, 3), dtype=np.uint8))
    a, _ = ranked_positions(image, 100, "fill", 2.)
    b, _ = ranked_positions(image, 100, "fill", 2.)
    assert np.array_equal(a, b)
    assert len(a) == 100


def test_invalid_threshold_and_policy():
    image = Image.new("RGB", (64, 64))
    for policy, threshold in (("unknown", 1.), ("fill", -1.), ("fill", float("nan"))):
        with pytest.raises(ValueError):
            ranked_positions(image, 10, policy, threshold)
