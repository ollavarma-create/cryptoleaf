#!/usr/bin/env python3
"""Fourier pilot frequency-band separation vs DWT-QIM survival.

Experimental only. Compares identical random ring signatures at three radial
frequency bands, using the existing Fourier and DWT research prototypes.
The original dimensions are used ONLY for DWT oracle diagnostics.
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
from dwt_fourier_hybrid import crop_to_aspect

# Cycles per pixel in the ORIGINAL image. All radii remain below 0.38 * 0.75,
# so the existing blind detector can search 75% scaling without truncation.
BANDS = {
    'original': (0.055, 0.195),
    'low': (0.035, 0.105),
    'middle': (0.115, 0.175),
    'high': (0.205, 0.275),
}


def parse_list(text, fn):
    return [fn(x.strip()) for x in text.split(',') if x.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--csv', type=Path, default=Path('fourier_band_separation.csv'))
    p.add_argument('--bands', default='original,low,middle,high')
    p.add_argument('--strengths', default='0,0.10,0.18')
    p.add_argument('--sizes', default='1280x720,640x480')
    p.add_argument('--scales', default='100,99,90,75')
    p.add_argument('--jpeg', default='none,60')
    p.add_argument('--bytes', type=int, default=50)
    p.add_argument('--delta', type=float, default=32)
    p.add_argument('--repeat', type=int, default=9)
    p.add_argument('--seed', type=int, default=20261114)
    p.add_argument('--save-quality', type=int, default=85)
    p.add_argument('--tolerance', type=float, default=2.0)
    p.add_argument('--low-scale', type=float, default=0.70)
    p.add_argument('--high-scale', type=float, default=1.02)
    p.add_argument('--step', type=float, default=0.002)
    args = p.parse_args()

    bands = parse_list(args.bands, str)
    if any(b not in BANDS for b in bands):
        p.error(f'Unknown band; choose from {list(BANDS)}')
    strengths = parse_list(args.strengths, float)
    if any(s < 0 for s in strengths):
        p.error('Strength must be nonnegative')
    if not 1 <= args.bytes <= 200:
        p.error('Message size must be 1..200 bytes')
    sizes = [tuple(map(int, s.lower().split('x'))) for s in parse_list(args.sizes, str)]
    scales = [float(s)/100 for s in parse_list(args.scales, str)]
    qualities = [None if s == 'none' else int(s) for s in parse_list(args.jpeg, str)]
    if min(scales) < args.low_scale or max(scales) > args.high_scale:
        p.error('Scale values must be inside the detector search interval')
    if args.repeat < 1 or args.repeat % 2 == 0:
        p.error('Repeat must be positive and odd')

    with Image.open(args.image) as image:
        source = image.convert('RGB')
    message = np.random.default_rng(args.seed).integers(
        0, 256, args.bytes, dtype=np.uint8).tobytes()

    fields = ['width','height','band','band_start','band_end','strength',
              'true_percent','jpeg_quality','estimated_percent','scale_error_pp',
              'scale_pass','pilot_score','score_median','score_std','score_z',
              'dwt_oracle_pass','both_pass','psnr_db','error']
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    with args.csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for w, h in sizes:
            base = crop_to_aspect(source, w, h)
            dwt_marked = dwt.embed(base, message, args.delta, args.repeat, args.seed)
            for band in bands:
                start, end = BANDS[band]
                # fm.embed and fm.estimate_scale both use this module constant.
                # One band at a time; no concurrent calls.
                fm.RADII = np.linspace(start, end, 32)
                for strength in strengths:
                    marked = fm.embed(dwt_marked, strength) if strength else dwt_marked
                    encoded = dwt.jpeg_roundtrip(marked, args.save_quality)
                    quality_psnr = dwt.psnr(base, encoded)
                    for scale in scales:
                        size = (max(32, round(w*scale)), max(32, round(h*scale)))
                        scaled = encoded.resize(size, Image.Resampling.LANCZOS)
                        for jpeg in qualities:
                            received = dwt.jpeg_roundtrip(scaled, jpeg) if jpeg is not None else scaled
                            row = dict(width=w, height=h, band=band,
                                       band_start=start, band_end=end,
                                       strength=strength, true_percent=round(scale*100,3),
                                       jpeg_quality=jpeg if jpeg is not None else 'none',
                                       scale_pass=0, dwt_oracle_pass=0, both_pass=0,
                                       psnr_db=round(quality_psnr,3), error='')
                            try:
                                estimate, score, median, std = fm.estimate_scale(
                                    received, low=args.low_scale,
                                    high=args.high_scale, step=args.step)
                                error_pp = abs(estimate-scale)*100
                                row.update(estimated_percent=round(estimate*100,3),
                                           scale_error_pp=round(error_pp,3),
                                           scale_pass=int(error_pp <= args.tolerance),
                                           pilot_score=round(score,6),
                                           score_median=round(median,6),
                                           score_std=round(std,6),
                                           score_z=round((score-median)/max(std,1e-12),3))
                            except Exception as exc:
                                row['error'] += f'Fourier:{type(exc).__name__}:{exc};'
                            try:
                                row['dwt_oracle_pass'] = int(dwt.extract(
                                    received, (w,h), args.delta, args.repeat,
                                    args.seed, max_bytes=256) == message)
                            except ValueError:
                                pass
                            except Exception as exc:
                                row['error'] += f'DWT:{type(exc).__name__}:{exc};'
                            row['both_pass'] = int(row['scale_pass'] and row['dwt_oracle_pass'])
                            writer.writerow(row)
                            out.flush()
                            key = (band, strength, row['jpeg_quality'])
                            summary.setdefault(key, []).append(row)
                            print(f'{w}x{h} band={band:8s} strength={strength:.2f} '
                                  f'scale={scale*100:5.1f}% jpeg={str(jpeg):>4} '
                                  f'Fourier={row["scale_pass"]} DWT={row["dwt_oracle_pass"]} '
                                  f'both={row["both_pass"]}', flush=True)
    print('\nSUMMARY: scale / DWT-oracle / both')
    for (band, strength, jpeg), rows in summary.items():
        n = len(rows)
        print(f'{band:8s} strength={strength:.2f} jpeg={str(jpeg):>4}: '
              f'{sum(r["scale_pass"] for r in rows)}/{n} / '
              f'{sum(r["dwt_oracle_pass"] for r in rows)}/{n} / '
              f'{sum(r["both_pass"] for r in rows)}/{n}')
    print(f'CSV saved: {args.csv}')
    print('NOTE: DWT oracle uses original dimensions, not a blind hybrid decoder.')
    print('NOTE: scale_pass is not a pilot-presence detector; compare strength=0 controls.')

if __name__ == '__main__':
    main()
