"""Tests for generic scale-prior QIM synchronization research (decoder-only)."""
import csv
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_scale_bank_probe as scale


def test_scale_bank_contains_both_difficult_screen_dimensions():
    # Only received dimensions are inputs; the known originals are
    # test assertions, never supplied to the bank generator.
    bank_a = scale.scale_bank((640, 288))
    bank_b = scale.scale_bank((596, 488))
    assert (1280, 577) in bank_a
    assert (1193, 976) in bank_b
    assert len(bank_a) == len(set(bank_a))
    assert len(bank_b) == len(set(bank_b))
    assert all(max(size) <= robust.MAX_LONGEST for size in bank_a + bank_b)
    assert scale.scale_bank((640, 288)) == bank_a


def test_bank_uses_generic_multiple_ratios_not_oracle():
    bank = scale.scale_bank((599, 338))
    assert (1198, 677) in bank
    assert any(abs(w - 599 * 1.5) <= 2 for w, _ in bank)
    assert any(abs(w - 599 * 1.25) <= 2 for w, _ in bank)
    assert (1198, 677) not in scale.scale_bank(
        (599, 338), priors=(1.25, 1.5), jitter=2
    )


def test_invalid_prior_and_jitter_rejected():
    with pytest.raises(ValueError):
        scale.parse_priors("1,1")
    with pytest.raises(ValueError):
        scale.parse_priors("1,nan")
    with pytest.raises(ValueError):
        scale.parse_priors("0.5,2")
    with pytest.raises(ValueError):
        scale.scale_bank((640, 288), jitter=5)


def test_equal_budget_and_unmarked_control(monkeypatch):
    image = Image.new("RGB", (640, 288))
    true_size = (1280, 577)
    bank = [(800, 360), (1280, 576), true_size, (1279, 577)]
    monkeypatch.setattr(scale, "scale_bank",
                        lambda received_size, priors, jitter: bank)
    events = []

    def fake_rank(received, candidates, delta, repeat):
        assert candidates == bank
        if received is image:
            events.append("marked")
            scores = [
                dict(header=x, lattice=0.0,
                     wrong_seed_header=0.0, wrong_delta_header=0.0)
                for x in (0.1, 0.2, 0.9, 0.3)
            ]
            header_order = [bank[2], bank[3], bank[1], bank[0]]
        else:
            events.append("unmarked")
            scores = [
                dict(header=x, lattice=0.0,
                     wrong_seed_header=0.0, wrong_delta_header=0.0)
                for x in (0.01, 0.02, 0.03, 0.04)
            ]
            header_order = list(reversed(bank))
        return {
            "baseline": bank,
            "header": header_order,
            "lattice": bank,
            "wrong_seed_header": bank,
            "wrong_delta_header": bank,
        }, {
            "scores": scores,
            "scored_count": 4,
            "lattice_control_eligible_count": 4,
        }

    monkeypatch.setattr(scale.qim, "rank_sizes", fake_rank)
    decoded = []

    def fake_decode(received, size):
        decoded.append(size)
        if size == true_size:
            return b"payload"
        raise ValueError("wrong size")

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    result = scale.evaluate(
        image, true_size, b"payload", blind_budget=2,
        unmarked=Image.new("RGB", image.size),
    )
    assert events == ["marked", "unmarked"]
    assert result["baseline_exact_rank"] == 3
    assert result["header_exact_rank"] == 1
    assert result["baseline_blind_status"].startswith("FAIL")
    assert result["header_blind_status"] == "PASS"
    assert result["header_blind_attempts"] == 1
    assert result["marked_max_header_score"] == pytest.approx(0.9)
    assert result["unmarked_max_header_score"] == pytest.approx(0.04)
    assert result["unmarked_header_score_at_true_size"] == pytest.approx(0.03)
    assert decoded == [bank[0], bank[1], true_size]


def test_rank_only_never_decodes(monkeypatch):
    monkeypatch.setattr(
        scale, "scale_bank",
        lambda received_size, priors, jitter: [(100, 80)]
    )
    monkeypatch.setattr(
        scale.qim, "rank_sizes",
        lambda received, candidates, delta, repeat: (
            {key: candidates for key in (
                "baseline", "header", "lattice",
                "wrong_seed_header", "wrong_delta_header"
            )},
            {
                "scores": [dict(header=0.4, lattice=0.2,
                                wrong_seed_header=0.0,
                                wrong_delta_header=0.0)],
                "scored_count": 1,
                "lattice_control_eligible_count": 1,
            },
        ),
    )
    monkeypatch.setattr(
        robust, "decode_at_size",
        lambda *args: pytest.fail("rank-only test called decoder")
    )
    result = scale.evaluate(
        Image.new("RGB", (50, 40)), (100, 80), b"payload"
    )
    assert result["header_exact_rank"] == 1
    assert result["header_blind_status"] == "NOT_RUN"


def test_probe_csv_schema_and_oracle_after_scoring(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(11).integers(
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

    def fake_evaluate(received, original_size, payload, delta, repeat,
                      priors, jitter, blind_budget, unmarked):
        events.append("rank")
        assert original_size == (80, 64)
        assert received.size == (40, 32)
        assert unmarked.size == (40, 32)
        return {
            key: None for key in scale.columns()
            if key not in {
                "source", "source_sha256", "encoded_width",
                "encoded_height", "received_width", "received_height",
                "resize_scale", "pilot_strength",
                "effective_pilot_strength", "adaptive_pilot",
                "delta", "repeat", "scale_priors", "jitter",
                "status", "oracle",
            }
        }

    def fake_oracle(received, size, payload):
        events.append("oracle")
        return "PASS"

    monkeypatch.setattr(scale, "evaluate", fake_evaluate)
    monkeypatch.setattr(scale, "decode_known_at_size", fake_oracle)
    rows = scale.probe(
        source, b"payload", strengths=[0.12], scales=[0.5]
    )
    assert events == ["rank", "oracle"]
    assert len(rows) == 1
    assert rows[0]["oracle"] == "PASS"
    assert set(rows[0]) == set(scale.columns())
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=scale.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "unmarked_max_header_score" in output.getvalue()
