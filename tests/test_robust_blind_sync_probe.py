"""Fast regression tests for Fourier pilot blind-size synchronization probe."""
import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_blind_sync_probe as sync


def test_candidate_rank_and_nearest_distance():
    sizes = [(100, 80), (120, 90), (140, 100)]
    assert sync.rank_and_distance(sizes, (120, 90)) == (2, 0)
    assert sync.rank_and_distance(sizes, (121, 92)) == (None, 3)
    assert sync.rank_and_distance([], (120, 90)) == (None, None)


def test_extended_priority50_deduplicates_and_keeps_strongest_first(monkeypatch):
    def fake_candidates(_received_size, scale, limit):
        if scale == 0.5:
            yield from [(200, 160), (201, 160), (202, 160)]
        else:
            yield from [(200, 160), (300, 240)]
    monkeypatch.setattr(robust, "_candidate_sizes", fake_candidates)
    candidates = sync.priority_candidates_from_peaks(
        (100, 80), [(0.5, 0.9), (0.75, 0.6)], max_candidates=5
    )
    assert candidates == [(200, 160), (201, 160), (202, 160), (300, 240)]
    assert len(candidates) == len(set(candidates))


def test_extended_blind_decodes_only_from_candidates(monkeypatch):
    image = Image.new("RGB", (160, 120))
    payload = b"correct payload"
    attempted = []

    def fake_decode(_image, size):
        attempted.append(size)
        if size == (320, 240):
            return payload
        raise ValueError("No valid packet")

    monkeypatch.setattr(robust, "decode_at_size", fake_decode)
    status, attempts, size = sync.decode_from_candidates(
        image, [(200, 160), (320, 240), (400, 300)], payload
    )
    assert (status, attempts, size) == ("PASS", 2, "320x240")
    assert attempted == [(200, 160), (320, 240)]


def test_extended_blind_reports_failure_without_oracle_fallback(monkeypatch):
    monkeypatch.setattr(
        robust, "decode_at_size",
        lambda _image, _size: (_ for _ in ()).throw(ValueError("not found")),
    )
    status, attempts, size = sync.decode_from_candidates(
        Image.new("RGB", (160, 120)), [(320, 240), (400, 300)], b"data"
    )
    assert (status, attempts, size) == ("FAIL:not_recovered", 2, None)


def test_decoded_size_offsets_and_haar_ll2_shape():
    # Real-cover size pairs from the two successful blind CSVs.
    assert sync.decoded_size_metrics("1280x868", (1280, 867)) == (0, 1, True)
    assert sync.decoded_size_metrics("1200x677", (1198, 677)) == (2, 0, True)
    # Crossing the next four-pixel LL2 boundary changes the permutation grid.
    assert sync.decoded_size_metrics("1201x677", (1198, 677)) == (3, 0, False)
    assert sync.decoded_size_metrics("1280x869", (1280, 867)) == (0, 2, False)
    assert sync.decoded_size_metrics(None, (1280, 867)) == (None, None, None)


def test_scale_and_pilot_parsers():
    assert sync.parse_scales("0.75,0.5,0.75") == [0.75, 0.5]
    assert sync.parse_strengths("0,0.12,0.18,0") == [0, 0.12, 0.18]
    for value in ("", "nan", "inf", "0", "1.2"):
        with pytest.raises(ValueError):
            sync.parse_scales(value)
    for value in ("", "nan", "inf", "-0.1", "0.8"):
        with pytest.raises(ValueError):
            sync.parse_strengths(value)


def test_probe_separates_oracle_and_size_rank(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(1).integers(
            0, 256, (256, 320, 3), dtype=np.uint8
        )
    ).save(source)
    observed = []
    original = robust.DELTA, robust.REPEAT

    def fake_embed(image, _packet):
        observed.append((robust.DELTA, robust.REPEAT))
        return image

    monkeypatch.setattr(robust, "_feedback_embed", fake_embed)
    monkeypatch.setattr(robust, "_pilot_embed", lambda image, strength: image)
    monkeypatch.setattr(
        sync, "quality_metrics", lambda _a, _b: {
            "psnr_db": 40, "ssim_y": 0.99,
        }
    )
    monkeypatch.setattr(
        sync, "decode_known_at_size", lambda _image, _size, _payload: "PASS"
    )
    monkeypatch.setattr(sync, "effective_strength", lambda _img, x: x)
    monkeypatch.setattr(
        robust, "_peaks",
        lambda _img, **kwargs: [(0.5 if kwargs else 0.75, 0.8)]
    )
    monkeypatch.setattr(
        robust, "candidate_sizes_priority50",
        lambda _img, max_candidates: iter([(200, 180)])
    )
    monkeypatch.setattr(
        robust, "_candidate_sizes",
        lambda _received_size, scale, limit: iter([(320, 256)])
    )

    rows = sync.probe(
        source, b"test", [0.0, 0.12], [0.75, 0.5],
        38.0, 13, 160, False,
    )
    assert len(rows) == 4
    assert all(row["oracle"] == "PASS" for row in rows)
    assert all(row["standard_true_size_rank"] is None for row in rows)
    assert all(row["extended_true_size_rank"] == 1 for row in rows)
    assert all(row["blind_status"] == "NOT_RUN" for row in rows)
    assert all(row["extended_blind_status"] == "NOT_RUN" for row in rows)
    assert all(row["extended_blind_attempts"] is None for row in rows)
    assert all(row["blind_same_ll2_shape"] is None for row in rows)
    assert all(row["extended_blind_same_ll2_shape"] is None for row in rows)
    assert observed == [(38.0, 13), (38.0, 13)]
    assert (robust.DELTA, robust.REPEAT) == original
    assert set(rows[0]) == set(sync.columns())
