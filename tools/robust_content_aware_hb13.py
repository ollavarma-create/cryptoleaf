#!/usr/bin/env python3
"""H-B1.3: QIM margin and channel-instability diagnostics (oracle only).

Reads unchanged H-B1.2 marked PNGs and ordered positions.npy. Does not
re-embed, tune parameters, or claim that oracle margins predict blind recovery.
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

from src import robust_image as robust
from src.robust_packet import pack, HEADER_BYTES
from tools.robust_content_aware_hb1 import jpeg_after_resize
from tools.robust_content_aware_hb11 import diagnostics, region_types, TRANSFORMS
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image


def ll2(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return pywt.wavedec2(robust._ycc(image)[:, :, 0], "haar",
                         level=2, mode="periodization")[0].ravel()


def position_metrics(marked_ll: np.ndarray, received_ll: np.ndarray,
                     positions: np.ndarray, packet: bytes,
                     delta: float, repeat: int) -> dict[str, np.ndarray]:
    """Per-repetition margin to nearest rounding boundary, parity, and drift.

    Margin is coefficient units (0..delta/2), NOT distance to a
    correct-parity boundary. Both PNG and JPEG parity are reported.
    """
    expected = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)),
                         repeat)
    x = marked_ll[positions] / delta
    y = received_ll[positions] / delta
    png_parity = np.rint(x).astype(np.int64) & 1
    received_parity = np.rint(y).astype(np.int64) & 1
    return {
        "expected": expected,
        "png_error": png_parity != expected,
        "received_error": received_parity != expected,
        "changed_parity": png_parity != received_parity,
        "png_margin": (0.5 - np.abs(x - np.rint(x))) * delta,
        "received_margin": (0.5 - np.abs(y - np.rint(y))) * delta,
        "abs_drift": np.abs(received_ll[positions] - marked_ll[positions]),
    }


def summarise(mask: np.ndarray, m: dict[str, np.ndarray]) -> dict:
    if not np.any(mask):
        return {"n": 0, "png_errors": 0, "received_errors": 0,
                "parity_flips": 0, "png_margin_p10": None,
                "png_margin_median": None, "received_margin_p10": None,
                "abs_drift_median": None, "abs_drift_p90": None}
    def percentile(key, p):
        return round(float(np.percentile(m[key][mask], p)), 5)
    return {
        "n": int(mask.sum()),
        "png_errors": int(m["png_error"][mask].sum()),
        "received_errors": int(m["received_error"][mask].sum()),
        "parity_flips": int(m["changed_parity"][mask].sum()),
        "png_margin_p10": percentile("png_margin", 10),
        "png_margin_median": percentile("png_margin", 50),
        "received_margin_p10": percentile("received_margin", 10),
        "abs_drift_median": percentile("abs_drift", 50),
        "abs_drift_p90": percentile("abs_drift", 90),
    }


def run_one(source: Path, marked_dir: Path, packet: bytes,
            delta: float, repeat: int) -> tuple[list[dict], list[dict]]:
    with Image.open(source) as im:
        reference = reference_image(im)
    edge, flat = region_types(reference)
    count = len(packet) * 8 * repeat
    summaries, details = [], []
    for strategy in ("random", "texture", "balanced"):
        stem = f"{source.stem}-{strategy}"
        png_path = marked_dir / (stem + ".png")
        map_path = marked_dir / (stem + "-positions.npy")
        with Image.open(png_path) as im:
            marked = im.convert("RGB")
        if marked.size != reference.size:
            raise ValueError(f"Image size mismatch: {png_path}")
        positions = np.load(map_path, allow_pickle=False)
        if positions.shape != (count,) or not np.issubdtype(positions.dtype, np.integer):
            raise ValueError(f"Unexpected map shape/type: {map_path}")
        if np.any(positions < 0) or np.any(positions >= edge.size) or np.unique(positions).size != count:
            raise ValueError(f"Invalid coefficient indices: {map_path}")
        marked_ll = ll2(marked, marked.size)
        for transform, scale, quality in TRANSFORMS:
            received = marked if scale is None else jpeg_after_resize(marked, scale, quality)
            m = position_metrics(marked_ll, ll2(received, marked.size),
                                 positions, packet, delta, repeat)
            result = diagnostics(received, marked.size, positions,
                                 packet, repeat, delta)
            classes = {
                "all": np.ones(count, dtype=bool),
                "directional_edge": edge[positions],
                "flat": flat[positions],
                "other": ~(edge[positions] | flat[positions]),
                "header": np.arange(count) < HEADER_BYTES * 8 * repeat,
                "codeword": np.arange(count) >= HEADER_BYTES * 8 * repeat,
                "low_png_margin": m["png_margin"] < delta * .1,
            }
            for label, mask in classes.items():
                summaries.append({
                    "source": source.name, "strategy": strategy,
                    "transform": transform, "class": label,
                    "status": result["status"],
                    "majority_bit_errors": result["majority_bit_errors"],
                    "header_bit_errors": result["header_bit_errors"],
                    "codeword_byte_errors": result["codeword_byte_errors"],
                    **summarise(mask, m),
                })
            # One row per majority bit, not per repeated coefficient.
            png_errors = m["png_error"].reshape(-1, repeat).sum(axis=1)
            rx_errors = m["received_error"].reshape(-1, repeat).sum(axis=1)
            bit_edges = edge[positions].reshape(-1, repeat).sum(axis=1)
            bit_flats = flat[positions].reshape(-1, repeat).sum(axis=1)
            for bit, (pe, re, be, bf) in enumerate(
                    zip(png_errors, rx_errors, bit_edges, bit_flats)):
                details.append({
                    "source": source.name, "strategy": strategy,
                    "transform": transform, "bit_index": bit,
                    "field": "header" if bit < HEADER_BYTES * 8 else "codeword",
                    "png_repetition_errors": int(pe),
                    "received_repetition_errors": int(re),
                    "majority_wrong": int(re > repeat // 2),
                    "edge_positions": int(be), "flat_positions": int(bf),
                    "png_margin_median": round(float(np.median(
                        m["png_margin"][bit * repeat:(bit + 1) * repeat])), 5),
                    "abs_drift_median": round(float(np.median(
                        m["abs_drift"][bit * repeat:(bit + 1) * repeat])), 5),
                })
            print(source.name, strategy, transform, result["status"],
                  "png parity errors", int(m["png_error"].sum()),
                  "received parity errors", int(m["received_error"].sum()),
                  flush=True)
    return summaries, details


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No diagnostic rows")
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--marked-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.0)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = p.parse_args()
    if args.out.exists():
        p.error("Output directory exists; refusing to overwrite")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid delta")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid repeat")
    if any(not source.is_file() for source in args.sources):
        p.error("Missing source image")
    packet = pack(args.message.encode("utf-8"))
    for source in args.sources:
        for strategy in ("random", "texture", "balanced"):
            for suffix in (".png", "-positions.npy"):
                path = args.marked_dir / (source.stem + "-" + strategy + suffix)
                if not path.is_file():
                    p.error(f"Missing H-B1.2 artifact: {path}")
    args.out.mkdir(parents=True, exist_ok=False)
    summary, bits = [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            a, b = run_one(source, args.marked_dir, packet,
                           args.delta, args.repeat)
            summary.extend(a)
            bits.extend(b)
    write_csv(args.out / "margin_summary.csv", summary)
    write_csv(args.out / "bit_diagnostics.csv", bits)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(p) for p in args.sources],
        "marked_dir": str(args.marked_dir),
        "marked_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for source in args.sources
                          for strategy in ("random", "texture", "balanced")
                          for p in [args.marked_dir / (source.stem + "-" + strategy + ".png")]},
        "delta": args.delta, "repeat": args.repeat,
        "message": args.message, "pilot": 0, "oracle_map": True,
        "transforms": [t[0] for t in TRANSFORMS],
    }, indent=2), encoding="utf-8")
    print("Saved", args.out, flush=True)


if __name__ == "__main__":
    main()
