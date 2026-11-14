#!/usr/bin/env python3
"""Research-only: compare DWT/Fourier embedding order and DWT refresh.

Strategies: DWT->pilot, pilot->DWT, DWT->pilot->DWT.
The last strategy is a *fresh QIM embedding*, not a guaranteed harmless refresh.
Oracle DWT extraction knows the original size; Fourier scale estimation does not.
Neither a scale match nor an oracle success proves blind hybrid decoding.
"""
import argparse
import csv
from pathlib import Path
import sys
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from dwt_fourier_hybrid import crop_to_aspect
from fourier_band_separation import BANDS

STRATEGIES = ('dwt_only', 'dwt_pilot', 'pilot_dwt', 'dwt_pilot_dwt')
FIELDS = ['width','height','band','strength','strategy','true_percent',
          'jpeg_quality','estimated_percent','scale_error_pp','scale_pass',
          'pilot_score','score_median','score_std','score_z',
          'dwt_oracle_pass','both_pass','psnr_db','error']

def parse_csv(s, transform):
    return [transform(x.strip()) for x in s.split(',') if x.strip()]

def make_marked(base, message, strategy, strength, args):
    if strategy == 'dwt_only':
        return dwt.embed(base, message, args.delta, args.repeat, args.seed)
    if strategy == 'dwt_pilot':
        return fm.embed(dwt.embed(base, message, args.delta, args.repeat, args.seed), strength)
    if strategy == 'pilot_dwt':
        return dwt.embed(fm.embed(base, strength), message, args.delta, args.repeat, args.seed)
    if strategy == 'dwt_pilot_dwt':
        marked = dwt.embed(base, message, args.delta, args.repeat, args.seed)
        return dwt.embed(fm.embed(marked, strength), message, args.delta, args.repeat, args.seed)
    raise ValueError(strategy)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--csv', type=Path, default=Path('fourier_order_benchmark.csv'))
    p.add_argument('--bands', default='original,high')
    p.add_argument('--strengths', default='0.10,0.18')
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
    bands = parse_csv(args.bands, str)
    if not bands or any(b not in BANDS for b in bands): p.error(f'--bands must use {list(BANDS)}')
    strengths = parse_csv(args.strengths, float)
    if not strengths or any(s <= 0 for s in strengths): p.error('Strengths must be positive')
    sizes = [tuple(map(int, v.lower().split('x'))) for v in parse_csv(args.sizes, str)]
    scales = [float(v)/100 for v in parse_csv(args.scales, str)]
    qualities = [None if v.lower()=='none' else int(v) for v in parse_csv(args.jpeg, str)]
    if not sizes or any(w < 32 or h < 32 for w,h in sizes): p.error('Invalid sizes')
    if not scales or min(scales)<args.low_scale or max(scales)>args.high_scale: p.error('Scales outside detector range')
    if not 1 <= args.bytes <= 200: p.error('--bytes must be 1..200')
    if args.repeat < 1 or args.repeat%2 == 0: p.error('--repeat must be positive and odd')
    if not all(1 <= q <= 100 for q in qualities if q is not None): p.error('JPEG quality must be 1..100')
    message = np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    with Image.open(args.image) as im: source=im.convert('RGB')
    summary = {}
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS)
        writer.writeheader()
        for w,h in sizes:
            base=crop_to_aspect(source,w,h)
            for band in bands:
                fm.RADII=np.linspace(*BANDS[band],32)
                for strength in strengths:
                    # A no-pilot baseline is repeated per band/strength for matched comparisons.
                    for strategy in STRATEGIES:
                        try:
                            marked=make_marked(base,message,strategy,strength,args)
                            encoded=dwt.jpeg_roundtrip(marked,args.save_quality)
                            psnr=round(dwt.psnr(base,encoded),3)
                            setup_error=''
                        except Exception as exc:
                            encoded=None;psnr='';setup_error=f'Embed:{type(exc).__name__}:{exc};'
                        for scale in scales:
                            for quality in qualities:
                                row=dict(width=w,height=h,band=band,strength=strength,
                                         strategy=strategy,true_percent=round(scale*100,3),
                                         jpeg_quality='none' if quality is None else quality,
                                         scale_pass=0,dwt_oracle_pass=0,both_pass=0,
                                         psnr_db=psnr,error=setup_error)
                                if encoded is not None:
                                    try:
                                        received=encoded.resize((round(w*scale),round(h*scale)),Image.Resampling.LANCZOS)
                                        if quality is not None: received=dwt.jpeg_roundtrip(received,quality)
                                        est,score,median,std=fm.estimate_scale(received,low=args.low_scale,high=args.high_scale,step=args.step)
                                        err=abs(est-scale)*100
                                        row.update(estimated_percent=round(est*100,3),scale_error_pp=round(err,3),
                                                   scale_pass=int(err<=args.tolerance),pilot_score=round(score,6),
                                                   score_median=round(median,6),score_std=round(std,6),
                                                   score_z=round((score-median)/max(std,1e-12),3))
                                    except Exception as exc:
                                        row['error']+=f'Fourier:{type(exc).__name__}:{exc};'
                                    try:
                                        row['dwt_oracle_pass']=int(dwt.extract(received,(w,h),args.delta,args.repeat,args.seed,max_bytes=256)==message)
                                    except ValueError as exc:
                                        row['error']+=f'DWT:{exc};'
                                    except Exception as exc:
                                        row['error']+=f'DWT:{type(exc).__name__}:{exc};'
                                row['both_pass']=int(row['scale_pass'] and row['dwt_oracle_pass'])
                                writer.writerow(row);out.flush()
                                key=(band,strength,strategy,row['jpeg_quality'])
                                summary.setdefault(key,[]).append(row)
                                print(f'{w}x{h} {band:8} {strength:.2f} {strategy:15} '
                                      f'{scale*100:5.1f}% JPEG={str(quality):>4} '
                                      f'scale={row["scale_pass"]} DWT={row["dwt_oracle_pass"]}',flush=True)
    print('\nSUMMARY: Fourier scale / DWT oracle / both')
    for (band,strength,strategy,quality),rows in summary.items():
        print(f'{band:8} {strength:.2f} {strategy:15} JPEG={str(quality):>4}: '
              f'{sum(r["scale_pass"] for r in rows)}/{len(rows)} / '
              f'{sum(r["dwt_oracle_pass"] for r in rows)}/{len(rows)} / '
              f'{sum(r["both_pass"] for r in rows)}/{len(rows)}')
    print('Saved:',args.csv)
    print('CAUTION: DWT oracle knows the original dimensions. This is NOT a blind decoder test.')
    print('CAUTION: Scale success does NOT imply pilot detection; compare dwt_only controls.')

if __name__=='__main__': main()
