import numpy as np
from PIL import Image
from tools.robust_content_aware_hb22 import CHANNELS, STRATEGIES, transform


def test_unique_channels_and_strategies():
    assert len(CHANNELS) == len({row[0] for row in CHANNELS})
    assert STRATEGIES == ("random", "texture", "balanced")


def test_channels_restore_or_preserve_expected_dimensions():
    pixels = np.random.default_rng(22).integers(0, 256, (80, 112, 3), dtype=np.uint8)
    image = Image.fromarray(pixels)
    for label, scale, quality in CHANNELS:
        received = transform(image, scale, quality)
        if scale is not None and quality is not None:
            assert received.size == tuple(max(32, round(d * scale)) for d in image.size)
        else:
            assert received.size == image.size


def test_identity_exact():
    image = Image.new("RGB", (64, 64), (12, 34, 56))
    assert np.array_equal(np.asarray(transform(image, None, None)), np.asarray(image))
