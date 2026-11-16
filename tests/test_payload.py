"""Tests for the internal payload model and wire-format compatibility."""
import pytest

from src.payload import Payload


def test_utf8_text_is_bytes():
    payload = Payload.from_text("Hei 🌲")
    assert payload.data == "Hei 🌲".encode("utf-8")
    assert payload.as_text() == "Hei 🌲"
    assert payload.filename is None


def test_binary_roundtrip_and_metadata(tmp_path):
    original = bytes(range(256)) + bytes([0, 255])
    source = tmp_path / "sample.bin"
    source.write_bytes(original)
    payload = Payload.from_file(source)
    assert payload.data == original
    assert payload.filename == "sample.bin"
    assert payload.media_type == "application/octet-stream"
    assert source.read_bytes() == original


def test_payload_is_immutable():
    payload = Payload(b"hello")
    with pytest.raises(AttributeError):
        payload.data = b"changed"


@pytest.mark.parametrize("name", ["../secret", "a/b", "a\\\\b", "", ".", ".."])
def test_filename_must_be_basename(name):
    with pytest.raises(ValueError):
        Payload(b"data", filename=name)


def test_reject_nonbytes():
    with pytest.raises(TypeError):
        Payload("text")


def test_binary_is_not_forced_to_utf8():
    with pytest.raises(UnicodeDecodeError):
        Payload(bytes([255])).as_text()
