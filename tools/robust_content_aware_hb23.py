#!/usr/bin/env python3
"""H-B2.3: capacity-aware texture fallback and pre-embed warning experiment.

Research-only original-cover oracle. Never modifies production codec.
"""
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
from src.robust_packet import pack
from src import robust_image as robust
from tools.robust_content_aware_hb1 import coefficient_scores, select_positions
from tools.robust_content_aware_hb11 import diagnostics, region_types
from tools.robust_content_aware_hb15 import feedback_step
from tools.robust_content_aware_hb22 import CHANNELS, transform
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_quality_compare import quality_metrics

# The threshold is an experimental eligibility policy, NOT a validated
# predictor of perceptual quality or resampling robustness.
POLICIES = ("strict", "relaxed", "fill")
THRESHOLDS = (0., 2., 5., 10.)


def ranked_positions(image, count, policy, threshold):
    """Return positions and capacity diagnostics, or (None, diagnostics).

    Strict: original saturation-safe candidates only, std >= threshold.
    Relaxed: saturation-safe candidates, std >= threshold; can be less
      selective than the original top-texture ranking at lower thresholds.
    Fill: candidates above threshold first, then remaining positions in
      descending texture order, including unsafe/saturated if necessary.
    All choices are from ORIGINAL cover only, with deterministic tie-breaks.
    """
    if policy not in POLICIES or not np.isfinite(threshold) or threshold < 0:
        raise ValueError("Invalid placement policy or threshold")
    score = coefficient_scores(image)
    if count > score.size:
        return None, {"reason": "LL2_CAPACITY", "eligible": 0, "fallback": 0}
    # Recompute local std without the saturation exclusion for fallback order.
    y = robust._ycc(image)[:, :, 0]
    h, w = y.shape
    blocks = np.pad(y, ((0, -h % 4), (0, -w % 4)), mode="wrap").reshape(
        (h + (-h % 4)) // 4, 4, (w + (-w % 4)) // 4, 4)
    std = blocks.std(axis=(1, 3)).ravel()
    safe = np.isfinite(score)
    eligible = safe & (std >= threshold)
    perm = np.random.default_rng(robust.SEED).permutation(score.size)
    ordered = perm[np.argsort(-std[perm], kind="stable")]
    first = ordered[eligible[ordered]]
    info = {"eligible": int(eligible.sum()), "safe": int(safe.sum()),
            "ll2_capacity": len(score), "threshold": threshold, "policy": policy}
    if policy in ("strict", "relaxed") and len(first) < count:
        return None, {**info, "reason": "INSUFFICIENT_ELIGIBLE", "fallback": 0}
    if policy == "fill":
        second = ordered[~eligible[ordered]]
        positions = np.concatenate([first, second])[:count]
    else:
        positions = first[:count]
    fallback = int(np.count_nonzero(~eligible[positions]))
    if len(positions) != count or np.unique(positions).size != count:
        raise AssertionError("Placement capacity/uniqueness invariant")
    return positions.astype(np.int64), {**info, "reason": "",
                                       "fallback": fallback,
                                       "fallback_fraction": fallback / count,
                                       "selected_std_median": float(np.median(std[positions])),
                                       "selected_std_min": float(std[positions].min()),
                                       "selected_saturated_fraction": float((~safe[positions]).mean())}


def write_csv(path, rows):
    if not rows:
        raise ValueError("No output")
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_one(source, out, packet, delta, repeat, thresholds):
    with Image.open(source) as im:
        ref = reference_image(im)
    carrier = ref.convert("YCbCr").convert("RGB")
    count = len(packet) * 8 * repeat
    edge, flat = region_types(ref)
    rows = []
    for threshold in thresholds:
        # 'strict' is a no-fallback control; 'fill' is the explicit
        # capacity-preserving treatment. A lower threshold is not itself
        # a new strategy unless the selected map changes.
        for policy in ("strict", "fill"):
            positions, info = ranked_positions(ref, count, policy, threshold)
            common = {"source": source.name, "policy": policy,
                      "threshold": threshold, "delta": delta, "repeat": repeat,
                      "selected_count": count, **info}
            if positions is None:
                rows.append({**common, "channel": "not_run", "status": "SKIP"})
                print(source.name, policy, threshold, "SKIP", info["reason"], flush=True)
                continue
            marked, trace = feedback_step(carrier, packet, positions, delta, repeat, "inward")
            stem = f"{source.stem}-{policy}-t{threshold:g}"
            path = out / (stem + ".png")
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
            for name, scale, jpeg_quality in CHANNELS:
                received = transform(marked, scale, jpeg_quality)
                d = diagnostics(received, marked.size, positions, packet, repeat, delta)
                rows.append({**details, "channel": name, **d})
                print(source.name, policy, threshold, name, d["status"], flush=True)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    p.add_argument("--thresholds", nargs="+", type=float, default=list(THRESHOLDS))
    args = p.parse_args()
    if args.out.exists():
        p.error("Output exists; refusing overwrite")
    if not math.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if args.repeat < 1 or args.repeat > 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if not args.thresholds or any(not math.isfinite(t) or t < 0 for t in args.thresholds):
        p.error("Invalid thresholds")
    if len(set(args.thresholds)) != len(args.thresholds):
        p.error("Duplicate thresholds")
    if not args.sources or len({s.stem for s in args.sources}) != len(args.sources):
        p.error("Provide uniquely named source images")
    if any(not s.is_file() or s.suffix.lower() not in (".png", ".jpg", ".jpeg")
           for s in args.sources):
        p.error("Missing PNG/JPEG source")
    packet = pack(args.message.encode("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            rows.extend(run_one(source, args.out, packet, args.delta, args.repeat,
                                args.thresholds))
    write_csv(args.out / "metrics.csv", rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest()
                          for s in args.sources},
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "thresholds": args.thresholds, "policies": ["strict", "fill"],
        "pilot": 0, "oracle_map": True, "embedding": "inward",
        "channels": [c[0] for c in CHANNELS],
        "warning": "Experimental capacity warning only; not perceptual risk classifier",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
