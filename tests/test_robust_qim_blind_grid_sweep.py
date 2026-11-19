"""Tests for blind aspect-ratio LL2-grid QIM research probe."""
import csv
import inspect
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_blind_grid_sweep as sweep


@pytest.mark.parametrize(
    "received,original",
    [
        ((794, 358), (1280, 577)),
        ((740, 605), (1193, 976)),
        ((743, 420), (1198, 677)),
        ((794, 595), (1280, 960)),
    ],
)
def test_blind_bank_includes_off_prior_62_percent_sizes(received, original):
    grids = sweep.blind_grid_bank(received, 0.5, 2)
    all_sizes = [size for sizes in grids.values() for size in sizes]
    assert original in all_sizes
    assert len(all_sizes) == len(set(all_sizes))
    assert len(grids) < len(all_sizes)
    assert all(
        sweep.grid_key(size) == key
        for key, sizes in grids.items() for size in sizes
    )
    assert all(max(size) <= robust.MAX_LONGEST for size in all_sizes)


def test_blind_rank_does_not_accept_original_size():
    assert "original_size" not in inspect.signature(sweep.blind_rank).parameters
    with pytest.raises(ValueError):
        sweep.blind_grid_bank((100, 80), min_scale=0.1)
    with pytest.raises(ValueError):
        sweep.blind_grid_bank((100, 80), height_jitter=5)
    with pytest.raises(ValueError):
        sweep.blind_rank(Image.new("RGB", (100, 80)), top_grids=0)


def test_representative_is_deterministic_and_inside_grid():
    sizes = [(120, 80), (119, 79), (118, 78), (117, 77)]
    selected = sweep.representative(sizes, (60, 40))
    assert selected in sizes
    assert selected == sweep.representative(list(reversed(sizes)), (60, 40))


def test_coarse_to_fine_and_blind_decode(monkeypatch):
    image = Image.new("RGB", (60, 40))
    true_size = (120, 80)
    true_grid = sweep.grid_key(true_size)
    seen = []

    def fake_score(received, size, delta, repeat):
        seen.append(size)
        assert received is image
        score = (
            0.95 if size == true_size else
            0.65 if sweep.grid_key(size) == true_grid else 0.01
        )
        return {"header": score}

    monkeypatch.setattr(sweep.qim, "score_size", fake_score)
    decoded = []

    def fake_decode(received, size):
        decoded.append(size)
        if size == true_size:
            return b"payload"
        raise ValueError("wrong size")

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    result = sweep.evaluate(
        image, true_size, b"payload",
        top_grids=3, blind_budget=40,
    )
    assert result["grid_count"] > 3
    assert result["candidate_count"] > result["grid_count"]
    assert result["coarse_true_grid_rank"] == 1
    assert result["true_grid_shortlisted"]
    assert result["refined_exact_rank"] == 1
    assert result["refined_true_score"] == pytest.approx(0.95)
    assert result["blind_status"] == "PASS"
    assert result["blind_attempts"] == 1
    assert decoded == [true_size]
    assert len(seen) == result["grid_count"] + result["refined_count"] - 3
    assert set(result).issubset(set(sweep.columns()))


def test_rank_only_never_decodes(monkeypatch):
    image = Image.new("RGB", (60, 40))
    monkeypatch.setattr(
        sweep.qim, "score_size",
        lambda received, size, delta, repeat: {
            "header": 0.7 if sweep.grid_key(size) == (30, 20) else 0.0
        },
    )
    monkeypatch.setattr(
        robust, "decode_at_size",
        lambda *args: pytest.fail("rank-only called packet decoder"),
    )
    result = sweep.evaluate(
        image, (120, 80), b"payload", top_grids=2
    )
    assert result["blind_status"] == "NOT_RUN"
    assert result["refined_exact_rank"] is not None


def test_probe_oracle_only_after_rank(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(15).integers(
            0, 255, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed",
        lambda image, strength: image.convert("YCbCr").convert("RGB")
    )
    monkeypatch.setattr(
        robust, "_feedback_embed", lambda image, packet: image
    )
    events = []

    def fake_evaluate(received, original_size, payload, min_scale,
                      height_jitter, top_grids, delta, repeat, blind_budget):
        events.append("rank")
        assert original_size == (80, 64)
        assert received.size == (50, 40)
        assert blind_budget == 0
        return {
            key: None for key in sweep.columns()
            if key not in {
                "source", "source_sha256", "encoded_width",
                "encoded_height", "received_width", "received_height",
                "resize_scale", "pilot_strength",
                "effective_pilot_strength", "adaptive_pilot",
                "delta", "repeat", "min_scale", "height_jitter",
                "status", "oracle",
            }
        }

    def fake_oracle(received, size, payload):
        events.append("oracle")
        return "PASS"

    monkeypatch.setattr(sweep, "evaluate", fake_evaluate)
    monkeypatch.setattr(sweep, "decode_known_at_size", fake_oracle)
    rows = sweep.probe(source, b"payload", [0.12], [0.62])
    assert events == ["rank", "oracle"]
    assert len(rows) == 1
    assert rows[0]["oracle"] == "PASS"
    assert set(rows[0]) == set(sweep.columns())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=sweep.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "coarse_true_grid_rank" in buffer.getvalue()
