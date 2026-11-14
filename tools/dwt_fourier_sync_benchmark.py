#!/usr/bin/env python3
"""Cryptoleaf research: blind DWT size search versus reference-assisted Fourier-Mellin.

NOT a self-contained Fourier synchronization watermark. The Fourier-Mellin arm
uses the encoded image as a reference (oracle); blind arm uses candidate sizes
and validates DWT packet CRC. No EXIF information is used.

Dependencies: numpy Pillow PyWavelets opencv-python.
Place alongside dwt_probe.py. Does not modify Cryptoleaf production code.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from dwt_probe import embed, extract, jpeg_roundtrip, psnr

try:
    import cv2
except ImportError:
    cv2 = None


def parse_sizes(s):
    sizes = []
    for token in s.split(','):
        w, h = token.strip().lower().split('x')
        sizes.append((int(w), int(h)))
    return sizes


def gray_float(image):
    return np.asarray(image.convert('L'), dtype=np.float32)


def logpolar_spectrum(image, side=512):
    """Normalized log-magnitude DFT in log-polar coordinates (for phase correlation)."""
    if cv2 is None:
        raise RuntimeError('OpenCV missing: pip install opencv-python')
    arr = gray_float(image)
    # Fixed canvas: avoid shape-dependent frequency grids when comparing sizes.
    arr = cv2.resize(arr, (side, side), interpolation=cv2.INTER_AREA)
    arr = (arr - arr.mean()) * cv2.createHanningWindow((side, side), cv2.CV_32F)
    spectrum = np.fft.fftshift(np.fft.fft2(arr))
    magnitude = np.log1p(np.abs(spectrum)).astype(np.float32)
    center = (side / 2.0, side / 2.0)
    max_radius = side / 2.0
    polar = cv2.warpPolar(magnitude, (side, side), center, max_radius,
                          cv2.WARP_POLAR_LOG | cv2.WARP_FILL_OUTLIERS)
    polar -= polar.mean()
    return polar


def fourier_mellin_reference_score(reference, observed):
    """Diagnostic log-polar DFT phase correlation; reference image REQUIRED.

    Note: resizing both images to a common canvas makes global resize largely
    invisible to this comparison. The returned shift is NOT a calibrated
    original-size estimate. This is a similarity diagnostic only.
    """
    a = logpolar_spectrum(reference)
    b = logpolar_spectrum(observed)
    shift, response = cv2.phaseCorrelate(a, b)
    return float(shift[0]), float(shift[1]), float(response)


def trial_decode(image, candidates, delta, repeat, seed, max_bytes, message):
    errors = []
    for size in candidates:
        try:
            recovered = extract(image, size, delta, repeat, seed, max_bytes=max_bytes)
            if recovered == message:
                return size, 'PASS', ''
            errors.append(f'{size[0]}x{size[1]}:MessageMismatch')
        except Exception as exc:
            errors.append(f'{size[0]}x{size[1]}:{type(exc).__name__}')
    return None, 'FAIL', ';'.join(errors[:4])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image', type=Path)
    ap.add_argument('--sources', default='1920x1080,1280x720,640x480', help='Source sizes; original image center-cropped to each aspect ratio')
    ap.add_argument('--candidates', default=None, help='Blind candidate sizes (default: source size list); avoid treating as unknown unrestricted dimensions')
    ap.add_argument('--resize', default='100,99,90,75')
    ap.add_argument('--recompress', default='none,60')
    ap.add_argument('--bytes', type=int, default=50)
    ap.add_argument('--delta', type=float, default=32)
    ap.add_argument('--repeat', type=int, default=9)
    ap.add_argument('--seed', type=int, default=20261114)
    ap.add_argument('--quality', type=int, default=85)
    ap.add_argument('--csv', type=Path, default=Path('dwt_fourier_sync.csv'))
    ap.add_argument('--no-fourier', action='store_true', help='Run only blind candidate-size search (OpenCV not needed)')
    args = ap.parse_args()
    if args.bytes < 1 or args.bytes > 65535:
        ap.error('--bytes must be 1..65535')
    if args.repeat < 1 or args.repeat % 2 == 0:
        ap.error('--repeat must be positive and odd')
    if not args.no_fourier and cv2 is None:
        ap.error('Install OpenCV (python -m pip install opencv-python) or pass --no-fourier')
    sources = parse_sizes(args.sources)
    candidates = parse_sizes(args.candidates) if args.candidates else sources
    scales = [int(v) for v in args.resize.split(',')]
    recompress = [None if v == 'none' else int(v) for v in args.recompress.split(',')]
    if any(v < 1 or v > 100 for v in scales):
        ap.error('--resize percentages must be 1..100')
    source = Image.open(args.image).convert('RGB')
    # Fixed UTF-8 prefix, deterministic byte filler. Payload is bytes (not encryption).
    prefix = 'Cryptoleaf äöå 🌿 '.encode('utf-8')
    message = (prefix + bytes((i * 37 + 13) % 256 for i in range(args.bytes)))[:args.bytes]
    rows = []
    for width, height in sources:
        ratio = width / height
        sw, sh = source.size
        if sw / sh > ratio:
            cw, ch = round(sh * ratio), sh
        else:
            cw, ch = sw, round(sw / ratio)
        left = (sw - cw) // 2
        top = (sh - ch) // 2
        base = source.crop((left, top, left + cw, top + ch)).resize((width, height), Image.Resampling.LANCZOS)
        available = ((width + 3) // 4) * ((height + 3) // 4)
        needed = (args.bytes + 10) * 8 * args.repeat
        if needed > available:
            print(f'{width}x{height}: SKIP_CAPACITY need={needed} available={available}')
            for pct in scales:
                for q in recompress:
                    rows.append(dict(source_size=f'{width}x{height}', message_bytes=args.bytes,
                                     resize_percent=pct, recompress_quality=q if q is not None else 'none',
                                     status='SKIP_CAPACITY', found_size='', blind_error='',
                                     fm_shift_x='', fm_shift_y='', fm_response='',
                                     psnr_db='', needed=needed, available=available))
            continue
        encoded = embed(base, message, args.delta, args.repeat, args.seed)
        saved = jpeg_roundtrip(encoded, args.quality)
        quality = psnr(base, saved)
        for pct in scales:
            for q in recompress:
                target = (max(1, round(width * pct / 100)), max(1, round(height * pct / 100)))
                processed = saved if pct == 100 else saved.resize(target, Image.Resampling.LANCZOS)
                if q is not None:
                    processed = jpeg_roundtrip(processed, q)
                found, status, error = trial_decode(processed, candidates, args.delta, args.repeat,
                                                    args.seed, args.bytes, message)
                fx = fy = response = ''
                if not args.no_fourier:
                    try:
                        fx, fy, response = fourier_mellin_reference_score(saved, processed)
                    except Exception as exc:
                        error += f';FourierError:{type(exc).__name__}'
                rows.append(dict(source_size=f'{width}x{height}', message_bytes=args.bytes,
                                 resize_percent=pct, recompress_quality=q if q is not None else 'none',
                                 status=status, found_size=f'{found[0]}x{found[1]}' if found else '',
                                 blind_error=error, fm_shift_x=fx, fm_shift_y=fy,
                                 fm_response=response, psnr_db=round(quality, 3),
                                 needed=needed, available=available))
                print(f'{width}x{height} -> {target[0]}x{target[1]} jpeg={str(q):>4}: '
                      f'{status:>4} found={str(found):>12} FM_response={str(round(response, 3)) if response != "" else "n/a"}')
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    valid = [r for r in rows if r['status'] != 'SKIP_CAPACITY']
    passed = sum(r['status'] == 'PASS' for r in valid)
    print(f'\nBlind candidate-size recovery: {passed}/{len(valid)} passed; CSV: {args.csv}')
    print('IMPORTANT: Blind search is limited to --candidates; Fourier arm uses a reference image.')
    print('Fourier shifts are NOT estimates of original dimensions; this script does NOT implement a Fourier pilot.')


if __name__ == '__main__':
    main()
