#!/usr/bin/env python3
"""Research-only blind Fourier->DWT hybrid benchmark.

Decoder receives only the attacked image, public pilot and DWT parameters.
It does NOT receive original dimensions, reference pixels, or true scale.
CRC32 validates candidate payloads. A separate oracle diagnostic uses the
original dimensions ONLY for comparison. Not a production steganography codec.
"""
import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from dwt_fourier_hybrid import crop_to_aspect

FIELDS = ['width','height','pilot','true_percent','jpeg_quality',
          'estimated_percent','scale_error_pp','pilot_score','score_z',
          'candidate_count','attempts','found_width','found_height',
          'blind_pass','oracle_pass','baseline_pass','psnr_db','error']


def parse_list(text, fn):
    return [fn(x.strip()) for x in text.split(',') if x.strip()]


def candidate_sizes(received_size, estimated_scale, radius_pp, limit):
    """Rank candidate sizes by scale deviation, with rounding-aware sizes.

    Each dimension may be independently rounded during resizing. Search a
    scale interval around the pilot peak, rather than known resolution presets.
    The finite search budget is explicit and can cause false negatives.
    """
    rw, rh = received_size
    lo = max(0.01, estimated_scale - radius_pp / 100)
    hi = estimated_scale + radius_pp / 100
    minw, maxw = max(32, math.floor(rw/hi)-1), math.ceil(rw/lo)+1
    minh, maxh = max(32, math.floor(rh/hi)-1), math.ceil(rh/lo)+1
    options = []
    for w in range(minw, maxw+1):
        # For a candidate original width, infer its scale from received width;
        # check heights within +/- 2px of matching scale and roundoff.
        s = rw / w
        if not lo <= s <= hi:
            continue
        h_center = round(rh / s)
        for h in range(max(minh, h_center-2), min(maxh, h_center+2)+1):
            # Both dimensions must round to the observed pixels for a common
            # scale, within finite pixel rounding tolerance.
            sh = rh/h
            disagreement = abs(s-sh)
            if disagreement > max(1/w, 1/h):
                continue
            priority = (abs((s+sh)/2-estimated_scale), disagreement,
                        abs(h-h_center), abs(w-rw/estimated_scale))
            options.append((priority,(w,h)))
    options.sort(key=lambda x:x[0])
    seen=set()
    for _, size in options:
        if size not in seen:
            seen.add(size)
            yield size
            if len(seen)>=limit:
                return


def blind_extract(received, args):
    est, score, median, std = fm.estimate_scale(
        received, low=args.low_scale, high=args.high_scale, step=args.step)
    count=0
    found=None
    payload=None
    for size in candidate_sizes(received.size,est,args.search_pp,args.max_candidates):
        count+=1
        try:
            candidate=dwt.extract(received,size,args.delta,args.repeat,args.seed,
                                  max_bytes=args.max_bytes)
            # DWT extractor validates MAGIC and CRC; compare payload in caller.
            payload=candidate
            found=size
            break
        except ValueError:
            pass
    return est,score,median,std,count,found,payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path)
    p.add_argument('--csv',type=Path,default=Path('fourier_blind_hybrid.csv'))
    p.add_argument('--sizes',default='1280x720,640x480')
    p.add_argument('--scales',default='100,99,90,75')
    p.add_argument('--jpeg',default='none,60')
    p.add_argument('--pilot',default='on,off',help='on,off for negative controls')
    p.add_argument('--strength',type=float,default=0.18)
    p.add_argument('--bytes',type=int,default=50)
    p.add_argument('--delta',type=float,default=32)
    p.add_argument('--repeat',type=int,default=9)
    p.add_argument('--seed',type=int,default=20261114)
    p.add_argument('--save-quality',type=int,default=85)
    p.add_argument('--max-bytes',type=int,default=256)
    p.add_argument('--low-scale',type=float,default=0.70)
    p.add_argument('--high-scale',type=float,default=1.02)
    p.add_argument('--step',type=float,default=0.002)
    p.add_argument('--search-pp',type=float,default=1.0,
                   help='Search +/- percentage points around Fourier peak (default 1.0)')
    p.add_argument('--max-candidates',type=int,default=160,
                   help='Maximum DWT extractions per case (default 160)')
    args=p.parse_args()
    if not (1<=args.bytes<=args.max_bytes<=65535):p.error('Invalid payload length')
    if args.repeat<1 or args.repeat%2==0:p.error('--repeat must be positive odd')
    if args.search_pp<=0 or args.max_candidates<1:p.error('Invalid search budget')
    if args.low_scale<=0 or args.high_scale<=args.low_scale or args.step<=0:p.error('Invalid scale bounds')
    sizes=[tuple(map(int,s.lower().split('x'))) for s in parse_list(args.sizes,str)]
    scales=[float(x)/100 for x in parse_list(args.scales,str)]
    qualities=[None if x=='none' else int(x) for x in parse_list(args.jpeg,str)]
    pilots=parse_list(args.pilot,str)
    if not sizes or any(w<32 or h<32 for w,h in sizes):p.error('Invalid sizes')
    if not scales or any(not args.low_scale<=s<=args.high_scale for s in scales):p.error('Invalid scales')
    if not qualities or any(q is not None and not 1<=q<=100 for q in qualities):p.error('Invalid JPEG quality')
    if not pilots or any(x not in ('on','off') for x in pilots):p.error('--pilot must be on,off')
    message=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    with Image.open(args.image) as im: source=im.convert('RGB')
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    totals={}
    with args.csv.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS)
        writer.writeheader()
        for w,h in sizes:
            base=crop_to_aspect(source,w,h)
            for pilot in pilots:
                try:
                    # The previously successful embedding order: PILOT -> DWT.
                    pre=fm.embed(base,args.strength) if pilot=='on' else base
                    marked=dwt.embed(pre,message,args.delta,args.repeat,args.seed)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    quality_psnr=round(dwt.psnr(base,saved),3)
                    setup_error=''
                except Exception as exc:
                    saved=None;quality_psnr='';setup_error=f'Embed:{type(exc).__name__}:{exc}'
                for scale in scales:
                    for jpeg in qualities:
                        row=dict(width=w,height=h,pilot=pilot,true_percent=scale*100,
                                 jpeg_quality='none' if jpeg is None else jpeg,
                                 blind_pass=0,oracle_pass=0,baseline_pass=0,
                                 candidate_count=0,attempts=0,psnr_db=quality_psnr,error=setup_error)
                        if saved is not None:
                            received=saved.resize((round(w*scale),round(h*scale)),Image.Resampling.LANCZOS)
                            if jpeg is not None:received=dwt.jpeg_roundtrip(received,jpeg)
                            try:
                                est,score,median,std,attempts,found,payload=blind_extract(received,args)
                                row.update(estimated_percent=round(est*100,3),
                                           scale_error_pp=round(abs(est-scale)*100,3),
                                           pilot_score=round(score,6),
                                           score_z=round((score-median)/max(std,1e-12),3),
                                           attempts=attempts,candidate_count=attempts,
                                           found_width=found[0] if found else '',
                                           found_height=found[1] if found else '',
                                           blind_pass=int(payload==message))
                            except Exception as exc:
                                row['error']+=f' Blind:{type(exc).__name__}:{exc}'
                            try:
                                row['oracle_pass']=int(dwt.extract(received,(w,h),args.delta,args.repeat,args.seed,args.max_bytes)==message)
                            except ValueError:pass
                            try:
                                row['baseline_pass']=int(dwt.extract(received,received.size,args.delta,args.repeat,args.seed,args.max_bytes)==message)
                            except ValueError:pass
                        writer.writerow(row);out.flush()
                        totals.setdefault(pilot,[]).append(row)
                        print(f'{w}x{h} pilot={pilot:3} scale={scale*100:5.1f}% '
                              f'jpeg={str(jpeg):>4} est={row.get("estimated_percent","-")} '
                              f'blind={row["blind_pass"]} oracle={row["oracle_pass"]} '
                              f'tried={row["attempts"]}',flush=True)
    print('\nSUMMARY (blind / oracle / uncorrected):')
    for pilot,rows in totals.items():
        print(f'{pilot}: {sum(r["blind_pass"] for r in rows)}/{len(rows)} / '
              f'{sum(r["oracle_pass"] for r in rows)}/{len(rows)} / '
              f'{sum(r["baseline_pass"] for r in rows)}/{len(rows)}')
    print('CSV:',args.csv)
    print('CAUTION: no-pilot success is not proof of pilot detection; '
          'the DWT message is also present in the controls.')

if __name__=='__main__':main()
