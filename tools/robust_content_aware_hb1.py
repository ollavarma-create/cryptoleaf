#!/usr/bin/env python3
"""H-B1 oracle-map ablation: fixed-capacity Haar LL2 placement, research only.

The decoder is explicitly given the ORIGINAL coefficient map. This is not a
blind codec or a deployable wire format. Never changes src/robust_image.py.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pywt
from PIL import Image

from src import robust_image as robust
from src.robust_packet import pack, unpack
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_quality_compare import quality_metrics

SEED = robust.SEED


def coefficient_scores(image: Image.Image) -> np.ndarray:
    """Robust-ish 4x4 texture and saturation score from unmarked luminance.

    This deliberately uses the original image. Scores are NOT expected to be
    reproducible from a resized/JPEG received image (H-B2 is separate).
    """
    ycc = robust._ycc(image)
    y = ycc[:, :, 0]
    h, w = y.shape
    # Periodic padding matches periodized Haar's LL2 coefficient dimensions.
    ph, pw = (-h) % 4, (-w) % 4
    blocks = np.pad(y, ((0, ph), (0, pw)), mode="wrap").reshape(
        (h + ph) // 4, 4, (w + pw) // 4, 4
    )
    texture = blocks.std(axis=(1, 3))
    # Exclude near-black/white regions where RGB clipping is likely.
    safe = ((blocks.min(axis=(1, 3)) > 8) &
            (blocks.max(axis=(1, 3)) < 247))
    score = np.where(safe, texture, -np.inf)
    return score.ravel()


def select_positions(image: Image.Image, count: int, strategy: str) -> np.ndarray:
    scores = coefficient_scores(image)
    if count > scores.size:
        raise ValueError("Insufficient LL2 coefficient capacity")
    rng = np.random.default_rng(SEED)
    permutation = rng.permutation(scores.size)
    if strategy == "random":
        return permutation[:count]
    if strategy != "texture":
        raise ValueError("Unknown placement strategy")
    eligible = np.isfinite(scores)
    if int(eligible.sum()) < count:
        raise ValueError(f"Insufficient eligible texture capacity: {eligible.sum()} < {count}")
    # Seeded tie-breaking prevents a systematic top-left preference.
    order = np.argsort(-scores[permutation], kind="stable")
    return permutation[order[:count]]


def embed_with_map(image: Image.Image, packet: bytes, positions: np.ndarray) -> Image.Image:
    """Reproduce baseline feedback loop with an explicit coefficient order."""
    a = robust._ycc(image)
    coeffs = pywt.wavedec2(a[:, :, 0], "haar", level=2, mode="periodization")
    ll = coeffs[0].copy()
    flat = ll.ravel()
    bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    target = np.repeat(bits, robust.REPEAT).astype(np.int64)
    if len(positions) != target.size or len(set(positions.tolist())) != len(positions):
        raise ValueError("Map length/uniqueness mismatch")
    q = robust._nearest_parity(flat[positions], target)
    for iteration in range(robust.FEEDBACK_ITERATIONS + 1):
        flat[positions] = q * robust.DELTA
        coeffs[0] = ll
        reconstructed = pywt.waverec2(coeffs, "haar", mode="periodization")
        out = a.copy()
        out[:, :, 0] = np.clip(reconstructed[:a.shape[0], :a.shape[1]], 0, 255)
        result = robust._from_ycc(out)
        observed = pywt.wavedec2(robust._ycc(result)[:, :, 0], "haar",
                                 level=2, mode="periodization")[0].ravel()
        wrong = (np.rint(observed[positions] / robust.DELTA).astype(np.int64) & 1) != target
        if not wrong.any() or iteration == robust.FEEDBACK_ITERATIONS:
            return result
        q[wrong] = robust._nearest_parity(observed[positions][wrong], target[wrong])
    raise AssertionError("unreachable")


def oracle_decode(image: Image.Image, original_size: tuple[int, int],
                  positions: np.ndarray, packet_length: int) -> bytes:
    """Explicitly supplied original dimensions, map, and packet length."""
    if image.size != original_size:
        image = image.resize(original_size, Image.Resampling.LANCZOS)
    ll = pywt.wavedec2(robust._ycc(image)[:, :, 0], "haar",
                       level=2, mode="periodization")[0].ravel()
    q = np.rint(ll[positions] / robust.DELTA).astype(np.int64) & 1
    bits = (q.reshape(-1, robust.REPEAT).sum(axis=1) >
            robust.REPEAT // 2).astype(np.uint8)
    received = np.packbits(bits).tobytes()
    if len(received) != packet_length:
        raise ValueError("Incorrect received length")
    return unpack(received)


def jpeg_after_resize(image: Image.Image, scale: float, quality: int) -> Image.Image:
    size = tuple(max(32, round(d * scale)) for d in image.size)
    scaled = image.resize(size, Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    scaled.save(stream, format="JPEG", quality=quality, subsampling=2)
    stream.seek(0)
    with Image.open(stream) as decoded:
        return decoded.convert("RGB")


def run(source: Path, out: Path, packet: bytes, delta: float, repeat: int) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    count = len(packet) * 8 * repeat
    rows = []
    with codec_parameters(delta, repeat):
        for strategy in ("random", "texture"):
            try:
                positions = select_positions(reference, count, strategy)
            except ValueError as exc:
                rows.append({"source": source.name, "strategy": strategy,
                             "status": "SKIP", "reason": str(exc)})
                continue
            # Match baseline's YCbCr roundtrip, without Fourier pilot.
            carrier = reference.convert("YCbCr").convert("RGB")
            marked = embed_with_map(carrier, packet, positions)
            target = out / f"{source.stem}-{strategy}.png"
            marked.save(target)
            metrics = quality_metrics(reference, marked)
            for label, received in (
                ("png", marked),
                ("resize083_jpeg85", jpeg_after_resize(marked, .83, 85)),
                ("resize068_jpeg70", jpeg_after_resize(marked, .68, 70)),
            ):
                try:
                    exact = oracle_decode(received, marked.size, positions, len(packet)) == unpack(packet)
                    status = "PASS" if exact else "WRONG_PAYLOAD"
                except ValueError as exc:
                    status = "FAIL:" + type(exc).__name__
                rows.append({
                    "source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "strategy": strategy, "status": status, "transform": label,
                    "map": "ORIGINAL_ORACLE", "delta": delta, "repeat": repeat,
                    "capacity": coefficient_scores(reference).size,
                    "eligible": int(np.isfinite(coefficient_scores(reference)).sum()),
                    "used": count, "marked_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    **metrics,
                })
                print(source.name, strategy, label, status, flush=True)
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path, nargs="+")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.0)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = p.parse_args()
    if args.out.exists():
        p.error("Output directory exists; refusing to overwrite")
    if not 8 <= args.delta <= 128 or not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid DELTA or REPEAT")
    if any(not x.is_file() or x.suffix.lower() not in (".png", ".jpg", ".jpeg") for x in args.sources):
        p.error("Sources must be existing PNG/JPEG images")
    packet = pack(args.message.encode("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    for source in args.sources:
        rows.extend(run(source, args.out, packet, args.delta, args.repeat))
        with (args.out / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
            fields = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(x) for x in args.sources], "delta": args.delta,
        "repeat": args.repeat, "message": args.message, "pilot": 0,
        "map": "oracle original only", "seed": SEED,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
