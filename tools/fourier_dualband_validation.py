#!/usr/bin/env python3
"""Dual-band Fourier synchronization experiment; research only.

Requires local tools: dwt_probe.py, fourier_blind_pilot.py,
feedback_50photos_validation.py, fourier_blind_hybrid_benchmark.py.
Place this script alongside them.

Four embedding modes: baseline, low+mid with split strength, low+mid
with full strength per band, and one wide band. Evaluate pilot estimates,
quality and oracle decoding for every photo. Evaluate blind decoding for
baseline and split dual band on a held-out set.

NOTE: Two bands with split strength do not necessarily lower SNR: this
experiment measures the trade-off instead of assuming it.
"""
import argparse
import csv
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0,str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from feedback_50photos_validation import feedback_embed, prepare
from fourier_blind_hybrid_benchmark import candidate_sizes

BANDS = {
    'baseline': [(0.055,0.195,0.18)],
    'dual_split': [(0.030,0.130,0.09),(0.080,0.220,0.09)],
    'dual_full': [(0.030,0.130,0.18),(0.080,0.220,0.18)],
    'wide': [(0.040,0.240,0.18)],
}
FIELDS = ['file','split','mode','width','height','scale_pct','jpeg',
          'est_low_pct','est_mid_pct','est_fused_pct','error_pp',
          'low_score','mid_score','low_z','mid_z','band_disagreement_pp',
          'within_1pp','within_2pp','oracle_pass','raw_pass','jpeg85_pass',
          'psnr_db','feedback_iterations','feedback_wrong_final','error']
BLIND_FIELDS = ['file','mode','scale_pct','jpeg','oracle_pass','blind_pass',
                'attempts','found_width','found_height','est_fused_pct',
                'band_disagreement_pp','error']

def radii(low,high):
    return np.linspace(low,high,32)

def template(shape,low,high):
    old=fm.RADII.copy()
    try:
        fm.RADII=radii(low,high)
        return fm.pilot_template(shape)
    finally:
        fm.RADII=old

def embed_multiband(image,bands):
    """One FFT and one clipping pass for all pilot bands."""
    ycc=np.asarray(image.convert('YCbCr'),dtype=np.uint8).copy()
    y=ycc[:,:,0].astype(np.float32)
    fft=np.fft.fft2(y)
    logmod=np.zeros(y.shape,dtype=np.float32)
    for low,high,strength in bands:
        logmod+=strength*template(y.shape,low,high)
    fft*=np.exp(logmod)
    ycc[:,:,0]=np.clip(np.rint(np.fft.ifft2(fft).real),0,255).astype(np.uint8)
    return Image.fromarray(ycc,'YCbCr').convert('RGB')

def estimates(image,bands,args):
    """Independent band estimators, then confidence-weighted fusion."""
    results=[]
    old=fm.RADII.copy()
    try:
        for low,high,_ in bands:
            fm.RADII=radii(low,high)
            est,score,median,std=fm.estimate_scale(
                image,args.low_scale,args.high_scale,args.step)
            z=(score-median)/max(std,1e-12)
            results.append((est,score,z))
    finally:
        fm.RADII=old
    # Do not average contradictory scales: retain each peak as a candidate.
    # Fusion picks strongest z; if estimates agree within 1 pp, weighted mean.
    if len(results)==1:
        fused=results[0][0]
        disagree=0.
    else:
        disagree=abs(results[0][0]-results[1][0])*100
        if disagree<=1.0:
            weights=np.maximum([r[2] for r in results],0.01)
            fused=float(np.average([r[0] for r in results],weights=weights))
        else:
            fused=max(results,key=lambda r:r[2])[0]
    return results,fused,disagree

def decode(img,size,msg,args):
    try:
        return int(dwt.extract(img,size,args.delta,args.repeat,args.seed,
                               max_bytes=args.max_bytes)==msg)
    except ValueError:
        return 0

def blind(img,bands,msg,args):
    results,fused,disagree=estimates(img,bands,args)
    # Multi-hypothesis: each independent peak is checked; no oracle scale.
    peaks=[fused]+[r[0] for r in sorted(results,key=lambda x:-x[2])]
    seen=set()
    attempts=0
    for peak in peaks:
        for size in candidate_sizes(img.size,peak,args.search_pp,args.max_candidates):
            if size in seen: continue
            seen.add(size)
            attempts+=1
            try:
                payload=dwt.extract(img,size,args.delta,args.repeat,args.seed,
                                    max_bytes=args.max_bytes)
                if payload==msg:
                    return 1,attempts,size,fused,disagree
            except ValueError:
                pass
    return 0,attempts,None,fused,disagree

def attack(image,scale,jpeg):
    size=(max(32,round(image.width*scale)),max(32,round(image.height*scale)))
    out=image.resize(size,Image.Resampling.LANCZOS) if size!=image.size else image
    return dwt.jpeg_roundtrip(out,jpeg) if jpeg is not None else out

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_dualband.csv'))
    ap.add_argument('--blind-csv',type=Path,default=Path('fourier_dualband_blind.csv'))
    ap.add_argument('--longest',type=int,default=1280)
    ap.add_argument('--scales',default='100,90,75')
    ap.add_argument('--jpeg',default='none,60')
    ap.add_argument('--bytes',type=int,default=50)
    ap.add_argument('--delta',type=float,default=32)
    ap.add_argument('--repeat',type=int,default=9)
    ap.add_argument('--seed',type=int,default=20261114)
    ap.add_argument('--max-bytes',type=int,default=256)
    ap.add_argument('--feedback-iterations',type=int,default=6)
    ap.add_argument('--save-quality',type=int,default=85)
    ap.add_argument('--low-scale',type=float,default=.70)
    ap.add_argument('--high-scale',type=float,default=1.02)
    ap.add_argument('--step',type=float,default=.002)
    ap.add_argument('--search-pp',type=float,default=1.)
    ap.add_argument('--max-candidates',type=int,default=160)
    ap.add_argument('--holdout',type=float,default=.30)
    ap.add_argument('--skip-blind',action='store_true')
    args=ap.parse_args()
    if not args.directory.is_dir():ap.error('Directory not found')
    if not (0<args.holdout<1 and args.repeat>0 and args.repeat%2 and args.delta>0):
        ap.error('Invalid holdout/QIM settings')
    if not (0<args.bytes<=args.max_bytes and args.max_candidates>0 and args.step>0):
        ap.error('Invalid size/search settings')
    scales=[float(v)/100 for v in args.scales.split(',')]
    qualities=[None if v.strip().lower()=='none' else int(v) for v in args.jpeg.split(',')]
    if any(not args.low_scale<=s<=args.high_scale for s in scales):
        ap.error('Scale outside search range')
    if any(q is not None and not 1<=q<=100 for q in qualities):
        ap.error('Invalid JPEG quality')
    photos=sorted(p for p in args.directory.iterdir() if p.is_file()
                  and p.suffix.lower() in ('.jpg','.jpeg'))
    if not photos:ap.error('No JPEG photos')
    split={p:('holdout' if int(hashlib.sha256(p.name.encode()).hexdigest()[:8],16)/0xffffffff<args.holdout else 'train') for p in photos}
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    args.blind_csv.parent.mkdir(parents=True,exist_ok=True)
    print(f'{len(photos)} photos, {len(BANDS)} modes, {len(scales)*len(qualities)} attacks; {sum(x=="holdout" for x in split.values())} holdout',flush=True)
    with args.csv.open('w',newline='',encoding='utf-8') as file:
        wr=csv.DictWriter(file,fieldnames=FIELDS);wr.writeheader()
        for i,path in enumerate(photos,1):
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
            except Exception as exc:
                print('OPEN ERROR',path.name,exc,flush=True);continue
            print(f'[{i}/{len(photos)}] {path.name}',flush=True)
            for mode,bands in BANDS.items():
                try:
                    pilot=embed_multiband(base,bands)
                    marked,_,_,iters,_,wrong=feedback_embed(
                        pilot,msg,args.delta,args.repeat,args.seed,args.feedback_iterations)
                    raw=decode(marked,base.size,msg,args)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    savedpass=decode(saved,base.size,msg,args)
                    psnr=dwt.psnr(base,saved)
                    embed_error=''
                except Exception as exc:
                    saved=None;raw=savedpass=0;psnr=iters=wrong=''
                    embed_error=f'{type(exc).__name__}:{exc}'
                for scale in scales:
                    for jq in qualities:
                        row=dict(file=path.name,split=split[path],mode=mode,
                                 width=base.width,height=base.height,scale_pct=scale*100,
                                 jpeg='none' if jq is None else jq,
                                 est_low_pct='',est_mid_pct='',est_fused_pct='',
                                 error_pp='',low_score='',mid_score='',low_z='',mid_z='',
                                 band_disagreement_pp='',within_1pp=0,within_2pp=0,
                                 oracle_pass=0,raw_pass=raw,jpeg85_pass=savedpass,
                                 psnr_db=psnr,feedback_iterations=iters,
                                 feedback_wrong_final=wrong,error=embed_error)
                        if saved is not None:
                            try:
                                received=attack(saved,scale,jq)
                                estimates_,fused,disagree=estimates(received,bands,args)
                                err=abs(fused-scale)*100
                                row.update(est_low_pct=round(estimates_[0][0]*100,3),
                                           est_mid_pct=round(estimates_[1][0]*100,3) if len(estimates_)>1 else '',
                                           est_fused_pct=round(fused*100,3),
                                           error_pp=round(err,3),
                                           low_score=round(estimates_[0][1],5),
                                           mid_score=round(estimates_[1][1],5) if len(estimates_)>1 else '',
                                           low_z=round(estimates_[0][2],3),
                                           mid_z=round(estimates_[1][2],3) if len(estimates_)>1 else '',
                                           band_disagreement_pp=round(disagree,3),
                                           within_1pp=int(err<=1),within_2pp=int(err<=2),
                                           oracle_pass=decode(received,base.size,msg,args))
                            except Exception as exc:
                                row['error']+=f' estimate:{type(exc).__name__}:{exc}'
                        wr.writerow(row);file.flush()
                print(' ',mode,'complete',flush=True)
    if args.skip_blind:
        print('Pilot CSV:',args.csv);return
    with args.blind_csv.open('w',newline='',encoding='utf-8') as file:
        wr=csv.DictWriter(file,fieldnames=BLIND_FIELDS);wr.writeheader()
        for path in photos:
            if split[path]!='holdout':continue
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
            except Exception as exc:
                print('OPEN ERROR',path.name,exc,flush=True);continue
            for mode in ('baseline','dual_split','dual_full'):
                bands=BANDS[mode]
                try:
                    marked,*_=feedback_embed(embed_multiband(base,bands),msg,args.delta,
                                             args.repeat,args.seed,args.feedback_iterations)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    error=''
                except Exception as exc:
                    saved=None;error=f'{type(exc).__name__}:{exc}'
                for scale in scales:
                    for jq in qualities:
                        row=dict(file=path.name,mode=mode,scale_pct=scale*100,
                                 jpeg='none' if jq is None else jq,oracle_pass=0,
                                 blind_pass=0,attempts=0,found_width='',found_height='',
                                 est_fused_pct='',band_disagreement_pp='',error=error)
                        if saved is not None:
                            try:
                                received=attack(saved,scale,jq)
                                ok,n,size,est,disagree=blind(received,bands,msg,args)
                                row.update(oracle_pass=decode(received,base.size,msg,args),
                                           blind_pass=ok,attempts=n,
                                           found_width=size[0] if size else '',
                                           found_height=size[1] if size else '',
                                           est_fused_pct=round(est*100,3),
                                           band_disagreement_pp=round(disagree,3))
                            except Exception as exc:
                                row['error']+=f' blind:{type(exc).__name__}:{exc}'
                        wr.writerow(row);file.flush()
                print('BLIND',path.name,mode,'complete',flush=True)
    print('Finished:',args.csv,args.blind_csv)

if __name__=='__main__':
    main()
