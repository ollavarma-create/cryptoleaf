"""Research-only pilot/QIM visual ablation tests."""
import csv
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_artifact_ablation_probe as ablate


def test_flat_mask_and_regional_metrics_distinguish_texture():
    rng = np.random.default_rng(33)
    array = np.zeros((96, 128, 3), dtype=np.uint8)
    array[:, :48] = 110
    array[:, 64:] = rng.integers(0, 256, size=(96, 64, 3), dtype=np.uint8)
    original = Image.fromarray(array, "RGB")
    mask = ablate.flat_mask(original)
    assert mask.shape == (96, 128)
    assert mask[:, :30].all()
    assert not mask[:, 80:].any()
    changed = array.copy()
    changed[:, :40] = 125
    altered = Image.fromarray(changed, "RGB")
    stats = ablate.regional_metrics(original, altered, mask)
    assert 0 < stats["flat_fraction_pct"] < 100
    assert stats["flat_luma_mae"] > stats["textured_luma_mae"]
    assert stats["flat_luma_gt4_pct"] > 0
    assert stats["textured_luma_gt4_pct"] == 0


def test_regional_metrics_no_flat_or_no_textured():
    original = Image.new("RGB", (64, 64), (100, 100, 100))
    same = original.copy()
    all_flat = np.ones((64, 64), dtype=bool)
    result = ablate.regional_metrics(original, same, all_flat)
    assert result["flat_fraction_pct"] == 100
    assert result["textured_luma_mae"] is None
    assert result["textured_luma_gt4_pct"] is None
    with pytest.raises(ValueError):
        ablate.regional_metrics(original, same, np.ones((3, 4), bool))


def test_ablation_variants_metrics_and_full_resolution_samples(
    monkeypatch, tmp_path,
):
    source = tmp_path / "ui.png"
    arr = np.random.default_rng(17).integers(
        0, 230, size=(64, 80, 3), dtype=np.uint8
    )
    Image.fromarray(arr, "RGB").save(source)

    def pilot(image, strength):
        a = np.array(image.convert("RGB"), dtype=np.int16)
        a[:, :, 0] += 3
        return Image.fromarray(np.uint8(np.clip(a, 0, 255)), "RGB")

    def qim(image, packet):
        a = np.array(image.convert("RGB"), dtype=np.int16)
        a[:, :, 0] += 6
        return Image.fromarray(np.uint8(np.clip(a, 0, 255)), "RGB")

    monkeypatch.setattr(robust, "_pilot_embed", pilot)
    monkeypatch.setattr(robust, "_feedback_embed", qim)

    out = tmp_path / "samples"
    rows = ablate.probe(
        source, b"payload", [0.12], sample_dir=out
    )
    assert [row["variant"] for row in rows] == [
        "PILOT_ONLY", "QIM_ONLY", "FULL", "QIM_AFTER_PILOT"
    ]
    assert [row["comparison"] for row in rows] == [
        "ORIGINAL", "ORIGINAL", "ORIGINAL", "PILOT_ONLY"
    ]
    assert all(set(row) == set(ablate.columns()) for row in rows)
    assert rows[2]["rgb_mae"] > rows[1]["rgb_mae"] > rows[0]["rgb_mae"]
    assert rows[3]["rgb_mae"] == pytest.approx(rows[1]["rgb_mae"], abs=0.2)
    assert len(list(out.glob("*.png"))) == 8
    panel = next(out.glob("*-panel.png"))
    with Image.open(panel) as image:
        assert image.size == (160, 2 * (64 + 28))
    for file in out.glob("*.png"):
        assert file.stat().st_size > 0

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ablate.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "flat_luma_mae" in buffer.getvalue()
    assert "qim_after_pilot" in buffer.getvalue().lower()
