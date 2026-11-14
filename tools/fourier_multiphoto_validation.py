#!/usr/bin/env python3
"""Independent multi-photo validation of the frozen Fourier -> DWT prototype.

Usage:
 python tools/fourier_multiphoto_validation.py /home/jari/Pictures/DWTFourierTesti/ --csv fourier_multiphoto.csv

Preserves aspect ratio and portrait orientation. No original dimensions are
provided to the blind decoder. Original dimensions are used ONLY by oracle.
The pilot-off cases contain a DWT message: they are negative controls for
Fourier synchronization, not unwatermarked-image false-positive tests.
"""
import argparse
import csv
import hashlib
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from fourier_blind_hybrid_benchmark import blind_extract

FIELDS = ["file", "sha256_12", "source_width", "source_height",
          "width", "height", "orientation", "pilot", "true_percent",
          "jpeg_quality", "estimated_percent", "scale_error_pp",
          "pilot_score", "score_z", "attempts", "found_width",
          "found_height", "blind_pass", "oracle_pass", "baseline_pass",
          "psnr_db", "error"]


def image_files(root, recursive):
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in root.glob(pattern)
                  if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg"))


def prepare(source, longest):
    w, h = source.size
    ratio = min(1.0, longest / max(w, h))
    nw, nh = max(32, round(w*ratio)), max(32, round(h*ratio))
    if (nw, nh) != (w, h):
        source = source.resize((nw, nh), Image.Resampling.LANCZOS)
    return source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--csv", type=Path, default=Path("fourier_multiphoto.csv"))
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--longest", type=int, default=1280,
                   help="Limit longest side to N pixels; keep native aspect and orientation")
    p.add_argument("--scales", default="100,90,75")
    p.add_argument("--jpeg", default="none,60")
    p.add_argument("--pilot", default="on,off")
    p.add_argument("--strength", type=float, default=0.18)
    p.add_argument("--bytes", type=int, default=50)
    p.add_argument("--delta", type=float, default=32)
    p.add_argument("--repeat", type=int, default=9)
    p.add_argument("--seed", type=int, default=20261114)
    p.add_argument("--save-quality", type=int, default=85)
    p.add_argument("--max-bytes", type=int, default=256)
    p.add_argument("--low-scale", type=float, default=0.70)
    p.add_argument("--high-scale", type=float, default=1.02)
    p.add_argument("--step", type=float, default=0.002)
    p.add_argument("--search-pp", type=float, default=1.0)
    p.add_argument("--max-candidates", type=int, default=160)
    args = p.parse_args()

    if not args.directory.is_dir(): p.error(f"Directory not found: {args.directory}")
    if args.longest < 128: p.error("--longest must be >= 128")
    if not (1 <= args.bytes <= args.max_bytes <= 65535): p.error("Invalid payload length")
    if args.repeat < 1 or args.repeat % 2 == 0: p.error("--repeat must be positive odd")
    if args.max_candidates < 1 or args.search_pp <= 0: p.error("Invalid search budget")
    if args.low_scale <= 0 or args.high_scale <= args.low_scale or args.step <= 0:
        p.error("Invalid scale bounds")
    scales = [float(x.strip()) / 100 for x in args.scales.split(",")]
    qualities = [None if x.strip().lower() == "none" else int(x) for x in args.jpeg.split(",")]
    pilots = [x.strip().lower() for x in args.pilot.split(",")]
    if not scales or any(not args.low_scale <= s <= args.high_scale for s in scales):
        p.error("Scales outside configured estimator range")
    if not qualities or any(q is not None and not 1 <= q <= 100 for q in qualities):
        p.error("Invalid JPEG quality")
    if not pilots or any(x not in ("on", "off") for x in pilots):
        p.error("--pilot accepts on,off")
    files = image_files(args.directory, args.recursive)
    if not files: p.error("No JPG/JPEG images found")
    message = np.random.default_rng(args.seed).integers(
        0, 256, args.bytes, dtype=np.uint8).tobytes()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    totals = defaultdict(lambda: [0, 0, 0, 0])
    with args.csv.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for index, file in enumerate(files, 1):
            relative = str(file.relative_to(args.directory))
            digest = hashlib.sha256(file.read_bytes()).hexdigest()[:12]
            try:
                with Image.open(file) as im:
                    oriented = ImageOps.exif_transpose(im)
                    original_size = oriented.size
                    base = prepare(oriented.convert("RGB"), args.longest)
            except Exception as exc:
                print(f"[{index}/{len(files)}] SKIP {relative}: {exc}", flush=True)
                for pilot in pilots:
                    for scale in scales:
                        for quality in qualities:
                            writer.writerow(dict(file=relative, sha256_12=digest,
                                pilot=pilot, true_percent=scale*100,
                                jpeg_quality="none" if quality is None else quality,
                                blind_pass=0, oracle_pass=0, baseline_pass=0,
                                error=f"Open:{type(exc).__name__}:{exc}"))
                output.flush()
                continue
            w, h = base.size
            orientation = "portrait" if h > w else ("landscape" if w > h else "square")
            print(f"[{index}/{len(files)}] {relative}: {original_size} -> {base.size}",
                  flush=True)
            for pilot in pilots:
                try:
                    pre = fm.embed(base, args.strength) if pilot == "on" else base
                    marked = dwt.embed(pre, message, args.delta, args.repeat, args.seed)
                    saved = dwt.jpeg_roundtrip(marked, args.save_quality)
                    psnr = round(dwt.psnr(base, saved), 3)
                    embed_error = ""
                except Exception as exc:
                    saved = None
                    psnr = ""
                    embed_error = f"Embed:{type(exc).__name__}:{exc}"
                for scale in scales:
                    for quality in qualities:
                        row = dict(file=relative, sha256_12=digest,
                                   source_width=original_size[0],
                                   source_height=original_size[1],
                                   width=w, height=h, orientation=orientation,
                                   pilot=pilot, true_percent=round(scale*100, 3),
                                   jpeg_quality="none" if quality is None else quality,
                                   blind_pass=0, oracle_pass=0, baseline_pass=0,
                                   attempts=0, psnr_db=psnr, error=embed_error)
                        if saved is not None:
                            received = saved.resize(
                                (max(32, round(w*scale)), max(32, round(h*scale))),
                                Image.Resampling.LANCZOS)
                            if quality is not None:
                                received = dwt.jpeg_roundtrip(received, quality)
                            try:
                                est, score, median, std, attempts, found, payload = blind_extract(
                                    received, args)
                                row.update(
                                    estimated_percent=round(est*100, 3),
                                    scale_error_pp=round(abs(est-scale)*100, 3),
                                    pilot_score=round(score, 6),
                                    score_z=round((score-median)/max(std, 1e-12), 3),
                                    attempts=attempts,
                                    found_width=found[0] if found else "",
                                    found_height=found[1] if found else "",
                                    blind_pass=int(payload == message))
                            except Exception as exc:
                                row["error"] += f" Blind:{type(exc).__name__}:{exc}"
                            try:
                                row["oracle_pass"] = int(dwt.extract(
                                    received, (w,h), args.delta, args.repeat,
                                    args.seed, args.max_bytes) == message)
                            except ValueError:
                                pass
                            try:
                                row["baseline_pass"] = int(dwt.extract(
                                    received, received.size, args.delta, args.repeat,
                                    args.seed, args.max_bytes) == message)
                            except ValueError:
                                pass
                        writer.writerow(row)
                        output.flush()
                        t = totals[pilot]
                        t[0] += 1
                        t[1] += row["blind_pass"]
                        t[2] += row["oracle_pass"]
                        t[3] += row["baseline_pass"]
                        print(f"  pilot={pilot} scale={scale*100:g}% "
                              f"jpeg={quality if quality is not None else 'none'} "
                              f"blind={row['blind_pass']} oracle={row['oracle_pass']} "
                              f"est={row.get('estimated_percent','-')} "
                              f"tried={row['attempts']}", flush=True)
    print("\nSUMMARY: pilot: blind / oracle / baseline")
    for pilot, (total, blind, oracle, baseline) in totals.items():
        print(f"  {pilot}: {blind}/{total} / {oracle}/{total} / {baseline}/{total}")
    print("CSV:", args.csv)
    print("NOTE: pilot-off images still contain DWT payload; not pristine negatives.")
    print("NOTE: 50-byte payload may exceed capacity for very small images.")


if __name__ == "__main__":
    main()
