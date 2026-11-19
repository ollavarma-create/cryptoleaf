"""Tests for paired adaptive vs fixed pilot-amplitude research."""
import pytest

from src import robust_image as robust
from tools import robust_pilot_adaptation_probe as adaptation


def test_parse_modes():
    assert adaptation.parse_modes("adaptive,fixed") == adaptation.MODES
    assert adaptation.parse_modes("fixed") == ("fixed",)
    for invalid in ("", "adaptive,", "unknown", "fixed,fixed"):
        with pytest.raises(ValueError):
            adaptation.parse_modes(invalid)


def test_pilot_mode_restores_global_setting_even_on_error():
    previous = robust.ADAPTIVE_PILOT
    try:
        with adaptation.pilot_mode("fixed"):
            assert robust.ADAPTIVE_PILOT is False
            with adaptation.pilot_mode("adaptive"):
                assert robust.ADAPTIVE_PILOT is True
            assert robust.ADAPTIVE_PILOT is False
            raise RuntimeError("deliberate test failure")
    except RuntimeError:
        pass
    assert robust.ADAPTIVE_PILOT is previous
    with pytest.raises(ValueError):
        with adaptation.pilot_mode("invalid"):
            pass
    assert robust.ADAPTIVE_PILOT is previous


def test_probe_pairs_four_arm_and_blind_by_case_not_row_order(monkeypatch):
    original = robust.ADAPTIVE_PILOT
    spectral_calls = []
    blind_calls = []

    def fake_spectral(source, payload, strengths, scales, delta, repeat):
        mode = "adaptive" if robust.ADAPTIVE_PILOT else "fixed"
        spectral_calls.append(mode)
        # Deliberately reverse row order to ensure keyed join.
        return [
            {
                "source": "cover.png",
                "pilot_strength": 0.18,
                "resize_scale": 0.5,
                **{col: 0.18 for col in adaptation.SPECTRAL_COLUMNS},
            },
            {
                "source": "cover.png",
                "pilot_strength": 0.12,
                "resize_scale": 0.75,
                **{col: 0.12 for col in adaptation.SPECTRAL_COLUMNS},
            },
        ]

    def fake_blind(
        source, payload, strengths, scales, stages, delta,
        repeat, per_stage_candidates
    ):
        mode = "adaptive" if robust.ADAPTIVE_PILOT else "fixed"
        blind_calls.append(mode)
        assert stages == ((4, 10), (16, 10))
        return [
            {
                **{col: None for col in adaptation.cascade.columns()},
                "source": "cover.png",
                "pilot_strength": 0.12,
                "resize_scale": 0.75,
                "blind_status": "PASS" if mode == "fixed" else "FAIL",
            },
            {
                **{col: None for col in adaptation.cascade.columns()},
                "source": "cover.png",
                "pilot_strength": 0.18,
                "resize_scale": 0.5,
                "blind_status": "PASS",
            },
        ]

    monkeypatch.setattr(adaptation.signal, "probe", fake_spectral)
    monkeypatch.setattr(adaptation.cascade, "probe", fake_blind)
    rows = adaptation.probe(
        source="cover.png", payload=b"message",
        strengths=[0.12, 0.18], scales=[0.75, 0.5],
    )
    assert len(rows) == 4
    assert spectral_calls == ["adaptive", "fixed"]
    assert blind_calls == ["adaptive", "fixed"]
    assert robust.ADAPTIVE_PILOT is original
    assert [row["pilot_mode"] for row in rows] == [
        "adaptive", "adaptive", "fixed", "fixed",
    ]
    assert [row["pilot_dwt_true_score"] for row in rows] == [
        0.12, 0.18, 0.12, 0.18,
    ]
    assert rows[0]["blind_status"] == "FAIL"
    assert rows[2]["blind_status"] == "PASS"
    assert all(set(row) == set(adaptation.columns()) for row in rows)
