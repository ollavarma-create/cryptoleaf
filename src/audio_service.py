"""Save steganographic audio only after verifying a disk round-trip."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import soundfile as sf

from .audio_decoder import decode_audio


def save_verified_audio(
    target: str | Path,
    stego,
    samplerate: int,
    payload: bytes,
    password: str,
    *,
    format: str,
    subtype: str,
) -> Path:
    """Write privately, decode saved samples, then publish exclusively."""
    destination = Path(target)
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    with NamedTemporaryFile(dir=destination.parent, prefix=".cryptoleaf-", suffix=".tmp", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        sf.write(str(temporary), stego, samplerate, format=format, subtype=subtype)
        recovered = decode_audio(temporary, password)
        if recovered != payload:
            raise ValueError("Saved audio did not verify: decoded payload differs")
        os.link(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
