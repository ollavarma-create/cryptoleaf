#!/usr/bin/env python3
"""Research-only visual ablation: Fourier pilot vs LL2 QIM vs both.

For every source image, render the exact same payload with:
  PILOT_ONLY      _pilot_embed(reference, strength)
  QIM_ONLY        _feedback_embed(reference, packet)
  FULL            _feedback_embed(pilot, packet)
  QIM_AFTER_PILOT incremental difference: FULL vs PILOT_ONLY

Compare native-resolution image fidelity and the change on locally flat
versus textured pixels (flat = 15x15 luma variance < 4, matching the
adaptive-pilot criterion). A spatially structured artifact can remain
visible even with high global PSNR/SSIM.

Optionally save 100%-resolution original/pilot/QIM/full PNGs, a labeled
2x2 panel, and x8-amplified difference images. Evaluate visibility from
UNAMPLIFIED images at 100% zoom; x8 differences are diagnostics only.

No codec modifications. No output images are uploaded anywhere.
No claims about blind decode success from these ablation images.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import uniform_filter

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import parse_strengths
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import effective_strength, reference_image
from tools.robust_quality_compare import quality_metrics

METRICS = (
    "psnr_db", "ssim_y", "ssim_y_p01", "rgb_mae",
    "pixel_change_gt4_pct", "pixel_change_gt8_pct",
    "pixel_absdiff_p99", "worst_tile_luma_mae",
    "worst_tile_x", "worst_tile_y",
)


def flat_mask(reference: Image.Image) -> np.ndarray:
    """Exactly the global pilot's local-variance definition."""
    y = np.asarray(reference.convert("YCbCr"), dtype=np.uint8)[:, :, 0].astype(np.float32)
    mean = uniform_filter(y, size=15)
    sqr = uniform_filter(y * y, size=15)
    variance = np.maximum(sqr - mean * mean, 0.0)
    return variance < 4.0


def regional_metrics(
    baseline: Image.Image, candidate: Image.Image, mask: np.ndarray,
) -> dict:
    if baseline.size != candidate.size or mask.shape != (baseline.height, baseline.width):
        raise ValueError("Regional metrics require aligned images and mask")
    a = np.asarray(baseline.convert("YCbCr"), dtype=np.uint8)[:, :, 0].astype(np.float32)
    b = np.asarray(candidate.convert("YCbCr"), dtype=np.uint8)[:, :, 0].astype(np.float32)
    error = np.abs(b - a)
    result = {"flat_fraction_pct": round(float(mask.mean()) * 100, 4)}
    for name, selected in (("flat", mask), ("textured", ~mask)):
        if selected.any():
            result[f"{name}_luma_mae"] = round(float(error[selected].mean()), 4)
            result[f"{name}_luma_gt4_pct"] = round(float((error[selected] > 4).mean()) * 100, 4)
        else:
            result[f"{name}_luma_mae"] = None
            result[f"{name}_luma_gt4_pct"] = None
    return result


def columns() -> list[str]:
    return [
        "source", "source_sha256", "variant", "comparison",
        "pilot_strength", "effective_pilot_strength", "adaptive_pilot",
        "delta", "repeat", "width", "height",
        *METRICS, "flat_fraction_pct",
        "flat_luma_mae", "flat_luma_gt4_pct",
        "textured_luma_mae", "textured_luma_gt4_pct",
    ]


def _panel(images: list[tuple[str, Image.Image]], path: Path) -> None:
    if len(images) != 4 or len({im.size for _, im in images}) != 1:
        raise ValueError("Expected four same-size images")
    w, h = images[0][1].size
    bar = 28
    canvas = Image.new("RGB", (2 * w, 2 * (h + bar)), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, (label, im) in enumerate(images):
        x = (index % 2) * w
        y = (index // 2) * (h + bar)
        draw.text((x + 10, y + 7), label, fill=(255, 255, 255))
        canvas.paste(im.convert("RGB"), (x, y + bar))
    canvas.save(path, "PNG")


def save_samples(
    directory: Path, source: Path, strength: float,
    reference: Image.Image, pilot: Image.Image,
    qim: Image.Image, full: Image.Image,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
    prefix = f"{source.stem}-{tag}-p{strength:g}"
    images = [
        ("ORIGINAL", reference),
        ("PILOT_ONLY", pilot),
        ("QIM_ONLY", qim),
        ("FULL", full),
    ]
    for label, image in images:
        image.save(directory / f"{prefix}-{label.lower()}.png", "PNG")
    _panel(images, directory / f"{prefix}-panel.png")
    original = np.asarray(reference.convert("RGB"), dtype=np.int16)
    for label, image in images[1:]:
        marked = np.asarray(image.convert("RGB"), dtype=np.int16)
        amplified = np.clip(np.abs(marked - original) * 8, 0, 255).astype(np.uint8)
        Image.fromarray(amplified, "RGB").save(
            directory / f"{prefix}-{label.lower()}-diff-x8.png", "PNG"
        )


def probe(
    source: Path, payload: bytes, strengths: list[float],
    delta: float = 38.0, repeat: int = 13,
    sample_dir: Path | None = None,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    mask = flat_mask(reference)
    packet = pack(payload)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "delta": delta, "repeat": repeat,
        "width": reference.width, "height": reference.height,
    }
    rows: list[dict] = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = robust._pilot_embed(reference, strength=strength)
            qim = robust._feedback_embed(reference, packet)
            full = robust._feedback_embed(pilot, packet)
            comparisons = [
                ("PILOT_ONLY", "ORIGINAL", reference, pilot),
                ("QIM_ONLY", "ORIGINAL", reference, qim),
                ("FULL", "ORIGINAL", reference, full),
                ("QIM_AFTER_PILOT", "PILOT_ONLY", pilot, full),
            ]
            for variant, comparison, baseline, candidate in comparisons:
                values = quality_metrics(baseline, candidate)
                rows.append({
                    **base,
                    "variant": variant, "comparison": comparison,
                    "pilot_strength": strength,
                    "effective_pilot_strength": round(
                        effective_strength(reference, strength), 6
                    ),
                    **{k: values[k] for k in METRICS},
                    **regional_metrics(baseline, candidate, mask),
                })
            if sample_dir is not None:
                save_samples(sample_dir, source, strength, reference, pilot, qim, full)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12")
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    parser.add_argument("--sample-dir", type=Path)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        if not strengths or any(not 0 <= strength <= 0.5 for strength in strengths):
            raise ValueError("Pilot strengths must be in [0, 0.5]")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and in 1..31")
        if args.csv.exists():
            raise ValueError("Refusing to overwrite CSV: " + str(args.csv))
        if args.sample_dir is not None and (
            args.sample_dir.is_file() or
            (args.sample_dir.is_dir() and any(args.sample_dir.iterdir()))
        ):
            raise ValueError("Sample directory must be empty: " + str(args.sample_dir))
        sources = image_paths(args.directory, args.name or None)
        if not sources:
            raise ValueError("No supported source images found")
        pack(args.message.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Visual ablation: {len(sources)} sources x "
        f"{len(strengths)} pilot strengths x 4 variants",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(sources, 1):
            try:
                rows = probe(
                    source, args.message.encode("utf-8"),
                    strengths, args.delta, args.repeat, args.sample_dir,
                )
            except ValueError as exc:
                print(f"[{i}/{len(sources)}] SKIP {source.name}: {exc}", flush=True)
                continue
            writer.writerows(rows)
            handle.flush()
            print(f"[{i}/{len(sources)}] {source.name}: {len(rows)} rows", flush=True)
    print("CSV:", args.csv)
    if args.sample_dir is not None:
        print("100%-resolution visual samples:", args.sample_dir)


if __name__ == "__main__":
    main()
