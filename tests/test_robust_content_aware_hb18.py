import io
import numpy as np
from PIL import Image
from tools.robust_content_aware_hb18 import channel, ll2_received, ARMS, PAIRS


def test_channel_dimensions_and_jpeg_roundtrip():
    image = Image.fromarray(np.random.default_rng(3).integers(
        0, 256, (80, 120, 3), dtype=np.uint8), "RGB")
    for _, scale, quality in PAIRS:
        for arm in ARMS:
            result = channel(image, scale, quality, arm)
            expected_size = image.size if arm in ("identity", "jpeg_only") else (
                round(image.width * scale), round(image.height * scale))
            assert result.size == expected_size
            assert result.mode == "RGB"
            if arm == "identity":
                assert np.array_equal(np.asarray(result), np.asarray(image))


def test_jpeg_only_matches_direct_pillow_encode():
    image = Image.fromarray(np.random.default_rng(8).integers(
        0, 256, (64, 96, 3), dtype=np.uint8), "RGB")
    actual = channel(image, .83, 85, "jpeg_only")
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=85, subsampling=2)
    stream.seek(0)
    with Image.open(stream) as im:
        expected = im.convert("RGB")
    assert np.array_equal(np.asarray(actual), np.asarray(expected))


def test_ll2_roundtrip_shape():
    image = Image.fromarray(np.zeros((80, 120, 3), dtype=np.uint8), "RGB")
    small = channel(image, .83, 85, "resize_only")
    assert ll2_received(small, image.size).size == 20 * 30
