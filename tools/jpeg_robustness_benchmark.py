#!/usr/bin/env python3
"""Cryptoleaf JPEG v0.3 robustness test: recompression, resizing, and both.

Run from the Cryptoleaf project root with the project virtualenv active.
No source images are modified. Intermediate JPEGs are kept in memory.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.image_encoder import _embed_prepared_v03
from src.image_decoder import _decode_image_block
from src.jpeg_v03 import prepare_payload, required_blocks
from src.image_quality import calculate_psnr

FIELDS = ("image", "width", "height", "message_bytes", "strength", "save_quality",
          "operation", "resize_percent", "recompress_quality", "result_width",
          "result_height", "decode_ok", "error", "psnr_db", "jpeg_bytes", "seconds")


def integers(text):
    try:
        result = tuple(int(x.strip()) for x in text.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use comma-separated integers") from exc
    if not result:
        raise argparse.ArgumentTypeError("Empty value list")
    return result


def jpeg(image, quality):
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def verify(data, password, expected):
    try:
        with Image.open(io.BytesIO(data)) as img:
            recovered = _decode_image_block(img, password)
        return (recovered == expected, "" if recovered == expected else "payload mismatch")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="Original cover images (not _cryptoleaf.jpg)")
    parser.add_argument("--message", default="Cryptoleaf JPEG robustness benchmark")
    parser.add_argument("--password", required=True, help="Use a TEST password; shell history may retain it")
    parser.add_argument("--strengths", type=integers, default=(20, 30, 40, 50, 65, 80))
    parser.add_argument("--qualities", type=integers, default=(85,))
    parser.add_argument("--resize", type=integers, default=(90, 75, 50))
    parser.add_argument("--recompress", type=integers, default=(75, 60))
    parser.add_argument("--csv", type=Path, default=Path("jpeg_robustness.csv"))
    args = parser.parse_args()
    for name, vals, lo, hi in (("strengths", args.strengths, 1, 255),
                               ("qualities", args.qualities, 1, 100),
                               ("resize", args.resize, 1, 100),
                               ("recompress", args.recompress, 1, 100)):
        if any(not lo <= v <= hi for v in vals):
            parser.error(f"--{name} must be between {lo} and {hi}")
    if not args.password:
        parser.error("--password must not be empty")
    if any(not image.is_file() for image in args.images):
        parser.error("All input images must exist")
    if any(image.resolve() == args.csv.resolve() for image in args.images):
        parser.error("CSV output would overwrite an input image")

    message = args.message.encode("utf-8")
    prepared = prepare_payload(message, args.password)
    total = 0
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for path in args.images:
            with Image.open(path) as image:
                original = image.convert("RGB")
            width, height = original.size
            capacity = (width // 8) * max(0, height // 8 - 1)
            required = required_blocks(len(message))
            if required > capacity:
                print(f"SKIP {path.name}: insufficient capacity ({required} > {capacity})", flush=True)
                original.close()
                continue
            try:
                for strength in args.strengths:
                    stego = _embed_prepared_v03(path, prepared, strength=strength, cover_image=original)
                    try:
                        for quality in args.qualities:
                            initial = jpeg(stego, quality)
                            with Image.open(io.BytesIO(initial)) as img:
                                initial_rgb = img.convert("RGB")
                            try:
                                psnr = calculate_psnr(original, initial_rgb)
                                cases = [("original_saved", 100, "none", initial, width, height)]
                                for q in args.recompress:
                                    cases.append(("recompress", 100, str(q), jpeg(initial_rgb, q), width, height))
                                for pct in args.resize:
                                    target = (max(1, round(width * pct / 100)),
                                              max(1, round(height * pct / 100)))
                                    resized = initial_rgb.resize(target, Image.Resampling.LANCZOS)
                                    try:
                                        # Resize-only is still encoded as JPEG using original save quality.
                                        cases.append(("resize", pct, "none", jpeg(resized, quality), *target))
                                        for q in args.recompress:
                                            cases.append(("resize_and_recompress", pct, str(q), jpeg(resized, q), *target))
                                    finally:
                                        resized.close()
                                for operation, pct, q, candidate, outw, outh in cases:
                                    start = time.perf_counter()
                                    ok, error = verify(candidate, args.password, message)
                                    writer.writerow(dict(image=str(path), width=width, height=height,
                                        message_bytes=len(message), strength=strength, save_quality=quality,
                                        operation=operation, resize_percent=pct, recompress_quality=q,
                                        result_width=outw, result_height=outh, decode_ok=int(ok),
                                        error=error, psnr_db=f"{psnr:.3f}", jpeg_bytes=len(candidate),
                                        seconds=f"{time.perf_counter()-start:.3f}"))
                                    total += 1
                                    print(f"{path.name} strength={strength} q={quality} "
                                          f"{operation} resize={pct}% q2={q}: {'OK' if ok else 'FAIL'}", flush=True)
                            finally:
                                initial_rgb.close()
                    finally:
                        stego.close()
            finally:
                original.close()
    print(f"Completed: {total} cases; CSV: {args.csv}")
    return 0 if total else 2


if __name__ == "__main__":
    raise SystemExit(main())
