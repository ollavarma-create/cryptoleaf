"""Tests for the research-only axis-masked Fourier pilot detector."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_pilot_angular_probe as angular


def test_angle_and_cutoff_validation():
    assert angular.parse_angles("0,5,10,20") == [0, 5, 10, 20]
    assert angular.parse_angles("0,5,5") == [0, 5]
    assert angular.parse_freqs("0.38,0.48") == [0.38, 0.48]
    for invalid in ("", "-1", "45", "nan", "abc", "0,"):
        with pytest.raises(ValueError):
            angular.parse_angles(invalid)
    for invalid in ("", "0.2", "0.51", "nan", "abc", "0.38,"):
        with pytest.raises(ValueError):
            angular.parse_freqs(invalid)


@pytest.mark.parametrize("max_freq", [0.38, 0.48])
def test_zero_angle_mask_reproduces_existing_radial_profile(max_freq):
    image = Image.fromarray(
        np.random.default_rng(14).integers(
            0, 256, (91, 113, 3), dtype=np.uint8
        ), "RGB"
    )
    bins = round(1800 * max_freq / 0.38)
    baseline = robust._profile(image, bins=bins, max_freq=max_freq)
    masked = angular.masked_profile(
        angular.fft_workspace(image), max_freq, 0.0
    )
    np.testing.assert_allclose(masked, baseline, rtol=0, atol=1e-9)


def test_axis_exclusion_changes_profile_without_nans():
    image = Image.fromarray(
        np.random.default_rng(9).integers(
            0, 256, (100, 120, 3), dtype=np.uint8
        ), "RGB"
    )
    workspace = angular.fft_workspace(image)
    unmasked = angular.masked_profile(workspace, 0.38, 0)
    masked = angular.masked_profile(workspace, 0.38, 10)
    assert np.isfinite(masked).all()
    assert np.max(np.abs(unmasked - masked)) > 1e-4


def test_candidate_cascade_uses_two_stages_and_deduplicates(monkeypatch):
    seen = []

    def fake_candidates(size, peaks, limit, first_peak_quota):
        seen.append((size, len(peaks), limit, first_peak_quota))
        return (
            [(100, 80), (101, 80), (102, 80)]
            if len(peaks) == 4
            else [(100, 80), (103, 80)]
        )

    monkeypatch.setattr(
        angular, "priority_candidates_from_peaks", fake_candidates
    )
    peaks = [(0.7, 0.5)] * 16
    candidates = angular.staged_candidates((70, 56), peaks)
    assert candidates == [
        (100, 80), (101, 80), (102, 80), (103, 80)
    ]
    assert seen == [
        ((70, 56), 4, 160, 10),
        ((70, 56), 16, 160, 10),
    ]


def test_probe_returns_oracle_rank_only_with_negative_control(
    monkeypatch, tmp_path
):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(4).integers(
            0, 256, (64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    # Match the production pilot's RGB -> YCbCr -> RGB round trip.
    # The negative control uses the same conversion, so disabling both
    # embeddings must produce pixel-identical received images.
    monkeypatch.setattr(
        robust, "_pilot_embed",
        lambda image, strength: image.convert("YCbCr").convert("RGB"),
    )
    monkeypatch.setattr(
        robust, "_feedback_embed",
        lambda image, packet: image,
    )
    monkeypatch.setattr(
        angular, "decode_known_at_size",
        lambda image, size, payload: "PASS",
    )
    monkeypatch.setattr(
        angular, "staged_candidates",
        lambda size, peaks: [(80, 64), (81, 64)],
    )
    rows = angular.probe(
        source, b"payload", strengths=[0.12],
        scales=[0.75], angles=[0, 10], freqs=[0.38],
    )
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "OK"
        assert row["oracle"] == "PASS"
        assert row["blind_status"] == "NOT_RUN"
        assert row["blind_attempts"] is None
        assert row["safe_ll2_grid_rank"] == 1
        assert row["received_width"] == 60
        assert row["received_height"] == 48
        assert row["candidate_count"] == 2
        assert row["pilot_score_lift_vs_dwt_only"] == pytest.approx(0)
        assert set(row) == set(angular.columns())
