"""Internal byte-oriented payload model.

The existing image, audio and JPEG wire formats already accept raw bytes.
This module adds *application-level* metadata without inserting new bytes
into those formats, preserving backward compatibility.

A future Mosaic format can serialize this metadata in its own versioned
container; current codecs must receive only Payload.data.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Payload:
    data: bytes
    filename: str | None = None
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise TypeError("Payload.data must be bytes")
        if self.filename is not None:
            if not isinstance(self.filename, str) or not self.filename:
                raise ValueError("Payload.filename must be a nonempty string or None")
            if Path(self.filename).name != self.filename or self.filename in {".", ".."}:
                raise ValueError("Payload.filename must not contain a directory")
            if "/" in self.filename or "\\" in self.filename:
                raise ValueError("Payload.filename must not contain path separators")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError("Payload.media_type must be a nonempty string")

    @classmethod
    def from_text(cls, text: str) -> "Payload":
        if not isinstance(text, str):
            raise TypeError("text must be str")
        return cls(text.encode("utf-8"), media_type="text/plain; charset=utf-8")

    @classmethod
    def from_file(cls, path: str | Path) -> "Payload":
        import mimetypes
        source = Path(path)
        return cls(
            source.read_bytes(),
            filename=source.name,
            media_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
        )

    def as_text(self) -> str:
        return self.data.decode("utf-8")
