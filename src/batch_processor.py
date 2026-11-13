"""Format-aware, sequential batch image encoding for Cryptoleaf."""

from __future__ import annotations

import csv
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from .image_encoder import CapacityError, encode_image
from .image_decoder import decode_image
from .jpeg_optimizer import optimize_jpeg

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


def process_batch(
    input_dir: str | Path,
    output_dir: str | Path,
    payload: bytes,
    password: str,
    *,
    quality: int = 85,
    dry_run: bool = False,
    skip_existing: bool = False,
) -> list[BatchResult]:
    """Process immediate image files, returning one result per supported file.

    Does not overwrite outputs. Existing files are either skipped or reported as
    errors. Output and report directories must be separate from the input tree.
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
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")

    files = sorted((p for p in source.iterdir() if p.is_file() and p.suffix.lower() in FORMATS), key=lambda p: p.name)
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    results: list[BatchResult] = []
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
                status = "DRY_RUN"
            elif fmt == "JPEG":
                # Optimize into a private file, then publish atomically without overwrite.
                with NamedTemporaryFile(dir=destination, prefix=".cryptoleaf-", suffix=".jpg", delete=False) as temp:
                    temp_path = Path(temp.name)
                try:
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
        results.append(BatchResult(cover.name, str(output), fmt, status, strength, attempts, psnr, round(time.perf_counter() - start, 3), error))
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
