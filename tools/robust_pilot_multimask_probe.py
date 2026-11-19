#!/usr/bin/env python3
"""Research-only blind Fourier search with a PRESET sequence of angular masks.

Fixed detector variants are evaluated in the same order for EVERY received
image, independent of its cover, true resize factor or original dimensions.
The blind search sees ONLY received pixels and the expected test payload.
Known original dimensions are used later for an independent oracle and
post-hoc decoded-size diagnostics, never for selecting variants or candidates.

Each variant uses the validated 4:10,16:10 candidate cascade. Duplicate
PIXEL dimensions are skipped across all variants/stages, but distinct
dimensions with identical LL2 grids are retained because resizing affects
QIM recovery. This uses a much larger total budget than the old 2-stage
baseline: report attempts and per-variant costs rather than claiming a
same-budget improvement. No production codec changes.
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
from tools import robust_pilot_angular_probe as angular
from tools import robust_pilot_cascade_probe as cascade
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, decoded_size_metrics, parse_scales, parse_strengths,
    priority_candidates_from_peaks,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_spectral_ablation import score_spectrum, select_peaks
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)
from tools.robust_quality_compare import quality_metrics


# Frozen before the full five-cover comparison: no true-scale-dependent choice.
DEFAULT_VARIANTS = ((0.38, 0.0), (0.38, 5.0), (0.48, 20.0))


def parse_variants(value: str) -> tuple[tuple[float, float], ...]:
    """Parse ordered frequency:axis-mask pairs, without oracle hints."""
    result = []
    try:
        for part in value.split(","):
            freq_text, angle_text = part.strip().split(":")
            freq, angle = float(freq_text), float(angle_text)
            angular.parse_freqs(str(freq))
            angular.parse_angles(str(angle))
            result.append((freq, angle))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Variants must be frequency:axis-degrees pairs, "
            "e.g. 0.38:0,0.38:5,0.48:20"
        ) from exc
    if not 1 <= len(result) <= 8 or len(set(result)) != len(result):
        raise ValueError("Specify 1..8 distinct detector variants")
    return tuple(result)


def variant_name(freq: float, angle: float) -> str:
    return f"{freq:g}:{angle:g}"


def variant_peaks(
    workspace, freq: float, angle: float, max_peaks: int,
) -> list[tuple[float, float]]:
    """Select peaks from received pixels only; no known scale is supplied."""
    profile = angular.masked_profile(workspace, freq, angle)
    scales, scores = score_spectrum(profile, freq, False)
    return select_peaks(scales, scores, max_peaks=max_peaks)


def decode_multimask(
    received: Image.Image,
    payload: bytes,
    variants: tuple[tuple[float, float], ...] = DEFAULT_VARIANTS,
    stages: tuple[tuple[int, int], ...] = cascade.DEFAULT_STAGES,
    per_stage_candidates: int = 160,
) -> dict:
    """Search all preset masks, skipping duplicate pixel sizes globally.

    The returned PASS means robust.decode_at_size returned exactly the
    expected payload, not merely that the LL2 shape happened to match.
    """
    if not variants or not stages or per_stage_candidates < 1:
        raise ValueError("Nonempty variants/stages and positive budget required")
    if any(count < 1 or quota < 0 for count, quota in stages):
        raise ValueError("Invalid search stage")
    workspace = angular.fft_workspace(received)
    seen: set[tuple[int, int]] = set()
    total_attempts = 0
    attempts_by_variant: list[str] = []
    new_sizes_by_variant: list[str] = []
    for freq, angle in variants:
        name = variant_name(freq, angle)
        peaks = variant_peaks(
            workspace, freq, angle, max_peaks=max(count for count, _ in stages),
        )
        variant_attempts = 0
        variant_new_sizes = 0
        for count, quota in stages:
            candidates = priority_candidates_from_peaks(
                received.size, peaks[:count], per_stage_candidates,
                first_peak_quota=quota,
            )
            for size in candidates:
                if size in seen:
                    continue
                seen.add(size)
                variant_new_sizes += 1
                if not cascade.safe_size(size):
                    continue
                variant_attempts += 1
                total_attempts += 1
                try:
                    recovered = robust.decode_at_size(received, size)
                except ValueError:
                    continue
                if recovered == payload:
                    attempts_by_variant.append(f"{name}:{variant_attempts}")
                    new_sizes_by_variant.append(f"{name}:{variant_new_sizes}")
                    return {
                        "blind_status": "PASS",
                        "blind_attempts": total_attempts,
                        "blind_decoded_size": f"{size[0]}x{size[1]}",
                        "successful_variant": name,
                        "successful_stage": f"{count}/{quota}",
                        "variants_run": len(attempts_by_variant),
                        "unique_pixel_candidates_generated": len(seen),
                        "safe_attempts_by_variant": ";".join(attempts_by_variant),
                        "new_candidates_by_variant": ";".join(new_sizes_by_variant),
                    }
        attempts_by_variant.append(f"{name}:{variant_attempts}")
        new_sizes_by_variant.append(f"{name}:{variant_new_sizes}")
    return {
        "blind_status": "FAIL:not_recovered",
        "blind_attempts": total_attempts,
        "blind_decoded_size": None,
        "successful_variant": None,
        "successful_stage": None,
        "variants_run": len(attempts_by_variant),
        "unique_pixel_candidates_generated": len(seen),
        "safe_attempts_by_variant": ";".join(attempts_by_variant),
        "new_candidates_by_variant": ";".join(new_sizes_by_variant),
    }


def columns() -> list[str]:
    return [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "pilot_strength", "effective_pilot_strength", "delta", "repeat",
        "variants", "stages", "per_stage_candidate_limit", "status",
        "oracle", "marked_psnr_db", "marked_ssim_y",
        "blind_status", "blind_attempts", "blind_decoded_size",
        "successful_variant", "successful_stage", "variants_run",
        "unique_pixel_candidates_generated", "safe_attempts_by_variant",
        "new_candidates_by_variant", "blind_width_error_px",
        "blind_height_error_px", "blind_same_ll2_shape", "seconds",
    ]


def probe(
    source: Path,
    payload: bytes,
    strengths: list[float],
    scales: list[float],
    variants: tuple[tuple[float, float], ...] = DEFAULT_VARIANTS,
    stages: tuple[tuple[int, int], ...] = cascade.DEFAULT_STAGES,
    delta: float = 38.0,
    repeat: int = 13,
    per_stage_candidates: int = 160,
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
        "variants": ",".join(variant_name(*v) for v in variants),
        "stages": ",".join(f"{c}:{q}" for c, q in stages),
        "per_stage_candidate_limit": per_stage_candidates,
    }
    rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = (
                reference.convert("YCbCr").convert("RGB")
                if strength == 0 else
                robust._pilot_embed(reference, strength=strength)
            )
            try:
                marked = robust._feedback_embed(pilot, packet)
            except ValueError as exc:
                for scale in scales:
                    rows.append({
                        **base, "pilot_strength": strength,
                        "resize_scale": scale, "status": "SKIP:" + str(exc),
                        "blind_status": "NOT_RUN",
                    })
                continue
            metrics = quality_metrics(reference, marked)
            for scale in scales:
                size = tuple(max(32, round(d * scale)) for d in marked.size)
                received = marked.resize(size, Image.Resampling.LANCZOS)
                started = time.perf_counter()
                # Deliberately run BLIND first. Oracle is not available to
                # any variant, ranking, candidate generator or decode loop.
                result = decode_multimask(
                    received, payload, variants, stages, per_stage_candidates
                )
                elapsed = time.perf_counter() - started
                oracle = decode_known_at_size(received, marked.size, payload)
                werr, herr, same_grid = decoded_size_metrics(
                    result["blind_decoded_size"], marked.size
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
                    "marked_psnr_db": metrics["psnr_db"],
                    "marked_ssim_y": metrics["ssim_y"],
                    **result,
                    "blind_width_error_px": werr,
                    "blind_height_error_px": herr,
                    "blind_same_ll2_shape": same_grid,
                    "seconds": round(elapsed, 3),
                })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument(
        "--name", action="append", default=[],
        help="Exact source filename, repeatable; defaults to five covers",
    )
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--variants", default="0.38:0,0.38:5,0.48:20")
    parser.add_argument("--stages", default="4:10,16:10")
    parser.add_argument("--max-candidates-per-stage", type=int, default=160)
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        variants = parse_variants(args.variants)
        stages = cascade.parse_stages(args.stages)
        if not 1 <= args.max_candidates_per_stage <= 1000:
            raise ValueError("Candidate budget must be 1..1000")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if args.csv.exists():
            raise ValueError(f"Refusing to overwrite CSV: {args.csv}")
        paths = image_paths(
            args.directory, args.name or list(DEFAULT_NAMES)
        )
        if not paths:
            raise ValueError("No supported input images found")
        payload = args.message.encode("utf-8")
        pack(payload)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(paths)} covers × {len(strengths)} strengths × "
        f"{len(scales)} resizes = "
        f"{len(paths)*len(strengths)*len(scales)} actual blind tests; "
        f"variants={args.variants}, stages={args.stages}; "
        f"up to {len(variants)*len(stages)*args.max_candidates_per_stage} "
        "generated sizes before cross-variant deduplication",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, payload, strengths, scales,
                    variants=variants, stages=stages,
                    delta=args.delta, repeat=args.repeat,
                    per_stage_candidates=args.max_candidates_per_stage,
                )
            except ValueError as exc:
                print(f"[{i}/{len(paths)}] {source.name}: SKIP: {exc}", flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{i}/{len(paths)}] {row['source']} "
                    f"pilot={row['pilot_strength']} "
                    f"resize={row['resize_scale']} "
                    f"oracle={row.get('oracle')} "
                    f"blind={row['blind_status']} "
                    f"mask={row.get('successful_variant')} "
                    f"attempts={row.get('blind_attempts')}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
