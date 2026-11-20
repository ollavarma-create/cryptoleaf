#!/usr/bin/env python3
"""H-B1.5: controlled same-parity lattice stepping, oracle research only.

Ablation: baseline vs one-step inward vs outward vs adaptive inward
per still-wrong coefficient. No inversion, blur, or source edits.
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
from src.robust_packet import pack
from tools.robust_content_aware_hb11 import diagnostics, TRANSFORMS
from tools.robust_content_aware_hb1 import jpeg_after_resize
from tools.robust_content_aware_hb14 import trace_feedback, parity, counts
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_quality_compare import quality_metrics

ARMS = ("baseline", "inward", "outward", "adaptive")
# A step of two integer lattice points preserves parity (2*DELTA LL2).
# Cap per-coefficient excursions at one such step relative to initial q.


def feedback_step(carrier, packet, positions, delta, repeat, mode):
    if mode not in ARMS[1:]:
        raise ValueError("Unknown feedback mode")
    a = robust._ycc(carrier)
    coeffs = pywt.wavedec2(a[:, :, 0], "haar", level=2, mode="periodization")
    ll = coeffs[0].copy()
    flat = ll.ravel()
    target = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
    if positions.shape != target.shape or np.unique(positions).size != len(positions):
        raise ValueError("Invalid coefficient map")
    q0 = robust._nearest_parity(flat[positions], target)
    q = q0.copy()
    # LL2 of Y for a 4x4 Haar block is approximately 4 * local mean.
    local_mean = flat[positions] / 4.
    direction = np.where(local_mean >= 128, -1, 1).astype(np.int64)
    if mode == "outward":
        direction *= -1
    rows = []
    previous_wrong = None
    for iteration in range(robust.FEEDBACK_ITERATIONS + 1):
        flat[positions] = q * delta
        coeffs[0] = ll
        reconstructed = pywt.waverec2(coeffs, "haar", mode="periodization")
        raw_y = reconstructed[:a.shape[0], :a.shape[1]]
        out = a.copy()
        out[:, :, 0] = np.clip(raw_y, 0, 255)
        result = robust._from_ycc(out)
        observed = pywt.wavedec2(robust._ycc(result)[:, :, 0],
                                 "haar", level=2, mode="periodization")[0].ravel()
        wrong = parity(observed[positions], delta) != target
        row = {
            "iteration": iteration,
            "clipped_pixel_fraction": float(np.mean((raw_y < 0) | (raw_y > 255))),
            "stepped_coefficients": int(np.count_nonzero(q != q0)),
            "fixed_from_previous": int((previous_wrong & ~wrong).sum()) if previous_wrong is not None else 0,
            "new_from_previous": int((~previous_wrong & wrong).sum()) if previous_wrong is not None else 0,
            **counts(parity(observed[positions], delta), target, repeat),
        }
        rows.append(row)
        if not wrong.any() or iteration == robust.FEEDBACK_ITERATIONS:
            return result, rows
        previous_wrong = wrong.copy()
        # Do not re-step coefficients already moved. This isolates the
        # single-lattice-excursion hypothesis and avoids oscillations.
        candidates = wrong & (q == q0)
        if mode == "adaptive":
            # Select the direction with greater original luminance headroom;
            # a one-step local perturbation is not guaranteed to be correct.
            step_direction = np.where(local_mean >= 128, -1, 1)
        else:
            step_direction = direction
        q[candidates] += 2 * step_direction[candidates]
        # No other coefficient or image parameter changes.
    raise AssertionError("unreachable")


def run_one(source, marked_dir, out, packet, delta, repeat):
    with Image.open(source) as im:
        reference = reference_image(im)
    carrier = reference.convert("YCbCr").convert("RGB")
    target = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
    rows, trace_rows = [], []
    for strategy in ("random", "texture", "balanced"):
        stem = source.stem + "-" + strategy
        positions = np.load(marked_dir / (stem + "-positions.npy"), allow_pickle=False)
        if positions.shape != target.shape or not np.issubdtype(positions.dtype, np.integer):
            raise ValueError("Map shape/type mismatch " + stem)
        if np.any(positions < 0) or np.any(positions >= ((reference.width+3)//4)*((reference.height+3)//4)) or np.unique(positions).size != len(positions):
            raise ValueError("Map index error " + stem)
        for arm in ARMS:
            if arm == "baseline":
                marked, trace = trace_feedback(carrier, packet, positions, delta, repeat)
                with Image.open(marked_dir / (stem + ".png")) as im:
                    saved = im.convert("RGB")
                if not np.array_equal(np.asarray(saved), np.asarray(marked)):
                    raise ValueError("BASELINE_REPLAY_MISMATCH " + stem)
            else:
                marked, trace = feedback_step(carrier, packet, positions, delta, repeat, arm)
            image_path = out / (stem + "-" + arm + ".png")
            marked.save(image_path)
            metrics = quality_metrics(reference, marked)
            for step in trace:
                trace_rows.append({"source": source.name, "strategy": strategy,
                                   "arm": arm, **step})
            for label, scale, quality in TRANSFORMS:
                received = marked if scale is None else jpeg_after_resize(marked, scale, quality)
                d = diagnostics(received, marked.size, positions, packet, repeat, delta)
                rows.append({
                    "source": source.name, "strategy": strategy, "arm": arm,
                    "transform": label, "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "baseline_replay_exact": arm == "baseline",
                    "iterations": len(trace),
                    "final_stepped_coefficients": trace[-1].get("stepped_coefficients", 0),
                    "final_clipped_fraction": trace[-1]["clipped_pixel_fraction"],
                    **d, **metrics,
                })
                print(source.name, strategy, arm, label, d["status"],
                      "majority", d["majority_bit_errors"], flush=True)
    return rows, trace_rows


def write_csv(path, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+", type=Path)
    p.add_argument("--marked-dir", required=True, type=Path)
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
    packet = pack(args.message.encode("utf-8"))
    for source in args.sources:
        for strategy in ("random", "texture", "balanced"):
            for suffix in (".png", "-positions.npy"):
                if not (args.marked_dir / (source.stem + "-" + strategy + suffix)).is_file():
                    p.error("Missing H-B1.2 artifact: " + source.stem + "-" + strategy + suffix)
    args.out.mkdir(parents=True, exist_ok=False)
    rows, trace_rows = [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            r, t = run_one(source, args.marked_dir, args.out, packet, args.delta, args.repeat)
            rows.extend(r)
            trace_rows.extend(t)
    write_csv(args.out / "metrics.csv", rows)
    write_csv(args.out / "feedback_trace.csv", trace_rows)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest() for s in args.sources},
        "marked_dir": str(args.marked_dir),
        "delta": args.delta, "repeat": args.repeat, "message": args.message,
        "pilot": 0, "oracle_map": True, "arms": list(ARMS),
        "max_extra_lattice_steps": 1, "step_size_ll2": 2 * args.delta,
        "transforms": [t[0] for t in TRANSFORMS],
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
