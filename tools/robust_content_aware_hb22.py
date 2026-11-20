#!/usr/bin/env python3
"""H-B2.2: multi-cover placement/visual-quality/robustness validation.

Research-only original-cover oracle; fresh embedding on each cover.
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
from tools.robust_content_aware_hb1 import coefficient_scores
from tools.robust_content_aware_hb11 import diagnostics, map_overlay, region_types
from tools.robust_content_aware_hb12 import select_arm
from tools.robust_content_aware_hb15 import feedback_step
from tools.robust_content_aware_hb18 import channel
from tools.robust_content_aware_hb19 import down_up
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_quality_compare import quality_metrics

STRATEGIES = ("random", "texture", "balanced")
CHANNELS = (
    ("identity", None, None),
    ("resize095", .95, None),
    ("resize090", .90, None),
    ("resize080", .80, None),
    ("resize070", .70, None),
    ("resize060", .60, None),
    ("jpeg85", None, 85),
    ("resize083_jpeg85", .83, 85),
    ("resize068_jpeg70", .68, 70),
)


def transform(marked, scale, quality):
    if scale is None and quality is None:
        return marked
    if quality is None:
        return down_up(marked, scale)
    if scale is None:
        return channel(marked, 1., quality, "jpeg_only")
    return channel(marked, scale, quality, "resize_jpeg")


def write_csv(path, rows):
    if not rows:
        raise ValueError("No rows")
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_one(source, out, packet, delta, repeat, quota):
    with Image.open(source) as opened:
        ref = reference_image(opened)
    carrier = ref.convert("YCbCr").convert("RGB")
    needed = len(packet) * 8 * repeat
    texture = coefficient_scores(ref)
    edge, flat = region_types(ref)
    metrics_rows, trace_rows = [], []
    for strategy in STRATEGIES:
        common = {
            "source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "width": ref.width, "height": ref.height,
            "strategy": strategy, "delta": delta, "repeat": repeat,
            "selected_count": needed, "ll2_capacity": texture.size,
            "texture_eligible_count": int(np.isfinite(texture).sum()),
        }
        try:
            positions, quota_info = select_arm(ref, needed, strategy, quota)
        except ValueError as exc:
            metrics_rows.append({**common, "channel": "not_run",
                                 "status": "SKIP", "reason": str(exc)})
            print(source.name, strategy, "SKIP", str(exc), flush=True)
            continue
        marked, trace = feedback_step(carrier, packet, positions, delta, repeat, "inward")
        stem = source.stem + "-" + strategy
        marked_path = out / (stem + "-inward.png")
        marked.save(marked_path)
        np.save(out / (stem + "-positions.npy"), positions)
        map_overlay(ref, positions, edge, flat, out / (stem + "-map.png"))
        quality = quality_metrics(ref, marked)
        details = {
            **common, **quota_info,
            "marked_sha256": hashlib.sha256(marked_path.read_bytes()).hexdigest(),
            "selected_edge_fraction": float(edge[positions].mean()),
            "selected_flat_fraction": float(flat[positions].mean()),
            "selected_saturated_fraction": float((~np.isfinite(texture))[positions].mean()),
            "feedback_iterations": len(trace),
            "feedback_stepped_coefficients": trace[-1]["stepped_coefficients"],
            "feedback_clipped_fraction": trace[-1]["clipped_pixel_fraction"],
            **quality,
        }
        for step in trace:
            trace_rows.append({"source": source.name, "strategy": strategy, **step})
        for label, scale, jpeg_quality in CHANNELS:
            received = transform(marked, scale, jpeg_quality)
            d = diagnostics(received, marked.size, positions, packet, repeat, delta)
            metrics_rows.append({**details, "channel": label, "scale": scale,
                                 "jpeg_quality": jpeg_quality, **d})
            print(source.name, strategy, label, d["status"],
                  d["repetition_errors"], d["majority_bit_errors"], flush=True)
    return metrics_rows, trace_rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--delta", type=float, default=38.)
    p.add_argument("--repeat", type=int, default=13)
    p.add_argument("--quota-fraction", type=float, default=.5)
    p.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = p.parse_args()
    if args.out.exists():
        p.error("Output exists; refusing overwrite")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if not np.isfinite(args.quota_fraction) or not 0 < args.quota_fraction <= 1:
        p.error("Invalid quota fraction")
    if len({s.stem for s in args.sources}) != len(args.sources):
        p.error("Source stems must be unique")
    if not args.sources or any(not s.is_file() or s.suffix.lower() not in
                               (".png", ".jpg", ".jpeg") for s in args.sources):
        p.error("Provide existing PNG/JPEG sources")
    packet = pack(args.message.encode("utf-8"))
    args.out.mkdir(parents=True, exist_ok=False)
    rows, traces = [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            r, t = run_one(source, args.out, packet, args.delta, args.repeat,
                           args.quota_fraction)
            rows.extend(r)
            traces.extend(t)
    write_csv(args.out / "metrics.csv", rows)
    if traces:
        write_csv(args.out / "feedback_trace.csv", traces)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest()
                          for s in args.sources},
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "pilot": 0, "oracle_map": True, "embedding": "inward",
        "strategies": list(STRATEGIES), "quota_fraction": args.quota_fraction,
        "channels": [name for name, _, _ in CHANNELS],
        "jpeg_subsampling": 2, "resampling": "Lanczos",
        "warning": "Research only; original-cover oracle map, not blind recovery",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
