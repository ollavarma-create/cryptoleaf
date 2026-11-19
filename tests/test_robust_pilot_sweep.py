"""Sanity checks for the pilot-strength sweep's adaptation accounting."""
import pytest
from PIL import Image

from src import robust_image as robust
from tools.robust_pilot_sweep import effective_strength


def test_flat_image_uses_minimum_adaptive_pilot_strength(monkeypatch):
    monkeypatch.setattr(robust, "ADAPTIVE_PILOT", True)
    img = Image.new("RGB", (64, 64), (120, 120, 120))
    assert effective_strength(img, 0.18) == pytest.approx(0.054, abs=1e-6)


def test_disabled_adaptation_preserves_nominal_strength(monkeypatch):
    monkeypatch.setattr(robust, "ADAPTIVE_PILOT", False)
    img = Image.new("RGB", (64, 64), (120, 120, 120))
    assert effective_strength(img, 0.18) == pytest.approx(0.18)
