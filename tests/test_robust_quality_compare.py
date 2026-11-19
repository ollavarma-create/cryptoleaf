"""Unit tests for full-reference image quality diagnostics."""
import numpy as np
import pytest
from PIL import Image

from tools.robust_quality_compare import quality_metrics


def test_identical_images_are_perfect_match():
    original = Image.new("RGB", (32, 32), (120, 150, 180))
    result = quality_metrics(original, original.copy())
    assert result["psnr_db"] is None  # Zero error: mathematically +infinity
    assert result["ssim_y"] == pytest.approx(1.0, abs=1e-6)
    assert result["pixel_change_pct"] == 0
    assert result["rgb_max_abs"] == 0
    assert result["worst_tile_luma_mae"] == 0


def test_single_patch_detected_and_localized():
    a = np.full((32, 32, 3), 100, dtype=np.uint8)
    b = a.copy()
    b[:16, :16] += 12
    result = quality_metrics(Image.fromarray(a), Image.fromarray(b))
    assert result["pixel_change_pct"] == 25.0
    assert result["rgb_max_abs"] == 12
    assert result["mean_signed_luma_change"] == pytest.approx(3.0)
    assert (result["worst_tile_x"], result["worst_tile_y"]) == (0, 0)
    assert result["worst_tile_luma_mae"] == pytest.approx(12.0)
    assert result["ssim_y"] < 1.0


def test_different_sizes_rejected():
    with pytest.raises(ValueError, match="dimensions differ"):
        quality_metrics(Image.new("RGB", (32, 32)), Image.new("RGB", (16, 16)))
