#!/usr/bin/env python3
"""Cryptoleaf research: isolate DWT capacity, JPEG loss and Fourier synchronization.

Uses the frozen experimental modules in tools/. Never edits the source photos.
The blind decoder sees only the received image and fixed public parameters.
The original size is supplied ONLY to the explicitly labelled oracle check.
"""
import argparse
import csv
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fourier
from fourier_blind_hybrid_benchmark import blind_extract

FIELDS = ["file", "sha256_12", "width", "height", "ll2_capacity", "bytes",
          "required_coefficients", "capacity_ok", "pilot", "stage", "scale_percent",
          "jpeg_quality", "received_width", "received_height", "dwt_oracle_pass",
          "dwt_oracle_error", "blind_pass", "blind_error", "estimated_scale_percent",
          "scale_error_pp", "pilot_score", "pilot_z", "blind_attempts", "found_width",
          "found_height", "psnr_db", "setup_error"]


def decode(img, size, message, args):
    try:
        decoded = dwt.extract(img, size, args.delta, args.repeat, args.seed,
                              max_bytes=args.max_bytes)
        return int(decoded == message), "" if decoded == message else "MessageMismatch"
    except Exception as exc:
        return 0, f"{type(exc).__name__}:{exc}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="*", type=Path,
                    help="JPEG paths; default: three named images in --directory")
    ap.add_argument("--directory", type=Path,
                    default=Path("/home/jari/Pictures/DWTFourierTesti"))
    ap.add_argument("--csv", type=Path, default=Path("fourier_failure_diagnostics.csv"))
    ap.add_argument("--lengths", default="10,25,50")
    ap.add_argument("--scales", default="100,90,75")
    ap.add_argument("--pilot", default="off,on")
    ap.add_argument("--strength", type=float, default=0.18)
    ap.add_argument("--delta", type=float, default=32)
    ap.add_argument("--repeat", type=int, default=9)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--save-quality", type=int, default=85)
    ap.add_argument("--attack-quality", type=int, default=60)
    ap.add_argument("--max-bytes", type=int, default=256)
    ap.add_argument("--low-scale", type=float, default=0.70)
    ap.add_argument("--high-scale", type=float, default=1.02)
    ap.add_argument("--step", type=float, default=0.002)
    ap.add_argument("--search-pp", type=float, default=1.0)
    ap.add_argument("--max-candidates", type=int, default=160)
    ap.add_argument("--blind", action="store_true",
                    help="Also run slow blind scale+candidate search at attack stages")
    args = ap.parse_args()
    if not args.images:
        args.images = [args.directory / name for name in (
            "GreatSportMoment1.jpg", "GreatSportsMoment8.jpg", "P1010892.JPG")]
    try:
        lengths = [int(x.strip()) for x in args.lengths.split(",")]
        scales = [float(x.strip()) / 100 for x in args.scales.split(",")]
        pilots = [x.strip() for x in args.pilot.split(",")]
    except ValueError as exc:
        ap.error(str(exc))
    if not lengths or any(n < 1 or n > args.max_bytes for n in lengths):
        ap.error("Invalid --lengths")
    if not scales or any(not 0 < s <= 1.02 for s in scales):
        ap.error("Invalid --scales")
    if not pilots or any(p not in ("on", "off") for p in pilots):
        ap.error("--pilot must contain on and/or off")
    if args.repeat < 1 or args.repeat % 2 != 1:
        ap.error("--repeat must be positive odd")
    if args.max_candidates < 1 or args.search_pp <= 0:
        ap.error("Invalid candidate search settings")
    if args.blind and any(s < args.low_scale or s > args.high_scale for s in scales):
        ap.error("Scale outside blind estimator range")

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with args.csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for path in args.images:
            if not path.is_file():
                print(f"MISSING: {path}", file=sys.stderr, flush=True)
                continue
            try:
                with Image.open(path) as original:
                    base = ImageOps.exif_transpose(original).convert("RGB")
            except Exception as exc:
                print(f"CANNOT OPEN {path}: {exc}", file=sys.stderr, flush=True)
                continue
            w, h = base.size
            ll2_capacity = ((w + 3) // 4) * ((h + 3) // 4)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            print(f"\n{path.name} {w}x{h}, LL2={ll2_capacity} coefficients", flush=True)
            for n in lengths:
                message = np.random.default_rng(args.seed).integers(
                    0, 256, n, dtype=np.uint8).tobytes()
                needed = (n + 10) * 8 * args.repeat  # DWT1 + length + CRC32 = 10 bytes
                for pilot in pilots:
                    common = dict(file=path.name, sha256_12=digest,
                                  width=w, height=h, ll2_capacity=ll2_capacity,
                                  bytes=n, required_coefficients=needed,
                                  capacity_ok=int(needed <= ll2_capacity), pilot=pilot)
                    if needed > ll2_capacity:
                        row = dict(common, stage="capacity", scale_percent=100,
                                   setup_error=f"Insufficient DWT capacity: need {needed}, have {ll2_capacity}")
                        writer.writerow(row); fh.flush()
                        print(f"  {n:2} bytes pilot={pilot}: CAPACITY FAIL ({needed}/{ll2_capacity})", flush=True)
                        continue
                    try:
                        pre = fourier.embed(base, args.strength) if pilot == "on" else base
                        embedded = dwt.embed(pre, message, args.delta, args.repeat, args.seed)
                        jpeg85 = dwt.jpeg_roundtrip(embedded, args.save_quality)
                        psnr = round(dwt.psnr(base, jpeg85), 3)
                    except Exception as exc:
                        row = dict(common, stage="embed", setup_error=f"{type(exc).__name__}:{exc}")
                        writer.writerow(row); fh.flush()
                        print(f"  {n:2} bytes pilot={pilot}: EMBED FAIL {exc}", flush=True)
                        continue
                    # Progressive stages: raw DWT, initial JPEG, scaling, then recompression.
                    stages = [("raw", 1.0, None, embedded),
                              ("jpeg85", 1.0, args.save_quality, jpeg85)]
                    for s in scales:
                        resized = jpeg85.resize((max(1, round(w*s)), max(1, round(h*s))),
                                                Image.Resampling.LANCZOS)
                        stages.append(("scaled", s, None, resized))
                        stages.append(("scaled_jpeg60", s, args.attack_quality,
                                       dwt.jpeg_roundtrip(resized, args.attack_quality)))
                    for stage, scale, quality, received in stages:
                        passed, error = decode(received, (w, h), message, args)
                        row = dict(common, stage=stage, scale_percent=round(scale*100, 3),
                                   jpeg_quality="none" if quality is None else quality,
                                   received_width=received.width, received_height=received.height,
                                   dwt_oracle_pass=passed, dwt_oracle_error=error,
                                   psnr_db=psnr)
                        if args.blind and stage in ("scaled", "scaled_jpeg60"):
                            try:
                                est, score, median, std, attempts, found, payload = blind_extract(received, args)
                                row.update(blind_pass=int(payload == message),
                                           estimated_scale_percent=round(est*100, 3),
                                           scale_error_pp=round(abs(est-scale)*100, 3),
                                           pilot_score=round(score, 6),
                                           pilot_z=round((score-median)/max(std, 1e-12), 3),
                                           blind_attempts=attempts,
                                           found_width=found[0] if found else "",
                                           found_height=found[1] if found else "")
                            except Exception as exc:
                                row["blind_pass"] = 0
                                row["blind_error"] = f"{type(exc).__name__}:{exc}"
                        writer.writerow(row)
                        fh.flush()
                        key = (stage, pilot, n)
                        counts.setdefault(key, [0, 0])
                        counts[key][0] += passed
                        counts[key][1] += 1
                        print(f"  {n:2}B pilot={pilot:3} {stage:13} scale={scale*100:5.1f}% "
                              f"oracle={'PASS' if passed else 'FAIL'} {error}"
                              + (f" blind={row.get('blind_pass','-')}" if args.blind else ""), flush=True)
    print("\nSTAGE SUMMARY (oracle):")
    for key, (success, total) in sorted(counts.items()):
        print(f"  {key}: {success}/{total}")
    print(f"\nCSV: {args.csv}")
    print("Interpretation: capacity failures are not JPEG/Fourier failures.")
    print("Note: --blind uses the unchanged candidate-search budget; misses can be search-limited.")

if __name__ == "__main__":
    main()
