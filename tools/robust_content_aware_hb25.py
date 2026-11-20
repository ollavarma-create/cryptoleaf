#!/usr/bin/env python3
"""H-B2.5: texture-first placement with a soft spatial concentration cap.

Oracle-map research only. No blind decoder or production-code changes.
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

TILE = 16
CAP_FACTORS = (1.5, 2.0, 3.0)


def capped_positions(image, count, factor=None, tile=TILE):
    """Rank original-cover eligible LL2 positions by texture, cap per tile.

    factor=None: unchanged H-B2.4 texture baseline.
    factor>1: cap=ceil(factor*count/number_of_active_eligible_tiles).
    A cap may make a previously feasible cover infeasible: report SKIP,
    never silently lift the cap or use saturation-unsafe positions.
    """
    if tile < 1 or (factor is not None and (not np.isfinite(factor) or factor <= 1)):
        raise ValueError("Invalid cap or tile")
    scores = coefficient_scores(image)
    eligible = np.isfinite(scores)
    safe_count = int(eligible.sum())
    if count > len(scores) or count > safe_count:
        return None, {"reason": "INSUFFICIENT_TEXTURE", "eligible": safe_count}
    cols = (image.width + 3) // 4
    rows = (image.height + 3) // 4
    if rows * cols != len(scores):
        raise AssertionError("LL2 grid mismatch")
    tile_cols = (cols + tile - 1) // tile
    ids = ((np.arange(len(scores)) // cols) // tile) * tile_cols + (
        (np.arange(len(scores)) % cols) // tile)
    active = int(np.unique(ids[eligible]).size)
    cap = count if factor is None else int(np.ceil(factor * count / active))
    rng = np.random.default_rng(robust.SEED)
    perm = rng.permutation(len(scores))
    ranked = perm[np.argsort(-scores[perm], kind="stable")]
    ranked = ranked[eligible[ranked]]
    counts = np.zeros(int(ids.max()) + 1, dtype=np.int32)
    chosen = []
    for index in ranked:
        tid = ids[index]
        if counts[tid] < cap:
            chosen.append(int(index))
            counts[tid] += 1
            if len(chosen) == count:
                break
    info = {
        "eligible": safe_count, "active_eligible_tiles": active,
        "tile_side_ll2": tile, "cap_factor": factor,
        "cap_positions_per_tile": cap,
        "occupied_tiles": int(np.count_nonzero(counts)),
        "max_positions_per_tile": int(counts.max()),
    }
    if len(chosen) < count:
        return None, {**info, "reason": "SPATIAL_CAPACITY",
                      "available_under_cap": len(chosen)}
    selected = np.asarray(chosen, dtype=np.int64)
    return selected, {**info, "reason": "",
                      "selected_texture_mean": float(np.mean(scores[selected])),
                      "selected_texture_median": float(np.median(scores[selected])),
                      "available_under_cap": len(chosen)}


def write_csv(path, rows):
    if not rows:
        raise ValueError("No results")
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_one(source, out, packet, delta, repeat, factors, tile):
    with Image.open(source) as opened:
        ref = reference_image(opened)
    carrier = ref.convert("YCbCr").convert("RGB")
    count = len(packet) * 8 * repeat
    edge, flat = region_types(ref)
    rows = []
    for factor in (None, *factors):
        name = "texture_baseline" if factor is None else f"cap_{factor:g}"
        positions, info = capped_positions(ref, count, factor, tile)
        common = {"source": source.name, "strategy": name, "delta": delta,
                  "repeat": repeat, "selected_count": count, **info}
        if positions is None:
            rows.append({**common, "channel": "not_run", "status": "SKIP"})
            print(source.name, name, "SKIP", info["reason"], flush=True)
            continue
        marked, trace = feedback_step(carrier, packet, positions, delta, repeat, "inward")
        stem = source.stem + "-" + name
        path = out / (stem + "-inward.png")
        marked.save(path)
        np.save(out / (stem + "-positions.npy"), positions)
        quality = quality_metrics(ref, marked)
        details = {**common, "marked_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "selected_edge_fraction": float(edge[positions].mean()),
                   "selected_flat_fraction": float(flat[positions].mean()),
                   "feedback_iterations": len(trace),
                   "feedback_stepped_coefficients": trace[-1]["stepped_coefficients"],
                   "feedback_clipped_fraction": trace[-1]["clipped_pixel_fraction"],
                   **quality}
        for channel, scale, jpeg in CHANNELS:
            received = transform(marked, scale, jpeg)
            result = diagnostics(received, marked.size, positions, packet, repeat, delta)
            rows.append({**details, "channel": channel, **result})
            print(source.name, name, channel, result["status"],
                  result["repetition_errors"], flush=True)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    p.add_argument("--tile", type=int, default=TILE)
    p.add_argument("--cap-factors", nargs="+", type=float, default=list(CAP_FACTORS))
    args = p.parse_args()
    if args.out.exists():
        p.error("Output exists; refusing overwrite")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if args.tile < 1 or not args.cap_factors or len(set(args.cap_factors)) != len(args.cap_factors):
        p.error("Invalid tile or duplicate factors")
    if any(not np.isfinite(x) or x <= 1 for x in args.cap_factors):
        p.error("Cap factors must be finite and greater than 1")
    if not args.sources or len({x.stem for x in args.sources}) != len(args.sources):
        p.error("Provide unique source stems")
    if any(not x.is_file() or x.suffix.lower() not in (".png", ".jpg", ".jpeg")
           for x in args.sources):
        p.error("Missing or unsupported source")
    packet = pack(args.message.encode("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            rows.extend(run_one(source, args.out, packet, args.delta, args.repeat,
                                args.cap_factors, args.tile))
    write_csv(args.out / "metrics.csv", rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(x) for x in args.sources],
        "source_sha256": {x.name: hashlib.sha256(x.read_bytes()).hexdigest()
                          for x in args.sources},
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "tile_side_ll2": args.tile, "cap_factors": args.cap_factors,
        "strategies": ["texture_baseline"] + [f"cap_{x:g}" for x in args.cap_factors],
        "pilot": 0, "oracle_map": True, "embedding": "inward",
        "channels": [c[0] for c in CHANNELS],
        "warning": "No blind decoding. No validated perceptual safety threshold.",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
