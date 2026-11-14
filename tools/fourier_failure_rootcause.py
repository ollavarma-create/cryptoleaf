#!/usr/bin/env python3
"""Diagnose baseline/priority50 failures from a previous Cryptoleaf CSV.

Run beside the earlier research scripts. Recreates the original 50-byte
payload, single-band marked image, JPEG85 save and the recorded attack.
Does NOT use original dimensions to select blind candidates; dimensions
are used ONLY for diagnostic oracle and neighborhood probes.

Produces one row per failure with independently interpretable flags.
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

FIELDS=['file','scale_pct','jpeg','oracle_csv','oracle_recheck',
        'original_width','original_height','received_width','received_height',
        'peak_count','top_peak_scale','top_peak_score','true_scale',
        'closest_peak_scale_error_pp','oracle_in_candidate_stream',
        'oracle_first_rank','oracle_first_peak','oracle_in_priority160',
        'oracle_candidate_attempt','blind_recheck_160',
        'blind_recheck_attempt','blind_recheck_size',
        'neighborhood_success','neighborhood_size','neighborhood_attempts',
        'expanded_success','expanded_size','expanded_attempts',
        'classification','elapsed_s','error']

def parse_args():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--previous-csv',type=Path,default=Path('fourier_priority_benchmark(1).csv'))
    ap.add_argument('--csv',type=Path,default=Path('fourier_failure_rootcause.csv'))
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
    ap.add_argument('--neighborhood',type=int,default=4,
                    help='Probe all original-size offsets in [-N,N] square')
    ap.add_argument('--expanded-budget',type=int,default=400)
    ap.add_argument('--expanded-search-pp',type=float,default=3.0)
    return ap.parse_args()

def decode(image,size,msg,args):
    try:
        return dwt.extract(image,size,args.delta,args.repeat,args.seed,
                           max_bytes=args.max_bytes)==msg
    except ValueError:
        return False

def failure_cases(path):
    with path.open(newline='',encoding='utf-8-sig') as f:
        r=csv.DictReader(f)
        required={'file','scale_pct','jpeg','embed_mode','strategy','budget','success'}
        if not required.issubset(r.fieldnames or []):
            raise ValueError('Missing previous CSV columns: '+str(required-set(r.fieldnames or [])))
        cases={}
        for row in r:
            if (row['embed_mode']=='baseline' and row['strategy']=='priority50'
                and int(row['budget'])==160 and int(row['success'])==0):
                key=(row['file'],float(row['scale_pct']),row['jpeg'].strip().lower())
                if key in cases:raise ValueError('Duplicate failure '+str(key))
                cases[key]=row
    if not cases:raise ValueError('No baseline priority50 / budget160 failures in CSV')
    return cases

def ordered_candidates(image,peaks,args,limit,search_pp):
    """Replicate priority50's round-robin order, deduplicated globally."""
    streams=[iter(candidate_sizes(image.size,p[0],search_pp,limit)) for p in peaks]
    seen=set()
    result=[]
    def take(stream,peak_rank):
        while True:
            try:size=next(stream)
            except StopIteration:return False
            if size in seen:continue
            seen.add(size)
            result.append((size,peak_rank))
            return True
    if streams:
        for _ in range(min(50,limit)):
            if not take(streams[0],1):break
    active=list(enumerate(streams,1))
    while active and len(result)<limit:
        nxt=[]
        for rank,stream in active:
            if take(stream,rank):nxt.append((rank,stream))
            if len(result)>=limit:break
        active=nxt
    return result

def classify(oracle,near,expanded,blind,oracle_in):
    if blind:return 'reproduced_blind_success_CHECK_PARAMETERS'
    if oracle:return 'synchronization_or_search_failure'
    if near:return 'size_sensitive_payload_recovery'
    if expanded:return 'recoverable_outside_original_neighborhood'
    if oracle_in:return 'payload_unrecovered_at_oracle_and_extended_search'
    return 'unresolved_payload_or_scale'

def main():
    args=parse_args()
    if not args.directory.is_dir():raise SystemExit('Photo directory missing')
    if not args.previous_csv.is_file():raise SystemExit('Previous CSV missing')
    if args.expanded_budget<160 or args.neighborhood<0:
        raise SystemExit('Invalid expanded-budget / neighborhood')
    cases=failure_cases(args.previous_csv)
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    by_file={}
    for key,row in cases.items():by_file.setdefault(key[0],[]).append((key,row))
    print(f'Diagnosing {len(cases)} failures across {len(by_file)} photos',flush=True)
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
        for file_idx,(name,items) in enumerate(sorted(by_file.items()),1):
            path=args.directory/name
            print(f'[{file_idx}/{len(by_file)}] {name}: {len(items)} cases',flush=True)
            try:
                with Image.open(path) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
                marked,*_=feedback_embed(embed_multiband(base,BANDS['baseline']),msg,
                    args.delta,args.repeat,args.seed,args.feedback_iterations)
                saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                image_error=''
            except Exception as exc:
                image_error=f'{type(exc).__name__}: {exc}'
                base=saved=None
            for (key,previous) in items:
                _,scale_pct,jpeg_text=key
                result={field:'' for field in FIELDS}
                result.update(file=name,scale_pct=scale_pct,jpeg=jpeg_text,
                              oracle_csv=previous.get('oracle_pass',''))
                t0=time.perf_counter()
                try:
                    if image_error:raise RuntimeError(image_error)
                    jpeg=None if jpeg_text in ('none','') else int(jpeg_text)
                    received=attack(saved,scale_pct/100,jpeg)
                    original=base.size
                    result.update(original_width=original[0],original_height=original[1],
                        received_width=received.width,received_height=received.height,
                        true_scale=round(received.width/original[0],6))
                    oracle=decode(received,original,msg,args)
                    result['oracle_recheck']=int(oracle)
                    peaks=select_peaks(received,'baseline','baseline_multi',args)
                    result['peak_count']=len(peaks)
                    if peaks:
                        result['top_peak_scale']=round(peaks[0][0],7)
                        result['top_peak_score']=round(peaks[0][1],7)
                        result['closest_peak_scale_error_pp']=round(
                            100*min(abs(s-received.width/original[0]) for s,_ in peaks),4)
                    ordered=ordered_candidates(received,peaks,args,160,args.search_pp)
                    oracle_pos=next(((i,rank) for i,(size,rank) in enumerate(ordered,1)
                                     if size==original),None)
                    result['oracle_in_priority160']=int(oracle_pos is not None)
                    if oracle_pos:
                        result['oracle_candidate_attempt']=oracle_pos[0]
                    # Check each peak's full stream separately, not just 160 combined attempts.
                    positions=[]
                    for rank,(s,_) in enumerate(peaks,1):
                        sizes=candidate_sizes(received.size,s,args.search_pp,args.max_candidates)
                        for i,size in enumerate(sizes,1):
                            if size==original:
                                positions.append((i,rank));break
                    result['oracle_in_candidate_stream']=int(bool(positions))
                    if positions:
                        first=min(positions)
                        result['oracle_first_rank'],result['oracle_first_peak']=first
                    blind_hit=None
                    for i,(size,rank) in enumerate(ordered,1):
                        if decode(received,size,msg,args):
                            blind_hit=(i,size);break
                    result['blind_recheck_160']=int(blind_hit is not None)
                    if blind_hit:
                        result['blind_recheck_attempt']=blind_hit[0]
                        result['blind_recheck_size']=str(blind_hit[1])
                    # Probe around ORIGINAL size, as a diagnostic ONLY.
                    # Center first, then increasing Chebyshev distance.
                    neighborhood=[]
                    n=args.neighborhood
                    for radius in range(n+1):
                        for dx in range(-radius,radius+1):
                            for dy in range(-radius,radius+1):
                                if max(abs(dx),abs(dy))!=radius:continue
                                size=(original[0]+dx,original[1]+dy)
                                if min(size)>0:neighborhood.append(size)
                    near_hit=None
                    for i,size in enumerate(neighborhood,1):
                        if decode(received,size,msg,args):
                            near_hit=size;break
                    result['neighborhood_success']=int(near_hit is not None)
                    result['neighborhood_size']=str(near_hit) if near_hit else ''
                    result['neighborhood_attempts']=len(neighborhood)
                    # More blind candidates, unchanged pilot, expanded scale window.
                    expanded=ordered_candidates(received,peaks,args,
                                               args.expanded_budget,args.expanded_search_pp)
                    expanded_hit=None
                    for i,(size,rank) in enumerate(expanded,1):
                        if decode(received,size,msg,args):
                            expanded_hit=(i,size);break
                    result['expanded_success']=int(expanded_hit is not None)
                    if expanded_hit:
                        result['expanded_size']=str(expanded_hit[1])
                        result['expanded_attempts']=expanded_hit[0]
                    result['classification']=classify(oracle,near_hit is not None,
                            expanded_hit is not None,blind_hit is not None,oracle_pos is not None)
                    if str(int(oracle))!=str(previous.get('oracle_pass','')):
                        result['error']='WARNING: oracle mismatch with previous CSV'
                except Exception as exc:
                    result['error']=f'{type(exc).__name__}: {exc}'
                    result['classification']='execution_error'
                result['elapsed_s']=round(time.perf_counter()-t0,3)
                writer.writerow(result)
                f.flush()
                print(f"  {scale_pct:g}% JPEG={jpeg_text}: {result['classification']}",flush=True)
    print('Finished:',args.csv,flush=True)

if __name__=='__main__':
    main()
