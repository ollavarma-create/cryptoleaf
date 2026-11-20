#!/usr/bin/env python3
"""H-B1.9: JPEG-free Lanczos down/up scale sweep, frozen inward carriers."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from src.robust_packet import pack
from tools.robust_content_aware_hb11 import diagnostics
from tools.robust_content_aware_hb14 import parity
from tools.robust_content_aware_hb18 import ll2_received
from tools.robust_content_aware_hb16 import cover_features
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image

SCALES = (1.0, .95, .90, .85, .80, .75, .70, .65, .60)
STRATEGIES = ("random", "texture", "balanced")


def down_up(image: Image.Image, scale: float) -> Image.Image:
    if not 0 < scale <= 1:
        raise ValueError("Scale must be in (0, 1]")
    if scale == 1.0:
        return image.copy()
    size = tuple(max(32, round(d * scale)) for d in image.size)
    return image.resize(size, Image.Resampling.LANCZOS).resize(
        image.size, Image.Resampling.LANCZOS)


def write_csv(path, rows):
    if not rows:
        raise ValueError("No rows")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_one(source, maps_dir, hb15_dir, packet, delta, repeat):
    with Image.open(source) as im:
        reference = reference_image(im)
    cover = cover_features(reference)
    expected = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
    summary, positions_rows = [], []
    for strategy in STRATEGIES:
        stem = source.stem + "-" + strategy
        positions = np.load(maps_dir / (stem + "-positions.npy"), allow_pickle=False)
        if (positions.shape != expected.shape or
            not np.issubdtype(positions.dtype, np.integer) or
            np.any(positions < 0) or np.any(positions >= len(cover["std"])) or
            np.unique(positions).size != len(positions)):
            raise ValueError("Invalid oracle map: " + stem)
        path = hb15_dir / (stem + "-inward.png")
        with Image.open(path) as im:
            marked = im.convert("RGB")
        if marked.size != reference.size:
            raise ValueError("Carrier size mismatch: " + stem)
        original_ll = ll2_received(marked, marked.size)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        for scale in SCALES:
            received = down_up(marked, scale)
            ll = ll2_received(received, marked.size)
            wrong = parity(ll[positions], delta) != expected
            result = diagnostics(received, marked.size, positions, packet, repeat, delta)
            if result["repetition_errors"] != int(wrong.sum()):
                raise AssertionError("Diagnostics disagree")
            drift = np.abs(ll[positions] - original_ll[positions])
            summary.append({
                "source": source.name, "strategy": strategy, "scale": scale,
                "channel": "lanczos_down_up_no_jpeg", "marked_sha256": sha,
                "n": len(positions), "error_fraction": round(float(wrong.mean()), 6),
                "median_abs_ll2_drift": round(float(np.median(drift)), 5),
                "p90_abs_ll2_drift": round(float(np.percentile(drift, 90)), 5),
                **result,
            })
            std = cover["std"][positions]
            for i, index in enumerate(positions):
                positions_rows.append({
                    "source": source.name, "strategy": strategy, "scale": scale,
                    "repetition_index": i, "bit_index": i // repeat,
                    "coefficient_index": int(index),
                    "cover_std": round(float(std[i]), 5),
                    "wrong": int(wrong[i]),
                    "abs_ll2_drift": round(float(drift[i]), 5),
                })
            print(source.name, strategy, scale, result["status"],
                  result["repetition_errors"], result["majority_bit_errors"], flush=True)
    return summary, positions_rows


def main():
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
        p.error("Output directory exists; refusing to overwrite")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if any(not s.is_file() for s in args.sources):
        p.error("Missing source")
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
    summary, rows = [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            s, r = run_one(source, args.maps_dir, args.hb15_dir,
                           packet, args.delta, args.repeat)
            summary.extend(s)
            rows.extend(r)
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / "scale_summary.csv", summary)
    write_csv(args.out / "scale_positions.csv", rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(x) for x in args.sources],
        "source_sha256": {x.name: hashlib.sha256(x.read_bytes()).hexdigest()
                          for x in args.sources},
        "maps_dir": str(args.maps_dir), "hb15_dir": str(args.hb15_dir),
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "pilot": 0, "oracle_map": True, "arm": "inward",
        "scales": list(SCALES), "resampling": "Lanczos down then Lanczos up",
        "jpeg": False, "no_reembedding": True,
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
