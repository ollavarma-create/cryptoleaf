"""Tests for the native and JPEG-after-resize QIM image fidelity gate."""
import csv
import io

import numpy as np
from PIL import Image
import pytest

from src import robust_image as robust
from tools import robust_qim_jpeg_fidelity_probe as fidelity


def test_paired_metrics_identical_and_different_images():
    original = Image.fromarray(
        np.random.default_rng(13).integers(
            0, 256, size=(48, 64, 3), dtype=np.uint8
        ), "RGB"
    )
    identical = fidelity.paired_metrics(original, original.copy())
    assert identical["psnr_db"] is None
    assert identical["ssim_y"] == pytest.approx(1.0)
    assert identical["pixel_change_gt8_pct"] == 0
    assert set(identical) == set(fidelity.METRICS)

    changed = np.array(original)
    changed[5:15, 10:20, :] = 0
    altered = fidelity.paired_metrics(
        original, Image.fromarray(changed, "RGB")
    )
    assert altered["psnr_db"] is not None
    assert altered["pixel_change_gt8_pct"] > 0
    assert altered["ssim_y"] < 1.0


def test_probe_uses_same_transform_on_marked_and_unmarked(
    monkeypatch, tmp_path,
):
    source = tmp_path / "new-screenshot.png"
    Image.fromarray(
        np.random.default_rng(14).integers(
            0, 256, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed", lambda image, strength: image
    )
    monkeypatch.setattr(
        robust, "_feedback_embed", lambda image, packet: image
    )
    samples = tmp_path / "visual"
    rows = fidelity.probe(
        source, b"payload", [0.12], [0.68], [70],
        sample_dir=samples, sample_scale=0.68, sample_quality=70,
    )
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == set(fidelity.columns())
    assert row["reference_width"] == 80
    assert row["reference_height"] == 64
    assert row["received_width"] == 54
    assert row["received_height"] == 44
    assert row["native_ssim_y"] == pytest.approx(1.0)
    assert row["received_ssim_y"] == pytest.approx(1.0)
    assert row["native_pixel_change_gt8_pct"] == 0
    assert row["received_pixel_change_gt8_pct"] == 0
    assert row["jpeg_subsampling"] == "4:2:0"
    assert row["transform_order"] == "resize_then_jpeg"
    assert len(list(samples.glob("*.png"))) == 3
    for file in samples.glob("*.png"):
        with Image.open(file) as image:
            assert image.mode == "RGB"
            assert image.width > 0
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fidelity.columns())
    writer.writeheader()
    writer.writerows(rows)
    assert "native_ssim_y_p01" in output.getvalue()


def test_probe_detects_embedding_only_distortion(monkeypatch, tmp_path):
    source = tmp_path / "cover.png"
    Image.fromarray(
        np.random.default_rng(15).integers(
            0, 256, size=(64, 80, 3), dtype=np.uint8
        ), "RGB"
    ).save(source)
    monkeypatch.setattr(
        robust, "_pilot_embed", lambda image, strength: image
    )

    def altered(image, packet):
        a = np.array(image.convert("RGB"))
        a[:, :, 0] = np.bitwise_xor(a[:, :, 0], 0x1F)
        return Image.fromarray(a, "RGB")

    monkeypatch.setattr(robust, "_feedback_embed", altered)
    rows = fidelity.probe(
        source, b"payload", [0.12], [0.55, 0.68], [85, 70]
    )
    assert len(rows) == 4
    assert all(row["native_ssim_y"] < 1 for row in rows)
    assert all(row["received_ssim_y"] < 1 for row in rows)
    assert all(row["received_pixel_change_gt4_pct"] > 0 for row in rows)
    assert all(set(row) == set(fidelity.columns()) for row in rows)
