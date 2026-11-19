#!/usr/bin/env python3
"""Research-only Fourier pilot spectral ablation, without codec changes.

Re-encode selected real covers using the matched DWT 38/13 candidate, then
compare four pilot *detectors* on the SAME received pixels:
  all38   : all 32 rings, radial profile ending at 0.38 cyc/pixel
  inner38 : only rings <= 0.16, profile ending at 0.38
  all48   : all 32 rings, profile ending at 0.48
  inner48 : only rings <= 0.16, profile ending at 0.48

All variants search 0.45..1.02 with a fixed 160-candidate budget.
Only all38 with four peaks and first-peak quota 50 matches the previous
experimental extended detector. No variant is installed in production.
Optionally compare correlation peak counts and the first-peak candidate
quota; pilot=0 is a negative control.
The known encoded dimensions are used ONLY for diagnostic labels and the
separate oracle check, NEVER to generate or reorder blind candidates.
By default this tool ranks candidates only. --blind opt-in runs actual
packet recovery on each configured candidate list; use narrow CLI filters
to keep this bounded.
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
    decode_from_candidates, decoded_size_metrics,
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


def nearest_peak_diagnostic(
    peaks: list[tuple[float, float]], actual_scale: float,
    tolerance: float = 0.01,
) -> tuple[int | None, float | None]:
    """True-scale local peak rank and closest peak distance, diagnostic only.

    Peak lists are ranked by correlation strength. The actual scale is used
    ONLY after peaks are independently selected, never to select candidates.
    """
    if not peaks:
        return None, None
    rank, closest = min(
        enumerate(peaks, 1), key=lambda pair: abs(pair[1][0] - actual_scale)
    )
    distance = abs(closest[0] - actual_scale)
    return (rank if distance <= tolerance else None), round(distance, 6)


def parse_first_peak_quotas(value: str) -> list[int]:
    try:
        quotas = [int(x.strip()) for x in value.split(",")]
    except ValueError as exc:
        raise ValueError("First-peak quotas must be comma-separated integers") from exc
    if not quotas or any(q < 0 or q > 1000 for q in quotas):
        raise ValueError("First-peak quotas must be integers from 0 to 1000")
    return list(dict.fromkeys(quotas))


def unique_safe_ll2_grids(
    candidates: list[tuple[int, int]],
) -> int:
    """Count distinct decodable LL2 geometries within a fixed candidate budget."""
    return len({
        ((w + 3) // 4, (h + 3) // 4)
        for w, h in candidates
        if max(w, h) <= robust.MAX_LONGEST
        and w * h <= robust.MAX_DECODE_PIXELS
    })


def parse_peak_counts(value: str) -> list[int]:
    try:
        counts = [int(x.strip()) for x in value.split(",")]
    except ValueError as exc:
        raise ValueError("Peak counts must be comma-separated integers") from exc
    if not counts or any(n < 1 or n > 64 for n in counts):
        raise ValueError("Peak counts must be between 1 and 64")
    return list(dict.fromkeys(counts))


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
        "profile_max_freq", "ring_count", "candidate_limit", "max_peaks",
        "first_peak_quota", "unique_safe_ll2_grids",
        "best_peak_scale", "best_peak_score", "top_four_peak_scales",
        "true_scale_score", "true_scale_score_percentile",
        "true_scale_local_peak_rank", "nearest_local_peak_distance",
        "candidate_count", "exact_size_rank", "same_ll2_safe_rank",
        "safe_candidates_examined_for_grid", "nearest_size_distance_px",
        "blind_status", "blind_attempts", "blind_decoded_size",
        "blind_width_error_px", "blind_height_error_px",
        "blind_same_ll2_shape", "seconds",
    ]


def probe(
    source: Path, payload: bytes, strengths: list[float],
    scales: list[float], delta: float = 38.0,
    repeat: int = 13, candidate_limit: int = 160,
    peak_counts: list[int] | None = None,
    variants: tuple[str, ...] | None = None,
    first_peak_quotas: list[int] | None = None,
    run_blind: bool = False,
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
    if peak_counts is None:
        peak_counts = [4]
    if first_peak_quotas is None:
        first_peak_quotas = [50]
    if variants is None:
        variants = tuple(name for name, _, _ in VARIANTS)
    rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = (
                reference.convert("YCbCr").convert("RGB")
                if strength == 0 else
                robust._pilot_embed(reference, strength=strength)
            )
            marked = robust._feedback_embed(pilot, packet)
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
                    if variant not in variants:
                        continue
                    started = time.perf_counter()
                    scale_values, scores = score_spectrum(
                        profiles[freq], freq, inner_only
                    )
                    all_peaks = select_peaks(
                        scale_values, scores, max_peaks=len(scale_values)
                    )
                    local_rank, local_distance = nearest_peak_diagnostic(
                        all_peaks, actual_scale
                    )
                    true_score = float(np.interp(
                        actual_scale, scale_values, scores
                    ))
                    for max_peaks in peak_counts:
                        peaks = all_peaks[:max_peaks]
                        for quota in first_peak_quotas:
                            candidates = priority_candidates_from_peaks(
                                received.size, peaks, candidate_limit,
                                first_peak_quota=quota,
                            )
                            exact_rank, nearest = rank_and_distance(
                                candidates, marked.size
                            )
                            grid_rank, safe_examined = first_safe_grid_rank(
                                candidates, marked.size
                            )
                            if run_blind:
                                blind_status, blind_attempts, decoded_size = (
                                    decode_from_candidates(
                                        received, candidates, payload
                                    )
                                )
                            else:
                                blind_status, blind_attempts, decoded_size = (
                                    "NOT_RUN", None, None
                                )
                            width_error, height_error, same_grid = (
                                decoded_size_metrics(decoded_size, marked.size)
                            )
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
                                "max_peaks": max_peaks,
                                "first_peak_quota": quota,
                                "unique_safe_ll2_grids": unique_safe_ll2_grids(
                                    candidates
                                ),
                                "best_peak_scale": peaks[0][0] if peaks else None,
                                "best_peak_score": peaks[0][1] if peaks else None,
                                "top_four_peak_scales": ";".join(
                                    f"{s:.3f}" for s, _ in peaks[:4]
                                ),
                                "true_scale_score": true_score,
                                "true_scale_score_percentile": round(
                                    100 * float(np.mean(scores <= true_score)), 2
                                ),
                                "true_scale_local_peak_rank": local_rank,
                                "nearest_local_peak_distance": local_distance,
                                "candidate_count": len(candidates),
                                "exact_size_rank": exact_rank,
                                "same_ll2_safe_rank": grid_rank,
                                "safe_candidates_examined_for_grid": safe_examined,
                                "nearest_size_distance_px": nearest,
                                "blind_status": blind_status,
                                "blind_attempts": blind_attempts,
                                "blind_decoded_size": decoded_size,
                                "blind_width_error_px": width_error,
                                "blind_height_error_px": height_error,
                                "blind_same_ll2_shape": same_grid,
                                "seconds": round(
                                    time.perf_counter() - started, 3
                                ),
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
        "--blind", action="store_true",
        help="Actually decode each candidate list (slow); use narrow filters",
    )
    parser.add_argument(
        "--peak-counts", default="4",
        help="Comma-separated peak budgets, e.g. 4,8,12; default 4",
    )
    parser.add_argument(
        "--first-peak-quotas", default="50",
        help="Comma-separated priority quotas, e.g. 0,10,25,50; default 50",
    )
    parser.add_argument(
        "--variants", default="all38,inner38,all48,inner48",
        help="Comma-separated detector variants",
    )
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        peak_counts = parse_peak_counts(args.peak_counts)
        first_peak_quotas = parse_first_peak_quotas(args.first_peak_quotas)
        variants = tuple(dict.fromkeys(
            part.strip() for part in args.variants.split(",")
        ))
        known_variants = {name for name, _, _ in VARIANTS}
        if not variants or any(v not in known_variants for v in variants):
            raise ValueError(
                "--variants must select one or more of " +
                ",".join(sorted(known_variants))
            )
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
        f"{len(scales)} scales × {len(variants)} detector variants × "
        f"{len(peak_counts)} peak budgets × "
        f"{len(first_peak_quotas)} first-peak quotas = "
        f"{len(paths)*len(strengths)*len(scales)*len(variants)*len(peak_counts)*len(first_peak_quotas)} rows",
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
                    peak_counts=peak_counts, variants=variants,
                    first_peak_quotas=first_peak_quotas,
                    run_blind=args.blind,
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
                    f"peaks={row['max_peaks']} "
                    f"quota={row['first_peak_quota']} "
                    f"oracle={row['oracle']} "
                    f"blind={row['blind_status']} "
                    f"attempts={row['blind_attempts']} "
                    f"grid_rank={row['same_ll2_safe_rank']} "
                    f"best_scale={row['best_peak_scale']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)
    print(
        "A same-LL2-grid rank is only a geometry diagnostic. "
        "Actual blind packet recovery is shown separately as blind_status "
        "when --blind is enabled. No production code was changed."
    )


if __name__ == "__main__":
    main()
