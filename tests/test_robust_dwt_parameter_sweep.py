"""Regression tests for the fixed-pilot, matched-parameter DWT sweep."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from src.robust_packet import pack
from tools import robust_dwt_parameter_sweep as sweep


def test_parameter_grid_varies_one_axis_and_has_one_baseline():
    grid = sweep.parameter_grid([24, 32, 40], [7, 9, 11])
    assert grid == [
        ("baseline", 32.0, 9),
        ("delta", 24, 9),
        ("delta", 40, 9),
        ("repeat", 32.0, 7),
        ("repeat", 32.0, 11),
    ]
    assert len(grid) == len(set((delta, repeat) for _, delta, repeat in grid))


def test_parameter_parsers_reject_unsafe_values():
    assert sweep.parse_deltas("24,32,40,32") == [24, 32, 40]
    assert sweep.parse_repeats("7,9,11,9") == [7, 9, 11]
    for value in ("nan", "inf", "0", "129", ""):
        with pytest.raises(ValueError):
            sweep.parse_deltas(value)
    for value in ("0", "8", "32", "abc", ""):
        with pytest.raises(ValueError):
            sweep.parse_repeats(value)


def test_codec_parameters_restored_after_exception():
    original = robust.DELTA, robust.REPEAT
    with pytest.raises(RuntimeError):
        with sweep.codec_parameters(48, 13):
            assert (robust.DELTA, robust.REPEAT) == (48, 13)
            raise RuntimeError("simulated encode failure")
    assert (robust.DELTA, robust.REPEAT) == original


def test_small_cover_is_explicit_capacity_skip():
    reference = Image.new("RGB", (32, 32), "gray")
    payload = b"capacity"
    row = sweep.test_pair(
        reference, reference, pack(payload), payload, 32, 9, 0.0, "baseline"
    )
    assert row["status"] == "SKIP:insufficient_DWT_capacity"
    assert row["required_coefficients"] > row["ll2_capacity"]


def test_pair_uses_matched_parameters_and_records_controls(monkeypatch):
    reference = Image.fromarray(
        np.random.default_rng(0).integers(0, 256, (192, 192, 3), dtype=np.uint8)
    )
    payload = b"test"
    packet = pack(payload)
    observed = []

    def fake_embed(image, _packet):
        observed.append(("encode", robust.DELTA, robust.REPEAT))
        return image

    def fake_decode(image, _size, _payload):
        observed.append(("decode", robust.DELTA, robust.REPEAT))
        return "PASS"

    def fake_errors(_image, _packet):
        observed.append(("errors", robust.DELTA, robust.REPEAT))
        return {key: 0 for key in sweep.ERROR_FIELDS}

    monkeypatch.setattr(robust, "_feedback_embed", fake_embed)
    monkeypatch.setattr(sweep, "decode_known_at_size", fake_decode)
    monkeypatch.setattr(sweep, "bit_errors", fake_errors)
    monkeypatch.setattr(sweep, "jpeg_roundtrip", lambda image, _q: image)
    monkeypatch.setattr(
        sweep, "quality_metrics",
        lambda _reference, _marked: {
            key: 0 for key in sweep.METRIC_FIELDS
        },
    )
    monkeypatch.setattr(
        robust, "_read_bytes", lambda _image, _size, _n: packet[:6]
    )
    before = robust.DELTA, robust.REPEAT
    row = sweep.test_pair(
        reference, reference, packet, payload, 40, 11, 0.0, "delta"
    )
    assert row["status"] == "OK"
    assert row["png_oracle"] == "PASS"
    assert row["jpeg60_oracle"] == "PASS"
    assert row["scale_0.75_oracle"] == "PASS"
    assert row["scale_0.5_oracle"] == "PASS"
    assert row["after50_codeword_byte_errors"] == 0
    assert row["after50_magic_bit_errors"] == 0
    assert row["after50_length_bit_errors"] == 0
    assert row["capacity_used_pct"] > 0
    assert observed and all((delta, repeat) == (40, 11) for _, delta, repeat in observed)
    assert (robust.DELTA, robust.REPEAT) == before


def test_encoder_failure_is_recorded_and_params_restored(monkeypatch):
    reference = Image.new("RGB", (192, 192), "gray")
    payload = b"test"
    packet = pack(payload)
    original = robust.DELTA, robust.REPEAT

    def fail(_image, _packet):
        raise ValueError("synthetic failure")

    monkeypatch.setattr(robust, "_feedback_embed", fail)
    row = sweep.test_pair(
        reference, reference, packet, payload, 48, 11, 0.0, "delta"
    )
    assert row["status"] == "SKIP:synthetic failure"
    assert (robust.DELTA, robust.REPEAT) == original
