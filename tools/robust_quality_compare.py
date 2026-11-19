#!/usr/bin/env python3
"""Compare two same-size RGB images for visible Robust DWT artifacts.

Only compares image quality; it does not prove message recoverability or
steganalytic security. No ML/computer vision models are required.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter


def _luma(rgb: np.ndarray) -> np.ndarray:
    """Display-oriented Rec.601 luma approximation on 8-bit RGB."""
    return rgb @ np.array([0.299, 0.587, 0.114])


def _ssim_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Luminance SSIM map with an 11x11 Gaussian window (sigma=1.5)."""
    def blur(x: np.ndarray) -> np.ndarray:
        return gaussian_filter(x, sigma=1.5, truncate=3.5, mode="reflect")

    ma, mb = blur(a), blur(b)
    va = np.maximum(blur(a * a) - ma * ma, 0)
    vb = np.maximum(blur(b * b) - mb * mb, 0)
    cov = blur(a * b) - ma * mb
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / (
        (ma * ma + mb * mb + c1) * (va + vb + c2)
    )


def quality_metrics(reference: Image.Image, candidate: Image.Image) -> dict:
    """Full-reference metrics; no resizing or image registration is performed."""
    if reference.size != candidate.size:
        raise ValueError(
            f"Image dimensions differ: {reference.size} vs {candidate.size}; "
            "use --resize-reference only if it matches the encoder's preprocessing"
        )

    a = np.asarray(reference.convert("RGB"), dtype=np.float64)
    b = np.asarray(candidate.convert("RGB"), dtype=np.float64)
    diff = b - a
    abs_rgb = np.abs(diff)
    pixel_max = abs_rgb.max(axis=2)
    changed = pixel_max > 0
    ya, yb = _luma(a), _luma(b)
    dy = yb - ya
    mse = float(np.mean(diff * diff))
    signal_power = float(np.mean(a * a))
    ssim = _ssim_map(ya, yb)

    # Measure the worst local luminance distortion rather than hiding it in
    # a global PSNR score. Edge tiles may be smaller than 16x16.
    worst = (-1.0, 0, 0)
    for y in range(0, reference.height, 16):
        for x in range(0, reference.width, 16):
            value = float(np.mean(np.abs(dy[y:y + 16, x:x + 16])))
            if value > worst[0]:
                worst = (value, x, y)

    # These are *new saturated output values*, not proof of clipping inside
    # the encoder; true pre-clip counts require codec instrumentation.
    new_saturation = np.any(
        ((b == 0) & (a != 0)) | ((b == 255) & (a != 255)), axis=2
    )
    n = changed.size

    return {
        "width": reference.width,
        "height": reference.height,
        "psnr_db": round(10 * math.log10(255 ** 2 / mse), 4) if mse else None,
        "snr_db": round(10 * math.log10(signal_power / mse), 4) if mse and signal_power else None,
        "ssim_y": round(float(np.mean(ssim)), 6),
        "ssim_y_p01": round(float(np.percentile(ssim, 1)), 6),
        "rgb_mae": round(float(np.mean(abs_rgb)), 4),
        "rgb_max_abs": int(pixel_max.max()),
        "pixel_change_pct": round(float(changed.sum() / n * 100), 4),
        "pixel_change_gt4_pct": round(float((pixel_max > 4).sum() / n * 100), 4),
        "pixel_change_gt8_pct": round(float((pixel_max > 8).sum() / n * 100), 4),
        "pixel_absdiff_p99": round(float(np.percentile(pixel_max, 99)), 4),
        "mean_signed_luma_change": round(float(np.mean(dy)), 4),
        "luma_brightened_pct": round(float((dy > 0.5).sum() / n * 100), 4),
        "luma_darkened_pct": round(float((dy < -0.5).sum() / n * 100), 4),
        "new_saturated_pixel_pct": round(float(new_saturation.sum() / n * 100), 4),
        "worst_tile_x": worst[1],
        "worst_tile_y": worst[2],
        "worst_tile_luma_mae": round(worst[0], 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="Unmarked original image")
    parser.add_argument("candidate", type=Path, help="Marked output image")
    parser.add_argument("--label", default="", help="Case identifier for CSV")
    parser.add_argument("--csv", type=Path, help="Append measurements to CSV")
    parser.add_argument("--diff", type=Path, help="Save exaggerated RGB difference PNG (12x)")
    parser.add_argument(
        "--resize-reference", action="store_true",
        help="Resize reference to candidate size (LANCZOS); use only for known encoder downscaling",
    )
    args = parser.parse_args()

    with Image.open(args.reference) as im:
        reference = ImageOps.exif_transpose(im).convert("RGB")
    with Image.open(args.candidate) as im:
        candidate = ImageOps.exif_transpose(im).convert("RGB")
    if args.resize_reference and reference.size != candidate.size:
        reference = reference.resize(candidate.size, Image.Resampling.LANCZOS)

    result = {
        "label": args.label,
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
        **quality_metrics(reference, candidate),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))

    if args.diff:
        args.diff.parent.mkdir(parents=True, exist_ok=True)
        a = np.asarray(reference, dtype=np.int16)
        b = np.asarray(candidate, dtype=np.int16)
        heat = np.clip(np.abs(b - a) * 12, 0, 255).astype(np.uint8)
        Image.fromarray(heat, "RGB").save(args.diff)
        print(f"Difference image: {args.diff}")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        exists = args.csv.exists() and args.csv.stat().st_size > 0
        with args.csv.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(result))
            if not exists:
                writer.writeheader()
            writer.writerow(result)
        print(f"CSV: {args.csv}")


if __name__ == "__main__":
    main()
