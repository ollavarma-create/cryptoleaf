#!/usr/bin/env python3
"""Cryptoleaf: paired search-budget / wall-time benchmark (research only).

Put alongside fourier_multipeak_fair_benchmark.py and its dependencies.
Measures the SAME deterministic search order at nested budgets
10,25,50,100,160; no repeated image embedding or search per budget.
Blind search never receives original dimensions or true scale.
Timing includes peak estimation, candidate enumeration and DWT attempts;
excludes embedding, JPEG attacks and image loading. CPU/OS load affects time.
"""
import argparse
import csv
import hashlib
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parent))
import dwt_probe as dwt
from feedback_50photos_validation import feedback_embed, prepare
from fourier_dualband_validation import embed_multiband, attack, BANDS
from fourier_blind_hybrid_benchmark import candidate_sizes
from fourier_multipeak_fair_benchmark import select_peaks

FIELDS=['file','split','embed_mode','strategy','scale_pct','jpeg',
        'budget','success','attempts','elapsed_ms','peak_ms','search_ms',
        'found_width','found_height','oracle_pass','psnr_db','error']
def decode(img,size,msg,args):
    try:
        return dwt.extract(img,size,args.delta,args.repeat,args.seed,
                           max_bytes=args.max_bytes)==msg
    except ValueError:
        return False

def timed_search(image,mode,strategy,msg,args,budgets):
    start=time.perf_counter()
    peaks=select_peaks(image,mode,strategy,args)
    peak_ms=(time.perf_counter()-start)*1000
    streams=[(rank+1,iter(candidate_sizes(image.size,p[0],args.search_pp,max(budgets))))
             for rank,p in enumerate(peaks)]
    seen=set()
    count=0
    found=None
    times={}
    total=max(budgets)
    # Record elapsed time at each boundary, including failures.
    while streams and count<total and found is None:
        active=[]
        for rank,stream in streams:
            try:
                size=next(stream)
            except StopIteration:
                continue
            active.append((rank,stream))
            if size in seen:continue
            seen.add(size)
            count+=1
            if decode(image,size,msg,args):
                found=size
            if count in budgets or found is not None:
                times[count]=(time.perf_counter()-start)*1000
            if count>=total or found is not None:break
        streams=active
    final_ms=(time.perf_counter()-start)*1000
    results=[]
    for budget in budgets:
        n=min(budget,count)
        # A successful search stops early, all higher budgets have same time.
        # If fewer candidates than budget exist, record actual elapsed time.
        if found is not None and count<=budget:
            elapsed=times[count]
            ok=1
        elif count<budget:
            elapsed=final_ms
            ok=0
        else:
            elapsed=times.get(budget,final_ms)
            ok=0
        results.append((budget,ok,n,elapsed,peak_ms,
                        max(0.,elapsed-peak_ms),found if ok else None))
    return results

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_budget_timing.csv'))
    ap.add_argument('--budgets',default='10,25,50,100,160')
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
    budgets=sorted(set(int(v.strip()) for v in args.budgets.split(',')))
    if not budgets or budgets[0]<1 or budgets[-1]>args.max_candidates:
        ap.error('Budgets must be 1..max-candidates')
    if not args.directory.is_dir():ap.error('Directory not found')
    scales=[float(v)/100 for v in args.scales.split(',')]
    qualities=[None if v.strip().lower()=='none' else int(v) for v in args.jpeg.split(',')]
    if not (0<args.holdout<1 and args.repeat>0 and args.repeat%2 and args.delta>0
            and 0<args.bytes<=args.max_bytes and args.max_peaks>0
            and args.step>0 and args.search_pp>0 and args.peak_separation_pp>0):
        ap.error('Invalid settings')
    photos=sorted(p for p in args.directory.iterdir() if p.is_file()
                  and p.suffix.lower() in ('.jpg','.jpeg'))
    if not photos:ap.error('No JPEG photos')
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
        for idx,path in enumerate(photos,1):
            split=('holdout' if int(hashlib.sha256(path.name.encode()).hexdigest()[:8],16)/0xffffffff<args.holdout else 'train')
            if args.only_holdout and split!='holdout':continue
            print(f'[{idx}/{len(photos)}] {path.name}',flush=True)
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
            except Exception as exc:
                print('OPEN ERROR:',exc,flush=True);continue
            for mode in ('baseline','dual_full'):
                strategies=(('baseline_single','baseline_multi') if mode=='baseline'
                            else ('dual_single','dual_multi'))
                try:
                    marked,*_=feedback_embed(embed_multiband(base,BANDS[mode]),msg,
                        args.delta,args.repeat,args.seed,args.feedback_iterations)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    psnr=dwt.psnr(base,saved)
                    error=''
                except Exception as exc:
                    saved=None;psnr=''
                    error=f'{type(exc).__name__}: {exc}'
                for scale in scales:
                    for jq in qualities:
                        received=attack(saved,scale,jq) if saved is not None else None
                        oracle=int(decode(received,base.size,msg,args)) if received is not None else 0
                        for strategy in strategies:
                            try:
                                result=timed_search(received,mode,strategy,msg,args,budgets) if received is not None else []
                                problem=error
                            except Exception as exc:
                                result=[]
                                problem=f'{type(exc).__name__}: {exc}'
                            by_budget={r[0]:r for r in result}
                            for budget in budgets:
                                r=by_budget.get(budget)
                                writer.writerow(dict(
                                    file=path.name,split=split,embed_mode=mode,
                                    strategy=strategy,scale_pct=scale*100,
                                    jpeg='none' if jq is None else jq,budget=budget,
                                    success=r[1] if r else 0,
                                    attempts=r[2] if r else 0,
                                    elapsed_ms=round(r[3],3) if r else '',
                                    peak_ms=round(r[4],3) if r else '',
                                    search_ms=round(r[5],3) if r else '',
                                    found_width=r[6][0] if r and r[6] else '',
                                    found_height=r[6][1] if r and r[6] else '',
                                    oracle_pass=oracle,psnr_db=psnr,error=problem))
                            f.flush()
                print(' ',mode,'complete',flush=True)
    print('Done:',args.csv,flush=True)

if __name__=='__main__':
    main()
