#!/usr/bin/env python3
"""DWT-QIM resolution benchmark. Standalone experiment, NOT Cryptoleaf format.

Uses unchanged embed/extract functions from dwt_probe.py. Creates a distinct
cover image at each resolution BEFORE embedding. Decoder is given that cover's
exact dimensions (oracle). Capacity skips are not decoding failures.
"""
import argparse
import csv
import time
from pathlib import Path

from PIL import Image, ImageOps
from dwt_probe import embed, extract, jpeg_roundtrip, psnr
from dwt_capacity_benchmark import message_of_size


def numbers(raw, kind=int):
    return [kind(x.strip()) for x in raw.split(',') if x.strip()]


def resolutions(raw):
    out = []
    for token in raw.split(','):
        try:
            w, h = (int(v) for v in token.strip().lower().split('x'))
            if min(w, h) < 16:
                raise ValueError()
        except (ValueError, TypeError):
            raise argparse.ArgumentTypeError(f'Invalid resolution: {token!r}; use WIDTHxHEIGHT')
        out.append((w, h))
    if not out:
        raise argparse.ArgumentTypeError('At least one resolution required')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--resolutions', type=resolutions, default=resolutions('3000x4000,1920x1080,1280x720,640x480'))
    p.add_argument('--sizes', default='50,200,500,1000,2000')
    p.add_argument('--deltas', default='20,32')
    p.add_argument('--repeat', type=int, default=9)
    p.add_argument('--quality', type=int, default=85)
    p.add_argument('--resize', default='100,99,90,75', help='Percent AFTER embedding')
    p.add_argument('--recompress', default='none,60')
    p.add_argument('--seed', type=int, default=20261114)
    p.add_argument('--csv', type=Path, default=Path('dwt_resolution.csv'))
    args = p.parse_args()
    sizes = numbers(args.sizes)
    deltas = numbers(args.deltas, float)
    scales = numbers(args.resize)
    recompress = [None if x.strip().lower() == 'none' else int(x.strip()) for x in args.recompress.split(',')]
    if not sizes or any(n < 50 or n > 65535 for n in sizes): p.error('--sizes must be 50..65535')
    if not deltas or any(d <= 0 for d in deltas): p.error('--deltas must be positive')
    if args.repeat < 1 or args.repeat % 2 == 0: p.error('--repeat must be positive and odd')
    if not 1 <= args.quality <= 100: p.error('--quality must be 1..100')
    if not scales or any(s < 1 or s > 100 for s in scales): p.error('--resize must be 1..100')
    if not recompress or any(q is not None and not 1 <= q <= 100 for q in recompress): p.error('--recompress must be none or 1..100')
    if not args.image.is_file(): p.error(f'Image not found: {args.image}')

    with Image.open(args.image) as source:
        source = ImageOps.exif_transpose(source).convert('RGB')
    print(f'Source: {source.width}x{source.height}. Each target uses center crop + Lanczos resize BEFORE embedding.')
    print('Decode uses known cover dimensions (oracle). No AES-GCM or Reed-Solomon.\n')
    rows = []
    for target_w, target_h in args.resolutions:
        cover = ImageOps.fit(source, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        available = ((target_w + 3) // 4) * ((target_h + 3) // 4)
        max_bytes = max(0, available // (8 * args.repeat) - 10)
        print(f'\n{target_w}x{target_h}: LL2={available:,} coefficients, theoretical max={max_bytes:,} bytes')
        for size in sizes:
            message = message_of_size(size)
            required = (size + 10) * 8 * args.repeat
            for delta in deltas:
                encoded = None
                error = ''
                quality_psnr = ''
                encode_seconds = ''
                if required <= available:
                    t0 = time.perf_counter()
                    try:
                        encoded = jpeg_roundtrip(embed(cover, message, delta, args.repeat, args.seed), args.quality)
                        quality_psnr = round(psnr(cover, encoded), 3)
                    except Exception as exc:
                        error = f'{type(exc).__name__}: {exc}'
                    encode_seconds = round(time.perf_counter() - t0, 3)
                else:
                    error = 'CAPACITY_EXCEEDED'
                for scale in scales:
                    for q in recompress:
                        status = 'SKIP_CAPACITY' if required > available else ('ERROR_ENCODE' if encoded is None else 'FAIL')
                        detail = error
                        if encoded is not None:
                            try:
                                processed = encoded
                                if scale != 100:
                                    new_size = (max(1, round(target_w * scale / 100)), max(1, round(target_h * scale / 100)))
                                    processed = processed.resize(new_size, Image.Resampling.LANCZOS)
                                if q is not None:
                                    processed = jpeg_roundtrip(processed, q)
                                decoded = extract(processed, cover.size, delta, args.repeat, args.seed, max_bytes=max(sizes))
                                if decoded == message:
                                    status, detail = 'PASS', ''
                                else:
                                    detail = 'MessageMismatch'
                            except Exception as exc:
                                detail = f'{type(exc).__name__}: {exc}'
                        rows.append(dict(width=target_w, height=target_h, message_bytes=size, delta=delta,
                                         repeat=args.repeat, save_quality=args.quality, resize_percent=scale,
                                         recompress_quality='none' if q is None else q,
                                         status=status, pass_decode=status == 'PASS', psnr_db=quality_psnr,
                                         required_coefficients=required, available_coefficients=available,
                                         theoretical_max_payload_bytes=max_bytes,
                                         encode_seconds=encode_seconds, error=detail))
                        print(f'{target_w}x{target_h} {size:4d} B delta={delta:g} resize={scale:3d}% jpeg={str(q):>4}: {status} {detail}')
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    tested = [r for r in rows if r['status'] in ('PASS', 'FAIL')]
    print(f'\nDecode: {sum(r["pass_decode"] for r in tested)}/{len(tested)} passed; capacity skips: {sum(r["status"] == "SKIP_CAPACITY" for r in rows)}; CSV: {args.csv}')


if __name__ == '__main__':
    main()
