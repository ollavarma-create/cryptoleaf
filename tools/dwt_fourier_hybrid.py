#!/usr/bin/env python3
"""Experimental DWT-QIM + blind Fourier radial pilot benchmark.

No original image or original size is passed to the hybrid decoder.
Pilot estimates scale; observed dimensions / scale estimate produce candidate
embedding dimensions. CRC validates DWT payload. A limited local size search
is allowed around that estimate, NOT a list of known original resolutions.

This is a watermark/synchronization experiment, NOT a secure steganography
format. The pilot is public/detectable. Do not merge into production.
"""
import argparse
import csv
import sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm


def crop_to_aspect(source, width, height):
    sw, sh = source.size
    aspect = width / height
    if sw / sh > aspect:
        cw = round(sh * aspect)
        source = source.crop(((sw-cw)//2, 0, (sw-cw)//2+cw, sh))
    else:
        ch = round(sw / aspect)
        source = source.crop((0, (sh-ch)//2, sw, (sh-ch)//2+ch))
    return source.resize((width, height), Image.Resampling.LANCZOS)


def decode_at_size(image, size, args):
    return dwt.extract(image, size, args.delta, args.repeat, args.seed,
                       max_bytes=args.max_bytes)


def blind_decode(image, args):
    """Uses only received pixels and known pilot template / codec parameters."""
    estimated, score, median, std = fm.estimate_scale(
        image, low=args.low, high=args.high, step=args.step)
    if estimated <= 0:
        raise ValueError("Invalid pilot estimate")
    # Width/height are independently rounded during attack; inferred size
    # can be off by a pixel or more. Try local 2D offsets, center first.
    w0 = round(image.width / estimated)
    h0 = round(image.height / estimated)
    offsets = [0]
    for d in range(1, args.radius+1):
        offsets.extend((-d, d))
    attempts = 0
    last_error = ""
    for dw in offsets:
        for dh in offsets:
            w, h = w0+dw, h0+dh
            if w < 32 or h < 32:
                continue
            attempts += 1
            try:
                payload = decode_at_size(image, (w, h), args)
                return payload, estimated, score, median, std, (w, h), attempts, ""
            except ValueError as exc:
                last_error = str(exc)
    return None, estimated, score, median, std, None, attempts, last_error


def run_case(base, args, pilot_enabled, scale, jpeg_quality, message):
    # DWT then Fourier pilot: checks whether pilot damages DWT coefficients.
    marked = dwt.embed(base, message, args.delta, args.repeat, args.seed)
    if pilot_enabled:
        marked = fm.embed(marked, args.strength)
    encoded = dwt.jpeg_roundtrip(marked, args.save_quality)
    size = (max(32, round(base.width * scale)),
            max(32, round(base.height * scale)))
    received = encoded.resize(size, Image.Resampling.LANCZOS)
    if jpeg_quality is not None:
        received = dwt.jpeg_roundtrip(received, jpeg_quality)

    # Blind hybrid: decoder never sees base or original dimensions.
    payload, estimated, score, median, std, inferred, attempts, error = blind_decode(received, args)
    hybrid_ok = payload == message
    # Baseline: decode received dimensions without scale correction.
    try:
        baseline_ok = decode_at_size(received, received.size, args) == message
    except ValueError:
        baseline_ok = False
    # ORACLE DIAGNOSTIC ONLY: forbidden to hybrid decoder.
    try:
        oracle_ok = decode_at_size(received, base.size, args) == message
    except ValueError:
        oracle_ok = False

    return {
        "width": base.width, "height": base.height,
        "pilot": int(pilot_enabled),
        "true_percent": round(scale*100, 3),
        "jpeg_quality": jpeg_quality if jpeg_quality is not None else "none",
        "estimated_percent": round(estimated*100, 3),
        "scale_error_pp": round(abs(estimated-scale)*100, 3),
        "pilot_score": round(score, 5),
        "score_median": round(median, 5),
        "score_std": round(std, 5),
        "inferred_width": inferred[0] if inferred else "",
        "inferred_height": inferred[1] if inferred else "",
        "attempts": attempts,
        "hybrid_pass": int(hybrid_ok),
        "baseline_pass": int(baseline_ok),
        "oracle_pass": int(oracle_ok),
        "psnr_db": round(dwt.psnr(base, encoded), 3),
        "error": "" if hybrid_ok else error or "PayloadMismatch",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--csv", type=Path, default=Path("dwt_fourier_hybrid.csv"))
    parser.add_argument("--sizes", default="1280x720,640x480")
    parser.add_argument("--scales", default="100,99,90,75")
    parser.add_argument("--jpeg", default="none,60")
    parser.add_argument("--bytes", type=int, default=50)
    parser.add_argument("--delta", type=float, default=32)
    parser.add_argument("--repeat", type=int, default=9)
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--strength", type=float, default=0.18)
    parser.add_argument("--save-quality", type=int, default=85)
    parser.add_argument("--max-bytes", type=int, default=256)
    parser.add_argument("--low", type=float, default=0.70)
    parser.add_argument("--high", type=float, default=1.02)
    parser.add_argument("--step", type=float, default=0.002)
    parser.add_argument("--radius", type=int, default=2,
                        help="Search +/- N pixels in both inferred dimensions")
    args = parser.parse_args()
    if args.bytes < 1 or args.bytes > args.max_bytes:
        parser.error("--bytes must be between 1 and --max-bytes")
    if args.repeat < 1 or args.repeat % 2 != 1:
        parser.error("--repeat must be a positive odd number")
    if args.radius < 0 or args.radius > 6:
        parser.error("--radius must be 0..6")
    if args.low <= 0 or args.high < args.low or args.step <= 0:
        parser.error("Invalid scale search range")
    sizes = []
    for item in args.sizes.split(","):
        w, h = map(int, item.lower().split("x"))
        sizes.append((w, h))
    scales = [float(s)/100 for s in args.scales.split(",")]
    qualities = [None if s.strip().lower()=="none" else int(s) for s in args.jpeg.split(",")]
    message = np.random.default_rng(args.seed).integers(
        0, 256, args.bytes, dtype=np.uint8).tobytes()

    with Image.open(args.image) as im:
        source = im.convert("RGB")
    rows = []
    for w, h in sizes:
        base = crop_to_aspect(source, w, h)
        for pilot_enabled in (False, True):
            for scale in scales:
                for quality in qualities:
                    try:
                        row = run_case(base, args, pilot_enabled, scale, quality, message)
                    except Exception as exc:
                        row = {
                            "width": w, "height": h, "pilot": int(pilot_enabled),
                            "true_percent": scale*100,
                            "jpeg_quality": quality if quality is not None else "none",
                            "hybrid_pass": 0, "baseline_pass": 0, "oracle_pass": 0,
                            "error": f"{type(exc).__name__}: {exc}"
                        }
                    rows.append(row)
                    print(f'{w}x{h} pilot={int(pilot_enabled)} '
                          f'scale={scale*100:5.1f}% jpeg={str(quality):>4} '
                          f'est={row.get("estimated_percent", "N/A")} '
                          f'hybrid={row["hybrid_pass"]} baseline={row["baseline_pass"]} '
                          f'oracle={row["oracle_pass"]} {row["error"]}', flush=True)
    fields = ["width", "height", "pilot", "true_percent", "jpeg_quality",
              "estimated_percent", "scale_error_pp", "pilot_score",
              "score_median", "score_std", "inferred_width", "inferred_height",
              "attempts", "hybrid_pass", "baseline_pass", "oracle_pass",
              "psnr_db", "error"]
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    for enabled in (0, 1):
        group = [r for r in rows if r["pilot"] == enabled]
        print(f'pilot={enabled}: hybrid={sum(r["hybrid_pass"] for r in group)}/{len(group)}; '
              f'baseline={sum(r["baseline_pass"] for r in group)}/{len(group)}; '
              f'oracle={sum(r["oracle_pass"] for r in group)}/{len(group)}')
    print(f"Saved: {args.csv}")
    print("NOTE: the oracle is a diagnostic upper bound, NOT a blind result.")


if __name__ == "__main__":
    main()
