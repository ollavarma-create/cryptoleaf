"""Fast regression tests for the local multi-cover robustness matrix."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from src.robust_packet import pack
from tools import robust_batch_matrix as matrix


def test_image_discovery_and_explicit_names(tmp_path):
    (tmp_path / "z photo.JPG").touch()
    (tmp_path / "a.png").touch()
    (tmp_path / "notes.txt").touch()
    assert [p.name for p in matrix.image_paths(tmp_path)] == [
        "a.png", "z photo.JPG"
    ]
    assert [p.name for p in matrix.image_paths(
        tmp_path, ["z photo.JPG", "a.png", "a.png"]
    )] == ["z photo.JPG", "a.png"]
    with pytest.raises(ValueError):
        matrix.image_paths(tmp_path, ["../other.jpg"])


def test_float_parser_and_column_names():
    assert matrix.parse_floats(
        "0,0.12,0.18,0", low=0, high=0.5, label="strengths"
    ) == [0.0, 0.12, 0.18]
    with pytest.raises(ValueError):
        matrix.parse_floats("nan", low=0, high=0.5, label="strengths")
    fields = matrix.columns([85, 60], [0.75, 0.5])
    assert "jpeg85_oracle" in fields
    assert "scale_0.75_oracle" in fields
    assert "scale_0.5_oracle" in fields


def test_small_cover_capacity_skip_does_not_crash(tmp_path):
    source = tmp_path / "tiny.png"
    Image.new("RGB", (32, 32), "gray").save(source)
    payload = b"matrix test"
    rows = matrix.run_image(
        source, pack(payload), payload, [0.0], [85], [0.75]
    )
    assert len(rows) == 1
    assert rows[0]["status"].startswith("SKIP:")
    assert rows[0]["source"] == "tiny.png"


def test_valid_cover_smoke(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(2).integers(0, 256, (256, 256, 3), dtype=np.uint8),
        "RGB",
    ).save(source)
    payload = b"small"
    packet = pack(payload)
    monkeypatch.setattr(
        matrix, "quality_metrics",
        lambda _reference, _marked: {key: 0 for key in matrix.METRIC_FIELDS},
    )
    monkeypatch.setattr(
        matrix, "jpeg_roundtrip", lambda image, _quality: image
    )
    rows = matrix.run_image(
        source, packet, payload, [0.0], [85], [0.75]
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "OK"
    assert rows[0]["png_oracle"] == "PASS"
    assert rows[0]["jpeg85_oracle"] == "PASS"
    assert rows[0]["scale_0.75_oracle"] in (
        "PASS", "FAIL:ValueError"
    )
