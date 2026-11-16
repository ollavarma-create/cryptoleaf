"""Format-aware, sequential batch image encoding for Cryptoleaf."""

from __future__ import annotations

import csv
import os
import time
from dataclasses import asdict, dataclass
from typing import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from .image_encoder import CapacityError, encode_image
from .image_decoder import decode_image
from .jpeg_optimizer import optimize_jpeg
from .jpeg_v03 import message_fits, max_message_size
from .robust_service import encode_message as encode_robust_message, MAX_MESSAGE_BYTES
from .robust_image import REPEAT, MAX_LONGEST
from .robust_packet import HEADER_BYTES, PARITY
from .payload import Payload
from PIL import ImageOps
from PIL import Image

FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".bmp": "BMP", ".webp": "WEBP"}
REPORT_FIELDS = ("image", "output", "format", "status", "strength", "attempts", "psnr", "elapsed_s", "error")


@dataclass(frozen=True)
class BatchResult:
    image: str
    output: str
    format: str
    status: str
    strength: int | None = None
    attempts: int | None = None
    psnr: float | None = None
    elapsed_s: float = 0.0
    error: str = ""


def _check_legacy_capacity(cover: Path, fmt: str, payload: bytes, password: str) -> None:
    """Validate geometric capacity without encrypting or writing output files."""
    with Image.open(cover) as image:
        width, height = image.size
    if fmt == "JPEG":
        if not message_fits(width, height, len(payload)):
            maximum = max_message_size(width, height)
            raise CapacityError(
                f"JPEG capacity exceeded: {len(payload)} bytes required, "
                f"maximum {maximum} bytes for {width}x{height}"
            )
    else:
        # Legacy AES-CBC wire format: salt(16) + IV(16) + PKCS#7 ciphertext.
        encrypted_size = 32 + 16 * (len(payload) // 16 + 1) if password else len(payload)
        # The encoder Reed-Solomon protects both the 32-byte header and payload.
        needed = (32 + 64) + encrypted_size + ((encrypted_size + 190) // 191) * 64
        available = width * height * 3 // 8
        if needed > available:
            raise CapacityError(
                f"{fmt} capacity exceeded: {needed} encoded bytes required, "
                f"{available} available for {width}x{height}"
            )


def _check_robust_capacity(cover: Path, payload: bytes) -> None:
    """Check the robust transport's maximum length and geometric LL2 capacity.

    This is a necessary preflight, not a guarantee that the saved image will
    survive JPEG recompression or pass the full robust round-trip check.
    """
    if len(payload) > MAX_MESSAGE_BYTES:
        raise CapacityError(
            f"Robust capacity exceeded: {len(payload)} bytes; maximum {MAX_MESSAGE_BYTES}"
        )
    with Image.open(cover) as image:
        width, height = ImageOps.exif_transpose(image).size
    scale = min(1.0, MAX_LONGEST / max(width, height))
    if scale < 1.0:
        width, height = (max(32, round(value * scale)) for value in (width, height))
    # GCM adds 44 bytes. RS8 adds 8 parity bytes and a 4-byte CRC;
    # CLR1 adds a 6-byte header. Each bit uses nine LL2 coefficients.
    packet_bytes = HEADER_BYTES + len(payload) + 44 + PARITY + 4
    needed = packet_bytes * 8 * REPEAT
    available = ((height + 3) // 4) * ((width + 3) // 4)
    if needed > available:
        raise CapacityError(
            f"Robust capacity exceeded: need {needed} LL2 coefficients, "
            f"available {available} for {width}x{height}"
        )


def process_batch(
    input_dir: str | Path,
    output_dir: str | Path,
    payload: bytes | Payload,
    password: str,
    *,
    quality: int = 85,
    mode: str = "legacy",
    dry_run: bool = False,
    skip_existing: bool = False,
    on_progress: Callable[[BatchResult, int, int], None] | None = None,
) -> list[BatchResult]:
    """Process immediate image files, returning one result per supported file.

    Does not overwrite outputs. Existing files are either skipped or reported as
    errors. Output and report directories must be separate from the input tree.
    Optional on_progress(result, completed, total) runs after each image,
    in the caller thread. GUI callers must emit a Qt signal, not touch widgets.
    """
    source = Path(input_dir).resolve()
    destination = Path(output_dir).resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    if source == destination or source in destination.parents:
        raise ValueError("Output directory must not be inside the input directory")
    if not password:
        raise ValueError("A password is required for JPEG v0.3")
    if not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    if mode not in {"legacy", "robust"}:
        raise ValueError("mode must be legacy or robust")
    if isinstance(payload, Payload):
        payload = payload.data
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes or Payload")

    files = sorted((p for p in source.iterdir() if p.is_file() and p.suffix.lower() in FORMATS), key=lambda p: p.name)
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    results: list[BatchResult] = []
    total = len(files)
    for cover in files:
        fmt = FORMATS[cover.suffix.lower()]
        output = destination / f"{cover.stem}_cryptoleaf{cover.suffix.lower()}"
        start = time.perf_counter()
        status, strength, attempts, psnr, error = "OK", None, None, None, ""
        try:
            if output.exists():
                if skip_existing:
                    status = "SKIPPED"
                else:
                    raise FileExistsError(f"Output exists: {output}")
            elif dry_run:
                if mode == "robust":
                    _check_robust_capacity(cover, payload)
                else:
                    _check_legacy_capacity(cover, fmt, payload, password)
                status = "DRY_RUN"
            elif mode == "robust":
                _check_robust_capacity(cover, payload)
                # The robust service may replace its target. Always give it a
                # private temporary target and publish via exclusive hard-link.
                with NamedTemporaryFile(dir=destination, prefix=".cryptoleaf-", suffix=".tmp", delete=False) as temp:
                    temp_path = Path(temp.name)
                try:
                    temp_path.unlink()  # service publishes exclusively; reserve a unique name first
                    encode_robust_message(cover, payload, password, temp_path, output_format=fmt)
                    os.link(temp_path, output)
                finally:
                    temp_path.unlink(missing_ok=True)
            elif fmt == "JPEG":
                # Optimize into a private file, then publish atomically without overwrite.
                with NamedTemporaryFile(dir=destination, prefix=".cryptoleaf-", suffix=".jpg", delete=False) as temp:
                    temp_path = Path(temp.name)
                try:
                    temp_path.unlink()  # optimizer publishes exclusively
                    result = optimize_jpeg(cover, temp_path, payload, password, quality=quality, mode="first_success")
                    os.link(temp_path, output)
                    strength, attempts, psnr = result.strength, result.attempts, result.psnr
                finally:
                    temp_path.unlink(missing_ok=True)
            else:
                # Lossless encoder returns (image, actual_format).
                image, actual_format = encode_image(cover, payload, password, output_format=fmt)
                try:
                    if actual_format != fmt:
                        raise ValueError(f"Unexpected output format: {actual_format}")
                    # Save to a private temporary file, then publish without replacing.
                    with NamedTemporaryFile(dir=destination, prefix=".cryptoleaf-", suffix=".tmp", delete=False) as temp:
                        temp_path = Path(temp.name)
                    try:
                        image.save(temp_path, format=fmt, **({"lossless": True} if fmt == "WEBP" else {}))
                        # Verify the bytes actually saved, not only the in-memory image.
                        if decode_image(temp_path, password) != payload:
                            raise ValueError("Round-trip verification failed")
                        # Hard-link provides exclusive creation (no silent overwrite).
                        os.link(temp_path, output)
                    finally:
                        temp_path.unlink(missing_ok=True)
                finally:
                    image.close()
        except CapacityError as exc:
            status = "SKIPPED"
            error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            status = "FAIL"
            error = f"{type(exc).__name__}: {exc}"
        item = BatchResult(cover.name, str(output), fmt, status, strength, attempts, psnr, round(time.perf_counter() - start, 3), error)
        results.append(item)
        if on_progress is not None:
            on_progress(item, len(results), total)
    return results


def write_report(results: list[BatchResult], report_path: str | Path) -> Path:
    """Write a CSV report without overwriting an existing report."""
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
    return path
