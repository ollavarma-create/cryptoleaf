#!/usr/bin/env python3
"""Reproduce failed multicover resize cases and isolate CLR1/DWT bit errors.

Input: the CSV from robust_batch_matrix.py and the SAME original local covers.
For every cover with a recorded failure, retest all three pilot strengths at
both resize scales, including the passing controls. No codec changes.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from src import robust_image as robust
from src.robust_packet import HEADER_BYTES, pack
from tools.robust_pilot_sweep import reference_image
from tools.robust_resize_diagnostics import bit_errors


def selected_rows(matrix_csv: Path) -> list[dict]:
    """All pilot variants of covers that failed at least one resize scale."""
    with matrix_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Input CSV has no rows")
    scale_columns = [key for key in rows[0] if key.startswith("scale_") and key.endswith("_oracle")]
    if not scale_columns:
        raise ValueError("Input CSV contains no oracle scale columns")
    failing_covers = {
        row["source"] for row in rows
        if any(row[col] and row[col] != "PASS" for col in scale_columns)
    }
    return [row for row in rows if row["source"] in failing_covers]


def header_errors(received_header: bytes, expected_header: bytes) -> dict:
    magic = sum((a ^ b).bit_count() for a, b in zip(
        received_header[:4], expected_header[:4]
    ))
    length = sum((a ^ b).bit_count() for a, b in zip(
        received_header[4:6], expected_header[4:6]
    ))
    return {
        "magic_bit_errors": magic,
        "length_bit_errors": length,
        "observed_length": int.from_bytes(received_header[4:6], "big"),
        "expected_length": int.from_bytes(expected_header[4:6], "big"),
    }


def test_case(
    marked: Image.Image, packet: bytes, payload: bytes, scale: float
) -> dict:
    size = tuple(max(32, round(d * scale)) for d in marked.size)
    down = marked.resize(size, Image.Resampling.LANCZOS)
    restored = down.resize(marked.size, Image.Resampling.LANCZOS)
    before = bit_errors(marked, packet)
    after = bit_errors(restored, packet)
    received_header = robust._read_bytes(down, marked.size, HEADER_BYTES)
    try:
        recovered = robust.decode_at_size(down, marked.size)
        oracle = "PASS" if recovered == payload else "FAIL:payload_mismatch"
    except ValueError as exc:
        oracle = "FAIL:" + str(exc)
    return {
        "oracle": oracle,
        "scaled_size": f"{size[0]}x{size[1]}",
        **header_errors(received_header, packet[:HEADER_BYTES]),
        **{"before_" + k: v for k, v in before.items()},
        **{"after_" + k: v for k, v in after.items()},
        "rs8_byte_budget_exceeded": after["codeword_byte_errors"] > 4,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Original local input covers")
    parser.add_argument("--matrix", type=Path, required=True,
                        help="CSV from robust_batch_matrix.py")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = parser.parse_args()
    if args.csv.exists():
        parser.error(f"Refusing to overwrite CSV: {args.csv}")
    if not args.directory.is_dir():
        parser.error(f"Missing input directory: {args.directory}")
    try:
        rows = selected_rows(args.matrix)
        packet = pack(args.message.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if not rows:
        print("No failed resize cases in matrix; nothing to diagnose.")
        return
    scale_columns = [
        k for k in rows[0] if k.startswith("scale_") and k.endswith("_oracle")
    ]
    scales = [(k, float(k[len("scale_"):-len("_oracle")])) for k in scale_columns]
    output = []
    for source in dict.fromkeys(row["source"] for row in rows):
        path = args.directory / source
        if not path.is_file():
            parser.error(f"Missing original image: {path}")
        with Image.open(path) as opened:
            reference = reference_image(opened)
        zero_pilot = reference.convert("YCbCr").convert("RGB")
        for matrix_row in (row for row in rows if row["source"] == source):
            strength = float(matrix_row["nominal_strength"])
            pilot = (
                zero_pilot if strength == 0.0
                else robust._pilot_embed(reference, strength=strength)
            )
            marked = robust._feedback_embed(pilot, packet)
            for col, scale in scales:
                result = test_case(marked, packet, args.message.encode("utf-8"), scale)
                record = {
                    "source": source, "strength": strength, "scale": scale,
                    "matrix_oracle": matrix_row[col],
                    "reproduced": (
                        (result["oracle"] == "PASS") ==
                        (matrix_row[col] == "PASS")
                    ),
                    **result,
                }
                output.append(record)
                print(
                    f"{source} pilot={strength:.2f} scale={scale:g} "
                    f"oracle={record['oracle']} reproduced={record['reproduced']} "
                    f"magic={record['magic_bit_errors']} "
                    f"length={record['length_bit_errors']} "
                    f"codeword_bytes={record['after_codeword_byte_errors']} "
                    f"majority_bits={record['after_majority_bit_errors']} "
                    f"RS8_over_budget={record['rs8_byte_budget_exceeded']}",
                    flush=True,
                )
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print("CSV:", args.csv)
    print("Known original dimensions are used in every decode; this is not blind recovery.")


if __name__ == "__main__":
    main()
