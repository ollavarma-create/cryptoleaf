#!/usr/bin/env python3
"""Research-only decoder-side scale-prior candidate bank for QIM sync.

The existing Fourier candidate search is left completely unchanged. This
separate experiment asks whether a generic bank of common image enlargement
ratios plus a small pixel jitter can supply dimensions missing from Fourier
search, and whether the public CLR1 QIM header can rank those dimensions.

All candidate dimensions come ONLY from the received image dimensions,
fixed generic scale priors, and fixed pixel offsets. True encoded dimensions
are used ONLY after scoring to evaluate ranks and for the oracle. No known
resize factor or source dimensions are passed into candidate generation.

Unmarked covers resized through the same channel provide a negative control.
--blind compares equal decoder-call budgets for bank order vs QIM header
order. The codec and production search are not changed.
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

DEFAULT_PRIORS = (1.0, 1.25, 4 / 3, 1.5, 1.75, 2.0)
DEFAULT_JITTER = 2


def parse_priors(text: str) -> tuple[float, ...]:
    try:
        values = tuple(float(part.strip()) for part in text.split(","))
    except ValueError as exc:
        raise ValueError("Scale priors must be comma-separated numbers") from exc
    if (
        not 1 <= len(values) <= 8
        or any(not math.isfinite(x) or not 1 <= x <= 2.5 for x in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Specify 1..8 distinct enlargement priors in [1,2.5]")
    return values


def scale_bank(
    received_size: tuple[int, int],
    priors: tuple[float, ...] = DEFAULT_PRIORS,
    jitter: int = DEFAULT_JITTER,
) -> list[tuple[int, int]]:
    """Blind bank; does not inspect original dimensions or Fourier scores."""
    if not priors or not 0 <= jitter <= 4:
        raise ValueError("Nonempty priors and pixel jitter in 0..4 required")
    if any(not math.isfinite(x) or not 1 <= x <= 2.5 for x in priors):
        raise ValueError("Invalid scale prior")
    offsets = sorted(
        ((dx, dy) for dx in range(-jitter, jitter + 1)
         for dy in range(-jitter, jitter + 1)),
        key=lambda xy: (abs(xy[0]) + abs(xy[1]), xy[0], xy[1]),
    )
    sizes = []
    seen = set()
    w, h = received_size
    for factor in priors:
        centre = (round(w * factor), round(h * factor))
        for dx, dy in offsets:
            candidate = (centre[0] + dx, centre[1] + dy)
            if candidate not in seen and cascade.safe_size(candidate):
                seen.add(candidate)
                sizes.append(candidate)
    return sizes


def _rank(sizes: list[tuple[int, int]], original: tuple[int, int]) -> int | None:
    try:
        return sizes.index(original) + 1
    except ValueError:
        return None


def _score_at_true(
    sizes: list[tuple[int, int]], scores: list[dict],
    original: tuple[int, int], field: str,
) -> float | None:
    """Post-hoc exact-size score; never used in candidate ranking."""
    try:
        return round(scores[sizes.index(original)][field], 6)
    except ValueError:
        return None


def evaluate_baseline_only(
    received: Image.Image,
    original_size: tuple[int, int],
    payload: bytes,
    priors: tuple[float, ...],
    jitter: int,
    blind_budget: int,
) -> dict:
    """Exhaustive direct decoding, without calculating ANY QIM scores.

    Timed generation and decoder costs are disjoint. Original size is used
    solely to report post-hoc diagnostic ranks, never to choose a candidate.
    """
    start = time.perf_counter()
    sizes = scale_bank(received.size, priors, jitter)
    generation_seconds = time.perf_counter() - start
    result = {
        "candidate_count": len(sizes),
        "lattice_control_eligible_count": None,
        "candidate_generation_seconds": round(generation_seconds, 6),
        "scoring_seconds": None,
        "baseline_grid_rank": qim.first_grid_rank(sizes, original_size),
        "header_grid_rank": None,
        "wrong_seed_grid_rank": None,
        "wrong_delta_grid_rank": None,
        "baseline_exact_rank": _rank(sizes, original_size),
        "header_exact_rank": None,
        "header_score_at_true_size": None,
        "wrong_seed_score_at_true_size": None,
        "wrong_delta_score_at_true_size": None,
        "marked_max_header_score": None,
        "unmarked_max_header_score": None,
        "unmarked_header_score_at_true_size": None,
        "unmarked_scoring_seconds": None,
        "blind_budget": blind_budget,
        "baseline_blind_status": "NOT_RUN",
        "baseline_blind_attempts": None,
        "baseline_blind_decoded_size": None,
        "baseline_blind_seconds": None,
        "header_blind_status": "NOT_RUN",
        "header_blind_attempts": None,
        "header_blind_decoded_size": None,
        "header_blind_seconds": None,
    }
    if blind_budget:
        start = time.perf_counter()
        decoded = qim.decode_budget(received, sizes, payload, blind_budget)
        result["baseline_blind_status"] = decoded["status"]
        result["baseline_blind_attempts"] = decoded["attempts"]
        result["baseline_blind_decoded_size"] = decoded["decoded_size"]
        result["baseline_blind_seconds"] = round(
            time.perf_counter() - start, 3
        )
    return result


def evaluate(
    received: Image.Image,
    original_size: tuple[int, int],
    payload: bytes,
    delta: float = 38.0,
    repeat: int = 13,
    priors: tuple[float, ...] = DEFAULT_PRIORS,
    jitter: int = DEFAULT_JITTER,
    blind_budget: int = 0,
    unmarked: Image.Image | None = None,
    baseline_only: bool = False,
) -> dict:
    if baseline_only:
        return evaluate_baseline_only(
            received, original_size, payload, priors, jitter, blind_budget
        )
    start = time.perf_counter()
    candidates = scale_bank(received.size, priors, jitter)
    generation_seconds = time.perf_counter() - start
    ranked, meta = qim.rank_sizes(received, candidates, delta, repeat)
    score_seconds = time.perf_counter() - start
    baseline = ranked["baseline"]
    header = ranked["header"]
    result = {
        "candidate_count": len(candidates),
        "candidate_generation_seconds": round(generation_seconds, 6),
        "lattice_control_eligible_count": meta["lattice_control_eligible_count"],
        "scoring_seconds": round(score_seconds, 3),
        "baseline_grid_rank": qim.first_grid_rank(baseline, original_size),
        "header_grid_rank": qim.first_grid_rank(header, original_size),
        "wrong_seed_grid_rank": qim.first_grid_rank(
            ranked["wrong_seed_header"], original_size
        ),
        "wrong_delta_grid_rank": qim.first_grid_rank(
            ranked["wrong_delta_header"], original_size
        ),
        "baseline_exact_rank": _rank(baseline, original_size),
        "header_exact_rank": _rank(header, original_size),
        "header_score_at_true_size": _score_at_true(
            candidates, meta["scores"], original_size, "header"
        ),
        "wrong_seed_score_at_true_size": _score_at_true(
            candidates, meta["scores"], original_size, "wrong_seed_header"
        ),
        "wrong_delta_score_at_true_size": _score_at_true(
            candidates, meta["scores"], original_size, "wrong_delta_header"
        ),
        "marked_max_header_score": max(
            (s["header"] for s in meta["scores"]), default=None
        ),
        "unmarked_max_header_score": None,
        "unmarked_header_score_at_true_size": None,
        "unmarked_scoring_seconds": None,
        "blind_budget": blind_budget,
    }
    if unmarked is not None:
        start = time.perf_counter()
        _unused_ranks, control = qim.rank_sizes(
            unmarked, candidates, delta, repeat
        )
        result["unmarked_scoring_seconds"] = round(
            time.perf_counter() - start, 3
        )
        result["unmarked_max_header_score"] = max(
            (s["header"] for s in control["scores"]), default=None
        )
        result["unmarked_header_score_at_true_size"] = _score_at_true(
            candidates, control["scores"], original_size, "header"
        )

    for arm, order in (("baseline", baseline), ("header", header)):
        result[f"{arm}_blind_status"] = "NOT_RUN"
        result[f"{arm}_blind_attempts"] = None
        result[f"{arm}_blind_decoded_size"] = None
        result[f"{arm}_blind_seconds"] = None
        if blind_budget:
            start = time.perf_counter()
            decoded = qim.decode_budget(received, order, payload, blind_budget)
            result[f"{arm}_blind_status"] = decoded["status"]
            result[f"{arm}_blind_attempts"] = decoded["attempts"]
            result[f"{arm}_blind_decoded_size"] = decoded["decoded_size"]
            result[f"{arm}_blind_seconds"] = round(
                time.perf_counter() - start, 3
            )
    return result


def columns() -> list[str]:
    return [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "pilot_strength", "effective_pilot_strength", "adaptive_pilot",
        "delta", "repeat", "scale_priors", "jitter", "status", "oracle",
        "candidate_count", "candidate_generation_seconds",
        "lattice_control_eligible_count",
        "baseline_grid_rank", "header_grid_rank",
        "wrong_seed_grid_rank", "wrong_delta_grid_rank",
        "baseline_exact_rank", "header_exact_rank",
        "header_score_at_true_size", "wrong_seed_score_at_true_size",
        "wrong_delta_score_at_true_size", "marked_max_header_score",
        "unmarked_max_header_score", "unmarked_header_score_at_true_size",
        "scoring_seconds", "unmarked_scoring_seconds", "blind_budget",
        "baseline_blind_status", "baseline_blind_attempts",
        "baseline_blind_decoded_size", "baseline_blind_seconds",
        "header_blind_status", "header_blind_attempts",
        "header_blind_decoded_size", "header_blind_seconds",
    ]


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    delta: float = 38.0, repeat: int = 13,
    priors: tuple[float, ...] = DEFAULT_PRIORS,
    jitter: int = DEFAULT_JITTER,
    blind_budget: int = 0, unmarked_control: bool = True,
    baseline_only: bool = False,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    packet = pack(payload)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "delta": delta, "repeat": repeat,
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "scale_priors": ",".join(f"{x:.9g}" for x in priors),
        "jitter": jitter,
    }
    rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = (
                reference.convert("YCbCr").convert("RGB")
                if strength == 0 else robust._pilot_embed(reference, strength=strength)
            )
            try:
                marked = robust._feedback_embed(pilot, packet)
            except ValueError as exc:
                for scale in scales:
                    rows.append({
                        **base, "pilot_strength": strength,
                        "resize_scale": scale,
                        "status": "SKIP:" + str(exc),
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
                unmarked = (
                    reference.resize(received_size, Image.Resampling.LANCZOS)
                    if unmarked_control and not baseline_only else None
                )
                eval_options = {"baseline_only": True} if baseline_only else {}
                result = evaluate(
                    received, marked.size, payload, delta, repeat,
                    priors, jitter, blind_budget, unmarked, **eval_options
                )
                oracle = decode_known_at_size(
                    received, marked.size, payload
                )
                rows.append({
                    **base,
                    "received_width": received.width,
                    "received_height": received.height,
                    "resize_scale": scale,
                    "pilot_strength": strength,
                    "effective_pilot_strength": round(
                        effective_strength(reference, strength), 6
                    ),
                    "status": "OK",
                    "oracle": oracle,
                    **result,
                })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.5")
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument(
        "--scale-priors", default="1,1.25,1.333333333,1.5,1.75,2",
        help="Generic enlargement ratios; never supplied true scale",
    )
    parser.add_argument("--jitter", type=int, default=DEFAULT_JITTER)
    parser.add_argument("--no-unmarked-control", action="store_true")
    parser.add_argument("--blind", action="store_true")
    parser.add_argument(
        "--baseline-only", action="store_true",
        help="Decode bank directly with no QIM scoring (fair cost baseline)",
    )
    parser.add_argument("--decode-budget", type=int, default=40)
    parser.add_argument("--fixed-pilot", action="store_true")
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        priors = parse_priors(args.scale_priors)
        if not strengths or any(s <= 0 for s in strengths):
            raise ValueError("Pilot strengths must be positive")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if not 0 <= args.jitter <= 4:
            raise ValueError("Jitter must be 0..4 pixels")
        if args.baseline_only and not args.blind:
            raise ValueError("--baseline-only requires --blind")
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
    if args.fixed_pilot:
        robust.ADAPTIVE_PILOT = False
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(paths)} covers x {len(strengths)} strengths x "
        f"{len(scales)} scales; priors={priors}, jitter={args.jitter}, "
        f"blind={args.blind}, baseline_only={args.baseline_only}, "
        f"adaptive={robust.ADAPTIVE_PILOT}",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for index, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, args.message.encode("utf-8"),
                    strengths, scales, args.delta, args.repeat,
                    priors, args.jitter,
                    args.decode_budget if args.blind else 0,
                    not args.no_unmarked_control,
                    args.baseline_only,
                )
            except ValueError as exc:
                print(f"[{index}/{len(paths)}] SKIP {source.name}: {exc}",
                      flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{index}/{len(paths)}] {row['source']} "
                    f"strength={row['pilot_strength']} "
                    f"scale={row['resize_scale']} "
                    f"oracle={row['oracle']} "
                    f"grid bank/header="
                    f"{row.get('baseline_grid_rank')}/"
                    f"{row.get('header_grid_rank')} "
                    f"blind bank/header="
                    f"{row.get('baseline_blind_status')}/"
                    f"{row.get('header_blind_status')}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
