"""Regression checks for JPEG output publishing safety."""
import pytest
from src.jpeg_optimizer import _publish_exclusive


def test_jpeg_publish_creates_output(tmp_path):
    target = tmp_path / "stego.jpg"
    _publish_exclusive(target, b"jpeg-data")
    assert target.read_bytes() == b"jpeg-data"
    assert not list(tmp_path.glob(".cryptoleaf-*"))


def test_jpeg_publish_refuses_existing_output(tmp_path):
    target = tmp_path / "stego.jpg"
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        _publish_exclusive(target, b"new")
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".cryptoleaf-*"))
