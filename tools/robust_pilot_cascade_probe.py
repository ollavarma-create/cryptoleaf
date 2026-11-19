#!/usr/bin/env python3
"""Research-only staged Fourier blind search; never changes the production codec.

The fixed default cascade tries 4 peaks/quota 10, then 4 peaks/quota 50
(the original extended-search baseline), then 16 peaks/quota 10. Each
stage receives at most 160 independently ranked size candidates. Duplicate
PIXEL dimensions across stages are decoded only once; different dimensions
with the same LL2 shape are retained because resampling can affect QIM
recovery. The total search budget is therefore larger than a single
160-candidate search; report this tradeoff, never compare it as equal cost.

The true encoded size is used ONLY for an independent oracle check and
post-decode diagnostics, never for candidate generation or selection.
No production code is modified.
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
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, decoded_size_metrics, parse_scales, parse_strengths,
    priority_candidates_from_peaks,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)
from tools.robust_quality_compare import quality_metrics


DEFAULT_STAGES = ((4, 10), (4, 50), (16, 10))


def parse_stages(value: str) -> tuple[tuple[int, int], ...]:
    """Parse ordered peak-count:quota stages; no oracle-dependent choices."""
    result = []
    try:
        for part in value.split(","):
            count_text, quota_text = part.strip().split(":")
            count, quota = int(count_text), int(quota_text)
            if not 1 <= count <= 64 or not 0 <= quota <= 1000:
                raise ValueError("Peak count must be 1..64 and quota 0..1000")
            result.append((count, quota))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Stages must be comma-separated peak-count:quota pairs, "
            "e.g. 4:10,4:50,16:10"
        ) from exc
    if not result or len(result) > 8:
        raise ValueError("Specify between 1 and 8 stages")
    if len(set(result)) != len(result):
        raise ValueError("Duplicate stages are not allowed")
    return tuple(result)


def safe_size(size: tuple[int, int]) -> bool:
    w, h = size
    return (
        min(w, h) >= 32
        and max(w, h) <= robust.MAX_LONGEST
        and w * h <= robust.MAX_DECODE_PIXELS
    )


def decode_staged(
    received: Image.Image,
    payload: bytes,
    stages: tuple[tuple[int, int], ...] = DEFAULT_STAGES,
    per_stage_candidates: int = 160,
) -> dict:
    """Attempt each independently ranked search, skipping duplicate pixel sizes.

    Return the exact stage and cumulative number of SAFE decoder calls.
    The decoded packet must match the fixed payload bytes; a valid but
    different packet is not a success.
    """
    if not stages or per_stage_candidates < 1:
        raise ValueError("At least one stage and a positive budget are required")
    if any(count < 1 or quota < 0 for count, quota in stages):
        raise ValueError("Invalid search stage")

    peaks = robust._peaks(
        received, low=0.45, high=1.02,
        max_peaks=max(count for count, _ in stages),
    )
    seen: set[tuple[int, int]] = set()
    total_safe_attempts = 0
    stage_counts: list[str] = []
    stage_new_sizes: list[str] = []

    for count, quota in stages:
        stage_name = f"{count}/{quota}"
        candidates = priority_candidates_from_peaks(
            received.size, peaks[:count], per_stage_candidates,
            first_peak_quota=quota,
        )
        new_candidates = [size for size in candidates if size not in seen]
        seen.update(new_candidates)
        stage_new_sizes.append(f"{stage_name}:{len(new_candidates)}")
        stage_safe = 0
        for size in new_candidates:
            if not safe_size(size):
                continue
            stage_safe += 1
            total_safe_attempts += 1
            try:
                recovered = robust.decode_at_size(received, size)
            except ValueError:
                continue
            if recovered == payload:
                stage_counts.append(f"{stage_name}:{stage_safe}")
                return {
                    "blind_status": "PASS",
                    "blind_attempts": total_safe_attempts,
                    "blind_decoded_size": f"{size[0]}x{size[1]}",
                    "successful_stage": stage_name,
                    "stages_run": len(stage_counts),
                    "unique_pixel_candidates_generated": len(seen),
                    "safe_attempts_by_stage": ";".join(stage_counts),
                    "new_candidates_by_stage": ";".join(stage_new_sizes),
                }
        stage_counts.append(f"{stage_name}:{stage_safe}")
    return {
        "blind_status": "FAIL:not_recovered",
        "blind_attempts": total_safe_attempts,
        "blind_decoded_size": None,
        "successful_stage": None,
        "stages_run": len(stage_counts),
        "unique_pixel_candidates_generated": len(seen),
        "safe_attempts_by_stage": ";".join(stage_counts),
        "new_candidates_by_stage": ";".join(stage_new_sizes),
    }


def columns() -> list[str]:
    return [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "pilot_strength", "effective_pilot_strength",
        "delta", "repeat", "per_stage_candidate_limit",
        "stages", "status", "oracle", "marked_psnr_db", "marked_ssim_y",
        "blind_status", "blind_attempts", "blind_decoded_size",
        "successful_stage", "stages_run",
        "unique_pixel_candidates_generated",
        "safe_attempts_by_stage", "new_candidates_by_stage",
        "blind_width_error_px", "blind_height_error_px",
        "blind_same_ll2_shape", "seconds",
    ]


def probe(
    source: Path,
    payload: bytes,
    strengths: list[float],
    scales: list[float],
    stages: tuple[tuple[int, int], ...] = DEFAULT_STAGES,
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
        "per_stage_candidate_limit": per_stage_candidates,
        "stages": ",".join(f"{count}:{quota}" for count, quota in stages),
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
                started = time.perf_counter()
                received_size = tuple(
                    max(32, round(d * scale)) for d in marked.size
                )
                received = marked.resize(
                    received_size, Image.Resampling.LANCZOS
                )
                oracle = decode_known_at_size(received, marked.size, payload)
                result = decode_staged(
                    received, payload, stages, per_stage_candidates
                )
                width_error, height_error, same_grid = decoded_size_metrics(
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
                    "blind_width_error_px": width_error,
                    "blind_height_error_px": height_error,
                    "blind_same_ll2_shape": same_grid,
                    "seconds": round(time.perf_counter() - started, 3),
                })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument(
        "--name", action="append", default=[],
        help="Exact source filename; repeat to override five-cover defaults",
    )
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--stages", default="4:10,4:50,16:10")
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
        stages = parse_stages(args.stages)
        if not 1 <= args.max_candidates_per_stage <= 1000:
            raise ValueError("Per-stage candidate budget must be 1..1000")
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
        f"{len(scales)} scales = "
        f"{len(paths)*len(strengths)*len(scales)} actual blind tests; "
        f"stages={args.stages}, "
        f"up to {len(stages)*args.max_candidates_per_stage} "
        "pixel-size candidates before cross-stage deduplication",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, payload, strengths, scales,
                    stages=stages, delta=args.delta, repeat=args.repeat,
                    per_stage_candidates=args.max_candidates_per_stage,
                )
            except ValueError as exc:
                print(
                    f"[{i}/{len(paths)}] {source.name}: SKIP: {exc}",
                    flush=True,
                )
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{i}/{len(paths)}] {row['source']} "
                    f"pilot={row['pilot_strength']} "
                    f"scale={row['resize_scale']} "
                    f"oracle={row.get('oracle')} "
                    f"blind={row['blind_status']} "
                    f"stage={row.get('successful_stage')} "
                    f"attempts={row.get('blind_attempts')}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
