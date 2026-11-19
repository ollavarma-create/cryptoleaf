#!/usr/bin/env python3
"""Research-only image fidelity gate for robust QIM under JPEG-after-resize.

Compare the same source image with and without robust embedding at:
  (1) the native codec reference dimensions, and
  (2) after identical LANCZOS resize + JPEG 4:2:0 recompression.

Quality metrics isolate the additional distortion from embedding: the
JPEG/resizing effects common to both arms are not counted as embedding
distortion. No decoder, oracle, QIM search, or production-code changes.

Optionally save native and received full-resolution side-by-side PNGs
and an 8x exaggerated native RGB difference. Inspect actual native
side-by-side images at 100% zoom; metrics can miss structured artifacts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import parse_scales, parse_strengths
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import effective_strength, reference_image
from tools.robust_quality_compare import quality_metrics
from tools.robust_qim_blind_grid_jpeg_probe import (
    jpeg_roundtrip_420, parse_qualities,
)

METRICS = (
    "psnr_db", "ssim_y", "ssim_y_p01", "rgb_mae",
    "pixel_change_gt4_pct", "pixel_change_gt8_pct",
    "pixel_absdiff_p99", "new_saturated_pixel_pct",
    "worst_tile_luma_mae", "worst_tile_x", "worst_tile_y",
)


def paired_metrics(
    unmarked: Image.Image, marked: Image.Image,
) -> dict[str, float | int | None]:
    """Only the embedding-induced difference, not common JPEG distortion."""
    values = quality_metrics(unmarked, marked)
    return {key: values[key] for key in METRICS}


def _save_pair(
    first: Image.Image, second: Image.Image, destination: Path,
) -> None:
    if first.size != second.size:
        raise ValueError("Cannot compare images with different dimensions")
    output = Image.new("RGB", (first.width * 2, first.height))
    output.paste(first.convert("RGB"), (0, 0))
    output.paste(second.convert("RGB"), (first.width, 0))
    output.save(destination, format="PNG")


def save_samples(
    directory: Path, source: Path,
    reference: Image.Image, marked: Image.Image,
    received_unmarked: Image.Image, received_marked: Image.Image,
    scale: float, quality: int,
) -> None:
    """Local-only visual samples; input images are never overwritten."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    suffix = hashlib.sha256(source.read_bytes()).hexdigest()[:8]
    label = f"{stem}-{suffix}"
    _save_pair(
        reference, marked, directory / f"{label}-native-pair.png"
    )
    _save_pair(
        received_unmarked, received_marked,
        directory / f"{label}-received-s{scale:g}-q{quality}-pair.png",
    )
    a = np.asarray(reference.convert("RGB"), dtype=np.int16)
    b = np.asarray(marked.convert("RGB"), dtype=np.int16)
    difference = np.clip(np.abs(b - a) * 8, 0, 255).astype(np.uint8)
    Image.fromarray(difference, "RGB").save(
        directory / f"{label}-native-diff-x8.png"
    )


def columns() -> list[str]:
    return [
        "source", "source_sha256", "pilot_strength",
        "effective_pilot_strength", "adaptive_pilot",
        "resize_scale", "jpeg_quality", "jpeg_subsampling",
        "transform_order", "delta", "repeat",
        "reference_width", "reference_height",
        "received_width", "received_height",
        *["native_" + key for key in METRICS],
        *["received_" + key for key in METRICS],
    ]


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    qualities: list[int], delta: float = 38.0,
    repeat: int = 13,
    sample_dir: Path | None = None,
    sample_scale: float = 0.68,
    sample_quality: int = 70,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "delta": delta, "repeat": repeat,
        "reference_width": reference.width,
        "reference_height": reference.height,
        "jpeg_subsampling": "4:2:0",
        "transform_order": "resize_then_jpeg",
    }
    rows: list[dict] = []
    packet = pack(payload)
    with codec_parameters(delta, repeat):
        for strength in strengths:
            marked = robust._feedback_embed(
                robust._pilot_embed(reference, strength=strength),
                packet,
            )
            native = paired_metrics(reference, marked)
            sample_saved = False
            for scale in scales:
                size = tuple(
                    max(32, round(d * scale)) for d in reference.size
                )
                resized_unmarked = reference.resize(
                    size, Image.Resampling.LANCZOS
                )
                resized_marked = marked.resize(
                    size, Image.Resampling.LANCZOS
                )
                for quality in qualities:
                    received_unmarked = jpeg_roundtrip_420(
                        resized_unmarked, quality
                    )
                    received_marked = jpeg_roundtrip_420(
                        resized_marked, quality
                    )
                    received = paired_metrics(
                        received_unmarked, received_marked
                    )
                    rows.append({
                        **base,
                        "pilot_strength": strength,
                        "effective_pilot_strength": round(
                            effective_strength(reference, strength), 6
                        ),
                        "resize_scale": scale,
                        "jpeg_quality": quality,
                        "received_width": size[0],
                        "received_height": size[1],
                        **{"native_" + k: v for k, v in native.items()},
                        **{"received_" + k: v for k, v in received.items()},
                    })
                    if (
                        sample_dir is not None
                        and not sample_saved
                        and scale == sample_scale
                        and quality == sample_quality
                    ):
                        save_samples(
                            sample_dir, source, reference, marked,
                            received_unmarked, received_marked,
                            scale, quality,
                        )
                        sample_saved = True
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12")
    parser.add_argument("--scales", default="0.55,0.68,0.83")
    parser.add_argument("--jpeg-qualities", default="85,70")
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--sample-dir", type=Path)
    parser.add_argument("--sample-scale", type=float, default=0.68)
    parser.add_argument("--sample-quality", type=int, default=70)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        qualities = parse_qualities(args.jpeg_qualities)
        if not strengths or any(not 0 < s <= 0.5 for s in strengths):
            raise ValueError("Pilot strengths must be in (0, 0.5]")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if args.sample_scale not in scales:
            raise ValueError("--sample-scale must occur in --scales")
        if args.sample_quality not in qualities:
            raise ValueError("--sample-quality must occur in --jpeg-qualities")
        if args.csv.exists():
            raise ValueError("Refusing to overwrite CSV: " + str(args.csv))
        sources = image_paths(args.directory, args.name or None)
        if not sources:
            raise ValueError("No PNG/JPEG source images found")
        pack(args.message.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Fidelity gate: {len(sources)} covers x "
        f"{len(strengths)} strengths x {len(scales)} scales x "
        f"{len(qualities)} JPEG qualities; "
        f"native and received paired metrics",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(sources, 1):
            try:
                rows = probe(
                    source, args.message.encode("utf-8"),
                    strengths, scales, qualities,
                    args.delta, args.repeat,
                    args.sample_dir, args.sample_scale,
                    args.sample_quality,
                )
            except ValueError as exc:
                print(
                    f"[{i}/{len(sources)}] SKIP {source.name}: {exc}",
                    flush=True,
                )
                continue
            for row in rows:
                writer.writerow(row)
            handle.flush()
            print(
                f"[{i}/{len(sources)}] {source.name}: "
                f"{len(rows)} paired metrics rows",
                flush=True,
            )
    print("CSV:", args.csv)
    if args.sample_dir is not None:
        print("Local visual samples:", args.sample_dir)


if __name__ == "__main__":
    main()
