#!/usr/bin/env python3
"""Cryptoleaf CLR1 real-photo pilot. Run from project root: python tools/robust_photo_pilot.py --images ~/Pictures/DWTFourierTesti --limit 10

Results are diagnostic, not comparable to the original DWT1 payload benchmark without accounting for packet length.
"""
import argparse
import csv
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from src.robust_image import encode, decode, decode_at_size

ATTACKS = ((1.0, False), (1.0, True), (.9, False), (.9, True), (.75, False), (.75, True))
MESSAGE = b"Cryptoleaf Fourier DWT RS8 validation message"
MESSAGE = MESSAGE.ljust(50, b" ")
assert len(MESSAGE) == 50

def jpeg(image, quality):
    f = io.BytesIO()
    image.save(f, format='JPEG', quality=quality, subsampling=0)
    f.seek(0)
    with Image.open(f) as im:
        return im.convert('RGB')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--limit', type=int, default=10)
    p.add_argument('--output', type=Path, default=Path('robust_photo_pilot.csv'))
    p.add_argument('--longest', type=int, default=1280)
    args = p.parse_args()
    files = sorted(x for x in args.images.iterdir() if x.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'} and x.is_file())[:args.limit]
    if not files:
        p.error('No supported images found')
    rows = []
    for i, path in enumerate(files, 1):
        print(f'[{i}/{len(files)}] {path.name}', flush=True)
        try:
            with Image.open(path) as f:
                cover = ImageOps.exif_transpose(f).convert('RGB')
            marked = encode(cover, MESSAGE, longest=args.longest)
            base = jpeg(marked, 85)
            # PSNR measures original cover rescaled to marked size vs marked image.
            reference = cover.resize(marked.size, Image.Resampling.LANCZOS) if cover.size != marked.size else cover
            a = np.asarray(reference, dtype=np.float32)
            b = np.asarray(marked, dtype=np.float32)
            mse = float(np.mean((a - b) ** 2))
            psnr = float('inf') if mse == 0 else 10 * np.log10(255 * 255 / mse)
            for scale, recompress in ATTACKS:
                received = base
                if scale != 1.0:
                    received = received.resize(tuple(max(1, round(v * scale)) for v in base.size), Image.Resampling.LANCZOS)
                if recompress:
                    received = jpeg(received, 60)
                t0 = time.perf_counter()
                try:
                    result = decode(received)
                    blind_ok = result.payload == MESSAGE
                    attempts = result.attempts
                    size_found = str(result.original_size)
                    blind_error = ''
                except Exception as exc:
                    blind_ok, attempts, size_found = False, '', ''
                    blind_error = f'{type(exc).__name__}: {exc}'
                ms = round((time.perf_counter() - t0) * 1000, 1)
                try:
                    oracle_ok = decode_at_size(received, marked.size) == MESSAGE
                    oracle_error = ''
                except Exception as exc:
                    oracle_ok = False
                    oracle_error = f'{type(exc).__name__}: {exc}'
                rows.append(dict(image=path.name, original_size=str(cover.size), embedded_size=str(marked.size), received_size=str(received.size), scale=scale, jpeg60=recompress, blind_ok=blind_ok, oracle_ok=oracle_ok, attempts=attempts, blind_ms=ms, psnr_db=round(psnr, 2), found_size=size_found, blind_error=blind_error, oracle_error=oracle_error))
                print(f'  {scale:.0%} JPEG60={recompress}: blind={blind_ok}, oracle={oracle_ok}, {ms:.0f}ms', flush=True)
        except Exception as exc:
            print(f'  ENCODE ERROR: {type(exc).__name__}: {exc}', flush=True)
            for scale, recompress in ATTACKS:
                rows.append(dict(image=path.name, scale=scale, jpeg60=recompress, blind_ok=False, oracle_ok=False, blind_error=f'ENCODE: {type(exc).__name__}: {exc}'))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('w', newline='', encoding='utf-8') as out:
            writer = csv.DictWriter(out, fieldnames=['image','original_size','embedded_size','received_size','scale','jpeg60','blind_ok','oracle_ok','attempts','blind_ms','psnr_db','found_size','blind_error','oracle_error'])
            writer.writeheader()
            writer.writerows(rows)
    print(f'Blind: {sum(r["blind_ok"] for r in rows)}/{len(rows)}; oracle: {sum(r["oracle_ok"] for r in rows)}/{len(rows)}; CSV: {args.output}')

if __name__ == '__main__':
    main()
