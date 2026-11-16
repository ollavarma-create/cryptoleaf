"""Audio persistence regression tests, independent of audio codec fixtures."""
from unittest.mock import patch

import pytest

from src.audio_service import save_verified_audio


def test_audio_save_verified(tmp_path):
    target = tmp_path / "result.wav"
    with patch("src.audio_service.sf.write", side_effect=lambda path, *a, **k: __import__("pathlib").Path(path).write_bytes(b"wav")), \
         patch("src.audio_service.decode_audio", return_value=b"hello"):
        assert save_verified_audio(target, None, 44100, b"hello", "pw", format="WAV", subtype="PCM_16") == target
    assert target.read_bytes() == b"wav"
    assert not list(tmp_path.glob(".cryptoleaf-*"))


def test_audio_verification_failure_does_not_publish(tmp_path):
    target = tmp_path / "result.wav"
    with patch("src.audio_service.sf.write", side_effect=lambda path, *a, **k: __import__("pathlib").Path(path).write_bytes(b"wav")), \
         patch("src.audio_service.decode_audio", return_value=b"wrong"):
        with pytest.raises(ValueError, match="verify"):
            save_verified_audio(target, None, 44100, b"hello", "pw", format="WAV", subtype="PCM_16")
    assert not target.exists()
    assert not list(tmp_path.glob(".cryptoleaf-*"))


def test_audio_existing_file_preserved(tmp_path):
    target = tmp_path / "result.wav"
    target.write_bytes(b"original")
    with patch("src.audio_service.sf.write", side_effect=lambda path, *a, **k: __import__("pathlib").Path(path).write_bytes(b"wav")), \
         patch("src.audio_service.decode_audio", return_value=b"hello"):
        with pytest.raises(FileExistsError):
            save_verified_audio(target, None, 44100, b"hello", "pw", format="WAV", subtype="PCM_16")
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".cryptoleaf-*"))
