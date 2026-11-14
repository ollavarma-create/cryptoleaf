#!/usr/bin/env python3
"""Independent DWT-QIM robustness probe. Not Cryptoleaf production format.
Requires Pillow, numpy, PyWavelets. Uses known original dimensions for resize recovery.
"""
import argparse, csv, io, zlib
from pathlib import Path
import numpy as np
import pywt
from PIL import Image

MAGIC = b'DWT1'

def bits_from_bytes(b):
    return np.unpackbits(np.frombuffer(b, dtype=np.uint8))

def embed(image, message, delta, repeat, seed):
    if len(message) > 65535:
        raise ValueError('Message too long')
    packet = MAGIC + len(message).to_bytes(2, 'big') + message
    packet += zlib.crc32(packet).to_bytes(4, 'big')
    bits = bits_from_bytes(packet)
    ycbcr = image.convert('YCbCr')
    a = np.asarray(ycbcr, dtype=np.float64).copy()
    coeffs = pywt.wavedec2(a[:,:,0], 'haar', level=2, mode='periodization')
    ll = coeffs[0].copy()
    flat = ll.ravel()
    count = len(bits) * repeat
    if count > flat.size:
        raise ValueError(f'Insufficient DWT capacity: need {count}, have {flat.size}')
    rng = np.random.default_rng(seed)
    positions = rng.permutation(flat.size)[:count]
    expanded = np.repeat(bits, repeat)
    # QIM: nearest quantization lattice with parity encoding
    q = np.rint(flat[positions] / delta).astype(np.int64)
    q += (expanded.astype(np.int64) - (q & 1)) % 2
    flat[positions] = q * delta
    coeffs[0] = ll
    a[:,:,0] = np.clip(pywt.waverec2(coeffs, 'haar', mode='periodization')[:a.shape[0], :a.shape[1]], 0, 255)
    return Image.fromarray(np.uint8(np.clip(np.rint(a),0,255)), 'YCbCr').convert('RGB')

def extract(image, original_size, delta, repeat, seed, max_bytes=256):
    # This is an ORACLE alignment: decoder is explicitly told the original size.
    if image.size != original_size:
        image = image.resize(original_size, Image.Resampling.LANCZOS)
    y = np.asarray(image.convert('YCbCr'), dtype=np.float64)[:,:,0]
    ll = pywt.wavedec2(y, 'haar', level=2, mode='periodization')[0].ravel()
    rng = np.random.default_rng(seed)
    # Must match embed permutation length, independent of packet length.
    pos = rng.permutation(ll.size)
    def read(nbytes):
        count = nbytes * 8 * repeat
        if count > ll.size: raise ValueError('Insufficient capacity')
        q = np.rint(ll[pos[:count]] / delta).astype(np.int64)
        bits = (q & 1).reshape(-1,repeat)
        majority = (bits.sum(axis=1) > repeat//2).astype(np.uint8)
        return np.packbits(majority).tobytes()
    header = read(6)
    if header[:4] != MAGIC: raise ValueError('BadMagic')
    length = int.from_bytes(header[4:6], 'big')
    if length > max_bytes: raise ValueError('LengthOutOfRange')
    packet = read(6 + length + 4)
    if zlib.crc32(packet[:-4]) != int.from_bytes(packet[-4:], 'big'):
        raise ValueError('BadCRC')
    return packet[6:-4]

def jpeg_roundtrip(img, quality):
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality, subsampling=0)
    buf.seek(0)
    with Image.open(buf) as loaded:
        return loaded.convert('RGB')

def psnr(a,b):
    x=np.asarray(a,dtype=np.float64); y=np.asarray(b,dtype=np.float64)
    mse=np.mean((x-y)**2)
    return float('inf') if mse==0 else 10*np.log10(255**2/mse)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--message', default='Cryptoleaf DWT probe')
    p.add_argument('--deltas', default='12,20,32')
    p.add_argument('--repeat', type=int, default=9)
    p.add_argument('--quality', type=int, default=85)
    p.add_argument('--resize', default='100,99,98,96,90,75')
    p.add_argument('--recompress', default='none,75,60')
    p.add_argument('--seed', type=int, default=20261114)
    p.add_argument('--csv', type=Path, default=Path('dwt_probe.csv'))
    args=p.parse_args()
    if args.repeat < 1 or args.repeat%2==0: p.error('--repeat must be positive odd')
    original=Image.open(args.image).convert('RGB')
    message=args.message.encode('utf-8')
    deltas=[float(v) for v in args.deltas.split(',')]
    sizes=[int(v) for v in args.resize.split(',')]
    recompress=[None if v=='none' else int(v) for v in args.recompress.split(',')]
    rows=[]
    for delta in deltas:
        try:
            encoded=embed(original,message,delta,args.repeat,args.seed)
            saved=jpeg_roundtrip(encoded,args.quality)
        except Exception as exc:
            print(f'delta={delta}: encode failed: {exc}')
            continue
        quality=psnr(original,saved)
        for size in sizes:
            for q in recompress:
                processed=saved
                if size != 100:
                    w=max(1,round(saved.width*size/100))
                    h=max(1,round(saved.height*size/100))
                    processed=saved.resize((w,h),Image.Resampling.LANCZOS)
                if q is not None: processed=jpeg_roundtrip(processed,q)
                try:
                    result=extract(processed,original.size,delta,args.repeat,args.seed)
                    success=result==message
                    error='' if success else 'MessageMismatch'
                except Exception as exc:
                    success=False; error=str(exc)
                rows.append(dict(delta=delta,repeat=args.repeat,save_quality=args.quality,resize_percent=size,
                                 recompress_quality=q if q is not None else 'none',pass_decode=success,
                                 psnr_db=round(quality,2),error=error))
                print(f'delta={delta:g} resize={size:3d}% jpeg={str(q):>4}  {"PASS" if success else "FAIL"} {error}')
    if rows:
        with args.csv.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        print(f'\n{sum(r["pass_decode"] for r in rows)}/{len(rows)} passed; CSV: {args.csv}')

if __name__=='__main__': main()
