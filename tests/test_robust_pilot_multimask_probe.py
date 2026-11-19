"""Regression tests for fixed, oracle-free multi-mask blind search."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_pilot_multimask_probe as multi


def test_parse_variants_and_default_order():
    assert multi.parse_variants("0.38:0,0.38:5,0.48:20") == (
        (0.38, 0.0), (0.38, 5.0), (0.48, 20.0)
    )
    assert multi.parse_variants("0.48:20") == ((0.48, 20.0),)
    for invalid in (
        "", "0.38", "0.38:", "0.51:5", "0.2:5",
        "0.38:45", "0.38:-1", "nan:0",
        "0.38:0,0.38:0", "0.38:0,",
    ):
        with pytest.raises(ValueError):
            multi.parse_variants(invalid)


def test_cross_variant_dedup_preserves_distinct_pixel_sizes(monkeypatch):
    monkeypatch.setattr(multi.angular, "fft_workspace", lambda image: "fft")
    monkeypatch.setattr(
        multi, "variant_peaks",
        lambda workspace, freq, angle, max_peaks: [(angle, 1.0)]
    )
    calls = []

    def candidates(received_size, peaks, max_candidates, first_peak_quota):
        assert received_size == (64, 48)
        assert max_candidates == 160
        assert first_peak_quota == 0
        return (
            [(100, 80), (101, 80)]
            if peaks[0][0] == 0
            else [(101, 80), (102, 80)]
        )

    def decode(image, size):
        calls.append(size)
        if size == (102, 80):
            return b"expected"
        raise ValueError("no packet")

    monkeypatch.setattr(multi, "priority_candidates_from_peaks", candidates)
    monkeypatch.setattr(robust, "decode_at_size", decode)
    received = Image.new("RGB", (64, 48), "white")
    result = multi.decode_multimask(
        received, b"expected",
        variants=((0.38, 0.0), (0.38, 5.0)),
        stages=((1, 0),),
    )
    assert result["blind_status"] == "PASS"
    assert result["blind_attempts"] == 3
    assert result["blind_decoded_size"] == "102x80"
    assert result["successful_variant"] == "0.38:5"
    assert result["successful_stage"] == "1/0"
    assert result["variants_run"] == 2
    assert result["unique_pixel_candidates_generated"] == 3
    assert result["safe_attempts_by_variant"] == "0.38:0:2;0.38:5:1"
    assert calls == [(100, 80), (101, 80), (102, 80)]


def test_first_variant_success_stops_before_other_masks(monkeypatch):
    monkeypatch.setattr(multi.angular, "fft_workspace", lambda image: "fft")
    seen_masks = []

    def peaks(workspace, freq, angle, max_peaks):
        seen_masks.append(angle)
        return [(0.75, 1.0)]

    monkeypatch.setattr(multi, "variant_peaks", peaks)
    monkeypatch.setattr(
        multi, "priority_candidates_from_peaks",
        lambda received_size, peaks, max_candidates, first_peak_quota:
            [(80, 64)],
    )
    monkeypatch.setattr(
        robust, "decode_at_size", lambda image, size: b"expected"
    )
    result = multi.decode_multimask(
        Image.new("RGB", (60, 48)), b"expected",
        variants=((0.38, 0), (0.38, 5), (0.48, 20)),
        stages=((1, 0),),
    )
    assert result["blind_status"] == "PASS"
    assert result["blind_attempts"] == 1
    assert result["successful_variant"] == "0.38:0"
    assert seen_masks == [0]


def test_probe_decodes_blind_before_oracle_and_records_size(
    monkeypatch, tmp_path,
):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(11).integers(
            10, 240, (64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed",
        lambda image, strength: image.convert("RGB"),
    )
    monkeypatch.setattr(
        robust, "_feedback_embed",
        lambda image, packet: image,
    )
    monkeypatch.setattr(
        multi, "quality_metrics",
        lambda original, marked: {"psnr_db": 42.0, "ssim_y": 0.99},
    )
    events = []

    def blind(received, payload, variants, stages, per_stage_candidates):
        events.append("blind")
        assert received.size == (60, 48)
        return {
            "blind_status": "PASS", "blind_attempts": 2,
            "blind_decoded_size": "80x64",
            "successful_variant": "0.38:5", "successful_stage": "4/10",
            "variants_run": 2, "unique_pixel_candidates_generated": 5,
            "safe_attempts_by_variant": "0.38:0:1;0.38:5:1",
            "new_candidates_by_variant": "0.38:0:3;0.38:5:2",
        }

    def oracle(received, original_size, payload):
        events.append("oracle")
        assert original_size == (80, 64)
        return "PASS"

    monkeypatch.setattr(multi, "decode_multimask", blind)
    monkeypatch.setattr(multi, "decode_known_at_size", oracle)
    rows = multi.probe(
        source, b"expected", strengths=[0.18], scales=[0.75],
    )
    assert events == ["blind", "oracle"]
    assert len(rows) == 1
    row = rows[0]
    assert row["blind_status"] == "PASS"
    assert row["blind_same_ll2_shape"] is True
    assert row["blind_width_error_px"] == 0
    assert row["blind_height_error_px"] == 0
    assert row["oracle"] == "PASS"
    assert set(row) == set(multi.columns())
