"""Unmarked negative controls for the blind LL2-grid QIM research tool."""
import csv
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_blind_grid_negative_control as neg


def fake_rank(received, min_scale, height_jitter, top_grids, delta, repeat):
    return [(100, 80), (104, 84)], {
        "candidate_count": 120,
        "grid_count": 25,
        "refined_count": 2,
        "coarse": [
            ((25, 20), 0.18, (100, 80)),
            ((26, 21), 0.11, (104, 84)),
        ],
        "refined_scores": [
            ((100, 80), 0.20),
            ((104, 84), 0.12),
        ],
        "bank_seconds": 0.001,
        "coarse_seconds": 0.1,
        "refine_seconds": 0.02,
    }


def test_unmarked_no_valid_packet_is_negative_control_pass(monkeypatch):
    received = Image.new("RGB", (60, 40))
    monkeypatch.setattr(neg.sweep, "blind_rank", fake_rank)
    calls = []

    def fake_decode(image, size):
        calls.append(size)
        raise ValueError("Invalid CLR1 header")

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    result = neg.evaluate(received, decode_budget=40)
    assert result["decode_status"] == "NO_VALID_PACKET"
    assert result["any_valid_packet"] is False
    assert result["decode_attempts"] == 2
    assert calls == [(100, 80), (104, 84)]
    assert result["coarse_max_header_score"] == 0.18
    assert result["refined_max_header_score"] == 0.20
    assert set(result).issubset(set(neg.columns()))


def test_any_valid_packet_is_false_positive_regardless_of_content(monkeypatch):
    received = Image.new("RGB", (60, 40))
    monkeypatch.setattr(neg.sweep, "blind_rank", fake_rank)

    def fake_decode(image, size):
        if size == (100, 80):
            raise ValueError("Invalid CLR1 header")
        return b"unexpected but CRC-validated payload"

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    result = neg.evaluate(received, decode_budget=40)
    assert result["decode_status"] == "FALSE_POSITIVE"
    assert result["any_valid_packet"] is True
    assert result["decode_attempts"] == 2
    assert result["decoded_size"] == "104x84"
    assert result["decoded_payload_length"] == len(
        b"unexpected but CRC-validated payload"
    )


def test_rank_only_does_not_call_packet_decoder(monkeypatch):
    received = Image.new("RGB", (60, 40))
    monkeypatch.setattr(neg.sweep, "blind_rank", fake_rank)
    monkeypatch.setattr(
        robust, "decode_at_size",
        lambda *args: pytest.fail("rank-only decoded a packet"),
    )
    result = neg.evaluate(received, decode_budget=0)
    assert result["decode_status"] == "NOT_RUN"
    assert result["any_valid_packet"] is None
    assert result["decode_attempts"] is None


def test_probe_never_embeds_or_calls_oracle(monkeypatch, tmp_path):
    source = tmp_path / "unmarked.png"
    Image.fromarray(
        np.random.default_rng(17).integers(
            0, 255, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)

    def prohibited(*args, **kwargs):
        pytest.fail("unmarked control invoked embedding or oracle")

    monkeypatch.setattr(robust, "_pilot_embed", prohibited)
    monkeypatch.setattr(robust, "_feedback_embed", prohibited)
    monkeypatch.setattr(neg, "decode_known_at_size", prohibited, raising=False)

    seen = []

    def fake_evaluate(received, min_scale, height_jitter, top_grids,
                      delta, repeat, decode_budget):
        seen.append((received.size, decode_budget))
        return {
            key: None for key in neg.columns()
            if key not in {
                "source", "source_sha256", "control_type",
                "received_width", "received_height", "resize_scale",
                "min_scale", "height_jitter", "delta", "repeat",
            }
        }

    monkeypatch.setattr(neg, "evaluate", fake_evaluate)
    rows = neg.probe(source, [0.62], decode_budget=40)
    assert seen == [((50, 40), 40)]
    assert len(rows) == 1
    assert rows[0]["control_type"] == "UNMARKED"
    assert set(rows[0]) == set(neg.columns())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=neg.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "coarse_max_header_score" in buffer.getvalue()
