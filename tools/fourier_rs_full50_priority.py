#!/usr/bin/env python3
"""Cryptoleaf research: paired full-50-image RS0/RS8/RS16 Priority50 blind test.

One-band Fourier pilot, Feedback-QIM, JPEG85 save, 100/90/75% scales,
no additional JPEG / JPEG60, 160 global DWT candidate attempts.
RS0 is the unchanged legacy packet; RS8/RS16 use an RS-coded payload INSIDE
that packet. For RS variants, read raw DWT majority bits even when the outer
packet CRC fails, then apply RS and validate exact 50-byte message. This is a
research decoder, not a proposed production format.
"""
import argparse
import csv
import hashlib
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pywt
from PIL import Image, ImageOps
try:
    from reedsolo import RSCodec, ReedSolomonError
except ImportError:
    raise SystemExit('Install reedsolo: python -m pip install reedsolo')

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
from feedback_50photos_validation import feedback_embed, prepare
from fourier_dualband_validation import embed_multiband, attack, BANDS
from fourier_blind_hybrid_benchmark import candidate_sizes
from fourier_multipeak_fair_benchmark import select_peaks

FIELDS=['file','split','scale_pct','jpeg','rs_parity','original_width','original_height',
        'received_width','received_height','encoded_bytes','psnr_db','capacity_ok',
        'embedded_ok','jpeg85_ok','oracle_ok','blind_ok','attempts','elapsed_ms',
        'peak_ms','found_width','found_height','oracle_byte_errors_before_rs',
        'oracle_bit_errors_before_rs','error']


def raw_payload(image, size, nbytes, args):
    """Read DWT majority vote without requiring MAGIC or CRC to be valid."""
    if image.size != size:
        image=image.resize(size,Image.Resampling.LANCZOS)
    y=np.asarray(image.convert('YCbCr'),dtype=np.float64)[:,:,0]
    ll=pywt.wavedec2(y,'haar',level=2,mode='periodization')[0].ravel()
    count=(nbytes+10)*8*args.repeat
    if count>ll.size:
        raise ValueError('DWT capacity too small')
    positions=np.random.default_rng(args.seed).permutation(ll.size)[:count]
    q=np.rint(ll[positions]/args.delta).astype(np.int64)&1
    bits=(q.reshape(-1,args.repeat).sum(axis=1)>args.repeat//2).astype(np.uint8)
    packet=np.packbits(bits).tobytes()
    return packet[6:6+nbytes],packet


def check(image,size,msg,encoded,parity,args,with_errors=False):
    if parity==0:
        try:
            ok=dwt.extract(image,size,args.delta,args.repeat,args.seed,
                           max_bytes=args.max_bytes)==msg
        except (ValueError,IndexError):
            ok=False
        if not with_errors:return ok,None,None
        try:
            recovered,_=raw_payload(image,size,len(encoded),args)
            diff=np.frombuffer(recovered,dtype=np.uint8)^np.frombuffer(encoded,dtype=np.uint8)
            return ok,int(np.count_nonzero(diff)),sum(int(x).bit_count() for x in diff)
        except ValueError:
            return ok,None,None
    try:
        received,_=raw_payload(image,size,len(encoded),args)
        diff=np.frombuffer(received,dtype=np.uint8)^np.frombuffer(encoded,dtype=np.uint8)
        try:
            decoded,_,_=RSCodec(parity).decode(received)
            ok=bytes(decoded)==msg
        except (ReedSolomonError,ValueError):
            ok=False
        if with_errors:
            return ok,int(np.count_nonzero(diff)),sum(int(x).bit_count() for x in diff)
        return ok,None,None
    except (ValueError,IndexError):
        return False,None,None


def priority_sizes(image,peaks,args):
    """Same priority50 ordering as previous benchmark, globally deduplicated."""
    streams=[iter(candidate_sizes(image.size,p[0],args.search_pp,args.max_candidates))
             for p in peaks]
    seen=set()
    def take(stream):
        while True:
            try:size=next(stream)
            except StopIteration:return None
            if size not in seen:
                seen.add(size)
                return size
    if streams:
        for _ in range(min(50,args.max_candidates)):
            size=take(streams[0])
            if size is None:break
            yield size
    active=list(streams)
    while active and len(seen)<args.max_candidates:
        remaining=[]
        for stream in active:
            size=take(stream)
            if size is not None:
                remaining.append(stream)
                yield size
            if len(seen)>=args.max_candidates:break
        active=remaining


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_rs_full50_priority.csv'))
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
    ap.add_argument('--holdout',type=float,default=.30)
    ap.add_argument('--only-holdout',action='store_true')
    ap.add_argument('--scales',default='100,90,75')
    ap.add_argument('--jpeg',default='none,60')
    ap.add_argument('--parities',default='0,8,16')
    args=ap.parse_args()
    if not args.directory.is_dir():ap.error('Image directory not found')
    if args.repeat<1 or args.repeat%2!=1 or args.delta<=0:ap.error('Invalid QIM parameters')
    if args.max_candidates<50 or args.max_peaks<1 or args.search_pp<=0 or args.step<=0:
        ap.error('Invalid search parameters')
    parities=[int(x) for x in args.parities.split(',')]
    if any(p<0 or p>100 for p in parities) or args.bytes+max(parities)>255:
        ap.error('Invalid RS parities / codeword too long')
    scales=[float(x)/100 for x in args.scales.split(',')]
    qualities=[None if x.strip().lower()=='none' else int(x) for x in args.jpeg.split(',')]
    files=sorted(p for p in args.directory.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg'))
    if not files:ap.error('No JPEG images found')
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader()
        for index,path in enumerate(files,1):
            split=('holdout' if int(hashlib.sha256(path.name.encode()).hexdigest()[:8],16)/0xffffffff<args.holdout else 'train')
            if args.only_holdout and split!='holdout':continue
            print(f'[{index}/{len(files)}] {path.name}',flush=True)
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
                pilot=embed_multiband(base,BANDS['baseline'])
                base_error=''
            except Exception as exc:
                base=pilot=None
                base_error=f'{type(exc).__name__}: {exc}'
            for parity in parities:
                encoded=msg if parity==0 else bytes(RSCodec(parity).encode(msg))
                try:
                    if base_error:raise RuntimeError(base_error)
                    marked,*_=feedback_embed(pilot,encoded,args.delta,args.repeat,args.seed,args.feedback_iterations)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    psnr=round(dwt.psnr(base,saved),5)
                    embedded_ok=int(check(marked,base.size,msg,encoded,parity,args)[0])
                    saved_ok=int(check(saved,base.size,msg,encoded,parity,args)[0])
                    setup_error=''
                except Exception as exc:
                    saved=None;psnr='';embedded_ok=saved_ok=0
                    setup_error=f'{type(exc).__name__}: {exc}'
                for scale in scales:
                    for quality in qualities:
                        row={k:'' for k in FIELDS}
                        row.update(file=path.name,split=split,scale_pct=round(scale*100,3),
                                   jpeg='none' if quality is None else quality,rs_parity=parity,
                                   original_width=base.width if base else '',
                                   original_height=base.height if base else '',
                                   encoded_bytes=len(encoded),psnr_db=psnr,
                                   capacity_ok=int(saved is not None),embedded_ok=embedded_ok,
                                   jpeg85_ok=saved_ok)
                        if setup_error:
                            row['error']=setup_error
                        else:
                            try:
                                received=attack(saved,scale,quality)
                                row.update(received_width=received.width,received_height=received.height)
                                oracle,byte_err,bit_err=check(received,base.size,msg,encoded,parity,args,True)
                                row.update(oracle_ok=int(oracle),oracle_byte_errors_before_rs=byte_err,
                                           oracle_bit_errors_before_rs=bit_err)
                                start=time.perf_counter()
                                peaks=select_peaks(received,'baseline','baseline_multi',args)
                                peak_ms=(time.perf_counter()-start)*1000
                                success=False;attempts=0;found=None
                                for size in priority_sizes(received,peaks,args):
                                    attempts+=1
                                    if check(received,size,msg,encoded,parity,args)[0]:
                                        success=True;found=size;break
                                row.update(blind_ok=int(success),attempts=attempts,
                                           elapsed_ms=round((time.perf_counter()-start)*1000,3),
                                           peak_ms=round(peak_ms,3),
                                           found_width=found[0] if found else '',
                                           found_height=found[1] if found else '')
                            except Exception as exc:
                                row['error']=f'{type(exc).__name__}: {exc}'
                        writer.writerow(row)
                        out.flush()
                print(f'  RS{parity} done',flush=True)
    print('Saved:',args.csv,flush=True)

if __name__=='__main__':main()
