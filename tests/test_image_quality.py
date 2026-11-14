
import math

import pytest
from PIL import Image

from src.image_quality import calculate_psnr


def test_identical_images_have_infinite_psnr():
    image = Image.new("RGB", (32, 32), "gray")
    assert calculate_psnr(image, image) == math.inf


def test_different_images_have_finite_psnr():
    original = Image.new("RGB", (32, 32), (100, 100, 100))
    modified = Image.new("RGB", (32, 32), (110, 110, 110))

    result = calculate_psnr(original, modified)

    assert result == pytest.approx(28.13, abs=0.02)


def test_psnr_rejects_different_dimensions():
    original = Image.new("RGB", (32, 32))
    modified = Image.new("RGB", (64, 64))

    with pytest.raises(ValueError):
        calculate_psnr(original, modified)
