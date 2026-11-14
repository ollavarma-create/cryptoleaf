#!/usr/bin/env python3
"""Measure Fourier pilot strength vs DWT survival and blind scale detection.

Imports the existing experimental codecs. No changes to production Cryptoleaf.
The original dimensions are used ONLY for oracle diagnostics, not blind decoding.
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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--csv', type=Path, default=Path('fourier_strength_sweep.csv'))
    p.add_argument('--strengths', default='0,0.02,0.05,0.10,0.18')
    p.add_argument('--sizes', default='1280x720,640x480')
    p.add_argument('--scales', default='100,99,90,75')
    p.add_argument('--jpeg', default='none,60')
    p.add_argument('--bytes', type=int, default=50)
    p.add_argument('--delta', type=float, default=32)
    p.add_argument('--repeat', type=int, default=9)
    p.add_argument('--seed', type=int, default=20261114)
    p.add_argument('--save-quality', type=int, default=85)
    p.add_argument('--tolerance', type=float, default=2.0,
                   help='Max scale error in percentage points')
    p.add_argument('--low', type=float, default=0.70)
    p.add_argument('--high', type=float, default=1.02)
    p.add_argument('--step', type=float, default=0.002)
    args = p.parse_args()
    strengths = [float(x) for x in args.strengths.split(',')]
    sizes = [tuple(map(int, x.lower().split('x'))) for x in args.sizes.split(',')]
    scales = [float(x)/100 for x in args.scales.split(',')]
    qualities = [None if x.strip().lower() == 'none' else int(x) for x in args.jpeg.split(',')]
    if any(x < 0 for x in strengths) or not (0 < args.bytes <= 200):
        p.error('Strength must be nonnegative; bytes must be 1..200')
    message = np.random.default_rng(args.seed).integers(0, 256, args.bytes, dtype=np.uint8).tobytes()
    with Image.open(args.image) as im:
        source = im.convert('RGB')
    fields = ['width','height','strength','true_percent','jpeg_quality',
              'estimated_percent','scale_error_pp','scale_pass','pilot_score',
              'score_median','score_std','score_z','dwt_oracle_pass',
              'dwt_received_size_pass','psnr_db','error']
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with args.csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for w,h in sizes:
            base = crop_to_aspect(source, w, h)
            dwt_marked = dwt.embed(base, message, args.delta, args.repeat, args.seed)
            for strength in strengths:
                marked = fm.embed(dwt_marked, strength) if strength else dwt_marked
                encoded = dwt.jpeg_roundtrip(marked, args.save_quality)
                quality_psnr = dwt.psnr(base, encoded)
                for scale in scales:
                    received_size = (max(32, round(w*scale)), max(32, round(h*scale)))
                    scaled = encoded.resize(received_size, Image.Resampling.LANCZOS)
                    for quality in qualities:
                        received = dwt.jpeg_roundtrip(scaled, quality) if quality is not None else scaled
                        row = dict(width=w, height=h, strength=strength,
                                   true_percent=round(scale*100,3),
                                   jpeg_quality=quality if quality is not None else 'none',
                                   psnr_db=round(quality_psnr,3),
                                   scale_pass=0, dwt_oracle_pass=0, dwt_received_size_pass=0,
                                   error='')
                        try:
                            est, score, median, std = fm.estimate_scale(
                                received, low=args.low, high=args.high, step=args.step)
                            err = abs(est-scale)*100
                            row.update(estimated_percent=round(est*100,3),
                                       scale_error_pp=round(err,3),
                                       scale_pass=int(err <= args.tolerance),
                                       pilot_score=round(score,6),
                                       score_median=round(median,6),
                                       score_std=round(std,6),
                                       score_z=round((score-median)/max(std,1e-12),3))
                        except Exception as exc:
                            row['error'] += f'scale:{type(exc).__name__}:{exc};'
                        for label, size in [('dwt_oracle_pass',(w,h)),
                                            ('dwt_received_size_pass',received.size)]:
                            try:
                                row[label] = int(dwt.extract(received, size, args.delta,
                                              args.repeat, args.seed, max_bytes=256) == message)
                            except ValueError:
                                pass
                            except Exception as exc:
                                row['error'] += f'{label}:{type(exc).__name__}:{exc};'
                        writer.writerow(row)
                        f.flush()
                        key = (strength, quality if quality is not None else 'none')
                        counts.setdefault(key, []).append(row)
                        print(f'{w}x{h} strength={strength:.3f} scale={scale*100:g}% '
                              f'jpeg={str(quality):>4} scale_ok={row["scale_pass"]} '
                              f'dwt_oracle={row["dwt_oracle_pass"]} '
                              f'psnr={row["psnr_db"]:.2f}', flush=True)
    print('\nSUMMARY (scale pass / DWT oracle pass; each denominator = tested cases)')
    for key, rows in counts.items():
        print(f'strength={key[0]:.3f} jpeg={str(key[1]):>4}: '
              f'scale {sum(r["scale_pass"] for r in rows)}/{len(rows)}, '
              f'DWT {sum(r["dwt_oracle_pass"] for r in rows)}/{len(rows)}')
    print(f'CSV: {args.csv}')
    print('WARNING: scale_pass alone is not evidence of pilot detection. '
          'Compare against strength=0 and inspect pilot_score / score_z.')

if __name__ == '__main__':
    main()
