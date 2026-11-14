#!/usr/bin/env python3
"""Read-only benchmark for Cryptoleaf JPEG v0.3 strength/quality robustness.

Run from the Cryptoleaf project root with its virtual environment active.
Only CSV output is retained; candidate JPEGs are processed in memory.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from pathlib import Path

from PIL import Image

# Allow: python tools/jpeg_parameter_benchmark.py ...
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.image_encoder import _embed_prepared_v03  # noqa: E402
from src.image_decoder import _decode_image_block  # noqa: E402
from src.jpeg_v03 import prepare_payload, required_blocks  # noqa: E402
from src.image_quality import calculate_psnr  # noqa: E402

DEFAULT_QUALITIES = (75, 85, 90, 95)
DEFAULT_STRENGTHS = (10, 20, 30, 40, 50, 65, 80)
DEFAULT_RECOMPRESS = (75, 60)
FIELDS = ["image", "width", "height", "message_bytes", "strength", "save_quality",
          "recompress_quality", "decode_ok", "error", "psnr_db", "jpeg_bytes",
          "seconds"]


def numbers(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use comma-separated integers") from exc
    if not result:
        raise argparse.ArgumentTypeError("At least one integer is required")
    return result


def jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def decoded_ok(data: bytes, password: str, expected: bytes) -> tuple[bool, str]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            result = _decode_image_block(img, password)
        if result != expected:
            return False, "payload mismatch"
        return True, ""
    except Exception as exc:
        # Benchmark must record unexpected decoder errors instead of stopping.
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="Cover images (not already stego images)")
    parser.add_argument("--message", default="Cryptoleaf JPEG robustness benchmark", help="Test message")
    parser.add_argument("--password", required=True, help="Test password (visible in shell history)")
    parser.add_argument("--qualities", type=numbers, default=DEFAULT_QUALITIES)
    parser.add_argument("--strengths", type=numbers, default=DEFAULT_STRENGTHS)
    parser.add_argument("--recompress", type=numbers, default=DEFAULT_RECOMPRESS)
    parser.add_argument("--csv", type=Path, default=Path("jpeg_benchmark.csv"))
    args = parser.parse_args()
    for name, values, upper in (("qualities", args.qualities, 100),
                                ("recompress", args.recompress, 100),
                                ("strengths", args.strengths, 255)):
        if any(v < 1 or v > upper for v in values):
            parser.error(f"--{name} values must be 1..{upper}")
    if not args.password:
        parser.error("--password cannot be empty")
    if any(not p.is_file() for p in args.images):
        parser.error("Every input image must exist")
    if any(p.resolve() == args.csv.resolve() for p in args.images):
        parser.error("CSV output cannot overwrite an input image")

    payload = args.message.encode("utf-8")
    # Prepare once per run: identical encrypted payload for fair comparisons.
    prepared = prepare_payload(payload, args.password)
    rows = 0
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        for cover in args.images:
            with Image.open(cover) as img:
                original = img.convert("RGB")
            width, height = original.size
            available = (width // 8) * max(0, height // 8 - 1)
            needed = required_blocks(len(payload))
            if needed > available:
                print(f"SKIP {cover}: insufficient capacity ({needed} > {available} blocks)", flush=True)
                original.close()
                continue
            for strength in args.strengths:
                start_embed = time.perf_counter()
                stego = _embed_prepared_v03(cover, prepared, strength=strength,
                                            cover_image=original)
                for quality in args.qualities:
                    started = time.perf_counter()
                    try:
                        data = jpeg_bytes(stego, quality)
                        with Image.open(io.BytesIO(data)) as saved:
                            saved_rgb = saved.convert("RGB")
                        try:
                            psnr = calculate_psnr(original, saved_rgb)
                        finally:
                            saved_rgb.close()
                        cases = [("none", data)]
                        # Recompression always starts from the saved JPEG, not the original.
                        with Image.open(io.BytesIO(data)) as saved:
                            for q in args.recompress:
                                cases.append((str(q), jpeg_bytes(saved.convert("RGB"), q)))
                        for rec_quality, candidate in cases:
                            ok, error = decoded_ok(candidate, args.password, payload)
                            writer.writerow({"image": str(cover), "width": width,
                                "height": height, "message_bytes": len(payload),
                                "strength": strength, "save_quality": quality,
                                "recompress_quality": rec_quality, "decode_ok": int(ok),
                                "error": error, "psnr_db": f"{psnr:.3f}",
                                "jpeg_bytes": len(data),
                                "seconds": f"{time.perf_counter()-started:.3f}"})
                            rows += 1
                            print(f"{cover.name} s={strength:3} q={quality:2} "
                                  f"recompress={rec_quality:>4} "
                                  f"{'OK' if ok else 'FAIL'}", flush=True)
                    except Exception as exc:
                        print(f"ERROR {cover.name} s={strength} q={quality}: {exc}",
                              file=sys.stderr, flush=True)
                stego.close()
                print(f"strength={strength}: embedding took {time.perf_counter()-start_embed:.1f}s", flush=True)
            original.close()
    print(f"Finished: {rows} rows written to {args.csv}")
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
