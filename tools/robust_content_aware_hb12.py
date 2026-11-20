#!/usr/bin/env python3
"""H-B1.2: capacity-aware edge-penalized placement, oracle-only research."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_content_aware_hb1 import (
    coefficient_scores, embed_with_map, jpeg_after_resize, select_positions,
)
from tools.robust_content_aware_hb11 import diagnostics, map_overlay, region_types, TRANSFORMS
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_quality_compare import quality_metrics

SEED = robust.SEED


def balanced_scores(image: Image.Image) -> np.ndarray:
    """Exploratory texture reward and soft edge/flat/saturation penalties."""
    y = robust._ycc(image)[:, :, 0]
    h, w = y.shape
    padded = np.pad(y, ((0, (-h) % 4), (0, (-w) % 4)), mode="wrap")
    bh, bw = padded.shape[0] // 4, padded.shape[1] // 4
    blocks = padded.reshape(bh, 4, bw, 4)
    std = blocks.std(axis=(1, 3)).ravel()
    saturated = (blocks.min(axis=(1, 3)) <= 8) | (blocks.max(axis=(1, 3)) >= 247)
    edge, flat = region_types(image)
    return np.log1p(std) - 2.5 * edge - 1.8 * flat - 2.0 * saturated.ravel()


def balanced_positions(image: Image.Image, count: int,
                       quota_fraction: float = .5,
                       tile_blocks: int = 8) -> tuple[np.ndarray, dict]:
    """Rank positions with seeded ties and bounded occupancy per 8x8 LL2 tile.

    If quotas are exhausted, fill the remainder from unused ranked positions;
    record this fallback explicitly. Never reduce payload capacity.
    """
    if not math.isfinite(quota_fraction) or not 0 < quota_fraction <= 1:
        raise ValueError("quota_fraction must be finite and in (0,1]")
    if tile_blocks < 1:
        raise ValueError("tile_blocks must be positive")
    scores = balanced_scores(image)
    if count < 1 or count > scores.size:
        raise ValueError("Insufficient LL2 capacity")
    bh, bw = ((image.height + 3) // 4, (image.width + 3) // 4)
    perm = np.random.default_rng(SEED).permutation(scores.size)
    order = perm[np.argsort(-scores[perm], kind="stable")]
    ids = np.arange(scores.size)
    tiles_per_row = (bw + tile_blocks - 1) // tile_blocks
    tile_ids = ((ids // bw) // tile_blocks) * tiles_per_row + (
        (ids % bw) // tile_blocks)
    capacities = np.bincount(tile_ids)
    quotas = np.ceil(capacities * quota_fraction).astype(int)
    occupancy = np.zeros_like(quotas)
    selected = []
    for index in order:
        tile = tile_ids[index]
        if occupancy[tile] < quotas[tile]:
            selected.append(int(index))
            occupancy[tile] += 1
            if len(selected) == count:
                break
    initial = len(selected)
    if initial < count:
        used = np.zeros(scores.size, dtype=bool)
        used[selected] = True
        selected.extend([int(i) for i in order if not used[i]][:count - initial])
    result = np.asarray(selected, dtype=np.int64)
    if len(result) != count or np.unique(result).size != count:
        raise AssertionError("Capacity-preserving placement failed")
    return result, {"quota_initial": initial, "quota_fallback_count": count - initial}


def select_arm(image: Image.Image, count: int, strategy: str,
               quota_fraction: float) -> tuple[np.ndarray, dict]:
    if strategy == "balanced":
        return balanced_positions(image, count, quota_fraction)
    return select_positions(image, count, strategy), {
        "quota_initial": None, "quota_fallback_count": None,
    }


def run_one(source: Path, out: Path, packet: bytes, delta: float,
            repeat: int, quota_fraction: float) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    carrier = reference.convert("YCbCr").convert("RGB")
    scores = balanced_scores(reference)
    texture = coefficient_scores(reference)
    edge, flat = region_types(reference)
    count = len(packet) * 8 * repeat
    rows = []
    with codec_parameters(delta, repeat):
        for strategy in ("random", "texture", "balanced"):
            try:
                positions, quota = select_arm(reference, count, strategy, quota_fraction)
            except ValueError as exc:
                print(source.name, strategy, "SKIP", exc, flush=True)
                rows.append({"source": source.name, "strategy": strategy,
                             "status": "SKIP:" + str(exc)})
                continue
            marked = embed_with_map(carrier, packet, positions)
            prefix = f"{source.stem}-{strategy}"
            image_path = out / (prefix + ".png")
            map_path = out / (prefix + "-positions.npy")
            marked.save(image_path)
            np.save(map_path, positions)
            map_overlay(reference, positions, edge, flat, out / (prefix + "-map.png"))
            quality = quality_metrics(reference, marked)
            common = {
                "source": source.name,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "strategy": strategy,
                "marked_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "packet_sha256": hashlib.sha256(packet).hexdigest(),
                "map_sha256": hashlib.sha256(map_path.read_bytes()).hexdigest(),
                "delta": delta, "repeat": repeat, "selected_count": count,
                "ll2_capacity": scores.size,
                "eligible_texture_count": int(np.isfinite(texture).sum()),
                "selected_edge_fraction": float(edge[positions].mean()),
                "selected_flat_fraction": float(flat[positions].mean()),
                "selected_saturated_fraction": float((~np.isfinite(texture))[positions].mean()),
                "selected_score_median": float(np.median(scores[positions])),
                **quota,
            }
            for label, scale, jpeg_quality in TRANSFORMS:
                received = marked if scale is None else jpeg_after_resize(
                    marked, scale, jpeg_quality)
                diagnostic = diagnostics(received, marked.size, positions,
                                         packet, repeat, delta)
                rows.append({**common, "transform": label, **diagnostic, **quality})
                print(source.name, strategy, label, diagnostic["status"],
                      "majority", diagnostic["majority_bit_errors"],
                      "RS8 bytes", diagnostic["codeword_byte_errors"], flush=True)
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path, nargs="+")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.0)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--quota-fraction", type=float, default=.5)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = p.parse_args()
    if args.out.exists():
        p.error("Refusing to overwrite output directory")
    if not math.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if not math.isfinite(args.quota_fraction) or not 0 < args.quota_fraction <= 1:
        p.error("Invalid quota fraction")
    if len(set(args.sources)) != len(args.sources):
        p.error("Duplicate source images")
    if any(not x.is_file() or x.suffix.lower() not in (".png", ".jpg", ".jpeg")
           for x in args.sources):
        p.error("Sources must be existing PNG/JPEG images")
    packet = pack(args.message.encode("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    for source in args.sources:
        rows.extend(run_one(source, args.out, packet, args.delta, args.repeat,
                            args.quota_fraction))
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (args.out / "metrics.csv").open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(x) for x in args.sources],
        "delta": args.delta, "repeat": args.repeat,
        "message": args.message, "pilot": 0,
        "quota_fraction": args.quota_fraction, "tile_blocks": 8,
        "map": "ORIGINAL_ORACLE", "seed": SEED,
        "transforms": [x[0] for x in TRANSFORMS],
    }, indent=2), encoding="utf-8")
    print("Output:", args.out, flush=True)


if __name__ == "__main__":
    main()
