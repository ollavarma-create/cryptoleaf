#!/usr/bin/env python3
"""Blind Fourier radial-pilot scale experiment (NOT a production steganography codec).

A known pseudo-random sequence of narrow frequency rings is embedded in the
luminance Fourier magnitude. Decoder has only the attacked image and the public
ring template, never the original image, its dimensions, or the true scale.

WARNING: the pilot is detectable and this is watermark/synchronization research.
"""
import argparse
import csv
import io
from pathlib import Path
import numpy as np
from PIL import Image

SEED = 20261114
# Frequencies in cycles per pixel; fixed absolute coordinates in the *encoded* image.
RADII = np.linspace(0.055, 0.195, 32)
RING_SIGMA = 0.00085

def pilot_template(shape):
    h, w = shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    radius = np.hypot(fx, fy).astype(np.float32)
    rng = np.random.default_rng(SEED)
    signs = rng.choice([-1., 1.], size=len(RADII))
    # Narrow rings; zero mean in the radial direction after local detrending.
    out = np.zeros(shape, np.float32)
    for r, sign in zip(RADII, signs):
        out += sign * np.exp(-0.5 * ((radius-r)/RING_SIGMA)**2)
    return out

def embed(image, strength):
    ycbcr = np.asarray(image.convert('YCbCr'), dtype=np.uint8).copy()
    y = ycbcr[:, :, 0].astype(np.float32)
    f = np.fft.fft2(y)
    # Multiplicative magnitude modulation preserves the original phase and
    # Fourier conjugate symmetry; large natural-image coefficients carry pilot.
    pilot = pilot_template(y.shape)
    f *= np.exp(strength * pilot)
    new_y = np.fft.ifft2(f).real
    clipped = np.clip(np.rint(new_y), 0, 255).astype(np.uint8)
    ycbcr[:, :, 0] = clipped
    return Image.fromarray(ycbcr, 'YCbCr').convert('RGB')

def radial_profile(image, bins=1800, max_freq=0.38):
    y = np.asarray(image.convert('L'), dtype=np.float32)
    h, w = y.shape
    # Window suppresses hard image-boundary discontinuities.
    win = np.hanning(h)[:, None] * np.hanning(w)[None, :]
    f = np.fft.rfft2((y-y.mean())*win)
    mag = np.log1p(np.abs(f)).astype(np.float32)
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    radius = np.hypot(fy, fx)
    idx = np.floor(radius/max_freq*bins).astype(np.int32)
    good = idx < bins
    sums = np.bincount(idx[good].ravel(), weights=mag[good].ravel(), minlength=bins)
    counts = np.bincount(idx[good].ravel(), minlength=bins)
    profile = sums / np.maximum(counts, 1)
    # Local background subtraction (high-pass in radial frequency).
    from scipy.ndimage import gaussian_filter1d
    return profile - gaussian_filter1d(profile, sigma=13)

def estimate_scale(image, low=0.70, high=1.02, step=0.002):
    profile = radial_profile(image)
    bin_freq = (np.arange(len(profile))+0.5) * (0.38/len(profile))
    rng = np.random.default_rng(SEED)
    signs = rng.choice([-1., 1.], size=len(RADII))
    # A scaled image moves embedded ring frequencies to radius / scale.
    # Estimate the pilot using positive and negative ring contrasts.
    scales = np.arange(low, high + step/2, step)
    scores = []
    for scale in scales:
        locs = RADII/scale
        at = np.interp(locs, bin_freq, profile)
        # remove smooth local spectral bias and normalize the observation
        score = float(np.dot(signs, at) / (np.linalg.norm(at)*np.linalg.norm(signs)+1e-12))
        scores.append(score)
    ix = int(np.argmax(scores))
    return float(scales[ix]), float(scores[ix]), float(np.median(scores)), float(np.std(scores))

def jpeg_roundtrip(image, quality):
    buf = io.BytesIO()
    image.save(buf, format='JPEG', quality=quality, subsampling=0)
    buf.seek(0)
    with Image.open(buf) as im:
        return im.convert('RGB')

def psnr(a,b):
    x=np.asarray(a,dtype=np.float32); y=np.asarray(b,dtype=np.float32)
    mse=float(np.mean((x-y)**2))
    return float('inf') if mse==0 else 10*np.log10(255**2/mse)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('--csv',type=Path,default=Path('fourier_blind_pilot.csv'))
    p.add_argument('--strength',type=float,default=0.18,help='Log magnitude modulation strength (default 0.18)')
    p.add_argument('--sizes',default='1280x720,640x480',help='Comma-separated WxH')
    p.add_argument('--scales',default='100,99,90,75')
    p.add_argument('--jpeg',default='none,60',help='JPEG quality or none')
    p.add_argument('--tolerance',type=float,default=2.0,help='Allowed error in percentage points')
    p.add_argument('--save-example',type=Path,default=None)
    args=p.parse_args()
    sizes=[]
    for s in args.sizes.split(','):
        w,h=map(int,s.lower().split('x')); sizes.append((w,h))
    scales=[float(s)/100 for s in args.scales.split(',')]
    qualities=[None if s.strip().lower()=='none' else int(s) for s in args.jpeg.split(',')]
    fields=['width','height','pilot','strength','true_percent','jpeg_quality','estimated_percent','abs_error_pp','score','score_median','score_std','pass_scale','psnr_db']
    rows=[]
    with Image.open(args.image) as source:
        source=source.convert('RGB')
        for w,h in sizes:
            # Center-crop source to requested aspect ratio to avoid distortion.
            sw,sh=source.size; aspect=w/h
            if sw/sh>aspect:
                cw=int(round(sh*aspect)); box=((sw-cw)//2,0,(sw-cw)//2+cw,sh)
            else:
                ch=int(round(sw/aspect)); box=(0,(sh-ch)//2,sw,(sh-ch)//2+ch)
            base=source.crop(box).resize((w,h),Image.Resampling.LANCZOS)
            for enabled in [False,True]:
                marked=embed(base,args.strength) if enabled else base
                quality=psnr(base,marked)
                if enabled and args.save_example:
                    args.save_example.parent.mkdir(parents=True,exist_ok=True)
                    marked.save(args.save_example.with_name(f'{args.save_example.stem}_{w}x{h}.png'))
                for scale in scales:
                    size=(max(32,round(w*scale)),max(32,round(h*scale)))
                    attacked=marked.resize(size,Image.Resampling.LANCZOS) if size!=(w,h) else marked
                    for jq in qualities:
                        candidate=jpeg_roundtrip(attacked,jq) if jq is not None else attacked
                        estimate,score,median,std=estimate_scale(candidate)
                        err=abs(100*(estimate-scale))
                        row=dict(width=w,height=h,pilot=int(enabled),strength=args.strength,
                                 true_percent=round(scale*100,3),jpeg_quality=jq if jq else 'none',
                                 estimated_percent=round(estimate*100,3),abs_error_pp=round(err,3),
                                 score=round(score,5),score_median=round(median,5),score_std=round(std,5),
                                 pass_scale=int(err<=args.tolerance),psnr_db=round(quality,3))
                        rows.append(row)
                        print(f'{w}x{h} pilot={int(enabled)} scale={scale*100:5.1f}% jpeg={str(jq):>4} '
                              f'est={estimate*100:6.2f}% err={err:5.2f}pp score={score:+.3f} '
                              f'{"PASS" if row["pass_scale"] else "FAIL"}',flush=True)
    args.csv.parent.mkdir(parents=True,exist_ok=True)
    with args.csv.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    print(f'\nCSV: {args.csv} ({len(rows)} rows)')
    for enabled in (0,1):
        subset=[r for r in rows if r['pilot']==enabled]
        print(f'pilot={enabled}: {sum(r["pass_scale"] for r in subset)}/{len(subset)} pass; '
              f'mean error={np.mean([r["abs_error_pp"] for r in subset]):.2f} pp')
    print('CAUTION: no reference image used by decoder; natural image can produce false positives. '
          'Pilot detection requires separate calibration on many unrelated images.')

if __name__=='__main__':
    main()
