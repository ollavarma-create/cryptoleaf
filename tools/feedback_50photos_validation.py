#!/usr/bin/env python3
"""50-photo paired baseline vs feedback-QIM validation (research only).

Place in Cryptoleaf/tools/ beside dwt_probe.py, fourier_blind_pilot.py,
 and fourier_blind_hybrid_benchmark.py.

Both methods receive the SAME image, pilot, payload and attacks.
Pilot is inserted before DWT in both arms. Blind decoder does not know
original size; oracle is a separate diagnostic. Output CSV is incremental.
Feedback-QIM uses original frozen QIM parity, with post-RGB iterative correction.
"""
import argparse
import csv
import hashlib
import sys
import zlib
from pathlib import Path
from collections import defaultdict
import numpy as np
import pywt
from PIL import Image, ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parent))
import dwt_probe as dwt
import fourier_blind_pilot as fm
from fourier_blind_hybrid_benchmark import blind_extract

def make_message(n, seed):
    return np.random.default_rng(seed).integers(0,256,n,dtype=np.uint8).tobytes()


def packet_bits(message):
    packet = dwt.MAGIC + len(message).to_bytes(2,'big') + message
    packet += zlib.crc32(packet).to_bytes(4,'big')
    return np.unpackbits(np.frombuffer(packet,dtype=np.uint8))


def ycc(img):
    return np.asarray(img.convert('YCbCr'),dtype=np.float64).copy()


def from_ycc(a):
    return Image.fromarray(np.uint8(np.clip(np.rint(a),0,255)),'YCbCr').convert('RGB')


def headroom(img, margin):
    a=ycc(img)
    a[:,:,0] = margin + a[:,:,0]*(255-2*margin)/255
    return from_ycc(a)


def expand_headroom(img, margin):
    a=ycc(img)
    a[:,:,0] = (a[:,:,0]-margin)*255/(255-2*margin)
    return from_ycc(a)


def qim_setup(img,message,delta,repeat,seed):
    a=ycc(img)
    coeffs=pywt.wavedec2(a[:,:,0], 'haar',level=2,mode='periodization')
    ll=coeffs[0].copy()
    flat=ll.ravel()
    bits=packet_bits(message)
    count=len(bits)*repeat
    if count>flat.size:
        raise ValueError(f'Insufficient capacity: need {count}, have {flat.size}')
    pos=np.random.default_rng(seed).permutation(flat.size)[:count]
    target=np.repeat(bits,repeat).astype(np.int64)
    q=np.rint(flat[pos]/delta).astype(np.int64)
    # EXACT original QIM lattice, including its one-sided parity correction
    q += (target-(q&1))%2
    return a,coeffs,ll,flat,pos,target,q


def render(a,coeffs,ll,flat,pos,q,delta):
    flat[pos]=q*delta
    coeffs[0]=ll
    unbounded=pywt.waverec2(coeffs,'haar',mode='periodization')[:a.shape[0],:a.shape[1]]
    low=float(np.mean(unbounded<0)*100)
    high=float(np.mean(unbounded>255)*100)
    out=a.copy()
    out[:,:,0]=np.clip(unbounded,0,255)
    return from_ycc(out),low,high


def observed_bits(img,pos,delta):
    recovered=pywt.wavedec2(ycc(img)[:,:,0],'haar',level=2,mode='periodization')[0].ravel()
    return np.rint(recovered[pos]/delta).astype(np.int64)&1


def header_ber(img,message,delta,repeat,seed):
    bits=packet_bits(message)
    count=len(bits)*repeat
    yy=pywt.wavedec2(ycc(img)[:,:,0],'haar',level=2,mode='periodization')[0].ravel()
    pos=np.random.default_rng(seed).permutation(yy.size)[:count]
    observed=np.rint(yy[pos[:48*repeat]]/delta).astype(np.int64)&1
    majority=(observed.reshape(-1,repeat).sum(axis=1)>repeat//2).astype(np.uint8)
    return float(np.mean(majority != bits[:48])*100)


def feedback_embed(img,message,delta,repeat,seed,max_iter):
    a,coeffs,ll,flat,pos,target,q=qim_setup(img,message,delta,repeat,seed)
    initial_wrong=None
    # Move erroneous coefficient by +/- 2 quantization levels, maintaining parity.
    # For bright images, favor decreasing LL2 coefficient to avoid high clipping.
    # Updates are vectorized. Each iteration evaluates the ACTUAL RGB round-trip.
    for iteration in range(max_iter+1):
        result,low,high=render(a,coeffs,ll,flat,pos,q,delta)
        observed=observed_bits(result,pos,delta)
        bad=observed!=target
        wrong=int(bad.sum())
        if initial_wrong is None: initial_wrong=wrong
        if wrong==0 or iteration==max_iter:
            return result,low,high,iteration,initial_wrong,wrong
        # Lower QIM level for bright carriers, shifting away from clipping.
        # Even jumps preserve target parity; errors can persist or oscillate.
        q[bad]-=2
    raise RuntimeError('unreachable')



def files_in(root, recursive):
    return sorted(p for p in root.glob('**/*' if recursive else '*')
                  if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg'))

def prepare(img,longest):
    w,h=img.size
    s=min(1.,longest/max(w,h))
    if s<1: img=img.resize((max(32,round(w*s)),max(32,round(h*s))),Image.Resampling.LANCZOS)
    return img

FIELDS=['file','sha256_12','source_width','source_height','width','height',
        'method','true_percent','jpeg_quality','estimated_percent','scale_error_pp',
        'pilot_score','score_z','attempts','found_width','found_height',
        'raw_pass','saved85_pass','oracle_pass','blind_pass','psnr_db',
        'feedback_iterations','wrong_bits_initial','wrong_bits_final',
        'clip_y_low_pct','clip_y_high_pct','error']

def checked(img,sz,msg,args):
    try:
        return int(dwt.extract(img,sz,args.delta,args.repeat,args.seed,args.max_bytes)==msg)
    except ValueError:
        return 0

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--csv',type=Path,default=Path('feedback_50photos.csv'))
    p.add_argument('--recursive',action='store_true')
    p.add_argument('--longest',type=int,default=1280)
    p.add_argument('--scales',default='100,90,75')
    p.add_argument('--jpeg',default='none,60')
    p.add_argument('--strength',type=float,default=.18)
    p.add_argument('--bytes',type=int,default=50)
    p.add_argument('--delta',type=float,default=32)
    p.add_argument('--repeat',type=int,default=9)
    p.add_argument('--seed',type=int,default=20261114)
    p.add_argument('--save-quality',type=int,default=85)
    p.add_argument('--max-bytes',type=int,default=256)
    p.add_argument('--feedback-iterations',type=int,default=6)
    p.add_argument('--low-scale',type=float,default=.70)
    p.add_argument('--high-scale',type=float,default=1.02)
    p.add_argument('--step',type=float,default=.002)
    p.add_argument('--search-pp',type=float,default=1.0)
    p.add_argument('--max-candidates',type=int,default=160)
    a=p.parse_args()
    if not a.directory.is_dir():p.error('Directory not found')
    if a.longest<128 or not 1<=a.bytes<=a.max_bytes<=65535:p.error('Invalid size or bytes')
    if a.repeat<1 or a.repeat%2!=1 or a.delta<=0 or a.feedback_iterations<0:p.error('Invalid QIM parameters')
    if a.max_candidates<1 or a.search_pp<=0 or a.step<=0 or a.high_scale<=a.low_scale:p.error('Invalid scale search')
    scales=[float(s)/100 for s in a.scales.split(',')]
    qualities=[None if s.strip().lower()=='none' else int(s) for s in a.jpeg.split(',')]
    if not scales or any(not a.low_scale<=s<=a.high_scale for s in scales):p.error('Invalid scales')
    if not qualities or any(q is not None and not 1<=q<=100 for q in qualities):p.error('Invalid JPEG qualities')
    files=files_in(a.directory,a.recursive)
    if not files:p.error('No JPEG images')
    msg=make_message(a.bytes,a.seed)
    a.csv.parent.mkdir(parents=True,exist_ok=True)
    totals=defaultdict(lambda: [0,0,0,0])
    with a.csv.open('w',newline='',encoding='utf-8') as f:
        wr=csv.DictWriter(f,fieldnames=FIELDS);wr.writeheader()
        for i,path in enumerate(files,1):
            name=str(path.relative_to(a.directory))
            digest=hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            try:
                with Image.open(path) as im:
                    source=ImageOps.exif_transpose(im).convert('RGB')
                source_size=source.size
                base=prepare(source,a.longest)
            except Exception as exc:
                print(f'[{i}/{len(files)}] ERROR {name}: {exc}',flush=True)
                continue
            print(f'[{i}/{len(files)}] {name} {source_size}->{base.size}',flush=True)
            for method in ('baseline','feedback_qim'):
                info={}; error=''; marked=None;saved=None
                try:
                    pre=fm.embed(base,a.strength)
                    if method=='baseline':
                        marked=dwt.embed(pre,msg,a.delta,a.repeat,a.seed)
                    else:
                        marked,low,high,iters,w0,w1=feedback_embed(pre,msg,a.delta,a.repeat,a.seed,a.feedback_iterations)
                        info=dict(clip_y_low_pct=round(low,4),clip_y_high_pct=round(high,4),
                                  feedback_iterations=iters,wrong_bits_initial=w0,wrong_bits_final=w1)
                    raw_pass=checked(marked,base.size,msg,a)
                    saved=dwt.jpeg_roundtrip(marked,a.save_quality)
                    saved85_pass=checked(saved,base.size,msg,a)
                    quality=round(dwt.psnr(base,saved),3)
                except Exception as exc:
                    error=f'Embed:{type(exc).__name__}:{exc}'
                    raw_pass=0;saved85_pass=0;quality=''
                for scale in scales:
                    for jpeg in qualities:
                        row=dict(file=name,sha256_12=digest,source_width=source_size[0],
                                 source_height=source_size[1],width=base.width,height=base.height,
                                 method=method,true_percent=round(scale*100,3),
                                 jpeg_quality='none' if jpeg is None else jpeg,
                                 raw_pass=raw_pass,saved85_pass=saved85_pass,
                                 oracle_pass=0,blind_pass=0,attempts=0,psnr_db=quality,error=error,**info)
                        if saved is not None:
                            received=saved.resize((max(32,round(base.width*scale)),
                                                   max(32,round(base.height*scale))),Image.Resampling.LANCZOS)
                            if jpeg is not None:received=dwt.jpeg_roundtrip(received,jpeg)
                            row['oracle_pass']=checked(received,base.size,msg,a)
                            try:
                                est,score,median,std,attempts,found,payload=blind_extract(received,a)
                                row.update(estimated_percent=round(est*100,3),
                                           scale_error_pp=round(abs(est-scale)*100,3),
                                           pilot_score=round(score,6),
                                           score_z=round((score-median)/max(std,1e-12),3),
                                           attempts=attempts,
                                           found_width=found[0] if found else '',
                                           found_height=found[1] if found else '',
                                           blind_pass=int(payload==msg))
                            except Exception as exc:
                                row['error']+=f' Blind:{type(exc).__name__}:{exc}'
                        wr.writerow(row);f.flush()
                        t=totals[method];t[0]+=1;t[1]+=row['blind_pass'];t[2]+=row['oracle_pass'];t[3]+=row['saved85_pass']
                        print(f'  {method:12} {scale*100:3g}% jpeg={str(jpeg):>4} '
                              f'blind={row["blind_pass"]} oracle={row["oracle_pass"]} '
                              f'raw={raw_pass} saved85={saved85_pass} '
                              f'wrong={info.get("wrong_bits_final","-")}',flush=True)
    print('\nSUMMARY method: blind / oracle / saved85 (saved85 is repeated across attack rows)')
    for method,(n,blind,oracle,saved) in totals.items():
        print(f'{method}: blind {blind}/{n}; oracle {oracle}/{n}; saved85 {saved}/{n}')
    print('CSV:',a.csv)
    print('NOTE: pilot always ON; no-pilot control is intentionally omitted to focus on paired DWT comparison.')

if __name__=='__main__':main()
