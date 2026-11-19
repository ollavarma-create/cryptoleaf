#!/usr/bin/env python3
"""Batch oracle-size robustness/quality matrix for diverse local cover images.

Research only. Does not modify input images or the CryptoLeaf codec. Source
images stay local. PNG is tested in-memory (lossless equivalence); JPEG tests
re-encode the marked RGB image. Blind size search is intentionally excluded.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, UnidentifiedImageError

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_pilot_sweep import (
    decode_known_at_size,
    effective_strength,
    jpeg_roundtrip,
    reference_image,
)
from tools.robust_quality_compare import quality_metrics

EXTENSIONS = {".jpg", ".jpeg", ".png"}
METRIC_FIELDS = (
    "psnr_db", "ssim_y", "ssim_y_p01", "rgb_mae",
    "pixel_change_gt4_pct", "pixel_change_gt8_pct",
    "new_saturated_pixel_pct", "worst_tile_luma_mae",
)


def image_paths(directory: Path, names: list[str] | None = None) -> list[Path]:
    """Discover images, or select exact names (including names with spaces)."""
    if not directory.is_dir():
        raise ValueError(f"Input directory does not exist: {directory}")
    if names:
        paths = []
        for name in dict.fromkeys(names):
            if Path(name).name != name:
                raise ValueError(f"--name must be a filename, not a path: {name}")
            path = directory / name
            if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                raise ValueError(f"Image not found or unsupported: {path}")
            paths.append(path)
        return paths
    return sorted(
        (p for p in directory.iterdir()
         if p.is_file() and p.suffix.lower() in EXTENSIONS),
        key=lambda p: p.name.casefold(),
    )


def parse_floats(text: str, *, low: float, high: float, label: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in text.split(",")]
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {text}") from exc
    if not values or any(not np.isfinite(x) or not low <= x <= high for x in values):
        raise ValueError(f"{label} must be finite values between {low} and {high}")
    return list(dict.fromkeys(values))


def columns(jpeg_qualities: list[int], scales: list[float]) -> list[str]:
    return [
        "source", "source_format", "source_bytes",
        "source_width", "source_height", "reference_width", "reference_height",
        "nominal_strength", "effective_strength", "delta", "repeat",
        "status", "png_oracle",
        *[f"jpeg{q}_oracle" for q in jpeg_qualities],
        *[f"scale_{s:g}_oracle" for s in scales],
        *METRIC_FIELDS, "seconds",
    ]


def run_image(
    path: Path,
    packet: bytes,
    payload: bytes,
    strengths: list[float],
    jpeg_qualities: list[int],
    scales: list[float],
    images_out: Path | None = None,
    index: int = 0,
) -> list[dict]:
    """Run one cover. One row per strength; capacity failures are recorded."""
    try:
        with Image.open(path) as opened:
            original_size = opened.size
            original_format = opened.format or "UNKNOWN"
            reference = reference_image(opened)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return [
            {"source": path.name, "nominal_strength": strength,
             "status": f"ERROR:unreadable:{type(exc).__name__}"}
            for strength in strengths
        ]

    # Equalise RGB/YCbCr roundtrips across all strengths as in pilot_sweep.
    zero_pilot = reference.convert("YCbCr").convert("RGB")
    base = {
        "source": path.name,
        "source_format": original_format,
        "source_bytes": path.stat().st_size,
        "source_width": original_size[0],
        "source_height": original_size[1],
        "reference_width": reference.width,
        "reference_height": reference.height,
        "delta": robust.DELTA,
        "repeat": robust.REPEAT,
    }
    rows = []
    for strength in strengths:
        started = time.perf_counter()
        row = {
            **base, "nominal_strength": strength,
            "effective_strength": round(effective_strength(reference, strength), 6),
            "status": "OK",
        }
        try:
            pilot = (
                zero_pilot if strength == 0
                else robust._pilot_embed(reference, strength=strength)
            )
            marked = robust._feedback_embed(pilot, packet)
        except ValueError as exc:
            row["status"] = f"SKIP:{str(exc)}"
            row["seconds"] = round(time.perf_counter() - started, 2)
            rows.append(row)
            continue

        row["png_oracle"] = decode_known_at_size(marked, marked.size, payload)
        for quality in jpeg_qualities:
            received = jpeg_roundtrip(marked, quality)
            row[f"jpeg{quality}_oracle"] = decode_known_at_size(
                received, marked.size, payload
            )
        for scale in scales:
            scaled_size = tuple(max(32, round(d * scale)) for d in marked.size)
            resized = marked.resize(scaled_size, Image.Resampling.LANCZOS)
            row[f"scale_{scale:g}_oracle"] = decode_known_at_size(
                resized, marked.size, payload
            )
        metrics = quality_metrics(reference, marked)
        row.update({field: metrics[field] for field in METRIC_FIELDS})
        if images_out is not None:
            # Prefix with index to avoid collisions among equal stems.
            name = f"{index:03d}-{path.stem}-s{strength:.3f}.png"
            marked.save(images_out / name)
        row["seconds"] = round(time.perf_counter() - started, 2)
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[],
                        help="Exact filename to test; repeat for a subset")
    parser.add_argument("--limit", type=int,
                        help="Maximum number of images (for a quick smoke test)")
    parser.add_argument("--strengths", default="0,0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--jpeg-qualities", default="85,75,60")
    parser.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    parser.add_argument("--images-out", type=Path,
                        help="Optional EMPTY directory to save marked PNGs")
    args = parser.parse_args()

    try:
        strengths = parse_floats(
            args.strengths, low=0, high=0.5, label="strengths"
        )
        scales = parse_floats(args.scales, low=0.2, high=1.0, label="scales")
        jpeg_qualities = [
            int(item.strip()) for item in args.jpeg_qualities.split(",")
        ]
        if not jpeg_qualities or any(not 1 <= q <= 100 for q in jpeg_qualities):
            raise ValueError("JPEG qualities must be integers from 1 to 100")
        jpeg_qualities = list(dict.fromkeys(jpeg_qualities))
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be positive")
        paths = image_paths(args.directory, args.name or None)
        if args.limit:
            paths = paths[:args.limit]
        if not paths:
            raise ValueError("No supported images found")
        packet = pack(args.message.encode("utf-8"))
        if args.csv.exists():
            raise ValueError(f"Refusing to overwrite existing CSV: {args.csv}")
        if args.images_out is not None and args.images_out.exists() and any(
            args.images_out.iterdir()
        ):
            raise ValueError(
                f"Image output directory must be empty: {args.images_out}"
            )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    if args.images_out is not None:
        args.images_out.mkdir(parents=True, exist_ok=True)
    fields = columns(jpeg_qualities, scales)
    print(
        f"Testing {len(paths)} covers × {len(strengths)} strengths "
        f"= {len(paths) * len(strengths)} encodes; oracle-size decoding only.",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, path in enumerate(paths, 1):
            rows = run_image(
                path, packet, args.message.encode("utf-8"),
                strengths, jpeg_qualities, scales, args.images_out, index,
            )
            for row in rows:
                writer.writerow(row)
                checks = [
                    str(row.get("png_oracle", "")),
                    *[str(row.get(f"jpeg{q}_oracle", "")) for q in jpeg_qualities],
                    *[str(row.get(f"scale_{s:g}_oracle", "")) for s in scales],
                ]
                print(
                    f"[{index}/{len(paths)}] {path.name} "
                    f"pilot={row['nominal_strength']:.3f} "
                    f"status={row['status']} "
                    f"pass={checks.count('PASS')}/{len(checks)} "
                    f"PSNR={row.get('psnr_db', 'N/A')} "
                    f"SSIM={row.get('ssim_y', 'N/A')}",
                    flush=True,
                )
            stream.flush()  # Keep partial results if interrupted.
    print("CSV:", args.csv)
    print(
        "All resize tests use the true original encoded size (oracle). "
        "No blind synchronization conclusions can be drawn from this CSV."
    )


if __name__ == "__main__":
    main()
