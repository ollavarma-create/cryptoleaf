#!/usr/bin/env python3
"""Research-only Fourier pilot spectral ablation, without codec changes.

Re-encode selected real covers using the matched DWT 38/13 candidate, then
compare four pilot *detectors* on the SAME received pixels:
  all38   : all 32 rings, radial profile ending at 0.38 cyc/pixel
  inner38 : only rings <= 0.16, profile ending at 0.38
  all48   : all 32 rings, profile ending at 0.48
  inner48 : only rings <= 0.16, profile ending at 0.48

All variants search 0.45..1.02 and use the SAME 160-candidate Priority50
ordering. Only all38 matches the previous experimental extended detector.
No detector variant is installed in production. The known encoded dimensions
are used ONLY for diagnostic labels and the separate oracle check, NEVER to
generate or reorder blind candidates. This tool ranks candidates; it does
not run expensive blind packet decoding.
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

import numpy as np
from PIL import Image
from scipy.signal import find_peaks

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, parse_scales, parse_strengths,
    priority_candidates_from_peaks, rank_and_distance,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)

STEP = 0.002
LOW = 0.45
HIGH = 1.02
VARIANTS = (
    ("all38", 0.38, False),
    ("inner38", 0.38, True),
    ("all48", 0.48, False),
    ("inner48", 0.48, True),
)


def score_spectrum(
    profile: np.ndarray,
    max_freq: float,
    inner_only: bool,
    low: float = LOW,
    high: float = HIGH,
    step: float = STEP,
) -> tuple[np.ndarray, np.ndarray]:
    """Match production correlation formula, with optional ring subset.

    The original all38 variant is numerically equivalent to
    robust._peaks(image, low=0.45, high=1.02) before peak selection.
    Frequency bins are generated using the actual profile length.
    """
    if len(profile) < 2 or max_freq <= 0:
        raise ValueError("Invalid radial profile")
    scales = np.arange(low, high + step / 2, step)
    frequencies = (np.arange(len(profile)) + .5) * (max_freq / len(profile))
    signs = np.random.default_rng(robust.SEED).choice(
        [-1., 1.], size=len(robust.RADII)
    )
    mask = robust.RADII <= 0.16 if inner_only else np.ones(
        len(robust.RADII), dtype=bool
    )
    radii, signs = robust.RADII[mask], signs[mask]
    scores = np.empty(len(scales), dtype=float)
    for i, scale in enumerate(scales):
        observed = np.interp(radii / scale, frequencies, profile)
        scores[i] = np.dot(signs, observed) / (
            np.linalg.norm(observed) * np.linalg.norm(signs) + 1e-12
        )
    return scales, scores


def select_peaks(
    scales: np.ndarray, scores: np.ndarray,
    step: float = STEP, max_peaks: int = 4,
) -> list[tuple[float, float]]:
    """Same peak separation, endpoints, and ranking as production _peaks."""
    if len(scales) != len(scores) or len(scores) < 2:
        raise ValueError("Invalid peak arrays")
    indexes = set(find_peaks(
        scores, distance=max(1, round(1.2 / 100 / step))
    )[0].tolist())
    indexes.add(int(np.argmax(scores)))
    if scores[0] > scores[1]:
        indexes.add(0)
    if scores[-1] > scores[-2]:
        indexes.add(len(scores) - 1)
    return sorted(
        ((float(scales[i]), float(scores[i])) for i in indexes),
        key=lambda item: -item[1],
    )[:max_peaks]


def same_ll2_shape(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return ((a[0] + 3) // 4, (a[1] + 3) // 4) == (
        (b[0] + 3) // 4, (b[1] + 3) // 4
    )


def first_safe_grid_rank(
    candidates: list[tuple[int, int]],
    true_size: tuple[int, int],
) -> tuple[int | None, int]:
    """First grid match by actual attempted-decode order; skip unsafe sizes."""
    safe_attempts = 0
    for candidate in candidates:
        if max(candidate) > robust.MAX_LONGEST or (
            candidate[0] * candidate[1] > robust.MAX_DECODE_PIXELS
        ):
            continue
        safe_attempts += 1
        if same_ll2_shape(candidate, true_size):
            return safe_attempts, safe_attempts
    return None, safe_attempts


def columns() -> list[str]:
    return [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "actual_width_scale", "pilot_strength", "effective_pilot_strength",
        "delta", "repeat", "oracle", "status", "variant",
        "profile_max_freq", "ring_count", "candidate_limit",
        "best_peak_scale", "best_peak_score", "top_four_peak_scales",
        "true_scale_score", "true_scale_score_percentile",
        "candidate_count", "exact_size_rank", "same_ll2_safe_rank",
        "safe_candidates_examined_for_grid", "nearest_size_distance_px",
        "seconds",
    ]


def probe(
    source: Path, payload: bytes, strengths: list[float],
    scales: list[float], delta: float = 38.0,
    repeat: int = 13, candidate_limit: int = 160,
) -> list[dict]:
    with Image.open(source) as opened:
        reference = reference_image(opened)
    packet = pack(payload)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "delta": delta,
        "repeat": repeat,
        "candidate_limit": candidate_limit,
    }
    rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            marked = robust._feedback_embed(
                robust._pilot_embed(reference, strength=strength),
                packet,
            )
            for scale in scales:
                received_size = tuple(
                    max(32, round(d * scale)) for d in marked.size
                )
                received = marked.resize(
                    received_size, Image.Resampling.LANCZOS
                )
                actual_scale = received.width / marked.width
                oracle = decode_known_at_size(received, marked.size, payload)
                profiles = {
                    freq: robust._profile(
                        received,
                        bins=round(1800 * freq / 0.38),
                        max_freq=freq,
                    )
                    for freq in (0.38, 0.48)
                }
                for variant, freq, inner_only in VARIANTS:
                    started = time.perf_counter()
                    scale_values, scores = score_spectrum(
                        profiles[freq], freq, inner_only
                    )
                    peaks = select_peaks(scale_values, scores)
                    candidates = priority_candidates_from_peaks(
                        received.size, peaks, candidate_limit
                    )
                    exact_rank, nearest = rank_and_distance(
                        candidates, marked.size
                    )
                    grid_rank, safe_examined = first_safe_grid_rank(
                        candidates, marked.size
                    )
                    true_score = float(np.interp(
                        actual_scale, scale_values, scores
                    ))
                    rows.append({
                        **base,
                        "received_width": received.width,
                        "received_height": received.height,
                        "resize_scale": scale,
                        "actual_width_scale": round(actual_scale, 8),
                        "pilot_strength": strength,
                        "effective_pilot_strength": round(
                            effective_strength(reference, strength), 6
                        ),
                        "oracle": oracle,
                        "status": "OK",
                        "variant": variant,
                        "profile_max_freq": freq,
                        "ring_count": int(np.sum(
                            robust.RADII <= 0.16
                        )) if inner_only else len(robust.RADII),
                        "best_peak_scale": peaks[0][0] if peaks else None,
                        "best_peak_score": peaks[0][1] if peaks else None,
                        "top_four_peak_scales": ";".join(
                            f"{s:.3f}" for s, _ in peaks
                        ),
                        "true_scale_score": true_score,
                        "true_scale_score_percentile": round(
                            100 * float(np.mean(scores <= true_score)), 2
                        ),
                        "candidate_count": len(candidates),
                        "exact_size_rank": exact_rank,
                        "same_ll2_safe_rank": grid_rank,
                        "safe_candidates_examined_for_grid": safe_examined,
                        "nearest_size_distance_px": nearest,
                        "seconds": round(time.perf_counter() - started, 3),
                    })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--max-candidates", type=int, default=160)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        if not 1 <= args.max_candidates <= 1000:
            raise ValueError("--max-candidates must be 1..1000")
        paths = image_paths(
            args.directory, args.name or list(DEFAULT_NAMES)
        )
        if not paths:
            raise ValueError("No supported input images found")
        if args.csv.exists():
            raise ValueError(f"Refusing to overwrite CSV: {args.csv}")
        payload = args.message.encode("utf-8")
        pack(payload)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(paths)} covers × {len(strengths)} pilot strengths × "
        f"{len(scales)} scales × {len(VARIANTS)} detector variants "
        f"= {len(paths)*len(strengths)*len(scales)*len(VARIANTS)} rows",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for index, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, payload, strengths, scales,
                    candidate_limit=args.max_candidates,
                )
            except ValueError as exc:
                print(
                    f"[{index}/{len(paths)}] {source.name}: "
                    f"SKIP: {exc}", flush=True,
                )
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{index}/{len(paths)}] {row['source']} "
                    f"pilot={row['pilot_strength']} "
                    f"resize={row['resize_scale']} "
                    f"variant={row['variant']} "
                    f"oracle={row['oracle']} "
                    f"grid_rank={row['same_ll2_safe_rank']} "
                    f"best_scale={row['best_peak_scale']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)
    print(
        "The same-LL2-grid rank is only a necessary-geometry diagnostic, "
        "NOT a successful blind decode. No production code was changed."
    )


if __name__ == "__main__":
    main()
