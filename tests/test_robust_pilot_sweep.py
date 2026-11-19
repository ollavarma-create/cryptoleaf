"""Sanity checks for the pilot-strength sweep's adaptation accounting."""
import pytest
from PIL import Image

from src import robust_image as robust
from tools.robust_pilot_sweep import (
    decode_known_at_size,
    effective_strength,
    exact_size_candidate_rank,
)


def test_flat_image_uses_minimum_adaptive_pilot_strength(monkeypatch):
    monkeypatch.setattr(robust, "ADAPTIVE_PILOT", True)
    img = Image.new("RGB", (64, 64), (120, 120, 120))
    assert effective_strength(img, 0.18) == pytest.approx(0.054, abs=1e-6)


def test_disabled_adaptation_preserves_nominal_strength(monkeypatch):
    monkeypatch.setattr(robust, "ADAPTIVE_PILOT", False)
    img = Image.new("RGB", (64, 64), (120, 120, 120))
    assert effective_strength(img, 0.18) == pytest.approx(0.18)


def test_exact_size_candidate_rank(monkeypatch):
    img = Image.new("RGB", (48, 32))
    monkeypatch.setattr(
        robust,
        "candidate_sizes_priority50",
        lambda _img: iter([(60, 40), (64, 44), (48, 32)]),
    )
    assert exact_size_candidate_rank(img, (64, 44)) == 2
    assert exact_size_candidate_rank(img, (72, 48)) is None


def test_known_size_oracle_uses_original_dimensions(monkeypatch):
    img = Image.new("RGB", (48, 32))
    calls = []

    def fake_decode(_img, size):
        calls.append(size)
        return b"test"

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    assert decode_known_at_size(img, (64, 44), b"test") == "PASS"
    assert decode_known_at_size(img, (64, 44), b"other") == "FAIL:payload_mismatch"
    assert calls == [(64, 44), (64, 44)]
