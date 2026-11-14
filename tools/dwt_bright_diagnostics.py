#!/usr/bin/env python3
"""Diagnose RAW DWT failures in bright P1010892.JPG; research only.

Compare baseline, luminance inversion, headroom, percentile mapping and gamma.
All transformations are applied BEFORE embedding and must be known to decoder;
this experiment does NOT establish a blind reversible scheme.
"""
import argparse
import csv
from pathlib import Path
import sys
import numpy as np
import pywt
from PIL import Image, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwt_probe as dwt

MAGIC = dwt.MAGIC
FIELDS = ['variant','delta','bytes','width','height','y_min','y_max','y_clip_low_pct',
          'y_clip_high_pct','rgb_clip_pct','ll2_header_ber','raw_pass','raw_error',
          'jpeg85_pass','jpeg85_error','jpeg60_pass','jpeg60_error','psnr_raw_db','psnr_jpeg85_db']


def transform(img, name):
    if name == 'original': return img.copy()
    if name == 'negative':
        return Image.fromarray(255-np.asarray(img, dtype=np.uint8), 'RGB')
    ycc = np.asarray(img.convert('YCbCr'), dtype=np.float64).copy()
    y = ycc[:,:,0]
    if name == 'headroom16':
        y = 16 + y*(223/255)
    elif name == 'headroom32':
        y = 32 + y*(191/255)
    elif name == 'percentile16':
        lo,hi = np.percentile(y, [1,99])
        y = 16 + (np.clip(y,lo,hi)-lo)*223/max(hi-lo,1)
    elif name == 'gamma07':
        y = 255*(y/255)**0.7
    elif name == 'gamma14':
        y = 255*(y/255)**1.4
    else: raise ValueError(name)
    ycc[:,:,0] = np.clip(np.rint(y),0,255)
    return Image.fromarray(ycc.astype(np.uint8), 'YCbCr').convert('RGB')


def coefficient_diagnostics(img, message, delta, repeat, seed):
    """Measure Y reconstruction clipping BEFORE rounding and RGB conversion.
    Also measure header bit error rate AFTER RGB conversion.
    """
    ycc = np.asarray(img.convert('YCbCr'), dtype=np.float64).copy()
    coeffs = pywt.wavedec2(ycc[:,:,0], 'haar', level=2, mode='periodization')
    ll = coeffs[0].copy(); flat = ll.ravel()
    packet = MAGIC + len(message).to_bytes(2,'big') + message
    import zlib
    packet += zlib.crc32(packet).to_bytes(4,'big')
    bits = np.unpackbits(np.frombuffer(packet,dtype=np.uint8))
    count = len(bits)*repeat
    if count > flat.size: raise ValueError('Insufficient DWT capacity')
    pos = np.random.default_rng(seed).permutation(flat.size)[:count]
    expanded = np.repeat(bits,repeat)
    q = np.rint(flat[pos]/delta).astype(np.int64)
    q += (expanded.astype(np.int64)-(q & 1)) % 2
    flat[pos] = q*delta
    coeffs[0] = ll
    raw_y = pywt.waverec2(coeffs,'haar',mode='periodization')[:img.height,:img.width]
    low = float(np.mean(raw_y < 0)*100)
    high = float(np.mean(raw_y > 255)*100)
    reconstructed = dwt.embed(img,message,delta,repeat,seed)
    rgb = np.asarray(reconstructed,dtype=np.uint8)
    rgb_clip = float(np.mean((rgb==0)|(rgb==255))*100)
    recovered_y = np.asarray(reconstructed.convert('YCbCr'),dtype=np.float64)[:,:,0]
    recovered_ll = pywt.wavedec2(recovered_y,'haar',level=2,mode='periodization')[0].ravel()
    header_n = 6*8*repeat
    rq = np.rint(recovered_ll[pos[:header_n]]/delta).astype(np.int64)
    recovered_bits = ((rq & 1).reshape(-1,repeat).sum(axis=1)>repeat//2).astype(np.uint8)
    ber = float(np.mean(recovered_bits != bits[:48])*100)
    return reconstructed,low,high,rgb_clip,ber


def decode(image,size,message,delta,repeat,seed):
    try:
        got=dwt.extract(image,size,delta,repeat,seed,max_bytes=max(256,len(message)))
        return int(got==message), '' if got==message else 'MessageMismatch'
    except Exception as exc:
        return 0, f'{type(exc).__name__}:{exc}'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image',nargs='?',type=Path,
                    default=Path('/home/jari/Pictures/DWTFourierTesti/P1010892.JPG'))
    ap.add_argument('--csv',type=Path,default=Path('dwt_bright_diagnostics.csv'))
    ap.add_argument('--deltas',default='16,24,32,48')
    ap.add_argument('--lengths',default='10,25,50')
    ap.add_argument('--repeat',type=int,default=9)
    ap.add_argument('--seed',type=int,default=20261114)
    args=ap.parse_args()
    deltas=[float(v) for v in args.deltas.split(',')]
    lengths=[int(v) for v in args.lengths.split(',')]
    if any(x<=0 for x in deltas) or any(x<1 for x in lengths): ap.error('Invalid deltas/lengths')
    if args.repeat<1 or args.repeat%2!=1: ap.error('Repeat must be positive odd')
    with Image.open(args.image) as source:
        original=ImageOps.exif_transpose(source).convert('RGB')
    variants=['original','negative','headroom16','headroom32','percentile16','gamma07','gamma14']
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    totals={v:[0,0,0] for v in variants}
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
        for variant in variants:
            image=transform(original,variant)
            y=np.asarray(image.convert('YCbCr'))[:,:,0]
            for length in lengths:
                message=np.random.default_rng(args.seed).integers(0,256,length,dtype=np.uint8).tobytes()
                for delta in deltas:
                    row=dict(variant=variant,delta=delta,bytes=length,
                             width=image.width,height=image.height,
                             y_min=int(y.min()),y_max=int(y.max()),
                             raw_pass=0,jpeg85_pass=0,jpeg60_pass=0)
                    try:
                        marked,low,high,rgbclip,ber=coefficient_diagnostics(
                            image,message,delta,args.repeat,args.seed)
                        row.update(y_clip_low_pct=round(low,4),y_clip_high_pct=round(high,4),
                                   rgb_clip_pct=round(rgbclip,4),ll2_header_ber=round(ber,3),
                                   psnr_raw_db=round(dwt.psnr(image,marked),3))
                        row['raw_pass'],row['raw_error']=decode(marked,image.size,message,delta,args.repeat,args.seed)
                        for quality in (85,60):
                            compressed=dwt.jpeg_roundtrip(marked,quality)
                            row[f'jpeg{quality}_pass'],row[f'jpeg{quality}_error']=decode(
                                compressed,image.size,message,delta,args.repeat,args.seed)
                            if quality==85:row['psnr_jpeg85_db']=round(dwt.psnr(image,compressed),3)
                    except Exception as exc:
                        row['raw_error']=f'{type(exc).__name__}:{exc}'
                    writer.writerow(row);f.flush()
                    totals[variant][0]+=row['raw_pass']
                    totals[variant][1]+=row['jpeg85_pass']
                    totals[variant][2]+=row['jpeg60_pass']
                    print(f'{variant:13} {length:2} B delta={delta:4g} '
                          f'RAW={row["raw_pass"]} J85={row["jpeg85_pass"]} J60={row["jpeg60_pass"]} '
                          f'headerBER={row.get("ll2_header_ber","-")} '
                          f'clipHigh={row.get("y_clip_high_pct","-")}',flush=True)
    print('\nSUMMARY (RAW, JPEG85, JPEG60; 12 trials per variant)')
    for variant, values in totals.items(): print(variant,values)
    print('Saved:',args.csv)
    print('CAUTION: transformed images are not invertible to originals without losses; '
          'PSNR is against the transformed image, not the source.')

if __name__=='__main__':main()
