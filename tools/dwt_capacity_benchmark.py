#!/usr/bin/env python3
"""DWT-QIM capacity/robustness experiment, using dwt_probe.py unchanged.

Not a Cryptoleaf file format. Original dimensions, delta, repetition and seed
are supplied to the decoder (oracle alignment). No encryption or RS yet.
"""
import argparse
import csv
import hashlib
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image
from dwt_probe import embed, extract, jpeg_roundtrip, psnr


def ints(value):
    return [int(x.strip()) for x in value.split(',') if x.strip()]


def floats(value):
    return [float(x.strip()) for x in value.split(',') if x.strip()]


def message_of_size(size):
    # Exact UTF-8 byte length, with multibyte text and reproducible opaque data.
    prefix = 'Cryptoleaf – ääkköset, 漢字, 🌿 | '.encode('utf-8')
    if size < len(prefix):
        return prefix[:size]  # intended test sizes are >= 50
    needed = size - len(prefix)
    output = bytearray(prefix)
    counter = 0
    while len(output) < size:
        output.extend(hashlib.sha256(f'dwt-capacity-{counter}'.encode()).digest())
        counter += 1
    return bytes(output[:size])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--sizes', default='50,200,500,1000,2000', help='Payload bytes (not characters)')
    p.add_argument('--deltas', default='20,32')
    p.add_argument('--repeat', type=int, default=9)
    p.add_argument('--quality', type=int, default=85)
    p.add_argument('--resize', default='100,99,90,75')
    p.add_argument('--recompress', default='none,60')
    p.add_argument('--seed', type=int, default=20261114)
    p.add_argument('--csv', type=Path, default=Path('dwt_capacity.csv'))
    args = p.parse_args()
    sizes, deltas, resizes = ints(args.sizes), floats(args.deltas), ints(args.resize)
    recompress = [None if s.strip().lower() == 'none' else int(s.strip()) for s in args.recompress.split(',')]
    if not sizes or any(n < 50 or n > 65535 for n in sizes): p.error('sizes must be 50..65535 bytes')
    if not deltas or any(d <= 0 for d in deltas): p.error('deltas must be positive')
    if args.repeat < 1 or args.repeat % 2 == 0: p.error('repeat must be a positive odd integer')
    if not 1 <= args.quality <= 100: p.error('quality must be 1..100')
    if not resizes or any(not 1 <= x <= 100 for x in resizes): p.error('resize must be 1..100')
    if any(q is not None and not 1 <= q <= 100 for q in recompress): p.error('recompress qualities must be 1..100')
    if not args.image.is_file(): p.error(f'image not found: {args.image}')

    with Image.open(args.image) as im:
        original = im.convert('RGB')
    # Haar level-2 LL with periodization: ceil(ceil(w/2)/2) * ceil(ceil(h/2)/2)
    w, h = original.size
    capacity_coefficients = ((w + 3) // 4) * ((h + 3) // 4)
    max_payload = capacity_coefficients // (8 * args.repeat) - 10  # magic(4), length(2), crc(4)
    print(f'Image {w}x{h}; LL coefficients {capacity_coefficients}; theoretical payload limit {max_payload} bytes at repeat={args.repeat}')
    print('Oracle alignment: original dimensions are supplied to decoder. Not a social-media compatibility guarantee.\n')
    rows = []
    for size in sizes:
        message = message_of_size(size)
        required = (size + 10) * 8 * args.repeat
        for delta in deltas:
            start = time.perf_counter()
            try:
                encoded = embed(original, message, delta, args.repeat, args.seed)
                saved = jpeg_roundtrip(encoded, args.quality)
                base_psnr = psnr(original, saved)
                encode_error = ''
            except Exception as exc:
                saved = None
                base_psnr = None
                encode_error = f'{type(exc).__name__}: {exc}'
            elapsed = round(time.perf_counter() - start, 3)
            for scale in resizes:
                for quality in recompress:
                    success = False
                    error = encode_error
                    if saved is not None:
                        try:
                            processed = saved
                            if scale != 100:
                                newsize = (max(1, round(w * scale / 100)), max(1, round(h * scale / 100)))
                                processed = saved.resize(newsize, Image.Resampling.LANCZOS)
                            if quality is not None:
                                processed = jpeg_roundtrip(processed, quality)
                            decoded = extract(processed, original.size, delta, args.repeat, args.seed, max_bytes=max(sizes))
                            success = decoded == message
                            error = '' if success else 'MessageMismatch'
                        except Exception as exc:
                            error = f'{type(exc).__name__}: {exc}'
                    row = dict(message_bytes=size, delta=delta, repeat=args.repeat,
                               save_quality=args.quality, resize_percent=scale,
                               recompress_quality='none' if quality is None else quality,
                               pass_decode=success, psnr_db='' if base_psnr is None else round(base_psnr, 3),
                               required_coefficients=required, available_coefficients=capacity_coefficients,
                               encode_seconds=elapsed, error=error)
                    rows.append(row)
                    print(f'{size:5d} bytes  delta={delta:g}  resize={scale:3d}%  jpeg={str(quality):>4}  {"PASS" if success else "FAIL"} {error}')
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'\n{sum(r["pass_decode"] for r in rows)}/{len(rows)} passed. Results: {args.csv}')


if __name__ == '__main__':
    main()
