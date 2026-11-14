#!/usr/bin/env python3
"""Cryptoleaf: paired, equal-budget Fourier peak selection/search benchmark.

Same baseline pilot, RS8 carrier and attacked image for every strategy.
Tests: priority50, priority25, round_robin, diverse50, confidence50.
All strategies have exactly the same GLOBAL maximum number of DWT attempts.
Oracle is diagnostic only, never used to choose blind candidates.

Place beside previous research scripts in tools/. Requires scipy and reedsolo.
"""
import argparse,csv,hashlib,sys,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reedsolo import RSCodec
import dwt_probe as dwt
from feedback_50photos_validation import feedback_embed,prepare
from fourier_dualband_validation import embed_multiband,attack,BANDS
from fourier_multipeak_fair_benchmark import peak_candidates
from fourier_blind_hybrid_benchmark import candidate_sizes
from fourier_rs_full50_priority import check

FIELDS=['file','group','scale_pct','jpeg','strategy','width','height','received_width',
        'received_height','psnr_db','jpeg85_ok','oracle_ok','blind_ok','attempts',
        'found_width','found_height','found_peak_rank','peak1_scale','peak1_score',
        'peak1_error_pp','nearest_peak_error_pp','nearest_peak_rank',
        'peak_count','candidate_count','candidate_contains_oracle',
        'peak_ms','search_ms','error']

def select_peaks(peaks,mode,args):
    if mode!='diverse50':return peaks[:args.max_peaks]
    # Greedy selection from all peaks: high scores plus scale separation.
    # Penalize close duplicates, not their absolute scale. No oracle data.
    selected=[]
    pool=peaks[:]
    if pool:selected.append(pool.pop(0))
    while pool and len(selected)<args.max_peaks:
        lo=min(x[1] for x in peaks)
        hi=max(x[1] for x in peaks)
        def value(p):
            confidence=(p[1]-lo)/(hi-lo+1e-12)
            distance=min(abs(p[0]-q[0]) for q in selected)
            diversity=min(distance/.04,1.0)
            return .65*confidence+.35*diversity
        best=max(range(len(pool)),key=lambda i:value(pool[i]))
        selected.append(pool.pop(best))
    return selected

def make_candidates(received_size,peaks,mode,args):
    streams=[iter(candidate_sizes(received_size,p[0],args.search_pp,args.max_candidates))
             for p in peaks]
    seen=set();result=[]
    def take(stream,rank):
        while True:
            try:size=next(stream)
            except StopIteration:return False
            if size in seen:continue
            seen.add(size);result.append((size,rank))
            return True
    def first(rank,count):
        if rank>=len(streams):return
        for _ in range(count):
            if len(result)>=args.max_candidates or not take(streams[rank],rank+1):break
    if mode in ('priority50','diverse50'):first(0,50)
    elif mode=='priority25':first(0,25)
    elif mode=='confidence50':
        # Strongest peak first; remaining 110 attempts allocated proportionally
        # to score-based weights (rather than pure round robin).
        first(0,50)
    if mode=='confidence50':
        scores=np.array([p[1] for p in peaks],dtype=float)
        if len(scores):
            z=(scores-scores.max())/max(scores.std(),1e-5)
            weights=np.exp(np.clip(z,-20,0))
            weights=weights/weights.sum()
            credit=np.zeros(len(peaks))
            while len(result)<args.max_candidates:
                credit+=weights
                progress=False
                for rank in np.argsort(-credit):
                    if take(streams[rank],int(rank)+1):
                        credit[rank]-=1;progress=True;break
                    credit[rank]=-1e12
                if not progress:break
    else:
        active=list(range(len(streams)))
        while active and len(result)<args.max_candidates:
            next_active=[]
            for rank in active:
                if take(streams[rank],rank+1):next_active.append(rank)
                if len(result)>=args.max_candidates:break
            active=next_active
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_peak_search_strategy.csv'))
    ap.add_argument('--all',action='store_true',help='All JPEGs instead of small+controls')
    ap.add_argument('--small-max',type=int,default=750)
    ap.add_argument('--controls',type=int,default=8)
    ap.add_argument('--strategies',default='priority50,priority25,round_robin,diverse50,confidence50')
    ap.add_argument('--scales',default='100,90,75')
    ap.add_argument('--jpeg',default='none,60')
    ap.add_argument('--longest',type=int,default=1280)
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
    args=ap.parse_args()
    strategies=[x.strip() for x in args.strategies.split(',')]
    valid={'priority50','priority25','round_robin','diverse50','confidence50'}
    if not strategies or any(s not in valid for s in strategies):ap.error('Invalid strategies')
    if args.max_candidates<50 or args.max_peaks<1 or args.step<=0 or args.repeat%2!=1:
        ap.error('Invalid search/QIM parameters')
    if not args.directory.is_dir():ap.error('Missing image directory')
    scales=[float(x)/100 for x in args.scales.split(',')]
    qualities=[None if x.strip().lower()=='none' else int(x) for x in args.jpeg.split(',')]
    small=[];large=[]
    for path in sorted(args.directory.iterdir()):
        if path.suffix.lower() not in ('.jpg','.jpeg') or not path.is_file():continue
        try:
            with Image.open(path) as im:
                size=ImageOps.exif_transpose(im).size
            (small if min(max(size),args.longest)<=args.small_max else large).append(path)
        except Exception as exc:print('SKIP',path.name,exc,flush=True)
    controls=sorted(large,key=lambda p:hashlib.sha256(p.name.encode()).hexdigest())[:args.controls]
    selected=sorted(small+large if args.all else small+controls)
    if not selected:ap.error('No images')
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    encoded=bytes(RSCodec(8).encode(msg))
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    print(f'{len(selected)} images, {len(strategies)} strategies, '
          f'{len(selected)*len(strategies)*len(scales)*len(qualities)} rows',flush=True)
    with args.csv.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader()
        for idx,path in enumerate(selected,1):
            print(f'[{idx}/{len(selected)}] {path.name}',flush=True)
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
                pilot=embed_multiband(base,BANDS['baseline'])
                marked,*_=feedback_embed(pilot,encoded,args.delta,args.repeat,args.seed,
                                          args.feedback_iterations)
                saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                psnr=round(dwt.psnr(base,saved),5)
                saved_ok=int(check(saved,base.size,msg,encoded,8,args)[0])
                error=''
            except Exception as exc:
                base=saved=None;psnr='';saved_ok=0
                error=f'{type(exc).__name__}: {exc}'
            for scale in scales:
                for quality in qualities:
                    if saved is not None:
                        try:
                            received=attack(saved,scale,quality)
                            oracle=int(check(received,base.size,msg,encoded,8,args)[0])
                            t=time.perf_counter()
                            peaks=peak_candidates(received,BANDS['baseline'][0],args)
                            peak_ms=round((time.perf_counter()-t)*1000,3)
                            attack_error=''
                        except Exception as exc:
                            received=None;peaks=[];oracle=''
                            peak_ms='';attack_error=f'{type(exc).__name__}: {exc}'
                    else:
                        received=None;peaks=[];oracle=''
                        peak_ms='';attack_error=error
                    for strategy in strategies:
                        row={k:'' for k in FIELDS}
                        row.update(file=path.name,
                            group='small' if path in small else 'control',
                            scale_pct=round(scale*100,3),
                            jpeg='none' if quality is None else quality,
                            strategy=strategy,width=base.width if base else '',
                            height=base.height if base else '',
                            received_width=received.width if received else '',
                            received_height=received.height if received else '',
                            psnr_db=psnr,jpeg85_ok=saved_ok,oracle_ok=oracle,
                            peak_ms=peak_ms,error=attack_error)
                        if received is not None:
                            chosen=select_peaks(peaks,strategy,args)
                            nearest=min(range(len(chosen)),key=lambda i:abs(chosen[i][0]-scale)) if chosen else None
                            row.update(peak_count=len(chosen),
                                peak1_scale=round(chosen[0][0],6) if chosen else '',
                                peak1_score=round(chosen[0][1],6) if chosen else '',
                                peak1_error_pp=round(abs(chosen[0][0]-scale)*100,4) if chosen else '',
                                nearest_peak_error_pp=round(abs(chosen[nearest][0]-scale)*100,4) if nearest is not None else '',
                                nearest_peak_rank=nearest+1 if nearest is not None else '')
                            t=time.perf_counter()
                            candidates=make_candidates(received.size,chosen,strategy,args)
                            row['candidate_count']=len(candidates)
                            row['candidate_contains_oracle']=int(base.size in {s for s,_ in candidates})
                            found=None;rank=None;attempts=0
                            for size,peak_rank in candidates:
                                attempts+=1
                                if check(received,size,msg,encoded,8,args)[0]:
                                    found=size;rank=peak_rank;break
                            row.update(blind_ok=int(found is not None),attempts=attempts,
                                       found_width=found[0] if found else '',
                                       found_height=found[1] if found else '',
                                       found_peak_rank=rank if rank else '',
                                       search_ms=round((time.perf_counter()-t)*1000,3))
                        writer.writerow(row);out.flush()
                        print(f"  {scale*100:g}% JPEG={row['jpeg']} {strategy}: "
                              f"blind={row['blind_ok']} oracle={oracle} "
                              f"attempts={row['attempts']} {row['error']}",flush=True)
    print('Saved:',args.csv,flush=True)

if __name__=='__main__':main()
