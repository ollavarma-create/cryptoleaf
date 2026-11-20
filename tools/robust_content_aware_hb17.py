#!/usr/bin/env python3
"""H-B1.7: DWT/JPEG geometry and conditional parity errors (oracle diagnosis).

Reuses H-B1.6 position_features.csv. No new embedding or image changes.
The resized JPEG grid is mapped approximately from original 4x4 footprints.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from tools.robust_content_aware_hb11 import TRANSFORMS


def jpeg_footprint(index: int, width: int, height: int, scale: float) -> dict:
    """Center-aligned approximate 4x4 source footprint in resized JPEG pixels.

    The exact Lanczos support is larger than this footprint. A coefficient
    spans four source pixels; report block crossing, not a false exact
    'JPEG block membership' after resampling.
    """
    llw = (width + 3) // 4
    row, col = divmod(int(index), llw)
    rw = max(1, round(width * scale))
    rh = max(1, round(height * scale))
    x0 = col * 4 * rw / width
    x1 = min((col + 1) * 4, width) * rw / width
    y0 = row * 4 * rh / height
    y1 = min((row + 1) * 4, height) * rh / height
    # Half-open footprint; floating-point epsilon avoids a boundary
    # accidentally counting an adjacent JPEG block.
    bx0, bx1 = int(np.floor(x0 / 8)), int(np.floor((x1 - 1e-9) / 8))
    by0, by1 = int(np.floor(y0 / 8)), int(np.floor((y1 - 1e-9) / 8))
    return {
        "dwt_phase_x": col % 2, "dwt_phase_y": row % 2,
        "jpeg_blocks_x": bx1 - bx0 + 1,
        "jpeg_blocks_y": by1 - by0 + 1,
        "jpeg_block_crossing": int(bx0 != bx1 or by0 != by1),
        "jpeg_footprint_x_mod8": round(float(x0 % 8), 5),
        "jpeg_footprint_y_mod8": round(float(y0 % 8), 5),
        "resized_width": rw, "resized_height": rh,
    }


def rate(group, key):
    return round(sum(int(r[key]) for r in group) / len(group), 6) if group else None


def aggregate(rows, field, values=None):
    """Stratify per image/strategy/channel; no pooled Simpson inference."""
    out = []
    combos = sorted({(r["source"], r["strategy"], r["transform"]) for r in rows})
    for source, strategy, transform in combos:
        subset = [r for r in rows if (r["source"], r["strategy"], r["transform"]) ==
                  (source, strategy, transform)]
        labels = sorted({str(r[field]) for r in subset}) if values is None else values
        for label in labels:
            group = [r for r in subset if str(r[field]) == str(label)]
            if not group:
                continue
            out.append({
                "source": source, "strategy": strategy, "transform": transform,
                "feature": field, "group": label, "n": len(group),
                "error_fraction": rate(group, "received_wrong"),
                "flip_fraction": rate(group, "channel_flip"),
                "median_drift": round(float(np.median(
                    [r["abs_ll2_drift"] for r in group])), 5),
                "median_png_margin": round(float(np.median(
                    [r["png_lattice_margin"] for r in group])), 5),
                "median_cover_std": round(float(np.median(
                    [r["cover_std"] for r in group])), 5),
            })
    return out


def quartiles(rows, feature, label):
    """Within-arm equal-count ranks; control for texture or PNG margin."""
    result = []
    combos = sorted({(r["source"], r["strategy"], r["transform"]) for r in rows})
    for source, strategy, transform in combos:
        group = [r for r in rows if (r["source"], r["strategy"], r["transform"]) ==
                 (source, strategy, transform)]
        order = np.argsort([float(r[feature]) for r in group], kind="stable")
        for rank, inds in enumerate(np.array_split(order, 4)):
            for i in inds:
                row = dict(group[int(i)])
                row[label] = rank
                result.append(row)
    return result


def conditioned(rows):
    """Phase and crossing effects within both texture and margin quartiles.

    These are descriptive observational contrasts, not causal effects.
    """
    enriched = quartiles(rows, "cover_std", "texture_quartile")
    enriched = quartiles(enriched, "png_lattice_margin", "margin_quartile")
    out = []
    keys = sorted({(r["source"], r["strategy"], r["transform"],
                    r["texture_quartile"], r["margin_quartile"])
                   for r in enriched})
    for source, strategy, transform, tq, mq in keys:
        base = [r for r in enriched if (r["source"], r["strategy"],
                r["transform"], r["texture_quartile"], r["margin_quartile"]) ==
                (source, strategy, transform, tq, mq)]
        for feature in ("dwt_phase", "jpeg_block_crossing"):
            for value in sorted({str(r[feature]) for r in base}):
                group = [r for r in base if str(r[feature]) == value]
                out.append({
                    "source": source, "strategy": strategy,
                    "transform": transform, "texture_quartile": tq,
                    "margin_quartile": mq, "feature": feature,
                    "group": value, "n": len(group),
                    "error_fraction": rate(group, "received_wrong"),
                    "flip_fraction": rate(group, "channel_flip"),
                })
    return out


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        raise ValueError("No rows")
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positions", required=True, type=Path,
                   help="H-B1.6 position_features.csv")
    p.add_argument("--sources", nargs="+", required=True, type=Path,
                   help="Original source images; matched by filename")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    if args.out.exists():
        p.error("Output directory exists; no overwrites")
    rows = read_csv(args.positions)
    if not rows:
        p.error("Empty input CSV")
    sizes = {}
    for source in args.sources:
        if source.name in sizes:
            p.error("Duplicate source basename")
        with Image.open(source) as im:
            sizes[source.name] = im.size
    expected_transforms = {x[0]: x[1] for x in TRANSFORMS if x[1] is not None}
    enriched = []
    seen = set()
    for row in rows:
        if row["source"] not in sizes:
            p.error("Missing original source " + row["source"])
        transform = row["transform"]
        if transform not in expected_transforms:
            # PNG contains no JPEG grid; omit rather than fake geometry.
            continue
        key = (row["source"], row["strategy"], transform, row["repetition_index"])
        if key in seen:
            p.error("Duplicate repetition row: " + str(key))
        seen.add(key)
        width, height = sizes[row["source"]]
        geo = jpeg_footprint(int(row["coefficient_index"]), width, height,
                             expected_transforms[transform])
        enriched.append({
            **row, **geo,
            "dwt_phase": str(geo["dwt_phase_x"]) + str(geo["dwt_phase_y"]),
            "cover_std_bin": ("low" if float(row["cover_std"]) < 2 else
                              "high" if float(row["cover_std"]) >= 20 else "mid"),
            "png_margin_bin": ("low" if float(row["png_lattice_margin"]) < 10 else
                               "high" if float(row["png_lattice_margin"]) >= 16 else "mid"),
        })
    if not enriched:
        p.error("No JPEG rows")
    for source in sizes:
        if not any(r["source"] == source for r in enriched):
            p.error("No rows for " + source)
    summary = []
    for feature in ("dwt_phase", "jpeg_block_crossing", "cover_std_bin",
                    "png_margin_bin"):
        summary.extend(aggregate(enriched, feature))
    interaction = conditioned(enriched)
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / "geometry_positions.csv", enriched)
    write_csv(args.out / "geometry_groups.csv", summary)
    write_csv(args.out / "conditional_groups.csv", interaction)
    (args.out / "settings.json").write_text(json.dumps({
        "input_csv": str(args.positions), "sources": [str(x) for x in args.sources],
        "transforms": expected_transforms,
        "geometry": "approximate resampled 4x4 footprint vs JPEG 8x8 grid",
        "limits": "Lanczos support exceeds footprint; associations not causal",
        "no_new_embedding": True,
    }, indent=2), encoding="utf-8")
    print("Saved", args.out, "positions", len(enriched),
          "groups", len(summary), "conditional groups", len(interaction))


if __name__ == "__main__":
    main()
