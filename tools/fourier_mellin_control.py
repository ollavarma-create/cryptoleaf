#!/usr/bin/env python3
"""Reference-based Fourier-Mellin SCALE control, no DWT or steganography.

Both images are placed at their *native pixel sizes* on a common zero-padded
canvas. Crucially, the transformed image is NOT resized back to reference size.
A log-polar FFT magnitude converts isotropic scaling into a horizontal shift.
The reference image is REQUIRED: this is not a blind decoder.
"""
import argparse
import csv
from pathlib import Path
import cv2
import numpy as np
from PIL import Image


def spectrum(image, side):
    # Native-pixel placement on same canvas; centered, no resampling.
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY).astype(np.float32)
    h, w = gray.shape
    if h > side or w > side:
        raise ValueError('Image larger than FFT canvas')
    gray -= gray.mean()
    gray *= cv2.createHanningWindow((w, h), cv2.CV_32F)
    canvas = np.zeros((side, side), np.float32)
    y, x = (side-h)//2, (side-w)//2
    canvas[y:y+h, x:x+w] = gray
    f = np.fft.fftshift(np.fft.fft2(canvas))
    mag = np.log1p(np.abs(f)).astype(np.float32)
    # Suppress strong low frequencies and edges of the Fourier plane.
    cy = cx = side//2
    yy, xx = np.ogrid[:side, :side]
    r = np.hypot(xx-cx, yy-cy)
    mag[(r < 6) | (r > side*0.46)] = 0
    return mag


def estimate(ref, transformed, side=1024, radial_bins=512, angular_bins=720):
    s1, s2 = spectrum(ref, side), spectrum(transformed, side)
    radius = side * 0.46
    size = (radial_bins, angular_bins)  # x=log(radius), y=angle
    flags = cv2.WARP_POLAR_LOG | cv2.WARP_FILL_OUTLIERS | cv2.INTER_LINEAR
    center = (side/2, side/2)
    a = cv2.warpPolar(s1, size, center, radius, flags)
    b = cv2.warpPolar(s2, size, center, radius, flags)
    # Remove radial mean and suppress near-origin bins.
    a[:, :int(radial_bins*0.23)] = 0
    b[:, :int(radial_bins*0.23)] = 0
    a -= a.mean(axis=0, keepdims=True)
    b -= b.mean(axis=0, keepdims=True)
    win = cv2.createHanningWindow((radial_bins, angular_bins), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, win)
    klog = radial_bins / np.log(radius)
    # Scaling spatial image by s moves Fourier magnitude radially by s^-1.
    scale = float(np.exp(-dx / klog))
    return scale, float(dx), float(dy), float(response)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--scales', default='100,99,90,75')
    p.add_argument('--qualities', default='none,60')
    p.add_argument('--sizes', default='1280x720,640x480')
    p.add_argument('--canvas', type=int, default=2048)
    p.add_argument('--csv', type=Path, default=Path('fourier_mellin_control.csv'))
    args = p.parse_args()
    src = Image.open(args.image).convert('RGB')
    scales = [int(x) for x in args.scales.split(',')]
    qualities = [None if x=='none' else int(x) for x in args.qualities.split(',')]
    rows=[]
    for spec in args.sizes.split(','):
        w,h=map(int,spec.lower().split('x'))
        if max(w,h) > args.canvas:
            print(f'{spec}: skipped (larger than --canvas {args.canvas}); choose --canvas 2048')
            continue
        ratio=w/h; sw,sh=src.size
        if sw/sh > ratio: cw,ch=round(sh*ratio),sh
        else: cw,ch=sw,round(sw/ratio)
        base=src.crop(((sw-cw)//2,(sh-ch)//2,(sw-cw)//2+cw,(sh-ch)//2+ch)).resize((w,h),Image.Resampling.LANCZOS)
        for pct in scales:
            tw,th=max(1,round(w*pct/100)),max(1,round(h*pct/100))
            transformed=base.resize((tw,th),Image.Resampling.LANCZOS)
            for q in qualities:
                test=transformed
                if q is not None:
                    import io
                    buf=io.BytesIO(); test.save(buf,format='JPEG',quality=q,subsampling=0)
                    buf.seek(0); test=Image.open(buf).convert('RGB')
                try:
                    estimated,dx,dy,response=estimate(base,test,side=args.canvas)
                    error=100*(estimated-pct/100)
                    status='PASS' if abs(error)<=2 else 'FAIL'
                    row=dict(source_size=spec,scale_percent=pct,jpeg_quality=q if q is not None else 'none',
                             estimated_percent=round(estimated*100,3),error_percentage_points=round(error,3),
                             shift_log_radius=round(dx,4),shift_angle=round(dy,4),response=round(response,5),status=status)
                except Exception as exc:
                    row=dict(source_size=spec,scale_percent=pct,jpeg_quality=q if q is not None else 'none',
                             estimated_percent='',error_percentage_points='',shift_log_radius='',shift_angle='',response='',status=f'ERROR:{type(exc).__name__}')
                rows.append(row)
                print(f'{spec:>10} {pct:>3}% jpeg={str(q):>4} -> estimated {str(row["estimated_percent"]):>8}%  {row["status"]}')
    if not rows: raise SystemExit('No tests: increase --canvas or select smaller --sizes')
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
    print(f'\n{sum(r["status"]=="PASS" for r in rows)}/{len(rows)} within ±2 percentage points. CSV: {args.csv}')
    print('Reference-based control only. Failure is informative; no Fourier pilot is embedded.')

if __name__=='__main__': main()
