"""Regression tests for batch capacity classification."""
from unittest.mock import patch

import pytest
from PIL import Image

from src.batch_processor import process_batch
from src.image_encoder import CapacityError


def _jpeg_input(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    Image.new("RGB", (16, 16), "white").save(source / "small.jpg")
    return source, tmp_path / "output"


def test_jpeg_capacity_error_is_skipped(tmp_path):
    source, output = _jpeg_input(tmp_path)
    with patch("src.batch_processor.optimize_jpeg", side_effect=CapacityError("too few blocks")):
        results = process_batch(source, output, b"message", "password")
    assert len(results) == 1
    assert results[0].status == "SKIPPED"
    assert "CapacityError" in results[0].error
    assert not (output / "small_cryptoleaf.jpg").exists()
    assert not list(output.glob(".cryptoleaf-*"))


def test_other_jpeg_error_is_failure(tmp_path):
    source, output = _jpeg_input(tmp_path)
    with patch("src.batch_processor.optimize_jpeg", side_effect=ValueError("no strength survived")):
        results = process_batch(source, output, b"message", "password")
    assert results[0].status == "FAIL"
    assert "ValueError" in results[0].error


def test_existing_output_is_still_skipped(tmp_path):
    source, output = _jpeg_input(tmp_path)
    output.mkdir()
    (output / "small_cryptoleaf.jpg").write_bytes(b"existing")
    results = process_batch(source, output, b"message", "password", skip_existing=True)
    assert results[0].status == "SKIPPED"
    assert results[0].error == ""


def test_existing_output_without_skip_is_failure(tmp_path):
    source, output = _jpeg_input(tmp_path)
    output.mkdir()
    (output / "small_cryptoleaf.jpg").write_bytes(b"existing")
    results = process_batch(source, output, b"message", "password")
    assert results[0].status == "FAIL"
    assert "FileExistsError" in results[0].error
