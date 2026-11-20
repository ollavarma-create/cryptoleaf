#!/usr/bin/env python3
"""H-B2.4: Does spatially dispersed texture placement improve quality/robustness?

Research only. Fixed packet, inward feedback, original-cover oracle map.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from src.robust_packet import pack
from src import robust_image as robust
from tools.robust_content_aware_hb1 import coefficient_scores
from tools.robust_content_aware_hb11 import diagnostics, region_types
from tools.robust_content_aware_hb15 import feedback_step
from tools.robust_content_aware_hb22 import CHANNELS, transform
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_quality_compare import quality_metrics

# Coefficients per tile side; each LL2 coefficient spans ~4x4 source pixels.
TILES = (8, 16, 32)


def positions_for(image, count, tile):
    """Choose top-texture safe positions, with optional spatial round-robin.

    tile=None is the unmodified strict top-texture baseline.
    For a tile size, each tile contributes its strongest unused position
    per pass, until count is reached. No saturated/unsafe fallback.
    """
    score = coefficient_scores(image)
    if count > len(score):
        return None, {"reason": "LL2_CAPACITY", "eligible": int(np.isfinite(score).sum())}
    eligible = np.flatnonzero(np.isfinite(score))
    if len(eligible) < count:
        return None, {"reason": "INSUFFICIENT_TEXTURE", "eligible": len(eligible)}
    y = robust._ycc(image)[:, :, 0]
    cols = (y.shape[1] + 3) // 4
    rows = (y.shape[0] + 3) // 4
    if cols * rows != len(score):
        raise AssertionError("Unexpected LL2 grid shape")
    # Seeded tie-breaker consistent across arms.
    perm = np.random.default_rng(robust.SEED).permutation(len(score))
    ranked = perm[np.argsort(-score[perm], kind="stable")]
    ranked = ranked[np.isfinite(score[ranked])]
    if tile is None:
        chosen = ranked[:count]
        group_tile = 16
    else:
        if tile <= 0:
            raise ValueError("Tile must be positive")
        group_tile = tile
        # Deterministic tile order by first appearance in global ranking;
        # round-robin within each tile, no random bit/position reordering.
        groups = defaultdict(list)
        for idx in ranked:
            r, c = divmod(int(idx), cols)
            groups[(r // tile, c // tile)].append(int(idx))
        chosen_list = []
        keys = list(groups)
        offset = 0
        while len(chosen_list) < count:
            advanced = False
            for key in keys:
                group = groups[key]
                if offset < len(group):
                    chosen_list.append(group[offset])
                    advanced = True
                    if len(chosen_list) == count:
                        break
            if not advanced:
                raise AssertionError("Exhausted eligible positions")
            offset += 1
        chosen = np.asarray(chosen_list, dtype=np.int64)
    tile_ids = ((chosen // cols) // group_tile) * ((cols + group_tile - 1) // group_tile) + ((chosen % cols) // group_tile)
    _, tile_counts = np.unique(tile_ids, return_counts=True)
    return np.asarray(chosen, dtype=np.int64), {
        "reason": "", "eligible": len(eligible),
        "tile_side_ll2": tile if tile is not None else 0,
        "occupied_tiles": len(tile_counts),
        "max_positions_per_tile": int(tile_counts.max()),
        "p90_positions_per_tile": float(np.percentile(tile_counts, 90)),
        "top_texture_mean": float(np.mean(score[chosen])),
        "top_texture_median": float(np.median(score[chosen])),
    }


def write_csv(path, rows):
    if not rows:
        raise ValueError("No data")
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_one(source, out, packet, delta, repeat, tiles):
    with Image.open(source) as opened:
        ref = reference_image(opened)
    carrier = ref.convert("YCbCr").convert("RGB")
    needed = len(packet) * 8 * repeat
    edge, flat = region_types(ref)
    rows = []
    for tile in (None, *tiles):
        label = "texture_baseline" if tile is None else f"spread_{tile}"
        positions, info = positions_for(ref, needed, tile)
        common = {"source": source.name, "strategy": label,
                  "delta": delta, "repeat": repeat, "selected_count": needed,
                  **info}
        if positions is None:
            rows.append({**common, "channel": "not_run", "status": "SKIP"})
            print(source.name, label, "SKIP", info["reason"], flush=True)
            continue
        marked, trace = feedback_step(carrier, packet, positions, delta, repeat, "inward")
        stem = source.stem + "-" + label
        path = out / (stem + "-inward.png")
        marked.save(path)
        np.save(out / (stem + "-positions.npy"), positions)
        q = quality_metrics(ref, marked)
        details = {**common, "marked_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "selected_edge_fraction": float(edge[positions].mean()),
                   "selected_flat_fraction": float(flat[positions].mean()),
                   "feedback_iterations": len(trace),
                   "feedback_stepped_coefficients": trace[-1]["stepped_coefficients"],
                   "feedback_clipped_fraction": trace[-1]["clipped_pixel_fraction"],
                   **q}
        for channel, scale, jpeg in CHANNELS:
            received = transform(marked, scale, jpeg)
            d = diagnostics(received, marked.size, positions, packet, repeat, delta)
            rows.append({**details, "channel": channel, **d})
            print(source.name, label, channel, d["status"],
                  d["repetition_errors"], flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--delta", type=float, default=38.)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    parser.add_argument("--tiles", nargs="+", type=int, default=list(TILES))
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output exists; refusing overwrite")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        parser.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        parser.error("Invalid REPEAT")
    if not args.tiles or len(set(args.tiles)) != len(args.tiles) or any(t < 1 for t in args.tiles):
        parser.error("Tile sizes must be positive and unique")
    if not args.sources or len({p.stem for p in args.sources}) != len(args.sources):
        parser.error("Supply images with distinct filename stems")
    if any(not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg")
           for p in args.sources):
        parser.error("Missing or unsupported input image")
    packet = pack(args.message.encode("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            rows.extend(run_one(source, args.out, packet, args.delta, args.repeat,
                                args.tiles))
    write_csv(args.out / "metrics.csv", rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(p) for p in args.sources],
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in args.sources},
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "strategies": ["texture_baseline"] + [f"spread_{t}" for t in args.tiles],
        "tile_sizes_ll2": args.tiles, "pilot": 0, "oracle_map": True,
        "embedding": "inward", "channels": [name for name, _, _ in CHANNELS],
        "warning": "Spatial dispersion is a research hypothesis, not a validated safety policy",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
