#!/usr/bin/env python3
"""H-B1.6: JPEG parity flip versus original-cover features, oracle diagnosis.

No new embedding. Uses H-B1.5 inward PNGs and exact H-B1.2 maps.
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
from tools.robust_content_aware_hb1 import coefficient_scores, jpeg_after_resize
from tools.robust_content_aware_hb11 import diagnostics, region_types, TRANSFORMS
from tools.robust_content_aware_hb14 import parity
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image


def cover_features(image):
    """All predictors derive from the original, unmarked image."""
    y = robust._ycc(image)[:, :, 0]
    h, w = y.shape
    y = np.pad(y, ((0, (-h) % 4), (0, (-w) % 4)), mode="wrap")
    b = y.reshape(y.shape[0] // 4, 4, y.shape[1] // 4, 4)
    means = b.mean(axis=(1, 3)).ravel()
    std = b.std(axis=(1, 3)).ravel()
    minimum = b.min(axis=(1, 3)).ravel()
    maximum = b.max(axis=(1, 3)).ravel()
    # 0 at black/white; large when both clipping directions have headroom.
    headroom = np.minimum(minimum, 255 - maximum)
    edge, flat = region_types(image)
    return {
        "cover_mean": means,
        "cover_std": std,
        "cover_headroom": headroom,
        "cover_edge": edge.astype(int),
        "cover_flat": flat.astype(int),
        "texture_eligible": np.isfinite(coefficient_scores(image)).astype(int),
    }


def ll2(image, size):
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return pywt.wavedec2(robust._ycc(image)[:, :, 0], "haar",
                         level=2, mode="periodization")[0].ravel()


def analyze(reference, marked, positions, packet, repeat, delta, strategy, source):
    features = cover_features(reference)
    original_ll = ll2(reference, reference.size)
    marked_ll = ll2(marked, marked.size)
    expected = np.repeat(np.unpackbits(np.frombuffer(packet, dtype=np.uint8)), repeat)
    if positions.shape != expected.shape or np.unique(positions).size != positions.size:
        raise ValueError("Invalid position map")
    png_parity = parity(marked_ll[positions], delta)
    # Predictors based on original cover (except explicitly labeled PNG
    # margin, which is an encoder-side diagnostic and not a cover feature).
    cover_margin = .5 - np.abs(original_ll[positions] / delta -
                               np.rint(original_ll[positions] / delta))
    png_margin = .5 - np.abs(marked_ll[positions] / delta -
                             np.rint(marked_ll[positions] / delta))
    rows, summary = [], []
    for label, scale, quality in TRANSFORMS:
        received = marked if scale is None else jpeg_after_resize(marked, scale, quality)
        received_ll = ll2(received, marked.size)
        rx_parity = parity(received_ll[positions], delta)
        wrong = rx_parity != expected
        flip = rx_parity != png_parity
        drift = np.abs(received_ll[positions] - marked_ll[positions])
        diagnostic = diagnostics(received, marked.size, positions, packet, repeat, delta)
        summary.append({"source": source, "strategy": strategy, "transform": label,
                        "n": len(positions), "status": diagnostic["status"],
                        "png_errors": int(np.count_nonzero(png_parity != expected)),
                        "received_errors": int(wrong.sum()), "flips": int(flip.sum()),
                        "majority_bit_errors": diagnostic["majority_bit_errors"],
                        "header_bit_errors": diagnostic["header_bit_errors"],
                        "codeword_byte_errors": diagnostic["codeword_byte_errors"]})
        for j, index in enumerate(positions):
            rows.append({
                "source": source, "strategy": strategy, "transform": label,
                "repetition_index": j, "bit_index": j // repeat,
                "coefficient_index": int(index),
                **{k: round(float(v[index]), 5) for k, v in features.items()},
                "cover_lattice_margin": round(float(cover_margin[j] * delta), 5),
                "png_lattice_margin": round(float(png_margin[j] * delta), 5),
                "png_wrong": int(png_parity[j] != expected[j]),
                "received_wrong": int(wrong[j]), "channel_flip": int(flip[j]),
                "abs_ll2_drift": round(float(drift[j]), 5),
            })
    return rows, summary


def bins(rows):
    """Equal-count rank bins; compute each strategy/channel separately.

    Binning is descriptive only; no fitted model or out-of-sample claims.
    """
    out = []
    for source in sorted({r["source"] for r in rows}):
        for strategy in ("random", "texture", "balanced"):
            for transform in ("resize083_jpeg85", "resize068_jpeg70"):
                group = [r for r in rows if r["source"] == source and
                         r["strategy"] == strategy and r["transform"] == transform]
                if not group:
                    continue
                for feature in ("cover_mean", "cover_std", "cover_headroom",
                                "cover_lattice_margin", "png_lattice_margin"):
                    order = np.argsort(np.array([r[feature] for r in group]),
                                       kind="stable")
                    for quintile, indices in enumerate(np.array_split(order, 5), 1):
                        chosen = [group[int(i)] for i in indices]
                        out.append({
                            "source": source, "strategy": strategy,
                            "transform": transform, "feature": feature,
                            "quintile": quintile, "n": len(chosen),
                            "feature_min": min(r[feature] for r in chosen),
                            "feature_max": max(r[feature] for r in chosen),
                            "received_error_fraction": round(
                                sum(r["received_wrong"] for r in chosen) / len(chosen), 6),
                            "channel_flip_fraction": round(
                                sum(r["channel_flip"] for r in chosen) / len(chosen), 6),
                            "median_ll2_drift": round(float(np.median(
                                [r["abs_ll2_drift"] for r in chosen])), 5),
                        })
    return out


def write_csv(path, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


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
        p.error("Output directory already exists")
    if not np.isfinite(args.delta) or not 8 <= args.delta <= 128:
        p.error("Invalid DELTA")
    if not 1 <= args.repeat <= 31 or args.repeat % 2 != 1:
        p.error("Invalid REPEAT")
    if any(not s.is_file() for s in args.sources):
        p.error("Source image missing")
    packet = pack(args.message.encode("utf-8"))
    for source in args.sources:
        for strategy in ("random", "texture", "balanced"):
            if not (args.maps_dir / (source.stem + "-" + strategy + "-positions.npy")).is_file():
                p.error("Missing H-B1.2 map for " + source.stem + " " + strategy)
            if not (args.hb15_dir / (source.stem + "-" + strategy + "-inward.png")).is_file():
                p.error("Missing H-B1.5 inward image for " + source.stem + " " + strategy)
    rows, summary = [], []
    with codec_parameters(args.delta, args.repeat):
        for source in args.sources:
            with Image.open(source) as im:
                reference = reference_image(im)
            for strategy in ("random", "texture", "balanced"):
                prefix = source.stem + "-" + strategy
                positions = np.load(args.maps_dir / (prefix + "-positions.npy"), allow_pickle=False)
                if positions.shape != (len(packet) * 8 * args.repeat,) or not np.issubdtype(positions.dtype, np.integer):
                    raise ValueError("Unexpected map shape/type")
                with Image.open(args.hb15_dir / (prefix + "-inward.png")) as im:
                    marked = im.convert("RGB")
                if marked.size != reference.size:
                    raise ValueError("Marked image dimension mismatch")
                max_index = ((reference.width + 3) // 4) * ((reference.height + 3) // 4)
                if np.any(positions < 0) or np.any(positions >= max_index):
                    raise ValueError("Map out of bounds")
                a, b = analyze(reference, marked, positions, packet, args.repeat,
                               args.delta, strategy, source.name)
                rows.extend(a)
                summary.extend(b)
                print(source.name, strategy, *(f"{r['transform']}={r['status']}" for r in b),
                      flush=True)
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / "position_features.csv", rows)
    write_csv(args.out / "feature_quintiles.csv", bins(rows))
    write_csv(args.out / "channel_summary.csv", summary)
    (args.out / "settings.json").write_text(json.dumps({
        "sources": [str(s) for s in args.sources],
        "source_sha256": {s.name: hashlib.sha256(s.read_bytes()).hexdigest()
                          for s in args.sources},
        "maps_dir": str(args.maps_dir), "hb15_dir": str(args.hb15_dir),
        "delta": args.delta, "repeat": args.repeat,
        "message": args.message, "pilot": 0, "oracle_map": True,
        "image_arm": "inward", "transforms": [t[0] for t in TRANSFORMS],
        "interpretation": "descriptive only; no trained selector",
    }, indent=2), encoding="utf-8")
    print("Saved", args.out)


if __name__ == "__main__":
    main()
