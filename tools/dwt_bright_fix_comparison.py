#!/usr/bin/env python3
"""Research: compare reversible-looking headroom restoration and feedback QIM.

Run from Cryptoleaf project after placing in tools/ next to dwt_probe.py:
 python tools/dwt_bright_fix_comparison.py /home/jari/Pictures/DWTFourierTesti/P1010892.JPG --csv dwt_bright_fix.csv

Uses the frozen DWT1 format, seed, Haar LL2, delta=32, repeat=9.
Headroom is applied to the visible carrier, then optionally expanded AFTER embed.
The latter is an intentionally difficult control, not a lossless inverse.
Feedback-QIM modifies the coefficient lattice based on measured post-RGB errors.
This is experimental, NOT a production codec. No pilot is used here.
"""
import argparse
import csv
import sys
import zlib
from pathlib import Path

import numpy as np
import pywt
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt

FIELDS = ['method','length','delta','repeat','raw_pass','jpeg85_pass','jpeg60_pass',
          'raw_error','jpeg85_error','jpeg60_error','psnr_raw_vs_source',
          'psnr_jpeg85_vs_source','psnr_jpeg60_vs_source',
          'clip_y_low_pct','clip_y_high_pct','header_ber_pct',
          'feedback_iterations','wrong_bits_initial','wrong_bits_final','note']


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


def check(img,size,message,delta,repeat,seed):
    try:
        found=dwt.extract(img,size,delta,repeat,seed,max_bytes=max(256,len(message)))
        return int(found==message), '' if found==message else 'MessageMismatch'
    except Exception as exc:
        return 0, f'{type(exc).__name__}:{exc}'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('dwt_bright_fix.csv'))
    ap.add_argument('--lengths',default='10,25,50')
    ap.add_argument('--deltas',default='32')
    ap.add_argument('--margins',default='16,32')
    ap.add_argument('--repeat',type=int,default=9)
    ap.add_argument('--seed',type=int,default=20261114)
    ap.add_argument('--feedback-iterations',type=int,default=6)
    args=ap.parse_args()
    if args.repeat<1 or args.repeat%2==0:ap.error('repeat must be odd positive')
    if args.feedback_iterations<0:ap.error('feedback iterations must be nonnegative')
    lengths=[int(x) for x in args.lengths.split(',')]
    deltas=[float(x) for x in args.deltas.split(',')]
    margins=[int(x) for x in args.margins.split(',')]
    if any(x<1 for x in lengths) or any(x<=0 for x in deltas) or any(x<=0 or x>=127 for x in margins):
        ap.error('invalid lengths/deltas/margins')
    with Image.open(args.image) as im:
        source=ImageOps.exif_transpose(im).convert('RGB')
    methods=['baseline']
    for m in margins:
        methods.extend([f'headroom{m}',f'headroom{m}_expand_after'])
    methods.append('feedback_qim')
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader()
        for length in lengths:
            message=make_message(length,args.seed)
            for delta in deltas:
                for method in methods:
                    row=dict(method=method,length=length,delta=delta,repeat=args.repeat,
                             raw_pass=0,jpeg85_pass=0,jpeg60_pass=0)
                    try:
                        margin=next((m for m in margins if method.startswith(f'headroom{m}')),None)
                        carrier=headroom(source,margin) if margin is not None else source
                        if method=='feedback_qim':
                            marked,low,high,iters,wrong0,wrong1=feedback_embed(
                                source,message,delta,args.repeat,args.seed,args.feedback_iterations)
                            row.update(feedback_iterations=iters,wrong_bits_initial=wrong0,
                                       wrong_bits_final=wrong1)
                            row['note']='Feedback uses post-RGB parity; original cover retained.'
                        else:
                            a,coeffs,ll,flat,pos,target,q=qim_setup(
                                carrier,message,delta,args.repeat,args.seed)
                            marked,low,high=render(a,coeffs,ll,flat,pos,q,delta)
                            if method.endswith('_expand_after'):
                                marked=expand_headroom(marked,margin)
                                row['note']='Post-embed expansion can destroy QIM; diagnostic control.'
                            elif margin is not None:
                                row['note']='Visible headroom applied; not restored.'
                            else:
                                row['note']='Original unmodified DWT baseline.'
                        row['clip_y_low_pct']=round(low,4)
                        row['clip_y_high_pct']=round(high,4)
                        row['header_ber_pct']=round(header_ber(marked,message,delta,args.repeat,args.seed),3)
                        row['psnr_raw_vs_source']=round(dwt.psnr(source,marked),3)
                        row['raw_pass'],row['raw_error']=check(marked,source.size,message,delta,args.repeat,args.seed)
                        for quality in (85,60):
                            compressed=dwt.jpeg_roundtrip(marked,quality)
                            row[f'jpeg{quality}_pass'],row[f'jpeg{quality}_error']=check(
                                compressed,source.size,message,delta,args.repeat,args.seed)
                            row[f'psnr_jpeg{quality}_vs_source']=round(dwt.psnr(source,compressed),3)
                    except Exception as exc:
                        row['raw_error']=f'{type(exc).__name__}:{exc}'
                    writer.writerow(row)
                    f.flush()
                    print(f'{method:26} {length:2}B delta={delta:g} '
                          f'RAW={row["raw_pass"]} J85={row["jpeg85_pass"]} J60={row["jpeg60_pass"]} '
                          f'PSNR={row.get("psnr_jpeg85_vs_source","-")} '
                          f'BER={row.get("header_ber_pct","-")} '
                          f'wrong={row.get("wrong_bits_final","-")}',flush=True)
    print('Saved:',args.csv)
    print('WARNING: no Fourier pilot or scaling here. Headroom expansion is not lossless.')

if __name__=='__main__':main()
