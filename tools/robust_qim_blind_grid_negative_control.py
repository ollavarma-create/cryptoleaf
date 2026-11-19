#!/usr/bin/env python3
"""Research-only UNMARKED negative control for the blind QIM LL2-grid sweep.

This runs exactly the same received-size -> LL2-grid -> QIM-CLR1-header
search as robust_qim_blind_grid_sweep.py, but on source images that have
NEVER been marked. Source images are resized to the same scale and
received dimensions as their marked counterparts. No pilot, payload
or oracle is involved.

A false positive is counted ONLY if robust.decode_at_size() returns
ANY CRC-validated payload, regardless of its contents. This is stricter
than testing whether a decoded packet matches an expected message.
Score maxima are diagnostics, not independently calibrated p-values.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from src import robust_image as robust
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import DEFAULT_NAMES, parse_scales
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import reference_image
from tools import robust_qim_blind_grid_sweep as sweep


def decode_any_valid_packet(
    received: Image.Image,
    candidates: list[tuple[int, int]],
    budget: int,
) -> dict:
    """CRC-validated packet at ANY size is a negative-control failure."""
    if budget < 0:
        raise ValueError("Budget must be nonnegative")
    attempts = 0
    for size in candidates[:budget]:
        attempts += 1
        try:
            payload = robust.decode_at_size(received, size)
        except ValueError:
            continue
        return {
            "any_valid_packet": True,
            "decode_status": "FALSE_POSITIVE",
            "decode_attempts": attempts,
            "decoded_size": f"{size[0]}x{size[1]}",
            "decoded_payload_length": len(payload),
        }
    return {
        "any_valid_packet": False,
        "decode_status": "NO_VALID_PACKET",
        "decode_attempts": attempts,
        "decoded_size": None,
        "decoded_payload_length": None,
    }


def evaluate(
    received: Image.Image,
    min_scale: float = 0.5,
    height_jitter: int = 2,
    top_grids: int = 5,
    delta: float = 38.0,
    repeat: int = 13,
    decode_budget: int = 40,
) -> dict:
    """No original size, true scale, expected payload, or oracle used."""
    ranked, meta = sweep.blind_rank(
        received, min_scale, height_jitter, top_grids, delta, repeat
    )
    result = {
        "candidate_count": meta["candidate_count"],
        "grid_count": meta["grid_count"],
        "top_grid_k": top_grids,
        "refined_count": meta["refined_count"],
        "coarse_max_header_score": (
            meta["coarse"][0][1] if meta["coarse"] else None
        ),
        "refined_max_header_score": (
            meta["refined_scores"][0][1]
            if meta["refined_scores"] else None
        ),
        "bank_seconds": meta["bank_seconds"],
        "coarse_seconds": meta["coarse_seconds"],
        "refine_seconds": meta["refine_seconds"],
        "decode_budget": decode_budget,
        "any_valid_packet": None,
        "decode_status": "NOT_RUN",
        "decode_attempts": None,
        "decoded_size": None,
        "decoded_payload_length": None,
        "decode_seconds": None,
    }
    if decode_budget:
        start = time.perf_counter()
        result.update(decode_any_valid_packet(received, ranked, decode_budget))
        result["decode_seconds"] = round(
            time.perf_counter() - start, 3
        )
    return result


def columns() -> list[str]:
    return [
        "source", "source_sha256", "control_type",
        "received_width", "received_height", "resize_scale",
        "min_scale", "height_jitter", "delta", "repeat",
        "candidate_count", "grid_count", "top_grid_k",
        "refined_count", "coarse_max_header_score",
        "refined_max_header_score",
        "bank_seconds", "coarse_seconds", "refine_seconds",
        "decode_budget", "any_valid_packet", "decode_status",
        "decode_attempts", "decoded_size",
        "decoded_payload_length", "decode_seconds",
    ]


def probe(
    source: Path,
    scales: list[float],
    min_scale: float = 0.5,
    height_jitter: int = 2,
    top_grids: int = 5,
    delta: float = 38.0,
    repeat: int = 13,
    decode_budget: int = 40,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "control_type": "UNMARKED",
        "min_scale": min_scale,
        "height_jitter": height_jitter,
        "delta": delta,
        "repeat": repeat,
    }
    rows = []
    with codec_parameters(delta, repeat):
        for scale in scales:
            received_size = tuple(
                max(32, round(d * scale)) for d in reference.size
            )
            received = reference.resize(
                received_size, Image.Resampling.LANCZOS
            )
            result = evaluate(
                received, min_scale, height_jitter, top_grids,
                delta, repeat, decode_budget
            )
            rows.append({
                **base,
                "received_width": received.width,
                "received_height": received.height,
                "resize_scale": scale,
                **result,
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--scales", default="0.62")
    parser.add_argument("--min-scale", type=float, default=0.5)
    parser.add_argument("--height-jitter", type=int, default=2)
    parser.add_argument("--top-grids", type=int, default=5)
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--decode-budget", type=int, default=40)
    args = parser.parse_args()
    try:
        scales = parse_scales(args.scales)
        # Validate parameters before creating any output file.
        sweep.blind_grid_bank(
            (64, 64), args.min_scale, args.height_jitter
        )
        if not 1 <= args.top_grids <= 20:
            raise ValueError("top_grids must be in 1..20")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if not 0 <= args.decode_budget <= 200:
            raise ValueError("Decode budget must be in 0..200")
        if args.csv.exists():
            raise ValueError("Refusing to overwrite CSV: " + str(args.csv))
        paths = image_paths(
            args.directory, args.name or list(DEFAULT_NAMES)
        )
        if not paths:
            raise ValueError("No supported source images found")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"UNMARKED negative control: {len(paths)} covers x "
        f"{len(scales)} scales; min_scale={args.min_scale}, "
        f"jitter={args.height_jitter}, top_grids={args.top_grids}, "
        f"decode_budget={args.decode_budget}",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, scales, args.min_scale,
                    args.height_jitter, args.top_grids,
                    args.delta, args.repeat, args.decode_budget,
                )
            except ValueError as exc:
                print(f"[{i}/{len(paths)}] SKIP {source.name}: {exc}",
                      flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{i}/{len(paths)}] {row['source']} "
                    f"scale={row['resize_scale']} "
                    f"coarse_max={row['coarse_max_header_score']} "
                    f"refined_max={row['refined_max_header_score']} "
                    f"valid_packet={row['any_valid_packet']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
