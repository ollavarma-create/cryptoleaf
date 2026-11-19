#!/usr/bin/env python3
"""Research-only QIM synchronization ranking of FROZEN Fourier size candidates.

A received image alone supplies the candidate sizes via the established
three-mask/two-stage detector. At each candidate size, Haar LL2 coefficients
are sampled using the codec's public seeded permutation. Two *decoder-only*
rankers are evaluated independently:

  lattice:  cos(2*pi*LL2/DELTA) contrast at seeded vs unseeded positions
  header:   centred correlation of cos(pi*LL2/DELTA) with the known CLR1 bits

A wrong seed and a wrong DELTA are predeclared negative controls for header.
The known original size is used ONLY to evaluate candidate ranks after
ranking, and for the independent oracle. The expected test payload is used
ONLY for embedding and verifying successful blind packet recovery.

By default NO candidate is decoded; --blind compares the same fixed
number of decoder calls in original, header-ranked, and lattice-ranked
candidate orders. Scoring overhead is measured separately. This is not
production code and never changes the encoder or the Fourier detector.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pywt
from PIL import Image

from src import robust_image as robust
from src.robust_packet import MAGIC, pack
from tools import robust_pilot_multimask_probe as multi
from tools import robust_pilot_cascade_probe as cascade
from tools import robust_pilot_angular_probe as angular
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, parse_scales, parse_strengths,
    priority_candidates_from_peaks,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)

DEFAULT_RANKED = 240
WRONG_SEED_OFFSET = 1
WRONG_DELTA_MULTIPLIER = 1.17


def frozen_candidates(
    received: Image.Image,
    variants=multi.DEFAULT_VARIANTS,
    stages=cascade.DEFAULT_STAGES,
    per_stage_candidates: int = 160,
) -> list[tuple[int, int]]:
    """Generate EXACT frozen multi-mask order; no true size or oracle input."""
    workspace = angular.fft_workspace(received)
    seen = set()
    candidates = []
    for freq, angle in variants:
        peaks = multi.variant_peaks(
            workspace, freq, angle, max_peaks=max(n for n, _ in stages)
        )
        for count, quota in stages:
            for size in priority_candidates_from_peaks(
                received.size, peaks[:count], per_stage_candidates,
                first_peak_quota=quota,
            ):
                if size in seen:
                    continue
                seen.add(size)
                if cascade.safe_size(size):
                    candidates.append(size)
    return candidates


def centred_correlation(template: np.ndarray, observed: np.ndarray) -> float:
    """Pearson correlation; removes nonzero-mean CLR1 parity/flat-cover bias."""
    a = np.asarray(template, dtype=np.float64)
    b = np.asarray(observed, dtype=np.float64)
    if a.shape != b.shape or not a.size:
        raise ValueError("Matching nonempty score vectors required")
    a = a - a.mean()
    b = b - b.mean()
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 1e-12 else 0.0


def score_ll2(
    ll: np.ndarray, delta: float, repeat: int, seed: int = robust.SEED,
) -> dict[str, float]:
    """Public-header QIM scores and predeclared negative controls.

    Only 4 known magic bytes are used. No packet length, payload or
    original size is used. Selected and negative-control sets are disjoint.
    """
    flat = np.asarray(ll, dtype=np.float64).ravel()
    bits = np.unpackbits(np.frombuffer(MAGIC, dtype=np.uint8))
    count = len(bits) * repeat
    if flat.size < 2 * count:
        raise ValueError("Insufficient LL2 coefficients for matched controls")

    template = np.repeat(1.0 - 2.0 * bits.astype(float), repeat)
    indices = np.random.default_rng(seed).permutation(flat.size)
    chosen = flat[indices[:count]]
    negative = flat[indices[count:2 * count]]
    wrong_indices = np.random.default_rng(
        seed + WRONG_SEED_OFFSET
    ).permutation(flat.size)[:count]
    wrong_chosen = flat[wrong_indices]

    phase = np.cos(np.pi * chosen / delta)
    wrong_seed_phase = np.cos(np.pi * wrong_chosen / delta)
    wrong_delta_phase = np.cos(
        np.pi * chosen / (delta * WRONG_DELTA_MULTIPLIER)
    )
    lattice = float(
        np.mean(np.cos(2 * np.pi * chosen / delta))
        - np.mean(np.cos(2 * np.pi * negative / delta))
    )
    return {
        "lattice": lattice,
        "header": centred_correlation(template, phase),
        "wrong_seed_header": centred_correlation(template, wrong_seed_phase),
        "wrong_delta_header": centred_correlation(template, wrong_delta_phase),
    }


def score_size(
    received: Image.Image, size: tuple[int, int],
    delta: float, repeat: int,
) -> dict[str, float]:
    """Score candidate dimensions using the exact decoder's Y/LL2 transform."""
    image = (
        received if received.size == size
        else received.resize(size, Image.Resampling.LANCZOS)
    )
    ll = pywt.wavedec2(
        robust._ycc(image)[:, :, 0], "haar", level=2,
        mode="periodization",
    )[0]
    return score_ll2(ll, delta, repeat)


def rank_sizes(
    received: Image.Image,
    candidates: list[tuple[int, int]],
    delta: float, repeat: int,
) -> tuple[dict[str, list[tuple[int, int]]], dict]:
    """Rank same fixed candidate pool; never introduce new dimensions."""
    scores = [score_size(received, size, delta, repeat) for size in candidates]
    fields = ("header", "lattice", "wrong_seed_header", "wrong_delta_header")
    ranked = {"baseline": list(candidates)}
    for field in fields:
        # Stable tie break preserves the original Fourier order.
        ranked[field] = [
            candidates[i] for i in sorted(
                range(len(candidates)),
                key=lambda i: (-scores[i][field], i),
            )
        ]
    return ranked, {
        "scores": scores,
        "scored_count": len(scores),
    }


def first_grid_rank(
    candidates: list[tuple[int, int]], original: tuple[int, int],
) -> int | None:
    """Post-hoc metric ONLY; LL2 shape match is not packet recovery."""
    w, h = original
    grid = ((w + 3) // 4, (h + 3) // 4)
    return next((
        i for i, (cw, ch) in enumerate(candidates, 1)
        if ((cw + 3) // 4, (ch + 3) // 4) == grid
    ), None)


def decode_budget(
    received: Image.Image,
    sizes: list[tuple[int, int]],
    payload: bytes,
    budget: int,
) -> dict:
    """Independent decode arm: same candidate pool and capped calls."""
    attempts = 0
    for size in sizes[:budget]:
        attempts += 1
        try:
            recovered = robust.decode_at_size(received, size)
        except ValueError:
            continue
        if recovered == payload:
            return {
                "status": "PASS",
                "attempts": attempts,
                "decoded_size": f"{size[0]}x{size[1]}",
            }
    return {
        "status": "FAIL:not_recovered",
        "attempts": attempts,
        "decoded_size": None,
    }


def columns() -> list[str]:
    return [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "pilot_strength", "effective_pilot_strength", "adaptive_pilot",
        "delta", "repeat", "variants", "stages",
        "max_ranked", "pool_total", "scored_count", "status", "oracle",
        "baseline_grid_rank", "header_grid_rank", "lattice_grid_rank",
        "wrong_seed_header_grid_rank", "wrong_delta_header_grid_rank",
        "baseline_exact_rank", "header_exact_rank", "lattice_exact_rank",
        "header_score_at_first_true_grid", "lattice_score_at_first_true_grid",
        "wrong_seed_header_score_at_first_true_grid",
        "wrong_delta_header_score_at_first_true_grid",
        "ranking_seconds", "blind_budget",
        "baseline_blind_status", "baseline_blind_attempts",
        "baseline_blind_decoded_size", "baseline_blind_seconds",
        "header_blind_status", "header_blind_attempts",
        "header_blind_decoded_size", "header_blind_seconds",
        "lattice_blind_status", "lattice_blind_attempts",
        "lattice_blind_decoded_size", "lattice_blind_seconds",
    ]


def evaluate(
    received: Image.Image,
    original_size: tuple[int, int],
    payload: bytes,
    delta: float = 38.0,
    repeat: int = 13,
    max_ranked: int = DEFAULT_RANKED,
    blind_budget: int = 0,
) -> dict:
    """Blind candidate generation/ranking first, post-hoc diagnostics later."""
    start = time.perf_counter()
    pool = frozen_candidates(received)
    sampled = pool[:max_ranked]
    ranked, meta = rank_sizes(received, sampled, delta, repeat)
    ranking_seconds = time.perf_counter() - start
    out = {
        "pool_total": len(pool),
        "scored_count": meta["scored_count"],
        "ranking_seconds": round(ranking_seconds, 3),
        "blind_budget": blind_budget,
    }
    for arm, sizes in ranked.items():
        out[f"{arm}_grid_rank"] = first_grid_rank(sizes, original_size)
        if arm in ("baseline", "header", "lattice"):
            try:
                out[f"{arm}_exact_rank"] = sizes.index(original_size) + 1
            except ValueError:
                out[f"{arm}_exact_rank"] = None

    true_grid_rank = out["baseline_grid_rank"]
    if true_grid_rank is not None:
        score = meta["scores"][true_grid_rank - 1]
        for field in ("header", "lattice", "wrong_seed_header", "wrong_delta_header"):
            out[f"{field}_score_at_first_true_grid"] = round(score[field], 6)

    for arm in ("baseline", "header", "lattice"):
        out[f"{arm}_blind_status"] = "NOT_RUN"
        out[f"{arm}_blind_attempts"] = None
        out[f"{arm}_blind_decoded_size"] = None
        out[f"{arm}_blind_seconds"] = None
        if blind_budget:
            start = time.perf_counter()
            result = decode_budget(
                received, ranked[arm], payload, blind_budget
            )
            out[f"{arm}_blind_status"] = result["status"]
            out[f"{arm}_blind_attempts"] = result["attempts"]
            out[f"{arm}_blind_decoded_size"] = result["decoded_size"]
            out[f"{arm}_blind_seconds"] = round(
                time.perf_counter() - start, 3
            )
    return out


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    delta: float = 38.0, repeat: int = 13,
    max_ranked: int = DEFAULT_RANKED, blind_budget: int = 0,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "delta": delta, "repeat": repeat,
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "variants": ",".join(multi.variant_name(*v) for v in multi.DEFAULT_VARIANTS),
        "stages": ",".join(f"{n}:{q}" for n, q in cascade.DEFAULT_STAGES),
        "max_ranked": max_ranked,
    }
    rows = []
    packet = pack(payload)
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
                size = tuple(max(32, round(d * scale)) for d in marked.size)
                received = marked.resize(size, Image.Resampling.LANCZOS)
                # The original size is used below ONLY for diagnostic ranks,
                # after candidate generation and QIM ranking have finished.
                result = evaluate(
                    received, marked.size, payload, delta, repeat,
                    max_ranked, blind_budget,
                )
                oracle = decode_known_at_size(received, marked.size, payload)
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
    parser.add_argument("--max-ranked", type=int, default=DEFAULT_RANKED)
    parser.add_argument(
        "--blind", action="store_true",
        help="Run actual independent equal-budget decode arms (slow)",
    )
    parser.add_argument(
        "--decode-budget", type=int, default=40,
        help="Max decoder calls PER arm; used only with --blind",
    )
    parser.add_argument(
        "--fixed-pilot", action="store_true",
        help="Research-only alternative to current adaptive embedding",
    )
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep",
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        if not strengths or any(s <= 0 for s in strengths):
            raise ValueError("Pilot strengths must be positive")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if not 1 <= args.max_ranked <= 960:
            raise ValueError("--max-ranked must be 1..960")
        if not 1 <= args.decode_budget <= args.max_ranked:
            raise ValueError("--decode-budget must be 1..max-ranked")
        if args.csv.exists():
            raise ValueError("Refusing to overwrite CSV: " + str(args.csv))
        paths = image_paths(args.directory, args.name or list(DEFAULT_NAMES))
        if not paths:
            raise ValueError("No supported source images found")
        pack(args.message.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    if args.fixed_pilot:
        robust.ADAPTIVE_PILOT = False
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(paths)} covers x {len(strengths)} strengths x {len(scales)} "
        f"scales; max_ranked={args.max_ranked}, "
        f"blind={'ON' if args.blind else 'OFF'}, "
        f"adaptive={robust.ADAPTIVE_PILOT}",
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
                    args.max_ranked,
                    args.decode_budget if args.blind else 0,
                )
            except ValueError as exc:
                print(f"[{i}/{len(paths)}] SKIP {source.name}: {exc}", flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{i}/{len(paths)}] {row['source']} "
                    f"strength={row['pilot_strength']} "
                    f"scale={row['resize_scale']} "
                    f"oracle={row['oracle']} "
                    f"grid original/header/lattice="
                    f"{row.get('baseline_grid_rank')}/"
                    f"{row.get('header_grid_rank')}/"
                    f"{row.get('lattice_grid_rank')} "
                    f"blind baseline/header/lattice="
                    f"{row.get('baseline_blind_status')}/"
                    f"{row.get('header_blind_status')}/"
                    f"{row.get('lattice_blind_status')}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
