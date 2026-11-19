"""Tests for JPEG-after-resize paired blind-grid research experiment."""
import csv
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_blind_grid_jpeg_probe as jpeg


@pytest.mark.parametrize(
    "value,expected",
    [("85,70", [85, 70]), ("70,85,70", [70, 85]), ("100", [100])],
)
def test_parse_jpeg_qualities(value, expected):
    assert jpeg.parse_qualities(value) == expected


@pytest.mark.parametrize("value", ["", "0", "101", "85.5", "85,x"])
def test_reject_bad_jpeg_qualities(value):
    with pytest.raises(ValueError):
        jpeg.parse_qualities(value)


def test_jpeg_roundtrip_420_has_same_dimensions_and_changes_pixels():
    source = Image.fromarray(
        np.random.default_rng(43).integers(
            0, 256, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    )
    result = jpeg.jpeg_roundtrip_420(source, 70)
    assert result.size == source.size
    assert result.mode == "RGB"
    assert not np.array_equal(np.asarray(result), np.asarray(source))
    with pytest.raises(ValueError):
        jpeg.jpeg_roundtrip_420(source, 0)


def test_paired_probe_uses_same_received_geometry_and_separate_oracle(
    monkeypatch, tmp_path,
):
    source = tmp_path / "fresh.png"
    Image.fromarray(
        np.random.default_rng(7).integers(
            0, 256, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed", lambda image, strength: image
    )
    monkeypatch.setattr(
        robust, "_feedback_embed", lambda image, packet: image
    )
    calls = []

    def fake_marked(received, original_size, payload, min_scale,
                    height_jitter, top_grids, delta, repeat, blind_budget):
        calls.append(("marked", received.size))
        assert original_size == (80, 64)
        assert received.size == (54, 44)
        assert blind_budget == 40
        return {
            "candidate_count": 60,
            "grid_count": 20,
            "refined_count": 5,
            "coarse_true_grid_rank": 1,
            "coarse_true_grid_score": 0.8,
            "coarse_best_wrong_grid_score": 0.1,
            "true_grid_shortlisted": True,
            "refined_exact_rank": 1,
            "refined_true_score": 0.9,
            "refined_best_score": 0.9,
            "bank_seconds": 0.001,
            "coarse_seconds": 0.2,
            "refine_seconds": 0.03,
            "blind_status": "PASS",
            "blind_attempts": 1,
            "blind_decoded_size": "80x64",
            "blind_seconds": 0.01,
        }

    def fake_unmarked(received, min_scale, height_jitter,
                      top_grids, delta, repeat, decode_budget):
        calls.append(("unmarked", received.size))
        assert received.size == (54, 44)
        assert decode_budget == 40
        return {
            "candidate_count": 60,
            "grid_count": 20,
            "refined_count": 5,
            "coarse_max_header_score": 0.11,
            "refined_max_header_score": 0.12,
            "bank_seconds": 0.001,
            "coarse_seconds": 0.2,
            "refine_seconds": 0.03,
            "decode_status": "NO_VALID_PACKET",
            "decode_attempts": 5,
            "decoded_size": None,
            "any_valid_packet": False,
            "decoded_payload_length": None,
            "decode_seconds": 0.04,
        }

    def fake_oracle(received, size, payload):
        calls.append(("oracle", received.size))
        assert size == (80, 64)
        return "PASS"

    monkeypatch.setattr(jpeg.sweep, "evaluate", fake_marked)
    monkeypatch.setattr(jpeg.neg, "evaluate", fake_unmarked)
    monkeypatch.setattr(jpeg, "decode_known_at_size", fake_oracle)

    rows = jpeg.probe(
        source, b"payload", [0.12], [0.68], [85],
    )
    assert calls == [
        ("marked", (54, 44)),
        ("oracle", (54, 44)),
        ("unmarked", (54, 44)),
    ]
    assert len(rows) == 2
    assert [r["arm"] for r in rows] == ["MARKED", "UNMARKED"]
    assert rows[0]["decode_status"] == "PASS"
    assert rows[0]["coarse_max_header_score"] == 0.8
    assert rows[1]["decode_status"] == "NO_VALID_PACKET"
    assert rows[1]["any_valid_packet"] is False
    assert all(r["jpeg_subsampling"] == "4:2:0" for r in rows)
    assert all(r["transform_order"] == "resize_then_jpeg" for r in rows)
    assert all(set(r) == set(jpeg.columns()) for r in rows)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=jpeg.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "jpeg_quality" in buffer.getvalue()
