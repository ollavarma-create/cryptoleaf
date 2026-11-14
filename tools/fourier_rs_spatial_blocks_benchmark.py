#!/usr/bin/env python3
"""Cryptoleaf research: Reed-Solomon parity x spatial DWT block placement.

Controlled oracle experiment, NOT production format. One Fourier pilot,
Feedback-QIM, JPEG85 save, then the recorded scale/JPEG attack.
Compare RS parity 0/8/16 with one whole-image block and four spatial tiles.
Original dimensions are used ONLY for oracle recovery, not blind extraction.
Install: python -m pip install reedsolo numpy pillow PyWavelets
"""
import argparse, csv, sys, zlib
from pathlib import Path
import numpy as np
import pywt
from PIL import Image, ImageOps
try:
    from reedsolo import RSCodec, ReedSolomonError
except ImportError:
    raise SystemExit('Missing dependency: python -m pip install reedsolo')
sys.path.insert(0,str(Path(__file__).resolve().parent))
import dwt_probe as dwt
from feedback_50photos_validation import feedback_embed, prepare
from fourier_dualband_validation import embed_multiband, attack, BANDS

FIELDS=['file','scale_pct','jpeg','rs_parity','tiles','original_width','original_height',
        'encoded_bytes','total_embedded_bytes','required_coefficients','available_coefficients',
        'capacity_ok','embedded_crc_ok','saved_crc_ok','oracle_crc_ok',
        'oracle_rs_ok','oracle_message_ok','byte_errors_before_rs',
        'bit_errors_before_rs','rs_corrected_symbols','raw_packet_crc_tiles_ok',
        'psnr_db','elapsed_s','error']
def read_cases(path, all_oracle_fail=False):
    with path.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        required={'file','scale_pct','jpeg','oracle_recheck','classification'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Root-cause CSV columns missing: '+str(required-set(reader.fieldnames or [])))
        seen=set()
        for r in reader:
            if r['oracle_recheck'].strip()!='0':continue
            if not all_oracle_fail and r['classification']!='payload_unrecovered_at_oracle_and_extended_search':
                continue
            key=(r['file'],float(r['scale_pct']),r['jpeg'].strip().lower())
            seen.add(key)
        return sorted(seen)

def rects(size, tiles):
    w,h=size
    if tiles==1:return [(0,0,w,h)]
    if tiles!=4:raise ValueError('tiles must be 1 or 4')
    x=w//2;y=h//2
    return [(0,0,x,y),(x,0,w,y),(0,y,x,h),(x,y,w,h)]

def split_bytes(data,tiles):
    # Consecutive byte chunks, RS code spans ALL chunks.
    n=len(data)
    return [data[i*n//tiles:(i+1)*n//tiles] for i in range(tiles)]

def seed_for_tile(seed,i):
    return seed+7919*i

def capacities(image,parts,repeat):
    return [((image.crop(rect).width+3)//4)*((image.crop(rect).height+3)//4)
            for rect in parts]

def build_carrier(pilot,encoded,args,tiles):
    parts=rects(pilot.size,tiles)
    chunks=split_bytes(encoded,tiles)
    capacity=capacities(pilot,parts,args.repeat)
    need=[(len(chunk)+10)*8*args.repeat for chunk in chunks]
    if any(n>c for n,c in zip(need,capacity)):
        raise ValueError('Insufficient tile capacity: required='+str(need)+' available='+str(capacity))
    output=pilot.copy()
    for i,(rect,chunk) in enumerate(zip(parts,chunks)):
        tile=pilot.crop(rect)
        embedded,*_=feedback_embed(tile,chunk,args.delta,args.repeat,
                                    seed_for_tile(args.seed,i),args.feedback_iterations)
        output.paste(embedded,rect[:2])
    return output,sum(need),sum(capacity)

def read_raw_chunk(img,rect,chunk_length,args,i):
    tile=img.crop(rect)
    y=np.asarray(tile.convert('YCbCr'),dtype=np.float64)[:,:,0]
    ll=pywt.wavedec2(y,'haar',level=2,mode='periodization')[0].ravel()
    count=(chunk_length+10)*8*args.repeat
    if count>ll.size:raise ValueError('Insufficient coefficients during extraction')
    pos=np.random.default_rng(seed_for_tile(args.seed,i)).permutation(ll.size)[:count]
    observed=(np.rint(ll[pos]/args.delta).astype(np.int64)&1).reshape(-1,args.repeat)
    majority=(observed.sum(axis=1)>args.repeat//2).astype(np.uint8)
    packet=np.packbits(majority).tobytes()
    good_crc=(packet[:4]==dwt.MAGIC and int.from_bytes(packet[4:6],'big')==chunk_length
              and zlib.crc32(packet[:-4])==int.from_bytes(packet[-4:],'big'))
    return packet[6:6+chunk_length],good_crc

def decode_oracle(image,original_size,encoded_len,args,tiles):
    if image.size!=original_size:
        image=image.resize(original_size,Image.Resampling.LANCZOS)
    chunks=split_bytes(bytes(encoded_len),tiles)
    parts=rects(original_size,tiles)
    received=[]
    checks=[]
    for i,(rect,chunk) in enumerate(zip(parts,chunks)):
        data,crc=read_raw_chunk(image,rect,len(chunk),args,i)
        received.append(data);checks.append(crc)
    return b''.join(received),sum(checks)

def rs_result(received,original,parity):
    if parity==0:
        return int(received==original),int(received==original),0
    try:
        decoded,corrected,positions=RSCodec(parity).decode(received)
        return 1,int(bytes(decoded)==original[:-parity]),len(positions)
    except ReedSolomonError:
        return 0,0,0

def run():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    ap.add_argument('--rootcause-csv',type=Path,default=Path('fourier_failure_rootcause.csv'))
    ap.add_argument('--csv',type=Path,default=Path('fourier_rs_spatial_blocks.csv'))
    ap.add_argument('--all-oracle-fail',action='store_true')
    ap.add_argument('--rs-parities',default='0,8,16')
    ap.add_argument('--tile-counts',default='1,4')
    ap.add_argument('--longest',type=int,default=1280)
    ap.add_argument('--bytes',type=int,default=50)
    ap.add_argument('--delta',type=float,default=32)
    ap.add_argument('--repeat',type=int,default=9)
    ap.add_argument('--seed',type=int,default=20261114)
    ap.add_argument('--feedback-iterations',type=int,default=6)
    ap.add_argument('--save-quality',type=int,default=85)
    args=ap.parse_args()
    if not args.directory.is_dir():ap.error('Image directory not found')
    if not args.rootcause_csv.is_file():ap.error('Rootcause CSV not found')
    parities=sorted(set(int(x) for x in args.rs_parities.split(',')))
    tiles_list=sorted(set(int(x) for x in args.tile_counts.split(',')))
    if not parities or any(x<0 or x>100 for x in parities) or any(x not in (1,4) for x in tiles_list):
        ap.error('Invalid parity/tile values')
    if args.bytes+max(parities)>255:ap.error('RS codeword exceeds 255 bytes')
    if args.repeat<1 or args.repeat%2!=1:ap.error('repeat must be positive and odd')
    cases=read_cases(args.rootcause_csv,args.all_oracle_fail)
    if not cases:ap.error('No cases selected')
    msg=np.random.default_rng(args.seed).integers(0,256,args.bytes,dtype=np.uint8).tobytes()
    by_file={}
    for name,scale,jpeg in cases:by_file.setdefault(name,[]).append((scale,jpeg))
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    import time
    with args.csv.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader()
        for index,(name,attacks) in enumerate(sorted(by_file.items()),1):
            print(f'[{index}/{len(by_file)}] {name}',flush=True)
            try:
                with Image.open(args.directory/name) as im:
                    base=prepare(ImageOps.exif_transpose(im).convert('RGB'),args.longest)
                pilot=embed_multiband(base,BANDS['baseline'])
                prep_error=''
            except Exception as exc:
                base=pilot=None
                prep_error=f'{type(exc).__name__}: {exc}'
            for parity in parities:
                encoded=msg if parity==0 else bytes(RSCodec(parity).encode(msg))
                for tiles in tiles_list:
                    start=time.perf_counter()
                    marked=saved=None
                    try:
                        if prep_error:raise ValueError(prep_error)
                        marked,need,available=build_carrier(pilot,encoded,args,tiles)
                        saved=dwt.jpeg_roundtrip(marked,args.save_quality)
                        psnr=round(dwt.psnr(base,saved),4)
                        embed_recv,embed_crc=decode_oracle(marked,base.size,len(encoded),args,tiles)
                        saved_recv,saved_crc=decode_oracle(saved,base.size,len(encoded),args,tiles)
                        setup_error=''
                    except Exception as exc:
                        setup_error=f'{type(exc).__name__}: {exc}'
                        need=available=0;psnr=''
                        embed_crc=saved_crc=0
                    for scale,jpeg_text in attacks:
                        row={k:'' for k in FIELDS}
                        row.update(file=name,scale_pct=scale,jpeg=jpeg_text,rs_parity=parity,
                                   tiles=tiles,encoded_bytes=len(encoded),
                                   total_embedded_bytes=len(encoded)+10*tiles,
                                   original_width=base.width if base else '',
                                   original_height=base.height if base else '',
                                   required_coefficients=need,available_coefficients=available,
                                   capacity_ok=int(not setup_error),
                                   embedded_crc_ok=int(embed_crc==tiles),
                                   saved_crc_ok=int(saved_crc==tiles),
                                   psnr_db=psnr)
                        if setup_error:
                            row['error']=setup_error
                        else:
                            try:
                                quality=None if jpeg_text in ('none','') else int(jpeg_text)
                                attacked=attack(saved,scale/100,quality)
                                received,crc_tiles=decode_oracle(attacked,base.size,len(encoded),args,tiles)
                                diff=np.frombuffer(received,dtype=np.uint8)^np.frombuffer(encoded,dtype=np.uint8)
                                bit_errors=sum(int(x).bit_count() for x in diff)
                                byte_errors=int(np.count_nonzero(diff))
                                rs_ok,msg_ok,corrected=rs_result(received,encoded,parity)
                                row.update(oracle_crc_ok=int(crc_tiles==tiles),
                                           oracle_rs_ok=rs_ok,oracle_message_ok=msg_ok,
                                           byte_errors_before_rs=byte_errors,
                                           bit_errors_before_rs=bit_errors,
                                           rs_corrected_symbols=corrected,
                                           raw_packet_crc_tiles_ok=crc_tiles)
                            except Exception as exc:
                                row['error']=f'{type(exc).__name__}: {exc}'
                        row['elapsed_s']=round(time.perf_counter()-start,3)
                        writer.writerow(row)
                        print(f"  RS={parity:2} tiles={tiles} scale={scale:g} jpeg={jpeg_text} "
                              f"ok={row['oracle_message_ok'] or '-'} "
                              f"errors={row['byte_errors_before_rs'] or '-'} "
                              f"{row['error']}",flush=True)
                        out.flush()
    print('Saved:',args.csv,flush=True)

if __name__=='__main__':
    run()
