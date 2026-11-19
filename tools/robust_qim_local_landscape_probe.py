#!/usr/bin/env python3
"""Oracle-assisted LOCAL QIM score landscape: mechanism test, NOT blind search.

This intentionally uses the encoded dimensions to place a symmetric
pixel-size neighborhood around the true size. It is NOT a candidate
generator for production and must not be used as evidence of blind
unknown-scale recovery. It tests whether CLR1-header correlation is
locally smooth (amenable to coarse-to-fine optimization) or sharply
discontinuous (requiring better candidate generation).

Only the received image, candidate size, public CLR1 header, seeded
permutation, DELTA and REPEAT are used to score a candidate. The
expected payload is used only for embedding and oracle verification.
The oracle runs after all scores have been computed.
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
from src.robust_packet import pack
from tools import robust_pilot_cascade_probe as cascade
from tools import robust_qim_sync_rank_probe as qim
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, parse_scales, parse_strengths,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)


def local_sizes(
    encoded_size: tuple[int, int], radius: int,
) -> list[tuple[int, int, int, int]]:
    """Oracle-assisted diagnostic window, including unsafe sizes for audit."""
    if not 0 <= radius <= 12:
        raise ValueError("Radius must be 0..12 pixels")
    w, h = encoded_size
    return [
        (w + dx, h + dy, dx, dy)
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
    ]


def columns() -> list[str]:
    return [
        "source", "source_sha256", "pilot_strength",
        "effective_pilot_strength", "adaptive_pilot",
        "resize_scale", "delta", "repeat",
        "encoded_width", "encoded_height",
        "received_width", "received_height",
        "dx", "dy", "candidate_width", "candidate_height",
        "same_ll2_grid", "status",
        "header_score", "wrong_seed_header_score",
        "wrong_delta_header_score", "lattice_score",
        "score_seconds", "oracle",
        "rank_of_true_size_in_local_window",
        "true_header_score", "best_wrong_header_score",
    ]


def score_window(
    received: Image.Image,
    encoded_size: tuple[int, int],
    delta: float, repeat: int, radius: int,
) -> list[dict]:
    """Return score per pixel-size offset, without any packet decoding."""
    true_grid = (
        (encoded_size[0] + 3) // 4,
        (encoded_size[1] + 3) // 4,
    )
    rows = []
    for width, height, dx, dy in local_sizes(encoded_size, radius):
        row = {
            "dx": dx, "dy": dy,
            "candidate_width": width, "candidate_height": height,
            "same_ll2_grid": (
                ((width + 3) // 4, (height + 3) // 4) == true_grid
            ),
            "status": "SKIP:unsafe_size",
            "header_score": None,
            "wrong_seed_header_score": None,
            "wrong_delta_header_score": None,
            "lattice_score": None,
            "score_seconds": None,
        }
        if cascade.safe_size((width, height)):
            start = time.perf_counter()
            try:
                scores = qim.score_size(
                    received, (width, height), delta, repeat
                )
            except ValueError as exc:
                row["status"] = "SKIP:" + str(exc)
            else:
                row.update({
                    "status": "OK",
                    "header_score": scores["header"],
                    "wrong_seed_header_score": scores["wrong_seed_header"],
                    "wrong_delta_header_score": scores["wrong_delta_header"],
                    "lattice_score": scores["lattice"],
                })
            row["score_seconds"] = round(
                time.perf_counter() - start, 6
            )
        rows.append(row)

    true = next(
        (r for r in rows if r["dx"] == 0 and r["dy"] == 0),
        None,
    )
    if true is None or true["status"] != "OK":
        rank = None
        true_score = None
        best_wrong = None
    else:
        true_score = true["header_score"]
        competitors = [
            r["header_score"] for r in rows
            if r["status"] == "OK" and (r["dx"], r["dy"]) != (0, 0)
        ]
        rank = 1 + sum(score > true_score for score in competitors)
        best_wrong = max(competitors, default=None)

    for row in rows:
        row["rank_of_true_size_in_local_window"] = rank
        row["true_header_score"] = true_score
        row["best_wrong_header_score"] = best_wrong
    return rows


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    delta: float = 38.0, repeat: int = 13,
    radius: int = 4,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "delta": delta,
        "repeat": repeat,
    }
    packet = pack(payload)
    all_rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = robust._pilot_embed(reference, strength=strength)
            marked = robust._feedback_embed(pilot, packet)
            for scale in scales:
                received_size = tuple(
                    max(32, round(d * scale)) for d in marked.size
                )
                received = marked.resize(
                    received_size, Image.Resampling.LANCZOS
                )
                # All scores are calculated before the oracle check.
                rows = score_window(
                    received, marked.size, delta, repeat, radius
                )
                oracle = decode_known_at_size(
                    received, marked.size, payload
                )
                for row in rows:
                    all_rows.append({
                        **base,
                        "pilot_strength": strength,
                        "effective_pilot_strength": round(
                            effective_strength(reference, strength), 6
                        ),
                        "resize_scale": scale,
                        "received_width": received.width,
                        "received_height": received.height,
                        **row,
                        "oracle": oracle,
                    })
    return all_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.62,0.75")
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--radius", type=int, default=4)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        local_sizes((1280, 960), args.radius)
        if not strengths or any(s <= 0 for s in strengths):
            raise ValueError("Pilot strengths must be positive")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if args.csv.exists():
            raise ValueError("Refusing to overwrite CSV: " + str(args.csv))
        paths = image_paths(
            args.directory, args.name or list(DEFAULT_NAMES)
        )
        if not paths:
            raise ValueError("No supported source images found")
        pack(args.message.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Oracle-assisted local landscape: {len(paths)} covers x "
        f"{len(strengths)} strengths x {len(scales)} scales x "
        f"{(2 * args.radius + 1) ** 2} sizes; "
        f"adaptive={robust.ADAPTIVE_PILOT}; NOT blind search",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, args.message.encode("utf-8"),
                    strengths, scales, args.delta, args.repeat,
                    args.radius,
                )
            except ValueError as exc:
                print(f"[{i}/{len(paths)}] SKIP {source.name}: {exc}",
                      flush=True)
                continue
            writer.writerows(rows)
            handle.flush()
            for strength in strengths:
                for scale in scales:
                    matched = [
                        row for row in rows
                        if row["pilot_strength"] == strength
                        and row["resize_scale"] == scale
                    ]
                    if not matched:
                        continue
                    row = matched[0]
                    print(
                        f"[{i}/{len(paths)}] {source.name} "
                        f"strength={strength} scale={scale} "
                        f"oracle={row['oracle']} "
                        f"true_rank={row['rank_of_true_size_in_local_window']} "
                        f"true_header={row['true_header_score']} "
                        f"best_wrong={row['best_wrong_header_score']}",
                        flush=True,
                    )
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
