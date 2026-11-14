#!/usr/bin/env python3
"""Research-only Fourier pilot sweep with paired baseline and held-out evaluation.

Place next to dwt_probe.py, fourier_blind_pilot.py,
feedback_50photos_validation.py and fourier_blind_hybrid_benchmark.py.

Stage 1: compare frequency bands / strengths on the same images, with a
fixed DWT-QIM payload and attacks. Pilot scale estimate is measured on all
cases, while blind decoding is run only for the winning configuration and
original baseline, avoiding an enormous exhaustive search.

IMPORTANT: The current radial pilot uses a global 32-ring template. Changing
fm.RADII and fm.RING_SIGMA changes both embedding and detection. Never use
these parameters for production without protocol/version signaling.
"""
import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from feedback_50photos_validation import feedback_embed, prepare
from fourier_blind_hybrid_benchmark import blind_extract

SWEEP_FIELDS = ['file','split','width','height','config','band_low','band_high',
                'sigma','strength','scale_pct','jpeg','estimated_pct','error_pp',
                'score','score_z','within_1pp','within_2pp','oracle_pass',
                'raw_pass','saved85_pass','psnr_db','feedback_iterations',
                'feedback_wrong_final','error']
BLIND_FIELDS = ['file','split','config','scale_pct','jpeg','estimated_pct',
                'error_pp','attempts','blind_pass','oracle_pass','error']

def parse_configs(spec):
    """Syntax: label:low:high:sigma:strength;..."""
    result=[]
    for entry in spec.split(';'):
        if not entry.strip(): continue
        fields=entry.strip().split(':')
        if len(fields)!=5: raise ValueError('Each config must be name:low:high:sigma:strength')
        name=fields[0]
        lo,hi,sigma,strength=map(float,fields[1:])
        if not (0<lo<hi<0.38 and sigma>0 and strength>0):
            raise ValueError(f'Invalid config {name}')
        if name in [c['name'] for c in result]:raise ValueError(f'Duplicate name {name}')
        result.append(dict(name=name,low=lo,high=hi,sigma=sigma,strength=strength))
    if not result:raise ValueError('No configurations')
    return result

def activate(cfg):
    fm.RADII=np.linspace(cfg['low'],cfg['high'],32)
    fm.RING_SIGMA=cfg['sigma']

def get_files(folder):
    return sorted(x for x in folder.iterdir() if x.is_file() and x.suffix.lower() in ('.jpg','.jpeg'))

def passed(img, original_size, msg, args):
    try:return int(dwt.extract(img,original_size,args.delta,args.repeat,args.seed,args.max_bytes)==msg)
    except ValueError:return 0

def receive(img, scale, jpeg):
    size=(max(32,round(img.width*scale)),max(32,round(img.height*scale)))
    out=img.resize(size,Image.Resampling.LANCZOS) if img.size!=size else img
    return dwt.jpeg_roundtrip(out,jpeg) if jpeg is not None else out

def run_case(base,cfg,msg,args):
    activate(cfg)
    pre=fm.embed(base,cfg['strength'])
    marked,_,_,iters,_,wrong=feedback_embed(pre,msg,args.delta,args.repeat,args.seed,args.feedback_iterations)
    raw=passed(marked,base.size,msg,args)
    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
    savedpass=passed(saved,base.size,msg,args)
    quality=dwt.psnr(base,saved)
    return saved,raw,savedpass,quality,iters,wrong

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_pilot_sweep_50.csv'))
    ap.add_argument('--blind-csv',type=Path,default=Path('fourier_pilot_sweep_blind.csv'))
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
    ap.add_argument('--skip-blind',action='store_true',help='Only pilot-scale sweep; skip blind validation')
    ap.add_argument('--configs',default=(
        'baseline:0.055:0.195:0.00085:0.18;'
        'low:0.030:0.130:0.00085:0.18;'
        'mid:0.080:0.220:0.00085:0.18;'
        'wide:0.040:0.240:0.00085:0.18;'
        'baseline_strong:0.055:0.195:0.00085:0.27;'
        'low_strong:0.030:0.130:0.00085:0.27'))
    a=ap.parse_args()
    if not a.directory.is_dir():ap.error('Directory not found')
    if not 0<a.holdout<1 or a.repeat<1 or a.repeat%2==0 or a.delta<=0:ap.error('Invalid holdout or QIM settings')
    if not 0<a.bytes<=a.max_bytes or a.longest<128:ap.error('Invalid size')
    if a.low_scale>=a.high_scale or a.step<=0 or a.max_candidates<1:ap.error('Invalid scale search')
    try:
        configs=parse_configs(a.configs)
        scales=[float(v)/100 for v in a.scales.split(',')]
        qualities=[None if v.strip()=='none' else int(v) for v in a.jpeg.split(',')]
        if not scales or not qualities or any(not a.low_scale<=s<=a.high_scale for s in scales):raise ValueError('Invalid attacks')
        if any(q is not None and not 1<=q<=100 for q in qualities):raise ValueError('Invalid JPEG')
    except ValueError as exc:ap.error(str(exc))
    files=get_files(a.directory)
    if not files:ap.error('No JPEG files')
    msg=np.random.default_rng(a.seed).integers(0,256,a.bytes,dtype=np.uint8).tobytes()
    # Stable image split: selection on train only; holdout never selects winner.
    split={p: ('holdout' if int(hashlib.sha256(p.name.encode()).hexdigest()[:8],16)/0xffffffff<a.holdout else 'train') for p in files}
    if not any(v=='train' for v in split.values()) or not any(v=='holdout' for v in split.values()):ap.error('Train/holdout split empty')
    a.csv.parent.mkdir(parents=True,exist_ok=True)
    a.blind_csv.parent.mkdir(parents=True,exist_ok=True)
    scores=defaultdict(lambda:[0,0,0.,0,0])
    print(f'{len(files)} photos, {len(configs)} configs, {len(scales)*len(qualities)} attacks, '
          f'{sum(v=="train" for v in split.values())} train / {sum(v=="holdout" for v in split.values())} holdout',flush=True)
    with a.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=SWEEP_FIELDS);writer.writeheader()
        for i,p in enumerate(files,1):
            try:
                with Image.open(p) as im:base=prepare(ImageOps.exif_transpose(im).convert('RGB'),a.longest)
            except Exception as exc:
                print(f'[{i}/{len(files)}] OPEN ERROR {p.name}: {exc}',flush=True);continue
            print(f'[{i}/{len(files)}] {p.name} {base.size} ({split[p]})',flush=True)
            for cfg in configs:
                error=''; saved=None;raw=savedpass=0;psnr=iters=wrong=''
                try:saved,raw,savedpass,psnr,iters,wrong=run_case(base,cfg,msg,a)
                except Exception as exc:error=f'{type(exc).__name__}:{exc}'
                for scale in scales:
                    for jq in qualities:
                        row=dict(file=p.name,split=split[p],width=base.width,height=base.height,
                                 config=cfg['name'],band_low=cfg['low'],band_high=cfg['high'],
                                 sigma=cfg['sigma'],strength=cfg['strength'],scale_pct=scale*100,
                                 jpeg='none' if jq is None else jq,estimated_pct='',error_pp='',
                                 score='',score_z='',within_1pp=0,within_2pp=0,oracle_pass=0,
                                 raw_pass=raw,saved85_pass=savedpass,psnr_db=psnr,
                                 feedback_iterations=iters,feedback_wrong_final=wrong,error=error)
                        if saved is not None:
                            try:
                                attacked=receive(saved,scale,jq)
                                est,sc,med,std=fm.estimate_scale(attacked,a.low_scale,a.high_scale,a.step)
                                err=abs(est-scale)*100
                                row.update(estimated_pct=round(est*100,3),error_pp=round(err,3),
                                           score=round(sc,6),score_z=round((sc-med)/max(std,1e-12),3),
                                           within_1pp=int(err<=1),within_2pp=int(err<=2),
                                           oracle_pass=passed(attacked,base.size,msg,a))
                            except Exception as exc:row['error']+=f' Estimate:{type(exc).__name__}:{exc}'
                        writer.writerow(row);f.flush()
                        if row['error']=='':
                            s=scores[(split[p],cfg['name'])];s[0]+=1;s[1]+=row['within_1pp'];s[2]+=row['error_pp'];s[3]+=row['oracle_pass'];s[4]+=row['within_2pp']
                print(f'  {cfg["name"]}: completed',flush=True)
    # Winner selection: prioritize 1pp accuracy; use mean absolute scale error to break ties.
    def rank(cfg):
        n,ok,total,oracle,_=scores[('train',cfg['name'])]
        return (ok/n if n else -1, -total/n if n else -1e6, oracle/n if n else -1)
    winner=max(configs,key=rank)
    chosen=[next((c for c in configs if c['name']=='baseline'),configs[0])]
    if winner['name']!=chosen[0]['name']:chosen.append(winner)
    print('\nPILOT RESULTS (training data only used for selection):')
    for cfg in configs:
        for part in ('train','holdout'):
            n,ok,total,oracle,ok2=scores[(part,cfg['name'])]
            print(f' {cfg["name"]:18} {part:7}: <=1pp {ok}/{n}, <=2pp {ok2}/{n}, '
                  f'MAE {total/n if n else float("nan"):.3f}pp, oracle {oracle}/{n}')
    print('TRAIN winner:',winner['name'])
    if a.skip_blind:
        print('Blind stage skipped. CSV:',a.csv);return
    # Run blind only on the held-out photos and baseline vs selected winner.
    # Re-embedding is intentional; no original size supplied to blind decoder.
    print('\nBLIND HOLDOUT: ', ', '.join(c['name'] for c in chosen),flush=True)
    with a.blind_csv.open('w',newline='',encoding='utf-8') as f:
        wr=csv.DictWriter(f,fieldnames=BLIND_FIELDS);wr.writeheader()
        for i,p in enumerate(files,1):
            if split[p]!='holdout':continue
            try:
                with Image.open(p) as im:base=prepare(ImageOps.exif_transpose(im).convert('RGB'),a.longest)
            except Exception as exc:print('OPEN ERROR',p.name,exc,flush=True);continue
            for cfg in chosen:
                activate(cfg)
                try:saved,*_=run_case(base,cfg,msg,a)
                except Exception as exc:
                    print('EMBED ERROR',p.name,cfg['name'],exc,flush=True);continue
                for scale in scales:
                    for jq in qualities:
                        row=dict(file=p.name,split='holdout',config=cfg['name'],scale_pct=scale*100,
                                 jpeg='none' if jq is None else jq,estimated_pct='',error_pp='',
                                 attempts=0,blind_pass=0,oracle_pass=0,error='')
                        try:
                            attacked=receive(saved,scale,jq)
                            row['oracle_pass']=passed(attacked,base.size,msg,a)
                            est,sc,med,std,attempts,found,payload=blind_extract(attacked,a)
                            row.update(estimated_pct=round(est*100,3),error_pp=round(abs(est-scale)*100,3),
                                       attempts=attempts,blind_pass=int(payload==msg))
                        except Exception as exc:row['error']=f'{type(exc).__name__}:{exc}'
                        wr.writerow(row);f.flush()
                print(f' {p.name} / {cfg["name"]} complete',flush=True)
    print('Finished:',a.csv,'and',a.blind_csv)
    print('WARNING: winner chosen using same training images; holdout measures generalization.')

if __name__=='__main__':main()
