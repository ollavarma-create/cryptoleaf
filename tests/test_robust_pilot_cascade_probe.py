"""Tests for research-only staged Fourier blind packet recovery."""
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_pilot_cascade_probe as cascade


def test_stage_parser_accepts_defaults_and_rejects_invalid():
    assert cascade.parse_stages("4:10,16:10") == cascade.DEFAULT_STAGES
    assert cascade.parse_stages("4:10,4:50,16:10") == (
        (4, 10), (4, 50), (16, 10)
    )
    assert cascade.parse_stages("8:0") == ((8, 0),)
    for invalid in ("", "4", "0:10", "65:10", "4:-1",
                    "4:10,4:10", "foo:10", "4:10,"):
        with pytest.raises(ValueError):
            cascade.parse_stages(invalid)


def test_staged_search_deduplicates_pixel_sizes_but_not_ll2_grids(monkeypatch):
    received = Image.new("RGB", (100, 80))
    monkeypatch.setattr(
        robust, "_peaks",
        lambda _image, low, high, max_peaks: [
            (0.75, 0.9), (0.5, 0.8), (0.65, 0.7),
        ],
    )
    stage_lists = {
        (1, 10): [(120, 100), (121, 100), (122, 100)],
        (1, 50): [(120, 100), (122, 100), (123, 100)],
        (3, 10): [(121, 100), (124, 100), (125, 100)],
    }

    def fake_candidates(size, peaks, max_candidates, first_peak_quota):
        assert size == received.size
        assert max_candidates == 160
        return stage_lists[(len(peaks), first_peak_quota)]

    monkeypatch.setattr(cascade, "priority_candidates_from_peaks", fake_candidates)
    calls = []

    def fake_decode(image, size):
        calls.append(size)
        if size == (124, 100):
            return b"payload"
        raise ValueError("no packet")

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    result = cascade.decode_staged(
        received, b"payload",
        stages=((1, 10), (1, 50), (3, 10)),
    )
    assert result["blind_status"] == "PASS"
    assert result["successful_stage"] == "3/10"
    assert result["blind_attempts"] == 5
    assert result["blind_decoded_size"] == "124x100"
    assert result["stages_run"] == 3
    assert result["safe_attempts_by_stage"] == "1/10:3;1/50:1;3/10:1"
    assert result["new_candidates_by_stage"] == "1/10:3;1/50:1;3/10:2"
    assert calls == [
        (120, 100), (121, 100), (122, 100),
        (123, 100), (124, 100),
    ]
    # All these widths map to the same or adjacent LL2 grids;
    # distinct pixel sizes must still be attempted.


def test_staged_search_reports_failure_and_skips_unsafe(monkeypatch):
    received = Image.new("RGB", (100, 80))
    monkeypatch.setattr(
        robust, "_peaks",
        lambda _image, low, high, max_peaks: [(0.75, 0.9)],
    )
    monkeypatch.setattr(
        cascade, "priority_candidates_from_peaks",
        lambda _size, _peaks, _limit, first_peak_quota: [
            (1500, 1000), (120, 100),
        ],
    )
    calls = []

    def fail(image, size):
        calls.append(size)
        raise ValueError("invalid")

    monkeypatch.setattr(robust, "decode_at_size", fail)
    result = cascade.decode_staged(
        received, b"payload", stages=((1, 10), (1, 50))
    )
    assert result["blind_status"] == "FAIL:not_recovered"
    assert result["blind_attempts"] == 1
    assert result["stages_run"] == 2
    assert result["safe_attempts_by_stage"] == "1/10:1;1/50:0"
    assert result["unique_pixel_candidates_generated"] == 2
    assert calls == [(120, 100)]


def test_staged_search_does_not_use_oracle_size_for_candidates(monkeypatch):
    received = Image.new("RGB", (60, 45))
    calls = []
    monkeypatch.setattr(
        robust, "_peaks",
        lambda image, low, high, max_peaks: [
            (0.75, 0.7),
        ],
    )
    monkeypatch.setattr(
        cascade, "priority_candidates_from_peaks",
        lambda received_size, peaks, max_candidates, first_peak_quota: [
            (80, 60),
        ],
    )
    monkeypatch.setattr(
        robust, "decode_at_size",
        lambda image, size: calls.append(size) or b"payload",
    )
    result = cascade.decode_staged(
        received, b"payload", stages=((1, 10),)
    )
    assert result["blind_status"] == "PASS"
    assert result["blind_attempts"] == 1
    assert calls == [(80, 60)]


def test_probe_records_actual_recovery_and_oracle(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(3).integers(
            0, 256, (64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed",
        lambda image, strength: image,
    )
    monkeypatch.setattr(
        robust, "_feedback_embed",
        lambda image, packet: image,
    )
    monkeypatch.setattr(
        cascade, "decode_known_at_size",
        lambda image, size, payload: "PASS",
    )
    monkeypatch.setattr(
        cascade, "decode_staged",
        lambda image, payload, stages, per_stage_candidates: {
            "blind_status": "PASS",
            "blind_attempts": 2,
            "blind_decoded_size": "80x64",
            "successful_stage": "4/10",
            "stages_run": 1,
            "unique_pixel_candidates_generated": 160,
            "safe_attempts_by_stage": "4/10:2",
            "new_candidates_by_stage": "4/10:160",
        },
    )
    rows = cascade.probe(
        source, b"payload", strengths=[0.12], scales=[0.75],
    )
    assert len(rows) == 1
    assert rows[0]["oracle"] == "PASS"
    assert rows[0]["blind_status"] == "PASS"
    assert rows[0]["blind_same_ll2_shape"] is True
    assert rows[0]["blind_width_error_px"] == 0
    assert rows[0]["blind_height_error_px"] == 0
    assert set(rows[0]) == set(cascade.columns())
