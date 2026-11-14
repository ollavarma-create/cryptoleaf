"""Experimental Cryptoleaf Fourier/DWT image transport (no GUI or encryption).

Implements the measured baseline pilot, LL2 Feedback-QIM, RS8 CLR1 packet,
and Priority50 blind size search. This is not a secrecy or steganalysis guarantee.
Do not change parameters without a new paired robustness benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pywt
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from .robust_packet import pack, unpack, HEADER_BYTES, MAX_CODEWORD

SEED = 20261114
RADII = np.linspace(0.055, 0.195, 32)
SIGMA = 0.00085
STRENGTH = 0.18
DELTA = 32.0
REPEAT = 9
FEEDBACK_ITERATIONS = 6
MAX_LONGEST = 1280
# Reject oversized images before allocating FFT/DWT working arrays.
MAX_DECODE_PIXELS = MAX_LONGEST * MAX_LONGEST


@dataclass(frozen=True)
class DecodeResult:
    payload: bytes
    original_size: tuple[int, int]
    attempts: int


def _pilot_template(shape):
    h, w = shape
    radius = np.hypot(np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]).astype(np.float32)
    signs = np.random.default_rng(SEED).choice([-1., 1.], size=len(RADII))
    out = np.zeros(shape, np.float32)
    for r, sign in zip(RADII, signs):
        out += sign * np.exp(-0.5 * ((radius - r) / SIGMA)**2)
    return out


def _pilot_embed(image):
    a = np.asarray(image.convert('YCbCr'), dtype=np.uint8).copy()
    fft = np.fft.fft2(a[:, :, 0].astype(np.float32))
    fft *= np.exp(STRENGTH * _pilot_template(a.shape[:2]))
    a[:, :, 0] = np.clip(np.rint(np.fft.ifft2(fft).real), 0, 255).astype(np.uint8)
    return Image.fromarray(a, 'YCbCr').convert('RGB')


def _ycc(image):
    return np.asarray(image.convert('YCbCr'), dtype=np.float64).copy()


def _from_ycc(a):
    return Image.fromarray(np.uint8(np.clip(np.rint(a), 0, 255)), 'YCbCr').convert('RGB')


def _feedback_embed(image, packet):
    a = _ycc(image)
    coeffs = pywt.wavedec2(a[:, :, 0], 'haar', level=2, mode='periodization')
    ll = coeffs[0].copy()
    flat = ll.ravel()
    bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    count = len(bits) * REPEAT
    if count > flat.size:
        raise ValueError(f'Insufficient robust capacity: need {count} LL2 coefficients, have {flat.size}')
    positions = np.random.default_rng(SEED).permutation(flat.size)[:count]
    target = np.repeat(bits, REPEAT).astype(np.int64)
    q = np.rint(flat[positions] / DELTA).astype(np.int64)
    q += (target - (q & 1)) % 2
    for iteration in range(FEEDBACK_ITERATIONS + 1):
        flat[positions] = q * DELTA
        coeffs[0] = ll
        reconstructed = pywt.waverec2(coeffs, 'haar', mode='periodization')
        out = a.copy()
        out[:, :, 0] = np.clip(reconstructed[:a.shape[0], :a.shape[1]], 0, 255)
        result = _from_ycc(out)
        observed_ll = pywt.wavedec2(_ycc(result)[:, :, 0], 'haar', level=2, mode='periodization')[0].ravel()
        wrong = (np.rint(observed_ll[positions] / DELTA).astype(np.int64) & 1) != target
        if not wrong.any() or iteration == FEEDBACK_ITERATIONS:
            return result
        q[wrong] -= 2
    raise AssertionError('unreachable')


def encode(image: Image.Image, payload: bytes, longest: int = MAX_LONGEST) -> Image.Image:
    """Embed an RS8 packet in a new RGB image. Caller saves it (JPEG85, subsampling=0 for benchmark parity)."""
    if longest < 32:
        raise ValueError('longest must be >= 32')
    image = ImageOps.exif_transpose(image).convert('RGB')
    scale = min(1.0, longest / max(image.size))
    if scale < 1:
        image = image.resize(tuple(max(32, round(v * scale)) for v in image.size), Image.Resampling.LANCZOS)
    return _feedback_embed(_pilot_embed(image), pack(payload))


def _read_from_ll(ll, nbytes, positions=None):
    """Read a packet prefix from one already-computed LL2 coefficient array."""
    count = nbytes * 8 * REPEAT
    if count > ll.size:
        raise ValueError('Insufficient DWT capacity')
    if positions is None:
        positions = np.random.default_rng(SEED).permutation(ll.size)
    q = np.rint(ll[positions[:count]] / DELTA).astype(np.int64) & 1
    bits = (q.reshape(-1, REPEAT).sum(axis=1) > REPEAT // 2).astype(np.uint8)
    return np.packbits(bits).tobytes()


def _read_bytes(image, size, nbytes):
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    ll = pywt.wavedec2(_ycc(image)[:, :, 0], 'haar', level=2, mode='periodization')[0].ravel()
    return _read_from_ll(ll, nbytes)


def decode_at_size(image: Image.Image, size: tuple[int, int]) -> bytes:
    """Oracle-size decoder; compute the DWT once for header and payload."""
    if min(size) < 32:
        raise ValueError('Invalid original size')
    if max(size) > MAX_LONGEST or size[0] * size[1] > MAX_DECODE_PIXELS:
        raise ValueError('Robust candidate exceeds safe image dimensions')
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    ll = pywt.wavedec2(_ycc(image)[:, :, 0], 'haar', level=2, mode='periodization')[0].ravel()
    # Generate only the header positions for the common no-message case.
    # On a valid header, regenerate the same deterministic permutation for
    # the complete packet; the prefix is identical.
    positions = np.random.default_rng(SEED).permutation(ll.size)
    header = _read_from_ll(ll, HEADER_BYTES, positions)
    if header[:4] != b'CLR1':
        raise ValueError('Invalid CLR1 header')
    length = int.from_bytes(header[4:6], 'big')
    if not 12 <= length <= MAX_CODEWORD:
        raise ValueError('Invalid CLR1 length')
    return unpack(_read_from_ll(ll, HEADER_BYTES + length, positions))


def _profile(image, bins=1800, max_freq=.38):
    y = np.asarray(image.convert('L'), dtype=np.float32)
    h, w = y.shape
    window = np.hanning(h)[:, None] * np.hanning(w)[None, :]
    fft = np.fft.rfft2((y-y.mean())*window)
    magnitude = np.log1p(np.abs(fft)).astype(np.float32)
    radius = np.hypot(np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :])
    idx = np.floor(radius/max_freq*bins).astype(np.int32)
    good = idx < bins
    sums = np.bincount(idx[good].ravel(), weights=magnitude[good].ravel(), minlength=bins)
    counts = np.bincount(idx[good].ravel(), minlength=bins)
    prof = sums / np.maximum(counts, 1)
    return prof - gaussian_filter1d(prof, sigma=13)


def _peaks(image, low=.70, high=1.02, step=.002, max_peaks=4, separation_pp=1.2):
    profile = _profile(image)
    frequencies = (np.arange(len(profile))+.5)*(.38/len(profile))
    signs = np.random.default_rng(SEED).choice([-1., 1.], size=len(RADII))
    scales = np.arange(low, high+step/2, step)
    scores = np.empty(len(scales))
    for i, scale in enumerate(scales):
        observed = np.interp(RADII/scale, frequencies, profile)
        scores[i] = np.dot(signs, observed)/(np.linalg.norm(observed)*np.linalg.norm(signs)+1e-12)
    indexes = set(find_peaks(scores, distance=max(1, round(separation_pp/100/step)))[0].tolist())
    indexes.add(int(np.argmax(scores)))
    if scores[0] > scores[1]: indexes.add(0)
    if scores[-1] > scores[-2]: indexes.add(len(scores)-1)
    return sorted(((float(scales[i]), float(scores[i])) for i in indexes), key=lambda p:-p[1])[:max_peaks]


def _candidate_sizes(received_size, estimated_scale, radius_pp=1., limit=160):
    rw, rh = received_size
    lo = max(.01, estimated_scale-radius_pp/100)
    hi = estimated_scale+radius_pp/100
    minw, maxw = max(32, math.floor(rw/hi)-1), math.ceil(rw/lo)+1
    minh, maxh = max(32, math.floor(rh/hi)-1), math.ceil(rh/lo)+1
    options = []
    for w in range(minw, maxw+1):
        s = rw/w
        if not lo <= s <= hi: continue
        hcenter = round(rh/s)
        for h in range(max(minh, hcenter-2), min(maxh, hcenter+2)+1):
            sh = rh/h
            disagreement = abs(s-sh)
            if disagreement > max(1/w, 1/h): continue
            priority = (abs((s+sh)/2-estimated_scale), disagreement,
                        abs(h-hcenter), abs(w-rw/estimated_scale))
            options.append((priority, (w, h)))
    options.sort(key=lambda item:item[0])
    seen = set()
    for _, size in options:
        if size not in seen:
            seen.add(size)
            yield size
            if len(seen) >= limit: return


def candidate_sizes_priority50(image, max_candidates=160):
    """Measured strongest-peak-first 50, then round-robin; globally deduplicated."""
    streams = [iter(_candidate_sizes(image.size, p[0], limit=max_candidates)) for p in _peaks(image)]
    seen = set()
    def take(stream):
        for size in stream:
            if size not in seen:
                seen.add(size)
                return size
        return None
    if streams:
        for _ in range(min(50, max_candidates)):
            size = take(streams[0])
            if size is None: break
            yield size
    active = list(streams)
    while active and len(seen) < max_candidates:
        remaining = []
        for stream in active:
            size = take(stream)
            if size is not None:
                remaining.append(stream)
                yield size
            if len(seen) >= max_candidates: break
        active = remaining


class MessageNotFoundError(ValueError):
    """No valid robust packet recovered within the configured search budget."""


def _prepare_decode_image(image: Image.Image, should_cancel=None) -> Image.Image:
    """Bound working resolution before FFT/DWT; do not modify source on disk.

    This is a compatibility attempt for oversized received images, not a
    guarantee that resampling preserves an embedded message.
    """
    if should_cancel is not None and should_cancel():
        raise InterruptedError('Robust extraction cancelled')
    # JPEG draft decoding may reduce peak memory before loading pixel data.
    if max(image.size) > MAX_LONGEST and image.format == 'JPEG':
        image.draft('RGB', (MAX_LONGEST, MAX_LONGEST))
    image = ImageOps.exif_transpose(image)
    if max(image.size) > MAX_LONGEST:
        image.thumbnail((MAX_LONGEST, MAX_LONGEST), Image.Resampling.LANCZOS)
    if should_cancel is not None and should_cancel():
        raise InterruptedError('Robust extraction cancelled')
    return image.convert('RGB')


def decode(image: Image.Image, max_candidates=160, should_cancel=None) -> DecodeResult:
    """Blind decode with no original dimensions. Failure does not imply no embedded message."""
    if max_candidates < 1:
        raise ValueError('max_candidates must be positive')
    image = _prepare_decode_image(image, should_cancel)
    attempts = 0
    for size in candidate_sizes_priority50(image, max_candidates):
        if should_cancel is not None and should_cancel():
            raise InterruptedError('Robust extraction cancelled')
        if max(size) > MAX_LONGEST or size[0] * size[1] > MAX_DECODE_PIXELS:
            continue
        attempts += 1
        try:
            return DecodeResult(decode_at_size(image, size), size, attempts)
        except ValueError:
            pass
    # Bounded fallback for cases where the pilot estimates only unsafe sizes.
    # This does not change the measured Priority50 ordering or its budget.
    # The half-size candidate covers an exact 2x enlargement.
    fallback_sizes = [
        image.size,
        tuple(max(32, round(v / 2)) for v in image.size),
    ]
    for size in dict.fromkeys(fallback_sizes):
        if should_cancel is not None and should_cancel():
            raise InterruptedError('Robust extraction cancelled')
        if max(size) > MAX_LONGEST or size[0] * size[1] > MAX_DECODE_PIXELS:
            continue
        attempts += 1
        try:
            return DecodeResult(decode_at_size(image, size), size, attempts)
        except ValueError:
            pass
    raise MessageNotFoundError(f'Robust message not recovered after {attempts} candidates')
