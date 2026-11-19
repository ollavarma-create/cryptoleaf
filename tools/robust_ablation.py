#!/usr/bin/env python3
"""Controlled Robust DWT/Fourier ablation: isolate pipeline stages.

Produces new images from the SAME source and SAME packed payload. It does not
change the codec or claim the stages' distortions are mathematically additive.
Run from the repository root with the project venv active.
"""
from __future__ import annotations

import argparse
import csv
from io import BytesIO
from pathlib import Path
import sys

# Allow "python tools/robust_ablation.py" from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageOps

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_quality_compare import quality_metrics


def prepare_reference(image: Image.Image) -> Image.Image:
    """Match encode() EXIF handling and maximum-dimension preprocessing."""
    reference = ImageOps.exif_transpose(image).convert("RGB")
    scale = min(1.0, robust.MAX_LONGEST / max(reference.size))
    if scale < 1:
        reference = reference.resize(
            tuple(max(32, round(v * scale)) for v in reference.size),
            Image.Resampling.LANCZOS,
        )
    return reference


def stages(reference: Image.Image, payload: bytes) -> dict[str, Image.Image]:
    """Recreate encode's pilot and DWT steps, without stochastic encryption."""
    packet = pack(payload)
    ycbcr_control = reference.convert("YCbCr").convert("RGB")
    pilot = robust._pilot_embed(reference)
    return {
        "ycbcr_control": ycbcr_control,
        "pilot_only": pilot,
        "dwt_only": robust._feedback_embed(reference, packet),
        # A second color conversion without a pilot: isolates pipeline
        # round-trip effects from the actual Fourier modulation.
        "ycbcr_then_dwt": robust._feedback_embed(ycbcr_control, packet),
        "pilot_and_dwt": robust._feedback_embed(pilot, packet),
    }


def decode_result(image: Image.Image, expected: bytes) -> str:
    try:
        recovered = robust.decode_at_size(image, image.size)
    except (ValueError, IndexError) as exc:
        return f"FAIL:{type(exc).__name__}"
    return "PASS" if recovered == expected else "FAIL:payload_mismatch"


def jpeg_result(image: Image.Image, expected: bytes, quality: int) -> str:
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=quality, subsampling=0)
    stream.seek(0)
    with Image.open(stream) as received:
        return decode_result(received.convert("RGB"), expected)


def diff_image(reference: Image.Image, candidate: Image.Image) -> Image.Image:
    a = np.asarray(reference, dtype=np.int16)
    b = np.asarray(candidate, dtype=np.int16)
    diff = np.clip(np.abs(b - a) * 12, 0, 255).astype(np.uint8)
    return Image.fromarray(diff, "RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--message", default="CryptoLeaf v0.4 controlled ablation")
    parser.add_argument("--jpeg-quality", type=int, nargs="*", default=[85, 75, 60])
    args = parser.parse_args()

    if any(not 1 <= q <= 100 for q in args.jpeg_quality):
        parser.error("JPEG quality must be between 1 and 100")
    payload = args.message.encode("utf-8")
    try:
        pack(payload)
    except ValueError as exc:
        parser.error(str(exc))

    with Image.open(args.source) as image:
        reference = prepare_reference(image)

    # All output paths are reserved before work starts; no existing test
    # artifacts will be overwritten even if a later stage fails.
    output_paths = {
        "reference": args.out / "ablation-reference.png",
        "ycbcr_control": args.out / "ablation-ycbcr.png",
        "pilot_only": args.out / "ablation-pilot.png",
        "dwt_only": args.out / "ablation-dwt.png",
        "ycbcr_then_dwt": args.out / "ablation-ycbcr-then-dwt.png",
        "pilot_and_dwt": args.out / "ablation-full.png",
        "pilot_vs_control": args.out / "ablation-pilot-vs-control-diff.png",
        "dwt_vs_reference": args.out / "ablation-dwt-vs-reference-diff.png",
        "full_vs_reference": args.out / "ablation-full-vs-reference-diff.png",
        "full_vs_ycbcr_dwt": args.out / "ablation-full-vs-ycbcr-dwt-diff.png",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing:
        parser.error("Refusing to overwrite existing files: " + ", ".join(existing))
    if args.csv and args.csv.exists() and args.csv.stat().st_size > 0:
        parser.error("CSV must be a new file to avoid mixing schemas: " + str(args.csv))

    results = stages(reference, payload)
    rows = []
    for name, candidate in results.items():
        row = {"stage": name, **quality_metrics(reference, candidate)}
        if name in {"dwt_only", "ycbcr_then_dwt", "pilot_and_dwt"}:
            row["png_oracle"] = decode_result(candidate, payload)
            for quality in args.jpeg_quality:
                row[f"jpeg{quality}_oracle"] = jpeg_result(candidate, payload, quality)
        else:
            row["png_oracle"] = "N/A"
            for quality in args.jpeg_quality:
                row[f"jpeg{quality}_oracle"] = "N/A"
        rows.append(row)
        print(
            f"{name:15} PSNR={row['psnr_db']} dB "
            f"SSIM={row['ssim_y']} >4={row['pixel_change_gt4_pct']}% "
            f"PNG={row['png_oracle']} "
            + " ".join(f"J{q}={row[f'jpeg{q}_oracle']}" for q in args.jpeg_quality),
            flush=True,
        )

    print("\nAdditional comparisons (same source image and packet):")
    for name, a, b in (
        ("pilot vs YCbCr control", results["ycbcr_control"], results["pilot_only"]),
        ("DWT vs YCbCr control", results["ycbcr_control"], results["dwt_only"]),
        ("YCbCr then DWT vs DWT only", results["dwt_only"], results["ycbcr_then_dwt"]),
        ("full vs YCbCr then DWT", results["ycbcr_then_dwt"], results["pilot_and_dwt"]),
        ("full vs pilot-only", results["pilot_only"], results["pilot_and_dwt"]),
    ):
        m = quality_metrics(a, b)
        print(f"{name}: PSNR={m['psnr_db']} dB, SSIM={m['ssim_y']}, >4={m['pixel_change_gt4_pct']}%")

    args.out.mkdir(parents=True, exist_ok=True)
    reference.save(output_paths["reference"])
    for name, image in results.items():
        image.save(output_paths[name])
    diff_image(results["ycbcr_control"], results["pilot_only"]).save(output_paths["pilot_vs_control"])
    diff_image(reference, results["dwt_only"]).save(output_paths["dwt_vs_reference"])
    diff_image(reference, results["pilot_and_dwt"]).save(output_paths["full_vs_reference"])
    diff_image(results["ycbcr_then_dwt"], results["pilot_and_dwt"]).save(output_paths["full_vs_ycbcr_dwt"])
    print(f"\nSaved images and 12x difference maps to: {args.out}")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV: {args.csv}")


if __name__ == "__main__":
    main()
