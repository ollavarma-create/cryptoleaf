#!/usr/bin/env python3
"""Controlled DWT DELTA/REPEAT ablation on fixed-pilot local cover images.

Research tool only: changes codec module parameters temporarily and restores
them even if an encode/decode fails. Encoder and decoder ALWAYS use the same
parameter pair. No production code or source images are modified.

The first stage tests *known original size*, not blind Fourier synchronization.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import hashlib
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from src import robust_image as robust
from src.robust_packet import HEADER_BYTES, pack
from tools.robust_batch_matrix import METRIC_FIELDS, image_paths
from tools.robust_multicover_diagnostics import header_errors
from tools.robust_pilot_sweep import (
    decode_known_at_size, jpeg_roundtrip, reference_image,
)
from tools.robust_quality_compare import quality_metrics
from tools.robust_resize_diagnostics import bit_errors

DEFAULT_NAMES = ("appfootprint-main.png", "Anna Maria Liikanen.jpg")
BASE_DELTA = 32.0
BASE_REPEAT = 9
ERROR_FIELDS = (
    "repeated_qim_errors", "majority_bit_errors", "header_bit_errors",
    "header_byte_errors", "codeword_byte_errors", "near_tie_votes",
)


@contextmanager
def codec_parameters(delta: float, repeat: int):
    """Use matched encoder/decoder parameters in one synchronous test case.

    Module constants are process-global: do NOT use this helper concurrently.
    The values are restored in a finally block, including on exceptions.
    """
    previous = robust.DELTA, robust.REPEAT
    robust.DELTA, robust.REPEAT = float(delta), int(repeat)
    try:
        yield
    finally:
        robust.DELTA, robust.REPEAT = previous


def parse_deltas(value: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError("DELTA values must be comma-separated numbers") from exc
    if not values or any(not math.isfinite(v) or not 8 <= v <= 128 for v in values):
        raise ValueError("DELTA values must be finite and between 8 and 128")
    return list(dict.fromkeys(values))


def parse_repeats(value: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError("REPEAT values must be comma-separated odd integers") from exc
    if not values or any(v < 1 or v > 31 or v % 2 == 0 for v in values):
        raise ValueError("REPEAT values must be odd integers from 1 to 31")
    return list(dict.fromkeys(values))


def parameter_grid(
    deltas: list[float], repeats: list[int],
    base_delta: float = BASE_DELTA, base_repeat: int = BASE_REPEAT,
) -> list[tuple[str, float, int]]:
    """Paired one-variable-at-a-time cases, with baseline exactly once."""
    return [
        ("baseline", base_delta, base_repeat),
        *[("delta", value, base_repeat) for value in deltas if value != base_delta],
        *[("repeat", base_delta, value) for value in repeats if value != base_repeat],
    ]


def columns() -> list[str]:
    return [
        "source", "source_sha256", "source_width", "source_height",
        "reference_width", "reference_height", "payload_sha256",
        "packet_bytes", "pilot_strength", "sweep_axis", "delta", "repeat",
        "ll2_capacity", "required_coefficients", "capacity_used_pct",
        "status", "png_oracle", "jpeg60_oracle",
        "scale_0.75_oracle", "scale_0.5_oracle",
        *METRIC_FIELDS,
        *["before_" + name for name in ERROR_FIELDS],
        *["after50_" + name for name in ERROR_FIELDS],
        "after50_magic_bit_errors", "after50_length_bit_errors",
        "after50_observed_length", "seconds",
    ]


def test_pair(
    reference: Image.Image,
    fixed_pilot: Image.Image,
    packet: bytes,
    payload: bytes,
    delta: float,
    repeat: int,
    pilot_strength: float,
    sweep_axis: str,
    images_out: Path | None = None,
    image_label: str = "",
) -> dict:
    """Encode once; evaluate matched known-size decoding and bit errors."""
    start = time.perf_counter()
    ll2_capacity = math.ceil(reference.width / 4) * math.ceil(reference.height / 4)
    needed = len(packet) * 8 * repeat
    row = {
        "pilot_strength": pilot_strength,
        "sweep_axis": sweep_axis,
        "delta": delta,
        "repeat": repeat,
        "ll2_capacity": ll2_capacity,
        "required_coefficients": needed,
        "capacity_used_pct": round(100 * needed / ll2_capacity, 2),
        "status": "OK",
    }
    if needed > ll2_capacity:
        row["status"] = "SKIP:insufficient_DWT_capacity"
        row["seconds"] = round(time.perf_counter() - start, 2)
        return row

    with codec_parameters(delta, repeat):
        try:
            marked = robust._feedback_embed(fixed_pilot, packet)
        except ValueError as exc:
            row["status"] = "SKIP:" + str(exc)
            row["seconds"] = round(time.perf_counter() - start, 2)
            return row

        row["png_oracle"] = decode_known_at_size(marked, marked.size, payload)
        row["jpeg60_oracle"] = decode_known_at_size(
            jpeg_roundtrip(marked, 60), marked.size, payload
        )
        metrics = quality_metrics(reference, marked)
        row.update({key: metrics[key] for key in METRIC_FIELDS})

        before = bit_errors(marked, packet)
        row.update({"before_" + key: before[key] for key in ERROR_FIELDS})
        for scale, label in ((0.75, "scale_0.75_oracle"), (0.5, "scale_0.5_oracle")):
            scaled_size = tuple(max(32, round(dim * scale)) for dim in marked.size)
            scaled = marked.resize(scaled_size, Image.Resampling.LANCZOS)
            row[label] = decode_known_at_size(scaled, marked.size, payload)
            if scale == 0.5:
                restored = scaled.resize(marked.size, Image.Resampling.LANCZOS)
                after = bit_errors(restored, packet)
                row.update({"after50_" + key: after[key] for key in ERROR_FIELDS})
                observed_header = robust._read_bytes(
                    restored, marked.size, HEADER_BYTES
                )
                h = header_errors(observed_header, packet[:HEADER_BYTES])
                row["after50_magic_bit_errors"] = h["magic_bit_errors"]
                row["after50_length_bit_errors"] = h["length_bit_errors"]
                row["after50_observed_length"] = h["observed_length"]

        if images_out is not None:
            marked.save(images_out / image_label)

    row["seconds"] = round(time.perf_counter() - start, 2)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Local input covers")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument(
        "--name", action="append", default=[],
        help="Exact source filename; repeat to override the two default covers",
    )
    parser.add_argument("--deltas", default="24,28,32,36,40,48,56,64")
    parser.add_argument("--repeats", default="5,7,9,11,13,15,17")
    parser.add_argument(
        "--pilot", type=float, default=0.0,
        help="Fixed nominal Fourier pilot strength for ALL cases (default: 0)",
    )
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep",
    )
    parser.add_argument(
        "--images-out", type=Path,
        help="Optional empty directory to save all marked PNGs for inspection",
    )
    args = parser.parse_args()

    try:
        if not math.isfinite(args.pilot) or not 0 <= args.pilot <= 0.5:
            raise ValueError("--pilot must be finite and between 0 and 0.5")
        deltas = parse_deltas(args.deltas)
        repeats = parse_repeats(args.repeats)
        grid = parameter_grid(deltas, repeats)
        paths = image_paths(args.directory, args.name or list(DEFAULT_NAMES))
        payload = args.message.encode("utf-8")
        packet = pack(payload)
        if args.csv.exists():
            raise ValueError(f"Refusing to overwrite existing CSV: {args.csv}")
        if args.images_out is not None and args.images_out.exists() and any(
            args.images_out.iterdir()
        ):
            raise ValueError(
                f"Image output directory must be empty: {args.images_out}"
            )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    if args.images_out is not None:
        args.images_out.mkdir(parents=True, exist_ok=True)

    print(
        f"Testing {len(paths)} covers × {len(grid)} DWT pairs "
        f"= {len(paths) * len(grid)} encodes; fixed pilot={args.pilot:g}; "
        "oracle-size decoding only.",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns())
        writer.writeheader()
        for index, path in enumerate(paths, 1):
            with Image.open(path) as opened:
                source_size = opened.size
                reference = reference_image(opened)
            fixed_pilot = (
                reference.convert("YCbCr").convert("RGB") if args.pilot == 0
                else robust._pilot_embed(reference, strength=args.pilot)
            )
            base = {
                "source": path.name,
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_width": source_size[0],
                "source_height": source_size[1],
                "reference_width": reference.width,
                "reference_height": reference.height,
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "packet_bytes": len(packet),
            }
            for axis, delta, repeat in grid:
                label = (
                    f"{index:02d}-{path.stem}-d{delta:g}-r{repeat}"
                    f"-pilot{args.pilot:g}.png"
                )
                result = test_pair(
                    reference, fixed_pilot, packet, payload,
                    delta, repeat, args.pilot, axis, args.images_out, label,
                )
                row = {**base, **result}
                writer.writerow(row)
                stream.flush()
                print(
                    f"[{index}/{len(paths)}] {path.name} "
                    f"{axis} DELTA={delta:g} REPEAT={repeat} "
                    f"PNG={row.get('png_oracle', '-')} "
                    f"J60={row.get('jpeg60_oracle', '-')} "
                    f"75%={row.get('scale_0.75_oracle', '-')} "
                    f"50%={row.get('scale_0.5_oracle', '-')} "
                    f"RSbytes={row.get('after50_codeword_byte_errors', '-')} "
                    f"PSNR={row.get('psnr_db', '-')} "
                    f"SSIM={row.get('ssim_y', '-')} "
                    f"status={row['status']}",
                    flush=True,
                )
    print("CSV:", args.csv)
    print(
        "IMPORTANT: DELTA/REPEAT are decoder-matched experimental parameters, "
        "NOT a backwards-compatible codec format. All scales use known "
        "original dimensions. Blind synchronization is not tested."
    )


if __name__ == "__main__":
    main()
