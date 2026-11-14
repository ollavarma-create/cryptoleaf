"""Service-layer checks using stubs for the already-tested heavy image codec."""
from unittest.mock import patch
from types import SimpleNamespace
import pytest
from PIL import Image
from src import robust_service as service


def test_maximum_plaintext_length():
    assert service.MAX_MESSAGE_BYTES == 199


def test_password_required(tmp_path):
    with pytest.raises(ValueError, match="password"):
        service.encode_message(tmp_path / "a.png", b"hi", "", tmp_path / "b.png")
    with pytest.raises(ValueError, match="password"):
        service.decode_message(tmp_path / "b.png", "")


def test_too_long_rejected_before_io(tmp_path):
    with pytest.raises(ValueError, match="maximum"):
        service.encode_message(tmp_path / "a.png", b"x" * 200, "secret", tmp_path / "b.png")


def test_roundtrip_saved_image(tmp_path):
    source = tmp_path / "source.png"
    dest = tmp_path / "output.png"
    Image.new("RGB", (32, 32), "grey").save(source)
    # Test orchestration, not Fourier mathematics: embed/extract is tested separately.
    with patch.object(service, "encrypt_gcm", return_value=b"cipher"), \
         patch.object(service, "decrypt_gcm", return_value=b"hello"), \
         patch.object(service, "embed_robust", return_value=Image.new("RGB", (32, 32))), \
         patch.object(service, "extract_robust", return_value=SimpleNamespace(payload=b"cipher")):
        service.encode_message(source, b"hello", "pw", dest)
        assert dest.exists()
        assert service.decode_message(dest, "pw") == b"hello"


def test_verification_failure_keeps_destination(tmp_path):
    source = tmp_path / "source.png"
    dest = tmp_path / "output.png"
    Image.new("RGB", (32, 32)).save(source)
    dest.write_bytes(b"existing")
    with patch.object(service, "encrypt_gcm", return_value=b"cipher"), \
         patch.object(service, "decrypt_gcm", return_value=b"different"), \
         patch.object(service, "embed_robust", return_value=Image.new("RGB", (32, 32))), \
         patch.object(service, "extract_robust", return_value=SimpleNamespace(payload=b"cipher")):
        with pytest.raises(ValueError, match="verify"):
            service.encode_message(source, b"hello", "pw", dest)
    assert dest.read_bytes() == b"existing"
    assert not (tmp_path / "output.png.tmp").exists()
