#!/usr/bin/env python3
"""H-B1.1: paired placement maps and QIM/RS8 failure diagnostics.

Reconstructs ORIGINAL oracle maps from source covers. No production changes.
No blind decoding claims. Outputs are always created in a NEW directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pywt
from PIL import Image
from scipy.ndimage import sobel

from src import robust_image as robust
from src.robust_packet import HEADER_BYTES, pack, unpack
from tools.robust_content_aware_hb1 import (
    coefficient_scores, jpeg_after_resize, select_positions,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image

TRANSFORMS = (("png", None, None), ("resize083_jpeg85", .83, 85),
              ("resize068_jpeg70", .68, 70))
COLUMNS = ("source", "source_sha256", "marked", "marked_sha256",
           "strategy", "transform", "status", "delta", "repeat", "packet_sha256",
           "selected_count", "eligible_count", "texture_score_median",
           "selected_edge_fraction", "selected_flat_fraction",
           "repetition_errors", "majority_bit_errors", "header_bit_errors",
           "header_byte_errors", "codeword_byte_errors", "near_tie_votes",
           "max_repetition_errors_in_byte", "mean_repetition_errors_per_bit")


def region_types(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Independent edge/flat diagnostic (not used to select positions).

    A block is an 'edge' if strong directional gradients dominate local
    luminance variance. Thresholds are exploratory, not calibrated labels.
    """
    y = robust._ycc(image)[:, :, 0]
    h, w = y.shape
    ph, pw = (-h) % 4, (-w) % 4
    y = np.pad(y, ((0, ph), (0, pw)), mode="wrap")
    blocks = y.reshape(y.shape[0] // 4, 4, y.shape[1] // 4, 4)
    std = blocks.std(axis=(1, 3))
    gx, gy = sobel(y, axis=1), sobel(y, axis=0)
    energy_x = (gx * gx).reshape(std.shape[0], 4, std.shape[1], 4).mean(axis=(1, 3))
    energy_y = (gy * gy).reshape(std.shape[0], 4, std.shape[1], 4).mean(axis=(1, 3))
    directional = np.maximum(energy_x, energy_y) / np.maximum(energy_x + energy_y, 1e-9)
    return ((std > 6) & (directional > .85)).ravel(), (std < 2).ravel()


def diagnostics(received: Image.Image, original_size: tuple[int, int],
                positions: np.ndarray, packet: bytes, repeat: int,
                delta: float) -> dict:
    if received.size != original_size:
        received = received.resize(original_size, Image.Resampling.LANCZOS)
    ll = pywt.wavedec2(robust._ycc(received)[:, :, 0], "haar",
                       level=2, mode="periodization")[0].ravel()
    expected_bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    expected = np.repeat(expected_bits, repeat)
    observed = np.rint(ll[positions] / delta).astype(np.int64) & 1
    votes = observed.reshape(-1, repeat).sum(axis=1)
    decoded_bits = (votes > repeat // 2).astype(np.uint8)
    raw = np.packbits(decoded_bits).tobytes()
    bit_errors = decoded_bits != expected_bits
    byte_errors = np.any(bit_errors.reshape(-1, 8), axis=1)
    per_bit = np.count_nonzero(observed != expected, axis=0) if False else (
        observed != expected).reshape(-1, repeat).sum(axis=1)
    try:
        status = "PASS" if unpack(raw) == unpack(packet) else "WRONG_PAYLOAD"
    except ValueError:
        status = "FAIL"
    return {
        "status": status,
        "repetition_errors": int(np.count_nonzero(observed != expected)),
        "majority_bit_errors": int(bit_errors.sum()),
        "header_bit_errors": int(bit_errors[:HEADER_BYTES * 8].sum()),
        "header_byte_errors": int(byte_errors[:HEADER_BYTES].sum()),
        "codeword_byte_errors": int(byte_errors[HEADER_BYTES:].sum()),
        "near_tie_votes": int(np.count_nonzero((votes == repeat // 2) |
                                               (votes == repeat // 2 + 1))),
        "max_repetition_errors_in_byte": int(per_bit.reshape(-1, 8).sum(axis=1).max()),
        "mean_repetition_errors_per_bit": round(float(per_bit.mean()), 5),
    }


def map_overlay(image: Image.Image, positions: np.ndarray,
                edge: np.ndarray, flat: np.ndarray, out: Path) -> None:
    """Red = selected directional edge, yellow = other selected, blue = flat."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
    height, width = rgb.shape[:2]
    ll_width = (width + 3) // 4
    for index in positions:
        row, col = divmod(int(index), ll_width)
        y0, x0 = row * 4, col * 4
        color = (255, 60, 60) if edge[index] else (255, 210, 20)
        region = rgb[y0:min(y0 + 4, height), x0:min(x0 + 4, width)]
        region[:] = np.rint(.5 * region.astype(np.float64) +
                            .5 * np.asarray(color)).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(out)


def run_one(source: Path, marked_dir: Path, out: Path, packet: bytes,
            delta: float, repeat: int) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    edge, flat = region_types(reference)
    scores = coefficient_scores(reference)
    count = len(packet) * 8 * repeat
    rows = []
    for strategy in ("random", "texture"):
        marked_path = marked_dir / f"{source.stem}-{strategy}.png"
        if not marked_path.is_file():
            raise ValueError(f"Missing H-B1 marked PNG: {marked_path}")
        with Image.open(marked_path) as im:
            marked = im.convert("RGB")
        if marked.size != reference.size:
            raise ValueError(f"Dimension mismatch: {marked_path}")
        positions = select_positions(reference, count, strategy)
        map_overlay(reference, positions, edge, flat,
                    out / f"{source.stem}-{strategy}-map.png")
        # Save the exact ordered map; hash enables later reproducibility checks.
        np.save(out / f"{source.stem}-{strategy}-positions.npy", positions)
        common = {
            "source": source.name,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "marked": marked_path.name,
            "marked_sha256": hashlib.sha256(marked_path.read_bytes()).hexdigest(),
            "strategy": strategy, "delta": delta, "repeat": repeat,
            "packet_sha256": hashlib.sha256(packet).hexdigest(),
            "selected_count": count, "eligible_count": int(np.isfinite(scores).sum()),
            "texture_score_median": float(np.median(scores[positions])),
            "selected_edge_fraction": float(edge[positions].mean()),
            "selected_flat_fraction": float(flat[positions].mean()),
        }
        for label, scale, quality in TRANSFORMS:
            received = marked if scale is None else jpeg_after_resize(marked, scale, quality)
            result = diagnostics(received, marked.size, positions, packet, repeat, delta)
            rows.append({**common, "transform": label, **result})
            print(source.name, strategy, label, result["status"],
                  "bit errors", result["majority_bit_errors"],
                  "RS8 bytes", result["codeword_byte_errors"], flush=True)
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--marked-dir", required=True, type=Path,
                   help="Existing H-B1 directory with saved marked PNGs")
    p.add_argument("--out", required=True, type=Path, help="NEW directory")
    p.add_argument("--delta", type=float, default=38.0)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = p.parse_args()
    if args.out.exists():
        p.error("Refusing to overwrite existing output directory")
    if not 8 <= args.delta <= 128 or not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid DELTA/REPEAT")
    if any(not x.is_file() for x in args.sources):
        p.error("Source image missing")
    packet = pack(args.message.encode("utf-8"))
    # Preflight before writing anything.
    for source in args.sources:
        for strategy in ("random", "texture"):
            if not (args.marked_dir / f"{source.stem}-{strategy}.png").is_file():
                p.error(f"Missing marked PNG: {source.stem}-{strategy}.png")
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            rows.extend(run_one(source, args.marked_dir, args.out,
                                packet, args.delta, args.repeat))
    with (args.out / "diagnostics.csv").open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(x) for x in args.sources],
        "marked_dir": str(args.marked_dir), "delta": args.delta,
        "repeat": args.repeat, "message": args.message,
        "map": "original-cover oracle", "pilot": 0,
        "transforms": [x[0] for x in TRANSFORMS],
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
