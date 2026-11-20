#!/usr/bin/env python3
"""H-B1.4 exact feedback replay: per-stage QIM parity and repair diagnostics."""
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
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools.robust_content_aware_hb11 import region_types


def parity(values, delta):
    return np.rint(values / delta).astype(np.int64) & 1


def counts(observed, target, repeat):
    wrong = observed != target
    per_bit = wrong.reshape(-1, repeat).sum(axis=1)
    majority = per_bit > repeat // 2
    head = HEADER_BYTES * 8
    return {
        "position_errors": int(wrong.sum()),
        "majority_bit_errors": int(majority.sum()),
        "header_bit_errors": int(majority[:head].sum()),
        "codeword_byte_errors": int(majority[head:].reshape(-1, 8).any(axis=1).sum()),
        "worst_bit_repetition_errors": int(per_bit.max()),
    }


def trace_feedback(carrier, packet, positions, delta, repeat):
    """Faithful copy of embed_with_map, with read-only intermediate probes."""
    a = robust._ycc(carrier)
    coeffs = pywt.wavedec2(a[:, :, 0], "haar", level=2, mode="periodization")
    ll = coeffs[0].copy()
    flat = ll.ravel()
    target = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
    if positions.shape != target.shape or np.unique(positions).size != len(positions):
        raise ValueError("Invalid map")
    q = robust._nearest_parity(flat[positions], target)
    rows = []
    previous_wrong = None
    for iteration in range(robust.FEEDBACK_ITERATIONS + 1):
        flat[positions] = q * delta
        coeffs[0] = ll
        reconstructed = pywt.waverec2(coeffs, "haar", mode="periodization")
        raw_y = reconstructed[:a.shape[0], :a.shape[1]]
        clipped_y = np.clip(raw_y, 0, 255)
        out = a.copy()
        out[:, :, 0] = clipped_y
        result = robust._from_ycc(out)
        stages = {
            "unclipped_y": raw_y,
            "clipped_y": clipped_y,
            "rounded_y": np.rint(clipped_y),
            "rgb_roundtrip_y": robust._ycc(result)[:, :, 0],
        }
        observed_ll = {}
        errors = {}
        for name, y in stages.items():
            observed_ll[name] = pywt.wavedec2(
                y, "haar", level=2, mode="periodization")[0].ravel()
            errors[name] = parity(observed_ll[name][positions], delta) != target
        wrong = errors["rgb_roundtrip_y"]
        row = {
            "iteration": iteration,
            "target_lattice_errors": int(np.count_nonzero((q & 1) != target)),
            "clipped_pixel_fraction": float(np.mean((raw_y < 0) | (raw_y > 255))),
            "rgb_y_abs_error_mean": float(np.mean(
                np.abs(stages["rgb_roundtrip_y"] - stages["rounded_y"]))),
            "repaired_since_previous": int((previous_wrong & ~wrong).sum())
                if previous_wrong is not None else 0,
            "new_errors_since_previous": int((~previous_wrong & wrong).sum())
                if previous_wrong is not None else 0,
        }
        for name, mask in errors.items():
            row[name + "_errors"] = int(mask.sum())
        row.update(counts(parity(observed_ll["rgb_roundtrip_y"][positions], delta),
                          target, repeat))
        rows.append(row)
        if not wrong.any() or iteration == robust.FEEDBACK_ITERATIONS:
            return result, rows
        q[wrong] = robust._nearest_parity(
            observed_ll["rgb_roundtrip_y"][positions][wrong], target[wrong])
        previous_wrong = wrong.copy()
    raise AssertionError("unreachable")


def run_one(source, marked_dir, packet, delta, repeat):
    with Image.open(source) as im:
        reference = reference_image(im)
    carrier = reference.convert("YCbCr").convert("RGB")
    edge, flat = region_types(reference)
    traces, final = [], []
    for strategy in ("random", "texture", "balanced"):
        stem = source.stem + "-" + strategy
        image_path = marked_dir / (stem + ".png")
        positions = np.load(marked_dir / (stem + "-positions.npy"), allow_pickle=False)
        count = len(packet) * 8 * repeat
        if positions.shape != (count,) or not np.issubdtype(positions.dtype, np.integer):
            raise ValueError("Bad map shape/type: " + stem)
        if np.any(positions < 0) or np.any(positions >= edge.size) or np.unique(positions).size != count:
            raise ValueError("Bad map indices: " + stem)
        replay, steps = trace_feedback(carrier, packet, positions, delta, repeat)
        with Image.open(image_path) as im:
            saved = im.convert("RGB")
        if saved.size != replay.size or not np.array_equal(np.asarray(saved), np.asarray(replay)):
            raise ValueError("REPLAY_MISMATCH: " + stem)
        traces.extend({"source": source.name, "strategy": strategy, **step} for step in steps)
        ll = pywt.wavedec2(robust._ycc(saved)[:, :, 0],
                           "haar", level=2, mode="periodization")[0].ravel()
        target = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
        wrong = parity(ll[positions], delta) != target
        for label, mask in (
            ("all", np.ones(count, dtype=bool)),
            ("directional_edge", edge[positions]),
            ("flat", flat[positions]),
            ("other", ~(edge[positions] | flat[positions])),
        ):
            final.append({
                "source": source.name, "strategy": strategy, "class": label,
                "n": int(mask.sum()), "wrong_positions": int((wrong & mask).sum()),
                "error_fraction": float(wrong[mask].mean()) if mask.any() else None,
                "saved_png_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "replay_pixel_equal": True,
            })
        print(source.name, strategy, "replay=EXACT", "iterations", len(steps),
              "PNG wrong positions", int(wrong.sum()), flush=True)
    return traces, final


def write_csv(path, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
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
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if any(not s.is_file() for s in args.sources):
        p.error("Missing source image")
    packet = pack(args.message.encode("utf-8"))
    for source in args.sources:
        for strategy in ("random", "texture", "balanced"):
            for suffix in (".png", "-positions.npy"):
                path = args.marked_dir / (source.stem + "-" + strategy + suffix)
                if not path.is_file():
                    p.error("Missing H-B1.2 artifact: " + str(path))
    traces, final = [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            a, b = run_one(source, args.marked_dir, packet, args.delta, args.repeat)
            traces.extend(a)
            final.extend(b)
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / "feedback_iterations.csv", traces)
    write_csv(args.out / "final_region_errors.csv", final)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest()
                          for s in args.sources},
        "marked_dir": str(args.marked_dir), "delta": args.delta,
        "repeat": args.repeat, "message": args.message,
        "pilot": 0, "map": "original-cover oracle",
        "replay": "pixel-identical required",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out, flush=True)


if __name__ == "__main__":
    main()
