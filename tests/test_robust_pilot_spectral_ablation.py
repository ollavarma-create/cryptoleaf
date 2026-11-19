"""Regression tests for research-only Fourier spectral detector ablation."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_pilot_spectral_ablation as spectral


def test_full_038_peaks_match_existing_extended_detector():
    image = Image.fromarray(
        np.random.default_rng(123).integers(
            0, 256, (96, 128, 3), dtype=np.uint8
        ),
        "RGB",
    )
    profile = robust._profile(image, bins=1800, max_freq=0.38)
    scales, scores = spectral.score_spectrum(
        profile, max_freq=0.38, inner_only=False
    )
    measured = spectral.select_peaks(scales, scores)
    expected = robust._peaks(image, low=0.45, high=1.02)
    assert len(measured) == len(expected)
    for (scale, score), (expected_scale, expected_score) in zip(
        measured, expected
    ):
        assert scale == pytest.approx(expected_scale, abs=1e-12)
        assert score == pytest.approx(expected_score, abs=1e-10)


def test_inner_rings_are_subset_and_scores_are_finite():
    profile = np.random.default_rng(456).normal(size=1800)
    scales, full = spectral.score_spectrum(profile, 0.38, False)
    _, inner = spectral.score_spectrum(profile, 0.38, True)
    assert len(scales) == len(full) == len(inner)
    assert np.isfinite(full).all()
    assert np.isfinite(inner).all()
    assert (robust.RADII <= 0.16).sum() < len(robust.RADII)
    assert not np.allclose(full, inner)


def test_peak_budget_parser_and_nearest_local_peak_diagnostic():
    assert spectral.parse_peak_counts("4,8,12,4") == [4, 8, 12]
    for value in ("", "0", "65", "foo", "4,"):
        with pytest.raises(ValueError):
            spectral.parse_peak_counts(value)
    peaks = [(0.89, 0.7), (0.75, 0.6), (0.5, 0.4)]
    assert spectral.nearest_peak_diagnostic(peaks, 0.749) == (2, 0.001)
    assert spectral.nearest_peak_diagnostic(peaks, 0.72) == (None, 0.03)
    assert spectral.nearest_peak_diagnostic([], 0.75) == (None, None)


def test_ll2_grid_matches_real_wrong_size_successes():
    assert spectral.same_ll2_shape((1198, 677), (1200, 677))
    assert spectral.same_ll2_shape((1198, 677), (1200, 678))
    assert spectral.same_ll2_shape((1280, 867), (1280, 868))
    assert not spectral.same_ll2_shape((1198, 677), (1201, 677))
    assert not spectral.same_ll2_shape((1280, 867), (1280, 869))


def test_grid_rank_skips_unsafe_candidates_and_never_uses_oracle_hint():
    candidates = [
        (1500, 960),  # unsafe, skipped
        (1280, 956),   # different LL2 grid
        (1280, 959),   # same LL2 grid as (1280, 960)
        (1280, 960),
    ]
    assert spectral.first_safe_grid_rank(
        candidates, (1280, 960)
    ) == (2, 2)
    assert spectral.first_safe_grid_rank(
        [(1280, 956)], (1280, 960)
    ) == (None, 1)


def test_probe_writes_four_variants_without_blind_decode(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(1).integers(
            0, 256, (64, 80, 3), dtype=np.uint8
        ),
        "RGB",
    ).save(source)
    original = robust.DELTA, robust.REPEAT
    observed = []

    def fake_embed(image, _packet):
        observed.append((robust.DELTA, robust.REPEAT))
        return image

    monkeypatch.setattr(robust, "_feedback_embed", fake_embed)
    monkeypatch.setattr(robust, "_pilot_embed", lambda image, strength: image)
    monkeypatch.setattr(
        spectral, "decode_known_at_size",
        lambda _image, _size, _payload: "PASS"
    )
    monkeypatch.setattr(
        robust, "_profile",
        lambda _image, bins, max_freq: np.random.default_rng(
            int(max_freq * 100)
        ).normal(size=bins)
    )
    rows = spectral.probe(
        source, b"payload", strengths=[0.12], scales=[0.75]
    )
    assert len(rows) == 4
    assert {r["variant"] for r in rows} == {
        "all38", "inner38", "all48", "inner48"
    }
    assert all(r["oracle"] == "PASS" for r in rows)
    assert all(set(r) == set(spectral.columns()) for r in rows)
    assert all(r["max_peaks"] == 4 for r in rows)
    assert all("true_scale_local_peak_rank" in r for r in rows)
    assert observed == [(38.0, 13)]
    assert (robust.DELTA, robust.REPEAT) == original


def test_probe_multiple_peak_budgets_preserves_encoded_image(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(2).integers(
            0, 256, (64, 80, 3), dtype=np.uint8
        ),
        "RGB",
    ).save(source)
    embed_calls = []
    monkeypatch.setattr(
        robust, "_feedback_embed",
        lambda image, _packet: (embed_calls.append(image.size), image)[1],
    )
    monkeypatch.setattr(robust, "_pilot_embed", lambda image, strength: image)
    monkeypatch.setattr(
        spectral, "decode_known_at_size",
        lambda _image, _size, _payload: "PASS"
    )
    monkeypatch.setattr(
        robust, "_profile",
        lambda _image, bins, max_freq: np.random.default_rng(10).normal(size=bins)
    )
    rows = spectral.probe(
        source, b"payload", [0.0, 0.12], [0.75],
        peak_counts=[4, 8, 12], variants=("all38",)
    )
    assert len(rows) == 6
    assert {r["max_peaks"] for r in rows} == {4, 8, 12}
    assert {r["variant"] for r in rows} == {"all38"}
    assert all(set(r) == set(spectral.columns()) for r in rows)
    assert len(embed_calls) == 2
    assert all(r["oracle"] == "PASS" for r in rows)
