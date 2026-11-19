#!/usr/bin/env python3
"""Research-only BLIND aspect-ratio LL2-grid search using the CLR1 QIM header.

Unlike the oracle-centred local landscape experiment, candidate generation
uses ONLY the received dimensions, a public 0.5 minimum resize-scale bound,
a preserved-aspect-ratio assumption, and a ±2-pixel height tolerance.

1. Enumerate plausible original widths and nearby aspect-ratio heights.
2. Group all safe pixel sizes by Haar LL2 shape (ceil(width/4), ceil(height/4)).
3. Score one deterministic central representative per grid.
4. Refine all pixel sizes in the top-K grids using the same header score.
5. Optionally decode the ranked shortlist with an equal fixed call budget.

The encoded original size is used ONLY AFTER candidate ranking to report
diagnostic ranks and for a separate oracle verification. The expected
payload is NEVER used in candidate generation or scoring. This is a
development-set experiment, not a validated scale-invariant receiver.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
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


def grid_key(size: tuple[int, int]) -> tuple[int, int]:
    return ((size[0] + 3) // 4, (size[1] + 3) // 4)


def blind_grid_bank(
    received_size: tuple[int, int],
    min_scale: float = 0.5,
    height_jitter: int = 2,
) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """No encoded size, oracle, Fourier estimate, or true resize ratio."""
    if not math.isfinite(min_scale) or not 0.25 <= min_scale <= 1.0:
        raise ValueError("min_scale must be in [0.25, 1]")
    if not 0 <= height_jitter <= 4:
        raise ValueError("height_jitter must be in 0..4")
    rw, rh = received_size
    if min(rw, rh) < 32:
        raise ValueError("Received dimensions are too small")
    max_width = min(robust.MAX_LONGEST, math.ceil(rw / min_scale))
    grids: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for width in range(rw, max_width + 1):
        centre = round(width * rh / rw)
        for height in range(centre - height_jitter, centre + height_jitter + 1):
            size = (width, height)
            if cascade.safe_size(size):
                grids.setdefault(grid_key(size), []).append(size)
    return grids


def representative(
    sizes: list[tuple[int, int]], received_size: tuple[int, int],
) -> tuple[int, int]:
    """Choose a central pixel size, not the oracle or highest-scoring size."""
    if not sizes:
        raise ValueError("Cannot choose a representative of an empty grid")
    rw, rh = received_size
    gw, gh = grid_key(sizes[0])
    center_w, center_h = 4 * gw - 1.5, 4 * gh - 1.5
    return min(
        sizes,
        key=lambda size: (
            abs(size[0] - center_w) + abs(size[1] - center_h),
            abs(size[1] - size[0] * rh / rw),
            size,
        ),
    )


def blind_rank(
    received: Image.Image,
    min_scale: float = 0.5,
    height_jitter: int = 2,
    top_grids: int = 5,
    delta: float = 38.0,
    repeat: int = 13,
) -> tuple[list[tuple[int, int]], dict]:
    """Fully blind ranker; intentionally has no original_size parameter."""
    if not 1 <= top_grids <= 20:
        raise ValueError("top_grids must be in 1..20")
    start = time.perf_counter()
    grids = blind_grid_bank(received.size, min_scale, height_jitter)
    bank_seconds = time.perf_counter() - start
    if not grids:
        raise ValueError("No safe aspect-ratio grid candidates")

    start = time.perf_counter()
    coarse = []
    cache: dict[tuple[int, int], float] = {}
    for grid, sizes in grids.items():
        size = representative(sizes, received.size)
        score = qim.score_size(received, size, delta, repeat)["header"]
        cache[size] = score
        coarse.append((grid, score, size))
    coarse_seconds = time.perf_counter() - start
    coarse.sort(key=lambda entry: (-entry[1], entry[0]))
    selected = coarse[:top_grids]

    start = time.perf_counter()
    refined = []
    for grid, _score, _rep in selected:
        for size in grids[grid]:
            if size not in cache:
                cache[size] = qim.score_size(
                    received, size, delta, repeat
                )["header"]
            refined.append((size, cache[size]))
    refined.sort(key=lambda entry: (-entry[1], entry[0]))
    refine_seconds = time.perf_counter() - start
    return [size for size, _score in refined], {
        "candidate_count": sum(len(sizes) for sizes in grids.values()),
        "grid_count": len(grids),
        "top_grid_k": top_grids,
        "coarse": coarse,
        "selected_grids": [grid for grid, _score, _size in selected],
        "refined_count": len(refined),
        "refined_scores": refined,
        "bank_seconds": round(bank_seconds, 6),
        "coarse_seconds": round(coarse_seconds, 3),
        "refine_seconds": round(refine_seconds, 3),
    }


def _rank(items: list, target) -> int | None:
    try:
        return items.index(target) + 1
    except ValueError:
        return None


def evaluate(
    received: Image.Image,
    original_size: tuple[int, int],
    payload: bytes,
    min_scale: float = 0.5,
    height_jitter: int = 2,
    top_grids: int = 5,
    delta: float = 38.0,
    repeat: int = 13,
    blind_budget: int = 0,
) -> dict:
    """Known original size is used for reporting ONLY, after blind_rank."""
    ranked, meta = blind_rank(
        received, min_scale, height_jitter, top_grids, delta, repeat
    )
    original_grid = grid_key(original_size)
    coarse_grids = [entry[0] for entry in meta["coarse"]]
    original_coarse = next(
        (entry[1] for entry in meta["coarse"] if entry[0] == original_grid),
        None,
    )
    best_wrong_coarse = max(
        (entry[1] for entry in meta["coarse"] if entry[0] != original_grid),
        default=None,
    )
    original_refined = next(
        (score for size, score in meta["refined_scores"]
         if size == original_size), None
    )
    result = {
        "candidate_count": meta["candidate_count"],
        "grid_count": meta["grid_count"],
        "top_grid_k": meta["top_grid_k"],
        "coarse_true_grid_rank": _rank(coarse_grids, original_grid),
        "coarse_true_grid_score": original_coarse,
        "coarse_best_wrong_grid_score": best_wrong_coarse,
        "true_grid_shortlisted": original_grid in meta["selected_grids"],
        "refined_count": meta["refined_count"],
        "refined_exact_rank": _rank(ranked, original_size),
        "refined_true_score": original_refined,
        "refined_best_score": (
            meta["refined_scores"][0][1] if meta["refined_scores"] else None
        ),
        "bank_seconds": meta["bank_seconds"],
        "coarse_seconds": meta["coarse_seconds"],
        "refine_seconds": meta["refine_seconds"],
        "blind_budget": blind_budget,
        "blind_status": "NOT_RUN",
        "blind_attempts": None,
        "blind_decoded_size": None,
        "blind_seconds": None,
    }
    if blind_budget:
        start = time.perf_counter()
        decoded = qim.decode_budget(received, ranked, payload, blind_budget)
        result["blind_status"] = decoded["status"]
        result["blind_attempts"] = decoded["attempts"]
        result["blind_decoded_size"] = decoded["decoded_size"]
        result["blind_seconds"] = round(time.perf_counter() - start, 3)
    return result


def columns() -> list[str]:
    return [
        "source", "source_sha256", "pilot_strength",
        "effective_pilot_strength", "adaptive_pilot",
        "resize_scale", "delta", "repeat",
        "encoded_width", "encoded_height",
        "received_width", "received_height",
        "min_scale", "height_jitter", "status", "oracle",
        "candidate_count", "grid_count", "top_grid_k",
        "coarse_true_grid_rank", "coarse_true_grid_score",
        "coarse_best_wrong_grid_score", "true_grid_shortlisted",
        "refined_count", "refined_exact_rank",
        "refined_true_score", "refined_best_score",
        "bank_seconds", "coarse_seconds", "refine_seconds",
        "blind_budget", "blind_status", "blind_attempts",
        "blind_decoded_size", "blind_seconds",
    ]


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    min_scale: float = 0.5, height_jitter: int = 2,
    top_grids: int = 5, delta: float = 38.0,
    repeat: int = 13, blind_budget: int = 0,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "delta": delta, "repeat": repeat,
        "min_scale": min_scale,
        "height_jitter": height_jitter,
    }
    packet = pack(payload)
    rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = robust._pilot_embed(reference, strength=strength)
            try:
                marked = robust._feedback_embed(pilot, packet)
            except ValueError as exc:
                for scale in scales:
                    rows.append({
                        **base, "pilot_strength": strength,
                        "resize_scale": scale, "status": "SKIP:" + str(exc),
                        "oracle": "NOT_RUN",
                    })
                continue
            for scale in scales:
                received_size = tuple(
                    max(32, round(d * scale)) for d in marked.size
                )
                received = marked.resize(
                    received_size, Image.Resampling.LANCZOS
                )
                result = evaluate(
                    received, marked.size, payload,
                    min_scale, height_jitter, top_grids,
                    delta, repeat, blind_budget
                )
                oracle = decode_known_at_size(
                    received, marked.size, payload
                )
                rows.append({
                    **base,
                    "received_width": received.width,
                    "received_height": received.height,
                    "pilot_strength": strength,
                    "effective_pilot_strength": round(
                        effective_strength(reference, strength), 6
                    ),
                    "resize_scale": scale,
                    "status": "OK", "oracle": oracle,
                    **result,
                })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12")
    parser.add_argument("--scales", default="0.62")
    parser.add_argument("--min-scale", type=float, default=0.5)
    parser.add_argument("--height-jitter", type=int, default=2)
    parser.add_argument("--top-grids", type=int, default=5)
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--blind", action="store_true")
    parser.add_argument("--decode-budget", type=int, default=40)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        if not strengths or any(s <= 0 for s in strengths):
            raise ValueError("Pilot strengths must be positive")
        if not 0.25 <= args.min_scale <= 1.0 or not math.isfinite(args.min_scale):
            raise ValueError("min_scale must be finite and in [0.25, 1]")
        if not 0 <= args.height_jitter <= 4:
            raise ValueError("height_jitter must be in 0..4")
        if not 1 <= args.top_grids <= 20:
            raise ValueError("top_grids must be in 1..20")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if not 1 <= args.decode_budget <= 200:
            raise ValueError("Decode budget must be 1..200")
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
        f"BLIND grid sweep: {len(paths)} covers x "
        f"{len(strengths)} strengths x {len(scales)} scales; "
        f"min_scale={args.min_scale}, jitter={args.height_jitter}, "
        f"top_grids={args.top_grids}, blind={args.blind}",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, args.message.encode("utf-8"),
                    strengths, scales, args.min_scale,
                    args.height_jitter, args.top_grids,
                    args.delta, args.repeat,
                    args.decode_budget if args.blind else 0,
                )
            except ValueError as exc:
                print(f"[{i}/{len(paths)}] SKIP {source.name}: {exc}",
                      flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{i}/{len(paths)}] {row['source']} "
                    f"strength={row['pilot_strength']} "
                    f"scale={row['resize_scale']} "
                    f"oracle={row['oracle']} "
                    f"grids={row.get('grid_count')} "
                    f"true_grid_rank={row.get('coarse_true_grid_rank')} "
                    f"refined_exact_rank={row.get('refined_exact_rank')} "
                    f"blind={row.get('blind_status')}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
