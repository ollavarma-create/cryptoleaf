"""Tests for decoder-only QIM candidate ranking (no production codec changes)."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from src.robust_packet import MAGIC
from tools import robust_qim_sync_rank_probe as qim


def test_known_magic_soft_parity_recovers_seeded_header():
    rng = np.random.default_rng(773)
    repeat = 13
    delta = 38.0
    ll = rng.normal(0, 115, size=(100, 100))
    positions = np.random.default_rng(robust.SEED).permutation(ll.size)
    bits = np.unpackbits(np.frombuffer(MAGIC, dtype=np.uint8))
    q = np.where(np.repeat(bits, repeat) == 1, 3.0, 2.0)
    # Controlled header is deliberately far from the wrong-seed template.
    ll.ravel()[positions[:len(q)]] = q * delta + rng.normal(
        0, 0.7, size=len(q)
    )
    result = qim.score_ll2(ll, delta, repeat)
    assert result["header"] > 0.98
    assert result["lattice"] > 0.2
    assert result["wrong_seed_header"] < 0.35
    assert all(np.isfinite(v) for v in result.values())


def test_flat_cover_scores_finite_and_uninformative():
    scores = qim.score_ll2(np.full((80, 80), 992.0), 38.0, 13)
    assert scores["lattice"] == pytest.approx(0, abs=1e-12)
    assert scores["header"] == pytest.approx(0, abs=1e-12)
    assert scores["wrong_seed_header"] == pytest.approx(0, abs=1e-12)


def test_score_requires_two_disjoint_header_samples():
    count = len(MAGIC) * 8 * 13
    with pytest.raises(ValueError, match="Insufficient"):
        qim.score_ll2(np.zeros(count * 2 - 1), 38.0, 13)


def test_frozen_candidate_order_and_pixel_dedup(monkeypatch):
    monkeypatch.setattr(qim.angular, "fft_workspace", lambda image: "fft")
    monkeypatch.setattr(
        qim.multi, "variant_peaks",
        lambda workspace, freq, angle, max_peaks: [(angle, 1.0)] * max_peaks,
    )
    def candidates(received_size, peaks, max_candidates, first_peak_quota):
        assert max_candidates == 160
        assert first_peak_quota == 10
        return [(100, 80), (101, 80)] if peaks[0][0] == 0 else [
            (101, 80), (102, 80)
        ]
    monkeypatch.setattr(qim, "priority_candidates_from_peaks", candidates)
    assert qim.frozen_candidates(
        Image.new("RGB", (60, 48)),
        variants=((0.38, 0.0), (0.38, 5.0)),
        stages=((4, 10), (16, 10)),
    ) == [(100, 80), (101, 80), (102, 80)]


def test_stable_tie_break_and_control_rankers(monkeypatch):
    image = Image.new("RGB", (60, 48))
    sizes = [(100, 80), (101, 80), (102, 80)]
    scores = {
        sizes[0]: dict(header=0.1, lattice=0.0, wrong_seed_header=0.9,
                       wrong_delta_header=0.2),
        sizes[1]: dict(header=0.8, lattice=0.7, wrong_seed_header=0.1,
                       wrong_delta_header=0.2),
        sizes[2]: dict(header=0.8, lattice=0.2, wrong_seed_header=0.2,
                       wrong_delta_header=0.2),
    }
    monkeypatch.setattr(
        qim, "score_size", lambda received, size, delta, repeat: scores[size]
    )
    ranked, meta = qim.rank_sizes(image, sizes, 38.0, 13)
    assert meta["scored_count"] == 3
    assert ranked["baseline"] == sizes
    assert ranked["header"] == [sizes[1], sizes[2], sizes[0]]
    assert ranked["lattice"] == [sizes[1], sizes[2], sizes[0]]
    assert ranked["wrong_seed_header"][0] == sizes[0]
    assert ranked["wrong_delta_header"] == sizes


def test_evaluate_blind_equal_budget_and_no_oracle_in_ranker(monkeypatch):
    sizes = [(100, 80), (105, 80), (109, 80)]
    monkeypatch.setattr(
        qim, "frozen_candidates", lambda received: sizes
    )
    def ranker(received, candidates, delta, repeat):
        assert candidates == sizes
        return {
            "baseline": sizes,
            "header": [sizes[2], sizes[1], sizes[0]],
            "lattice": [sizes[1], sizes[0], sizes[2]],
            "wrong_seed_header": sizes,
            "wrong_delta_header": sizes,
        }, {
            "scores": [
                dict(header=0.1, lattice=0.2, wrong_seed_header=0.0,
                     wrong_delta_header=0.0)
                for _ in sizes
            ],
            "scored_count": len(sizes),
        }
    monkeypatch.setattr(qim, "rank_sizes", ranker)
    calls = []
    def decoder(received, size):
        calls.append(size)
        if size == sizes[2]:
            return b"payload"
        raise ValueError("no packet")
    monkeypatch.setattr(robust, "decode_at_size", decoder)
    result = qim.evaluate(
        Image.new("RGB", (60, 48)), (109, 80), b"payload",
        max_ranked=3, blind_budget=2,
    )
    assert result["baseline_blind_status"].startswith("FAIL")
    assert result["header_blind_status"] == "PASS"
    assert result["header_blind_attempts"] == 1
    assert result["lattice_blind_status"].startswith("FAIL")
    assert result["baseline_blind_attempts"] == 2
    assert result["lattice_blind_attempts"] == 2
    assert calls == [sizes[0], sizes[1], sizes[2], sizes[1], sizes[0]]
    assert result["baseline_grid_rank"] == 3
    assert result["header_grid_rank"] == 1
    assert result["header_exact_rank"] == 1


def test_rank_only_does_not_decode(monkeypatch):
    sizes = [(100, 80), (101, 80)]
    monkeypatch.setattr(qim, "frozen_candidates", lambda received: sizes)
    monkeypatch.setattr(
        qim, "rank_sizes",
        lambda received, candidates, delta, repeat: (
            {key: sizes for key in (
                "baseline", "header", "lattice",
                "wrong_seed_header", "wrong_delta_header"
            )},
            {
                "scores": [
                    dict(header=0.0, lattice=0.0, wrong_seed_header=0.0,
                         wrong_delta_header=0.0)
                    for _ in sizes
                ],
                "scored_count": 2,
            },
        ),
    )
    monkeypatch.setattr(
        robust, "decode_at_size",
        lambda *args: pytest.fail("rank-only probe decoded packet"),
    )
    result = qim.evaluate(
        Image.new("RGB", (60, 48)), (101, 80), b"payload",
        max_ranked=2, blind_budget=0,
    )
    assert result["header_grid_rank"] == 2
    assert result["header_blind_status"] == "NOT_RUN"
    assert result["header_blind_attempts"] is None
