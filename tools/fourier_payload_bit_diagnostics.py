#!/usr/bin/env python3
"""Cryptoleaf research: bit-level diagnostics for oracle-unrecoverable cases.

Uses the existing root-cause CSV to select cases. This is NOT a blind decoder:
original dimensions are used intentionally to isolate DWT payload damage.
Uses the same embedding and image-processing pipeline as the prior benchmarks.
"""
import argparse
import csv
import sys
import zlib
from collections import Counter
from pathlib import Path

import numpy as np
import pywt
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt
from feedback_50photos_validation import feedback_embed, prepare
from fourier_dualband_validation import embed_multiband, attack, BANDS

FIELDS = [
    'file','scale_pct','jpeg','stage','source_width','source_height',
    'carrier_width','carrier_height','payload_bits','raw_bits','raw_errors',
    'raw_ber_pct','majority_errors','majority_ber_pct','header_errors',
    'body_errors','crc_errors','error_runs','longest_error_run',
    'wrong_repetitions_mean','wrong_repetitions_max','bit_errors_first_half',
    'bit_errors_second_half','magic_ok','length_ok','crc_ok','message_ok',
    'psnr_saved_db','error'
]

def packet_bits(message):
    packet=dwt.MAGIC+len(message).to_bytes(2,'big')+message
    packet+=zlib.crc32(packet).to_bytes(4,'big')
    return np.unpackbits(np.frombuffer(packet,dtype=np.uint8))

def bit_probe(img, size, expected, delta, repeat, seed):
    if img.size != size:
        img=img.resize(size,Image.Resampling.LANCZOS)
    y=np.asarray(img.convert('YCbCr'),dtype=np.float64)[:,:,0]
    ll=pywt.wavedec2(y,'haar',level=2,mode='periodization')[0].ravel()
    count=len(expected)*repeat
    if count>ll.size:
        raise ValueError(f'Not enough DWT coefficients: {count} > {ll.size}')
    positions=np.random.default_rng(seed).permutation(ll.size)[:count]
    observed=np.rint(ll[positions]/delta).astype(np.int64)&1
    truth=np.repeat(expected,repeat)
    raw_wrong=observed!=truth
    chunks=observed.reshape(-1,repeat)
    votes=chunks.sum(axis=1)
    recovered=(votes>repeat//2).astype(np.uint8)
    bad=(recovered!=expected)
    runs=[]
    current=0
    for x in bad:
        if x:current+=1
        elif current:
            runs.append(current);current=0
    if current:runs.append(current)
    recovered_packet=np.packbits(recovered).tobytes()
    actual_length=int.from_bytes(recovered_packet[4:6],'big')
    magic_ok=recovered_packet[:4]==dwt.MAGIC
    length_ok=actual_length==(len(expected)//8-10)
    crc_ok=(zlib.crc32(recovered_packet[:-4]) ==
            int.from_bytes(recovered_packet[-4:],'big'))
    # Payload packet: 4 magic + 2 length + N data + 4 CRC bytes.
    header=6*8
    crc_start=len(expected)-4*8
    return dict(payload_bits=len(expected),raw_bits=count,
        raw_errors=int(raw_wrong.sum()),raw_ber_pct=round(100*raw_wrong.mean(),4),
        majority_errors=int(bad.sum()),majority_ber_pct=round(100*bad.mean(),4),
        header_errors=int(bad[:header].sum()),
        body_errors=int(bad[header:crc_start].sum()),
        crc_errors=int(bad[crc_start:].sum()),
        error_runs=len(runs),longest_error_run=max(runs,default=0),
        wrong_repetitions_mean=round(float(raw_wrong.reshape(-1,repeat).sum(axis=1).mean()),4),
        wrong_repetitions_max=int(raw_wrong.reshape(-1,repeat).sum(axis=1).max()),
        bit_errors_first_half=int(bad[:len(bad)//2].sum()),
        bit_errors_second_half=int(bad[len(bad)//2:].sum()),
        magic_ok=int(magic_ok),length_ok=int(length_ok),crc_ok=int(crc_ok),
        message_ok=int(np.array_equal(recovered,expected)))

def load_cases(path, all_oracle_fail):
    with path.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        needed={'file','scale_pct','jpeg','oracle_recheck','classification'}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError('Missing rootcause CSV columns: '+str(needed-set(reader.fieldnames or [])))
        cases=[]
        seen=set()
        for row in reader:
            if row['oracle_recheck'].strip()!='0':continue
            if not all_oracle_fail and row['classification']!='payload_unrecovered_at_oracle_and_extended_search':
                continue
            key=(row['file'],float(row['scale_pct']),row['jpeg'].strip().lower())
            if key in seen:raise ValueError(f'Duplicate case: {key}')
            seen.add(key);cases.append(key)
    return sorted(cases)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--rootcause-csv',type=Path,default=Path('fourier_failure_rootcause.csv'))
    ap.add_argument('--csv',type=Path,default=Path('fourier_payload_bit_diagnostics.csv'))
    ap.add_argument('--all-oracle-fail',action='store_true',
                    help='Include the ambiguous 14th oracle failure')
    ap.add_argument('--longest',type=int,default=1280)
    ap.add_argument('--bytes',type=int,default=50)
    ap.add_argument('--delta',type=float,default=32)
    ap.add_argument('--repeat',type=int,default=9)
    ap.add_argument('--seed',type=int,default=20261114)
    ap.add_argument('--feedback-iterations',type=int,default=6)
    ap.add_argument('--save-quality',type=int,default=85)
    args=ap.parse_args()
    if args.repeat<1 or args.repeat%2==0 or args.delta<=0 or args.bytes<1:
        ap.error('Invalid repeat/delta/bytes')
    if not args.directory.is_dir():ap.error('Image directory missing')
    if not args.rootcause_csv.is_file():ap.error('Root-cause CSV missing')
    cases=load_cases(args.rootcause_csv,args.all_oracle_fail)
    if not cases:ap.error('No matching cases')
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    expected=packet_bits(msg)
    print(f'{len(cases)} cases, {len(expected)} packet bits, {len(expected)*args.repeat} raw carrier bits',flush=True)
    by_file={}
    for name,scale,jpeg in cases:
        by_file.setdefault(name,[]).append((scale,jpeg))
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader()
        for file_idx,(name,attacks) in enumerate(sorted(by_file.items()),1):
            print(f'[{file_idx}/{len(by_file)}] {name}',flush=True)
            try:
                with Image.open(args.directory/name) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
                marked,*_=feedback_embed(embed_multiband(base,BANDS['baseline']),msg,
                    args.delta,args.repeat,args.seed,args.feedback_iterations)
                saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                psnr=round(dwt.psnr(base,saved),4)
                stages_common=[('embedded_rgb',marked),('saved_jpeg85',saved)]
                setup_error=''
            except Exception as exc:
                base=saved=None
                setup_error=f'{type(exc).__name__}: {exc}'
                psnr=''
            for scale,jpeg_text in attacks:
                jq=None if jpeg_text in ('none','') else int(jpeg_text)
                stages=list(stages_common) if not setup_error else []
                if not setup_error:
                    try:
                        # Attack function exactly matches earlier benchmark.
                        stages.append(('resize_only',attack(saved,scale/100,None)))
                        if jq is not None:
                            stages.append(('jpeg_only',attack(saved,1.,jq)))
                        stages.append(('combined_attack',attack(saved,scale/100,jq)))
                    except Exception as exc:
                        setup_error=f'{type(exc).__name__}: {exc}'
                for stage in ('embedded_rgb','saved_jpeg85','resize_only',
                              'jpeg_only','combined_attack'):
                    img=dict(stages).get(stage)
                    row={k:'' for k in FIELDS}
                    row.update(file=name,scale_pct=scale,jpeg=jpeg_text,
                               stage=stage,psnr_saved_db=psnr)
                    if base is not None:
                        row.update(source_width=base.width,source_height=base.height)
                    if img is not None:
                        row.update(carrier_width=img.width,carrier_height=img.height)
                    if img is None:
                        if stage=='jpeg_only' and jq is None:continue
                        row['error']=setup_error or 'Stage not available'
                    else:
                        try:row.update(bit_probe(img,base.size,expected,
                                                args.delta,args.repeat,args.seed))
                        except Exception as exc:
                            row['error']=f'{type(exc).__name__}: {exc}'
                    writer.writerow(row)
                    if stage=='combined_attack':
                        print(f"  {scale:g}% JPEG={jpeg_text}: majority errors={row['majority_errors']} raw BER={row['raw_ber_pct']}%",flush=True)
                    out.flush()
    print('Saved:',args.csv,flush=True)

if __name__=='__main__':
    main()
