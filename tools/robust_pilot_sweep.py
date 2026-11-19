#!/usr/bin/env python3
"""Controlled Fourier pilot-strength sweep on one fixed Robust DWT packet.

All candidates use the same source, deterministic RS8 packet, DWT parameters
and number of RGB/YCbCr roundtrips. Nominal strength is adapted by the codec
on flat images; report both nominal and effective strength.

The default tests use known-size decoding. Add --blind-scale 0.75 to test
blind synchronization after resizing; this is intentionally opt-in because
the candidate-size search may be slow.
"""
from __future__ import annotations

import argparse
import csv
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import uniform_filter

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_quality_compare import quality_metrics


def reference_image(image: Image.Image) -> Image.Image:
    rgb = ImageOps.exif_transpose(image).convert("RGB")
    scale = min(1.0, robust.MAX_LONGEST / max(rgb.size))
    if scale < 1:
        rgb = rgb.resize(
            tuple(max(32, round(v * scale)) for v in rgb.size),
            Image.Resampling.LANCZOS,
        )
    return rgb


def effective_strength(reference: Image.Image, nominal: float) -> float:
    if not robust.ADAPTIVE_PILOT:
        return nominal
    y = np.asarray(reference.convert("YCbCr"), dtype=np.uint8)[:, :, 0].astype(np.float32)
    mean = uniform_filter(y, size=15)
    sqr = uniform_filter(y * y, size=15)
    variance = np.maximum(sqr - mean * mean, 0.0)
    flat_fraction = float((variance < 4.0).mean())
    return nominal * float(np.clip(1.0 - 0.8 * flat_fraction, 0.30, 1.0))


def decode_known(image: Image.Image, payload: bytes) -> str:
    try:
        actual = robust.decode_at_size(image, image.size)
        return "PASS" if actual == payload else "FAIL:payload_mismatch"
    except ValueError as exc:
        return "FAIL:" + type(exc).__name__


def decode_blind(image: Image.Image, payload: bytes) -> str:
    try:
        result = robust.decode(image)
        return f"PASS:{result.attempts}c" if result.payload == payload else "FAIL:payload_mismatch"
    except ValueError as exc:
        return "FAIL:" + type(exc).__name__


def jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=quality, subsampling=0)
    buf.seek(0)
    with Image.open(buf) as received:
        return received.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--csv", type=Path)
    parser.add_argument(
        "--strengths", default="0,0.04,0.08,0.12,0.18",
        help="Comma-separated nominal Fourier strengths; zero is always included",
    )
    parser.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    parser.add_argument("--jpeg-quality", type=int, nargs="*", default=[85, 75, 60])
    parser.add_argument(
        "--blind-scale", type=float, action="append", default=[],
        help="Optional scale factor for slow blind decode; may be repeated",
    )
    args = parser.parse_args()
    try:
        strengths = list(dict.fromkeys([0.0] + [float(x) for x in args.strengths.split(",")]))
    except ValueError:
        parser.error("Strengths must be comma-separated numbers")
    if any(not 0 <= s <= 0.5 or not np.isfinite(s) for s in strengths):
        parser.error("Strengths must be finite and between 0 and 0.5")
    if any(not 1 <= q <= 100 for q in args.jpeg_quality):
        parser.error("JPEG quality must be 1..100")
    if any(not 0.2 <= s <= 2.0 or not np.isfinite(s) for s in args.blind_scale):
        parser.error("Blind scale factors must be finite and between 0.2 and 2.0")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output directory must be empty; refusing to overwrite: " + str(args.out))
    if args.csv and args.csv.exists():
        parser.error("CSV already exists; refusing to overwrite: " + str(args.csv))

    payload = args.message.encode("utf-8")
    try:
        packet = pack(payload)
    except ValueError as exc:
        parser.error(str(exc))

    with Image.open(args.source) as opened:
        reference = reference_image(opened)

    # The strength=0 control gets the SAME extra RGB->YCbCr->RGB conversion
    # as pilot strengths >0, rather than using _pilot_embed's early return.
    pilot_zero = reference.convert("YCbCr").convert("RGB")
    zero = robust._feedback_embed(pilot_zero, packet)
    args.out.mkdir(parents=True, exist_ok=True)
    reference.save(args.out / "pilot-sweep-reference.png")
    rows = []
    for i, strength in enumerate(strengths):
        pilot = pilot_zero if strength == 0 else robust._pilot_embed(reference, strength=strength)
        marked = zero if strength == 0 else robust._feedback_embed(pilot, packet)
        label = f"s{i:02d}-strength-{strength:.3f}"
        marked.save(args.out / f"{label}.png")

        a = np.asarray(zero, dtype=np.int16)
        b = np.asarray(marked, dtype=np.int16)
        heat = np.clip(np.abs(b - a) * 12, 0, 255).astype(np.uint8)
        Image.fromarray(heat, "RGB").save(args.out / f"{label}-vs-zero-diff.png")

        row = {
            "nominal_strength": strength,
            "effective_strength": round(effective_strength(reference, strength), 6),
            "adaptive_pilot": robust.ADAPTIVE_PILOT,
            "delta": robust.DELTA,
            "repeat": robust.REPEAT,
            "png_known": decode_known(marked, payload),
            **{"original_" + k: v for k, v in quality_metrics(reference, marked).items()},
            **{"vs_zero_" + k: v for k, v in quality_metrics(zero, marked).items()},
        }
        for quality in args.jpeg_quality:
            row[f"jpeg{quality}_known"] = decode_known(jpeg_roundtrip(marked, quality), payload)
        for scale in args.blind_scale:
            size = tuple(max(32, round(v * scale)) for v in marked.size)
            scaled = marked.resize(size, Image.Resampling.LANCZOS)
            row[f"blind_scale_{scale:g}"] = decode_blind(scaled, payload)
        rows.append(row)
        print(
            f"nominal={strength:.3f} effective={row['effective_strength']:.4f} "
            f"PSNR={row['original_psnr_db']} SSIM={row['original_ssim_y']} "
            f"vs0_PSNR={row['vs_zero_psnr_db']} "
            f"PNG={row['png_known']} "
            + " ".join(f"J{q}={row[f'jpeg{q}_known']}" for q in args.jpeg_quality)
            + " " + " ".join(
                f"blind@{s:g}={row[f'blind_scale_{s:g}']}" for s in args.blind_scale
            ),
            flush=True,
        )

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print("CSV:", args.csv)
    print("Saved images and 12x difference maps:", args.out)
    print("Note: known-size JPEG success does not demonstrate blind scale synchronization.")


if __name__ == "__main__":
    main()
