"""Tests for controlled Fourier pilot/cover spectral contrast research."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_pilot_signal_probe as signal


def test_spectrum_diagnostic_returns_finite_scores_and_peak_rank():
    rng = np.random.default_rng(7)
    image = Image.fromarray(
        rng.integers(0, 256, (72, 96, 3), dtype=np.uint8), "RGB"
    )
    result = signal.spectrum_diagnostic(image, 0.75)
    assert set(result) == {
        "true_score", "score_percentile",
        "true_scale_local_peak_rank", "nearest_local_peak_distance",
        "best_peak_scale", "best_peak_score",
    }
    assert np.isfinite(result["true_score"])
    assert 0 <= result["score_percentile"] <= 100
    assert 0.45 <= result["best_peak_scale"] <= 1.02
    assert result["nearest_local_peak_distance"] >= 0


def test_four_arm_probe_has_matched_geometry_and_score_differences(
    monkeypatch, tmp_path
):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(5).integers(
            20, 210, (64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)

    def brighten(image, amount):
        arr = np.asarray(image.convert("RGB"), dtype=np.int16)
        return Image.fromarray(
            np.clip(arr + amount, 0, 255).astype(np.uint8), "RGB"
        )

    monkeypatch.setattr(
        robust, "_pilot_embed",
        lambda image, strength: brighten(image, 4),
    )
    monkeypatch.setattr(
        robust, "_feedback_embed",
        lambda image, packet: brighten(image, 2),
    )

    def fake_spectrum(image, actual_scale):
        assert image.size == (60, 48)
        assert abs(actual_scale - 0.75) < 1e-9
        score = round(float(np.asarray(image).mean() / 255.0), 8)
        return {
            "true_score": score,
            "score_percentile": 50.0,
            "true_scale_local_peak_rank": 1,
            "nearest_local_peak_distance": 0.0,
            "best_peak_scale": 0.75,
            "best_peak_score": score,
        }

    monkeypatch.setattr(signal, "spectrum_diagnostic", fake_spectrum)
    rows = signal.probe(
        source, b"payload", strengths=[0.12], scales=[0.75]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "OK"
    assert row["encoded_width"] == 80
    assert row["encoded_height"] == 64
    assert row["received_width"] == 60
    assert row["received_height"] == 48
    assert set(row) == set(signal.columns())
    assert row["pilot_lift_without_dwt"] == pytest.approx(
        row["pilot_only_true_score"] - row["cover_only_true_score"],
        abs=1e-7,
    )
    assert row["pilot_lift_with_dwt"] == pytest.approx(
        row["pilot_dwt_true_score"] - row["dwt_only_true_score"],
        abs=1e-7,
    )
    assert row["dwt_effect_without_pilot"] == pytest.approx(
        row["dwt_only_true_score"] - row["cover_only_true_score"],
        abs=1e-7,
    )
    assert row["dwt_effect_with_pilot"] == pytest.approx(
        row["pilot_dwt_true_score"] - row["pilot_only_true_score"],
        abs=1e-7,
    )
    assert row["pilot_lift_without_dwt"] > 0
    assert row["pilot_lift_with_dwt"] > 0


def test_zero_pilot_not_confused_with_four_arm_controls(tmp_path):
    source = tmp_path / "cover.png"
    Image.new("RGB", (80, 64), "gray").save(source)
    with pytest.raises(ValueError, match="positive"):
        signal.probe(source, b"payload", strengths=[0.0], scales=[0.75])
