#!/usr/bin/env python3
"""Generate deterministic synthetic UI covers for Fourier pilot diagnostics.

Research only. Seven matched 960x720 covers isolate horizontal lines,
vertical lines, their combination, coloured bars and correlated texture.
The fixed near-white background is RGB(248,248,248). Optional real
controls are copied byte-for-byte into the same output directory.
Nothing is embedded here; run the existing angular/multimask probes
on the generated images. Refuse to overwrite any previous results.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter


CASES = (
    ("00-flat.png", False, False, False, False),
    ("01-horizontal.png", True, False, False, False),
    ("02-vertical.png", False, True, False, False),
    ("03-grid.png", True, True, False, False),
    ("04-grid-bars.png", True, True, True, False),
    ("05-texture.png", False, False, False, True),
    ("06-grid-bars-texture.png", True, True, True, True),
)
MANIFEST = "synthetic-manifest.csv"
FIELDS = (
    "file", "kind", "horizontal", "vertical", "color_bars",
    "texture", "width", "height", "sha256",
    "near_white_fraction", "nearly_gray_fraction",
)


def _texture(width: int, height: int, seed: int) -> np.ndarray:
    """Spatially correlated greyscale texture, not independent pixel noise."""
    rng = np.random.default_rng(seed)
    shape = (height, width)
    fine = gaussian_filter(rng.normal(size=shape), sigma=2.0)
    coarse = gaussian_filter(rng.normal(size=shape), sigma=12.0)
    fine = fine / max(float(fine.std()), 1e-12)
    coarse = coarse / max(float(coarse.std()), 1e-12)
    y = np.clip(np.rint(248 + 7 * fine + 3 * coarse), 0, 255).astype(np.uint8)
    return np.repeat(y[:, :, None], 3, axis=2)


def make_covers(
    width: int = 960, height: int = 720, seed: int = 20261119,
) -> dict[str, Image.Image]:
    """Return seven paired RGB covers with precisely defined interventions."""
    if not 256 <= width <= 1280 or not 256 <= height <= 1280:
        raise ValueError("Width and height must each be 256..1280")
    if ((width + 3) // 4) * ((height + 3) // 4) < 6032:
        raise ValueError("Insufficient LL2 capacity for the 58-byte 38/13 packet")

    plain = np.full((height, width, 3), 248, dtype=np.uint8)
    textured = _texture(width, height, seed)
    margin = max(24, min(width, height) // 18)
    spacing = max(32, min(width, height) // 12)
    line_width = 2

    covers: dict[str, Image.Image] = {}
    for filename, horizontal, vertical, bars, texture in CASES:
        image = Image.fromarray(textured.copy() if texture else plain.copy(), "RGB")
        draw = ImageDraw.Draw(image)
        if horizontal:
            for y in range(margin, height - margin, spacing):
                draw.line((margin, y, width - margin - 1, y),
                          fill=(65, 65, 65), width=line_width)
        if vertical:
            for x in range(margin, width - margin, spacing):
                draw.line((x, margin, x, height - margin - 1),
                          fill=(65, 65, 65), width=line_width)
        if bars:
            top = height // 2
            bottom = min(height - margin - 1, top + height // 4)
            usable = width - 2 * margin
            for i, color in enumerate((
                (35, 150, 200), (190, 40, 70),
                (35, 150, 200), (190, 40, 70),
            )):
                left = margin + (2 * i + 1) * usable // 10
                right = margin + (2 * i + 2) * usable // 10
                draw.rectangle((left, top, right, bottom),
                               fill=color)
        covers[filename] = image
    return covers


def _row(path: Path, kind: str, flags: tuple | None = None) -> dict:
    with Image.open(path) as opened:
        rgb = np.asarray(opened.convert("RGB"), dtype=np.uint8)
    channel_spread = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    return {
        "file": path.name,
        "kind": kind,
        "horizontal": "" if flags is None else int(flags[0]),
        "vertical": "" if flags is None else int(flags[1]),
        "color_bars": "" if flags is None else int(flags[2]),
        "texture": "" if flags is None else int(flags[3]),
        "width": rgb.shape[1],
        "height": rgb.shape[0],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "near_white_fraction": round(float(np.all(rgb > 235, axis=2).mean()), 6),
        "nearly_gray_fraction": round(float((channel_spread < 8).mean()), 6),
    }


def write_covers(
    output: Path, controls: list[Path] | None = None,
    width: int = 960, height: int = 720, seed: int = 20261119,
) -> list[dict]:
    """Create images and manifest in an empty directory; preserve controls."""
    controls = controls or []
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be absent or empty")
    names = [p.name for p in controls]
    reserved = {item[0] for item in CASES} | {MANIFEST}
    if len(set(names)) != len(names) or any(name in reserved for name in names):
        raise ValueError("Duplicate or reserved control filename")
    for path in controls:
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError(f"Missing or unsupported control image: {path}")
    covers = make_covers(width, height, seed)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, *flags in CASES:
        path = output / name
        covers[name].save(path)
        rows.append(_row(path, "synthetic", tuple(flags)))
    for source in controls:
        destination = output / source.name
        shutil.copyfile(source, destination)
        rows.append(_row(destination, "real_control"))
    with (output / MANIFEST).open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control", type=Path, action="append", default=[],
                        help="Optional real control image to copy unchanged; repeat")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--seed", type=int, default=20261119)
    args = parser.parse_args()
    try:
        rows = write_covers(
            args.output, args.control, args.width, args.height, args.seed
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Generated {len(CASES)} synthetic covers and "
          f"{len(rows) - len(CASES)} copied controls in {args.output}")
    for row in rows:
        print(f"{row['file']}: near-white={row['near_white_fraction']:.3f}, "
              f"nearly-gray={row['nearly_gray_fraction']:.3f}")
    print("Manifest:", args.output / MANIFEST)


if __name__ == "__main__":
    main()
