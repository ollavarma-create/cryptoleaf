#!/usr/bin/env python3
"""Cryptoleaf: controlled Fourier pilot band sweep for small-image synchronization.

Baseline vs low-frequency vs wide-frequency single-band pilots, equal strength.
RS8, Feedback-QIM, Priority50, max 160 decode attempts; paired image/attack cases.
Default: small images plus a deterministic set of larger controls.
--all: all images. Output CSV contains both peak diagnostics and blind success.
Requires the same research modules as fourier_rs_full50_priority.py.
"""
import argparse,csv,hashlib,sys,time
from pathlib import Path
from PIL import Image,ImageOps
import numpy as np
from reedsolo import RSCodec

sys.path.insert(0,str(Path(__file__).resolve().parent))
import dwt_probe as dwt
from feedback_50photos_validation import feedback_embed,prepare
from fourier_dualband_validation import embed_multiband,attack,BANDS
from fourier_multipeak_fair_benchmark import peak_candidates
from fourier_rs_full50_priority import check,priority_sizes

BAND_SET={
    'baseline':(.055,.195,.18),
    'low':(.030,.130,.18),
    'mid_low':(.040,.160,.18),
    'wide':(.040,.240,.18),
}
FIELDS=['file','group','band','band_low','band_high','strength','scale_pct','jpeg',
        'width','height','received_width','received_height','true_scale',
        'peak1_scale','peak1_error_pp','nearest_peak_error_pp','nearest_peak_rank',
        'peak1_score','peaks_count','within_1pp_top4','within_2pp_top4',
        'oracle_ok','blind_ok','attempts','found_width','found_height',
        'psnr_db','jpeg85_ok','elapsed_ms','peak_ms','error']

def rank_info(peaks,scale):
    if not peaks:return ('','','',0,0)
    best=min(range(len(peaks)),key=lambda i:abs(peaks[i][0]-scale))
    return (round(abs(peaks[best][0]-scale)*100,4),best+1,
            int(any(abs(p[0]-scale)<=.01 for p in peaks[:4])),
            int(any(abs(p[0]-scale)<=.02 for p in peaks[:4])))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--csv',type=Path,default=Path('fourier_small_image_sync.csv'))
    ap.add_argument('--all',action='store_true',help='Run all images instead of small+controls')
    ap.add_argument('--small-max',type=int,default=750,help='Maximum prepared longest side for small group')
    ap.add_argument('--controls',type=int,default=8,help='Number of larger control images')
    ap.add_argument('--bands',default='baseline,low,mid_low,wide')
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
    if not args.directory.is_dir():ap.error('Image directory missing')
    bands=[x.strip() for x in args.bands.split(',')]
    if any(x not in BAND_SET for x in bands):ap.error('Unknown band: '+str(bands))
    if args.repeat<1 or args.repeat%2!=1 or args.delta<=0 or args.max_candidates<50:
        ap.error('Invalid QIM/search parameters')
    scales=[float(s)/100 for s in args.scales.split(',')]
    qualities=[None if q.strip().lower()=='none' else int(q) for q in args.jpeg.split(',')]
    files=sorted(x for x in args.directory.iterdir()
                 if x.is_file() and x.suffix.lower() in ('.jpg','.jpeg'))
    if not files:ap.error('No JPEG files')
    small=[];large=[]
    for path in files:
        try:
            with Image.open(path) as im:
                w,h=ImageOps.exif_transpose(im).size
            prepared_longest=min(max(w,h),args.longest)
            (small if prepared_longest<=args.small_max else large).append(path)
        except Exception as exc:print(f'SKIP {path.name}: {exc}',flush=True)
    if args.all:
        selected=sorted(small+large)
    else:
        controls=sorted(large,key=lambda p:hashlib.sha256(p.name.encode()).hexdigest())[:args.controls]
        selected=sorted(small+controls)
    print(f'Images: {len(selected)} ({sum(x in small for x in selected)} small); '
          f'bands: {bands}; cases: {len(selected)*len(bands)*len(scales)*len(qualities)}',flush=True)
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    encoded=bytes(RSCodec(8).encode(msg))
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
        for index,path in enumerate(selected,1):
            print(f'[{index}/{len(selected)}] {path.name}',flush=True)
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
                base_error=''
            except Exception as exc:
                base=None;base_error=f'{type(exc).__name__}: {exc}'
            for name in bands:
                low,high,strength=BAND_SET[name]
                try:
                    if base_error:raise RuntimeError(base_error)
                    pilot=embed_multiband(base,[(low,high,strength)])
                    marked,*_=feedback_embed(pilot,encoded,args.delta,args.repeat,
                                              args.seed,args.feedback_iterations)
                    saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                    psnr=round(dwt.psnr(base,saved),5)
                    saved_ok=int(check(saved,base.size,msg,encoded,8,args)[0])
                    error=''
                except Exception as exc:
                    saved=None;psnr='';saved_ok=0
                    error=f'{type(exc).__name__}: {exc}'
                for scale in scales:
                    for quality in qualities:
                        row={k:'' for k in FIELDS}
                        row.update(file=path.name,group='small' if path in small else 'control',
                                   band=name,band_low=low,band_high=high,strength=strength,
                                   scale_pct=round(scale*100,3),
                                   jpeg='none' if quality is None else quality,
                                   width=base.width if base else '',height=base.height if base else '',
                                   true_scale=scale,psnr_db=psnr,jpeg85_ok=saved_ok)
                        if saved is None:row['error']=error
                        else:
                            try:
                                received=attack(saved,scale,quality)
                                row.update(received_width=received.width,
                                           received_height=received.height)
                                row['oracle_ok']=int(check(received,base.size,msg,encoded,8,args)[0])
                                start=time.perf_counter()
                                peaks=peak_candidates(received,(low,high,strength),args)[:args.max_peaks]
                                peak_ms=(time.perf_counter()-start)*1000
                                near,rank,within1,within2=rank_info(peaks,scale)
                                row.update(peak1_scale=round(peaks[0][0],5) if peaks else '',
                                           peak1_score=round(peaks[0][1],6) if peaks else '',
                                           peak1_error_pp=round(abs(peaks[0][0]-scale)*100,4) if peaks else '',
                                           nearest_peak_error_pp=near,nearest_peak_rank=rank,
                                           peaks_count=len(peaks),within_1pp_top4=within1,
                                           within_2pp_top4=within2)
                                found=None;attempts=0
                                for size in priority_sizes(received,peaks,args):
                                    attempts+=1
                                    if check(received,size,msg,encoded,8,args)[0]:
                                        found=size;break
                                row.update(blind_ok=int(found is not None),attempts=attempts,
                                           found_width=found[0] if found else '',
                                           found_height=found[1] if found else '',
                                           elapsed_ms=round((time.perf_counter()-start)*1000,3),
                                           peak_ms=round(peak_ms,3))
                            except Exception as exc:
                                row['error']=f'{type(exc).__name__}: {exc}'
                        writer.writerow(row);f.flush()
                        print(f"  {name:8s} {scale*100:g}% jpeg={row['jpeg']}: "
                              f"oracle={row['oracle_ok']} blind={row['blind_ok']} "
                              f"peak_error_pp={row['peak1_error_pp']} {row['error']}",flush=True)
    print('Saved:',args.csv,flush=True)

if __name__=='__main__':
    main()
