#!/usr/bin/env python3
"""Fair-budget Fourier single- vs dual-band multi-peak blind decoding benchmark.

Research only. Exactly the same maximum number of DWT decode attempts per
attack for each strategy. No original dimensions or true scale in blind search.
Strategies:
  baseline_single : baseline pilot, strongest Fourier peak
  baseline_multi  : SAME baseline pilot/image, multiple local Fourier peaks
  dual_single     : dual-full pilot, strongest combined estimate
  dual_multi      : SAME dual-full pilot/image, multiple band peaks

All four run on every image, paired across attacks. The original dimensions
are used ONLY for separate oracle diagnostics, never for blind search.
"""
import argparse
import csv
import hashlib
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from scipy.signal import find_peaks

sys.path.insert(0,str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from feedback_50photos_validation import feedback_embed, prepare
from fourier_blind_hybrid_benchmark import candidate_sizes
from fourier_dualband_validation import embed_multiband, attack, BANDS

FIELDS=['file','split','embed_mode','strategy','width','height','scale_pct',
        'jpeg','psnr_db','raw_pass','jpeg85_pass','oracle_pass',
        'blind_pass','attempts','found_width','found_height',
        'peak_count','top_scale_pct','top_score','best_peak_rank',
        'error']
def peak_candidates(image,band,args):
    """Return local maxima of EXACT original normalized correlation curve."""
    profile=fm.radial_profile(image)
    bin_freq=(np.arange(len(profile))+.5)*(.38/len(profile))
    scales=np.arange(args.low_scale,args.high_scale+args.step/2,args.step)
    low,high,_=band
    radii=np.linspace(low,high,32)
    rng=np.random.default_rng(fm.SEED)
    signs=rng.choice([-1.,1.],size=len(radii))
    scores=np.empty(len(scales))
    for i,scale in enumerate(scales):
        at=np.interp(radii/scale,bin_freq,profile)
        scores[i]=float(np.dot(signs,at)/(np.linalg.norm(at)*np.linalg.norm(signs)+1e-12))
    # Force global maximum into the candidate set even if on a boundary.
    inds=set(find_peaks(scores,distance=max(1,round(args.peak_separation_pp/100/args.step)))[0].tolist())
    inds.add(int(np.argmax(scores)))
    # Include boundary local maxima.
    if scores[0]>scores[1]: inds.add(0)
    if scores[-1]>scores[-2]: inds.add(len(scores)-1)
    return sorted([(float(scales[i]),float(scores[i])) for i in inds],
                  key=lambda pair:-pair[1])

def select_peaks(image,mode,strategy,args):
    bands=BANDS[mode]
    perband=[peak_candidates(image,b,args) for b in bands]
    if strategy.endswith('single'):
        # Baseline: one global peak. Dual: strongest z-normalized band peak.
        if len(perband)==1:return perband[0][:1]
        # For dual, compare per-band peak prominence against each score curve.
        # Scores are correlation coefficients; rank them directly.
        return [max((p[0] for p in perband),key=lambda x:x[1])]
    if len(perband)==1:return perband[0][:args.max_peaks]
    # Interleave both bands, retaining independent alternatives.
    merged=[]
    for rank in range(args.max_peaks):
        for bandpeaks in perband:
            if rank<len(bandpeaks):merged.append(bandpeaks[rank])
    distinct=[]
    for p in merged:
        if all(abs(p[0]-q[0])>args.peak_separation_pp/200 for q in distinct):
            distinct.append(p)
        if len(distinct)>=args.max_peaks:break
    return distinct

def decode(img,size,msg,args):
    try:
        return int(dwt.extract(img,size,args.delta,args.repeat,args.seed,
                               max_bytes=args.max_bytes)==msg)
    except ValueError:
        return 0

def fair_blind(received,msg,peaks,args):
    """Round-robin candidate lists. STRICT global budget across all peaks."""
    streams=[(i+1,iter(candidate_sizes(received.size,p[0],args.search_pp,args.max_candidates)))
             for i,p in enumerate(peaks)]
    seen=set()
    count=0
    rank=None
    while streams and count<args.max_candidates:
        active=[]
        for j,stream in streams:
            pass
        # Streams carry their original peak rank for reporting.
        for peak_rank,stream in streams:
            try:
                size=next(stream)
                active.append((peak_rank,stream))
            except StopIteration:
                continue
            if size in seen:continue
            seen.add(size)
            count+=1
            if decode(received,size,msg,args):
                return 1,count,size,peak_rank
            if count>=args.max_candidates:break
        streams=active
    return 0,count,None,None

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_multipeak_fair.csv'))
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
    ap.add_argument('--max-peaks',type=int,default=4)
    ap.add_argument('--peak-separation-pp',type=float,default=1.2)
    ap.add_argument('--holdout',type=float,default=.30)
    ap.add_argument('--only-holdout',action='store_true')
    args=ap.parse_args()
    if not args.directory.is_dir():ap.error('Directory not found')
    if not (0<args.holdout<1 and args.repeat>0 and args.repeat%2 and args.delta>0):
        ap.error('Invalid holdout/QIM settings')
    if not (0<args.bytes<=args.max_bytes and args.max_candidates>0 and args.max_peaks>0
            and args.step>0 and args.peak_separation_pp>0 and args.search_pp>0):
        ap.error('Invalid sizes/search settings')
    scales=[float(v)/100 for v in args.scales.split(',')]
    qualities=[None if v.strip().lower()=='none' else int(v) for v in args.jpeg.split(',')]
    if any(not args.low_scale<=s<=args.high_scale for s in scales):
        ap.error('Scale outside search range')
    photos=sorted(p for p in args.directory.iterdir() if p.is_file()
                  and p.suffix.lower() in ('.jpg','.jpeg'))
    if not photos:ap.error('No JPEG photos')
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    print(f'{len(photos)} photos; four strategies; <= {args.max_candidates} DWT attempts/case',flush=True)
    with args.csv.open('w',newline='',encoding='utf-8') as file:
        wr=csv.DictWriter(file,fieldnames=FIELDS);wr.writeheader()
        for index,path in enumerate(photos,1):
            split=('holdout' if int(hashlib.sha256(path.name.encode()).hexdigest()[:8],16)/0xffffffff<args.holdout else 'train')
            if args.only_holdout and split!='holdout':continue
            print(f'[{index}/{len(photos)}] {path.name}',flush=True)
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
            except Exception as exc:
                print('OPEN ERROR:',exc,flush=True);continue
            for mode in ('baseline','dual_full'):
                strategies=([ 'baseline_single','baseline_multi'] if mode=='baseline'
                            else ['dual_single','dual_multi'])
                try:
                    marked,_,_,_,_,_=feedback_embed(
                        embed_multiband(base,BANDS[mode]),msg,args.delta,args.repeat,
                        args.seed,args.feedback_iterations)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    psnr=dwt.psnr(base,saved)
                    raw=decode(marked,base.size,msg,args)
                    jpeg85=decode(saved,base.size,msg,args)
                    embed_error=''
                except Exception as exc:
                    saved=None;psnr='';raw=jpeg85=0
                    embed_error=f'{type(exc).__name__}:{exc}'
                for scale in scales:
                    for jq in qualities:
                        received=attack(saved,scale,jq) if saved is not None else None
                        oracle=decode(received,base.size,msg,args) if received is not None else 0
                        for strategy in strategies:
                            row=dict(file=path.name,split=split,embed_mode=mode,
                                     strategy=strategy,width=base.width,height=base.height,
                                     scale_pct=scale*100,jpeg='none' if jq is None else jq,
                                     psnr_db=psnr,raw_pass=raw,jpeg85_pass=jpeg85,
                                     oracle_pass=oracle,blind_pass=0,attempts=0,
                                     found_width='',found_height='',peak_count=0,
                                     top_scale_pct='',top_score='',best_peak_rank='',
                                     error=embed_error)
                            if received is not None:
                                try:
                                    peaks=select_peaks(received,mode,strategy,args)
                                    ok,n,size,rank=fair_blind(received,msg,peaks,args)
                                    row.update(blind_pass=ok,attempts=n,
                                               found_width=size[0] if size else '',
                                               found_height=size[1] if size else '',
                                               peak_count=len(peaks),
                                               top_scale_pct=round(peaks[0][0]*100,3) if peaks else '',
                                               top_score=round(peaks[0][1],5) if peaks else '',
                                               best_peak_rank=rank if rank is not None else '')
                                except Exception as exc:
                                    row['error']+=f' blind:{type(exc).__name__}:{exc}'
                            wr.writerow(row);file.flush()
                print(' ',mode,'complete',flush=True)
    print('CSV:',args.csv,flush=True)

if __name__=='__main__':
    main()
