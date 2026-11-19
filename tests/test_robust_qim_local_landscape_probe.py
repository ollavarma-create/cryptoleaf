"""Tests for oracle-assisted QIM local score landscape (not blind search)."""
import csv
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_local_landscape_probe as landscape


def test_local_window_symmetric_including_true_size():
    sizes = landscape.local_sizes((1193, 976), radius=2)
    assert len(sizes) == 25
    assert len(set(sizes)) == 25
    assert (1193, 976, 0, 0) in sizes
    assert (1191, 974, -2, -2) in sizes
    assert (1195, 978, 2, 2) in sizes
    with pytest.raises(ValueError):
        landscape.local_sizes((100, 80), radius=13)


def test_true_size_rank_and_grid_diagnostics(monkeypatch):
    image = Image.new("RGB", (100, 80))
    monkeypatch.setattr(landscape.cascade, "safe_size", lambda size: True)
    seen = []

    def fake_score(received, size, delta, repeat):
        seen.append(size)
        dx, dy = size[0] - 100, size[1] - 80
        value = 0.8 if (dx, dy) == (0, 0) else (
            0.9 if (dx, dy) == (1, 0) else 0.1
        )
        return {
            "header": value,
            "wrong_seed_header": 0.0,
            "wrong_delta_header": 0.0,
            "lattice": 0.2,
        }

    monkeypatch.setattr(landscape.qim, "score_size", fake_score)
    rows = landscape.score_window(image, (100, 80), 38.0, 13, 1)
    assert len(rows) == 9
    assert len(seen) == 9
    assert all(r["rank_of_true_size_in_local_window"] == 2 for r in rows)
    assert all(r["true_header_score"] == 0.8 for r in rows)
    assert all(r["best_wrong_header_score"] == 0.9 for r in rows)
    assert next(
        r for r in rows if (r["dx"], r["dy"]) == (0, 0)
    )["same_ll2_grid"]


def test_unsafe_candidate_is_reported_not_scored(monkeypatch):
    image = Image.new("RGB", (100, 80))
    monkeypatch.setattr(
        landscape.cascade, "safe_size",
        lambda size: size[0] <= 100,
    )
    seen = []
    monkeypatch.setattr(
        landscape.qim, "score_size",
        lambda received, size, delta, repeat: (
            seen.append(size) or {
                "header": 0.7, "wrong_seed_header": 0.0,
                "wrong_delta_header": 0.0, "lattice": 0.1,
            }
        ),
    )
    rows = landscape.score_window(image, (100, 80), 38.0, 13, 1)
    assert len(rows) == 9
    assert len(seen) == 6
    assert sum(r["status"] == "SKIP:unsafe_size" for r in rows) == 3
    assert all(
        r["header_score"] is None
        for r in rows if r["status"] != "OK"
    )


def test_oracle_runs_only_after_all_local_scores(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(13).integers(
            0, 255, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed",
        lambda image, strength: image.convert("YCbCr").convert("RGB"),
    )
    monkeypatch.setattr(
        robust, "_feedback_embed", lambda image, packet: image
    )
    events = []

    def fake_score_window(received, encoded_size, delta, repeat, radius):
        events.append("score")
        assert encoded_size == (80, 64)
        assert received.size == (50, 40)
        assert radius == 1
        return [{
            "dx": 0, "dy": 0,
            "candidate_width": 80, "candidate_height": 64,
            "same_ll2_grid": True,
            "status": "OK",
            "header_score": 0.8,
            "wrong_seed_header_score": 0.0,
            "wrong_delta_header_score": 0.0,
            "lattice_score": 0.1,
            "score_seconds": 0.001,
            "rank_of_true_size_in_local_window": 1,
            "true_header_score": 0.8,
            "best_wrong_header_score": 0.1,
        }]

    def fake_oracle(received, size, payload):
        events.append("oracle")
        return "PASS"

    monkeypatch.setattr(landscape, "score_window", fake_score_window)
    monkeypatch.setattr(landscape, "decode_known_at_size", fake_oracle)
    rows = landscape.probe(
        source, b"payload", [0.12], [0.62], radius=1
    )
    assert events == ["score", "oracle"]
    assert len(rows) == 1
    assert rows[0]["oracle"] == "PASS"
    assert set(rows[0]) == set(landscape.columns())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=landscape.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "rank_of_true_size_in_local_window" in buffer.getvalue()
