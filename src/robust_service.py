"""Application-facing robust message API, independent of Qt.

Only this layer knows about text encryption and image file persistence.
Existing image codecs and legacy decoders remain untouched.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image

from .crypto_gcm import encrypt_gcm, decrypt_gcm
from .robust_image import encode as embed_robust, decode as extract_robust
from .robust_packet import MAX_PAYLOAD

GCM_OVERHEAD = 44  # 16-byte salt, 12-byte nonce, 16-byte tag
MAX_MESSAGE_BYTES = MAX_PAYLOAD - GCM_OVERHEAD
SUPPORTED_OUTPUTS = {"PNG", "JPEG", "WEBP", "BMP"}


def encode_message(cover_path: str | Path, message: bytes, password: str,
                   output_path: str | Path, output_format: str = "PNG") -> None:
    """Encrypt, embed and save; verify the *saved* image before replacing destination.

    A temporary sibling prevents a failed verification from leaving a corrupt output.
    """
    if not password:
        raise ValueError("Robust mode requires a password")
    if not isinstance(message, bytes):
        raise TypeError("message must be bytes")
    if len(message) > MAX_MESSAGE_BYTES:
        raise ValueError(f"Robust message too long: {len(message)} bytes; maximum {MAX_MESSAGE_BYTES}")
    fmt = output_format.upper()
    if fmt not in SUPPORTED_OUTPUTS:
        raise ValueError(f"Unsupported robust output format: {output_format}")
    target = Path(output_path)
    if Path(cover_path).resolve() == target.resolve():
        raise ValueError("Output file must differ from source image")
    with Image.open(cover_path) as source:
        encoded = embed_robust(source, encrypt_gcm(message, password))
    # Pillow needs explicit format because the temporary filename has a .tmp suffix.
    temporary = target.with_name(target.name + ".tmp")
    save_options = {"quality": 85, "subsampling": 0} if fmt == "JPEG" else ({"lossless": True} if fmt == "WEBP" else {})
    try:
        encoded.save(temporary, format=fmt, **save_options)
        with Image.open(temporary) as check:
            recovered = extract_robust(check).payload
        if decrypt_gcm(recovered, password) != message:
            raise ValueError("Saved robust image did not verify")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def decode_message(stego_path: str | Path, password: str) -> bytes:
    """Blindly recover and authenticate a robust message."""
    if not password:
        raise ValueError("Robust mode requires a password")
    with Image.open(stego_path) as source:
        encrypted = extract_robust(source).payload
    return decrypt_gcm(encrypted, password)
