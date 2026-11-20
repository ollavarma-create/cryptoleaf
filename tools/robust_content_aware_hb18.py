#!/usr/bin/env python3
"""H-B1.8: controlled resize x JPEG factorial on frozen inward PNGs.

No re-embedding, new placement, packet modification, or production changes.
Uses the original-cover oracle coefficient maps and dimensions.
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
from src.robust_packet import pack
from tools.robust_content_aware_hb11 import diagnostics
from tools.robust_content_aware_hb14 import parity
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image

# A paired 2x2 design for each of the two original JPEG channel settings.
PAIRS = (("083_85", .83, 85), ("068_70", .68, 70))
ARMS = ("identity", "resize_only", "jpeg_only", "resize_jpeg")
STRATEGIES = ("random", "texture", "balanced")


def channel(image: Image.Image, scale: float, quality: int, arm: str) -> Image.Image:
    if arm not in ARMS:
        raise ValueError("Unknown arm")
    output = image
    if arm in ("resize_only", "resize_jpeg"):
        # Match H-B1 jpeg_after_resize: minimum 32 px, Python round, Lanczos.
        size = tuple(max(32, round(d * scale)) for d in image.size)
        output = output.resize(size, Image.Resampling.LANCZOS)
    if arm in ("jpeg_only", "resize_jpeg"):
        stream = io.BytesIO()
        output.save(stream, format="JPEG", quality=quality, subsampling=2)
        stream.seek(0)
        with Image.open(stream) as decoded:
            output = decoded.convert("RGB")
    return output


def ll2_received(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return pywt.wavedec2(robust._ycc(image)[:, :, 0], "haar",
                         level=2, mode="periodization")[0].ravel()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No results")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_one(source: Path, maps_dir: Path, marked_dir: Path, packet: bytes,
            delta: float, repeat: int):
    with Image.open(source) as opened:
        reference = reference_image(opened)
    expected = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
    summary, positions_rows, interactions = [], [], []
    max_index = ((reference.width + 3) // 4) * ((reference.height + 3) // 4)
    for strategy in STRATEGIES:
        stem = source.stem + "-" + strategy
        positions = np.load(maps_dir / (stem + "-positions.npy"), allow_pickle=False)
        if (not np.issubdtype(positions.dtype, np.integer) or
                positions.shape != expected.shape or
                np.any(positions < 0) or np.any(positions >= max_index) or
                np.unique(positions).size != len(positions)):
            raise ValueError("Invalid oracle map: " + stem)
        marked_path = marked_dir / (stem + "-inward.png")
        with Image.open(marked_path) as opened:
            marked = opened.convert("RGB")
        if marked.size != reference.size:
            raise ValueError("Dimension mismatch: " + stem)
        marked_hash = hashlib.sha256(marked_path.read_bytes()).hexdigest()
        for pair, scale, quality in PAIRS:
            observed = {}
            for arm in ARMS:
                received = channel(marked, scale, quality, arm)
                ll = ll2_received(received, marked.size)
                bits = parity(ll[positions], delta)
                wrong = bits != expected
                observed[arm] = wrong
                d = diagnostics(received, marked.size, positions, packet, repeat, delta)
                if int(wrong.sum()) != d["repetition_errors"]:
                    raise AssertionError("Parity diagnostics mismatch")
                summary.append({
                    "source": source.name, "strategy": strategy, "pair": pair,
                    "scale": scale, "jpeg_quality": quality, "arm": arm,
                    "resized": int(arm in ("resize_only", "resize_jpeg")),
                    "jpeg": int(arm in ("jpeg_only", "resize_jpeg")),
                    "marked_sha256": marked_hash, "original_width": marked.width,
                    "original_height": marked.height,
                    "channel_width": received.width, "channel_height": received.height,
                    **d,
                })
                for i, index in enumerate(positions):
                    positions_rows.append({
                        "source": source.name, "strategy": strategy, "pair": pair,
                        "arm": arm, "repetition_index": i, "bit_index": i // repeat,
                        "coefficient_index": int(index),
                        "wrong": int(wrong[i]),
                        "abs_ll2_drift": round(float(abs(
                            ll[index] - ll2_received(marked, marked.size)[index])), 5),
                    })
                print(source.name, strategy, pair, arm, d["status"],
                      "repetition_errors", d["repetition_errors"],
                      "majority", d["majority_bit_errors"], flush=True)
            # A 2x2 factorial contrast in *error fraction*. It describes
            # interaction, not a causal attribution of individual flips.
            a, b, c, d = (observed[k] for k in ARMS)
            n = len(a)
            interactions.append({
                "source": source.name, "strategy": strategy, "pair": pair,
                "n": n, "identity_errors": int(a.sum()),
                "resize_only_errors": int(b.sum()),
                "jpeg_only_errors": int(c.sum()),
                "resize_jpeg_errors": int(d.sum()),
                "resize_only_fraction": round(float(b.mean()), 6),
                "jpeg_only_fraction": round(float(c.mean()), 6),
                "resize_jpeg_fraction": round(float(d.mean()), 6),
                "factorial_interaction_fraction": round(float(
                    d.mean() - b.mean() - c.mean() + a.mean()), 6),
                "both_single_channels_correct_but_combined_wrong": int(
                    np.count_nonzero(~b & ~c & d)),
                "both_single_channels_wrong_and_combined_wrong": int(
                    np.count_nonzero(b & c & d)),
                "combined_wrong_only_after_resize": int(
                    np.count_nonzero(b & ~c & d)),
                "combined_wrong_only_after_jpeg": int(
                    np.count_nonzero(~b & c & d)),
            })
    return summary, positions_rows, interactions


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--maps-dir", required=True, type=Path)
    p.add_argument("--hb15-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = p.parse_args()
    if args.out.exists():
        p.error("Output directory already exists; refusing to overwrite")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if any(not s.is_file() for s in args.sources):
        p.error("Source image missing")
    if len({s.stem for s in args.sources}) != len(args.sources):
        p.error("Source stems must be unique")
    packet = pack(args.message.encode("utf-8"))
    for source in args.sources:
        for strategy in STRATEGIES:
            stem = source.stem + "-" + strategy
            for path in (args.maps_dir / (stem + "-positions.npy"),
                         args.hb15_dir / (stem + "-inward.png")):
                if not path.is_file():
                    p.error("Missing prerequisite: " + str(path))
    summary, positions, interactions = [], [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            a, b, c = run_one(source, args.maps_dir, args.hb15_dir,
                              packet, args.delta, args.repeat)
            summary.extend(a)
            positions.extend(b)
            interactions.extend(c)
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / "channel_summary.csv", summary)
    write_csv(args.out / "position_errors.csv", positions)
    write_csv(args.out / "factorial_interactions.csv", interactions)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest()
                          for s in args.sources},
        "maps_dir": str(args.maps_dir), "hb15_dir": str(args.hb15_dir),
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "pilot": 0, "oracle_map": True, "arm": "inward",
        "pairs": [{"name": name, "scale": scale, "quality": quality}
                  for name, scale, quality in PAIRS],
        "channels": list(ARMS),
        "jpeg_subsampling": 2,
        "interpretation": "paired 2x2 factorial; descriptive error interactions",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
