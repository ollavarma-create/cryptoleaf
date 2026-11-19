#!/usr/bin/env python3
"""Pilot synchronization probe on the measured DWT 38/13 candidate.

Research only: tests whether Fourier peaks place the TRUE encoded dimensions
inside the blind search budget after 75% and 50% resizing. The true dimensions
are used only for the oracle control and diagnostics, never as a candidate hint.

Both the current production search (.70..1.02) and an extended experimental
search (.45..1.02) are ranked WITHOUT decoding by default. Optional --blind
executes the unchanged production blind decoder (slow); optional
--extended-blind attempts decoding against the extended Fourier candidates
using the unchanged matched DWT decoder. Neither option modifies production.
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
from tools.robust_batch_matrix import image_paths
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)
from tools.robust_quality_compare import quality_metrics

DEFAULT_NAMES = (
    "appfootprint-main.png",
    "Anna Maria Liikanen.jpg",
    "AarneArmeijassa.jpg",
    "cryptoleaf-robust.png",
    "P1000450.JPG",
)


def priority_candidates_from_peaks(
    received_size: tuple[int, int],
    peaks: list[tuple[float, float]],
    max_candidates: int = 160,
) -> list[tuple[int, int]]:
    """Same Priority50 ordering as production, for alternate peak ranges."""
    streams = [
        iter(robust._candidate_sizes(received_size, scale, limit=max_candidates))
        for scale, _score in peaks
    ]
    seen: set[tuple[int, int]] = set()
    candidates = []

    def take(stream):
        for size in stream:
            if size not in seen:
                seen.add(size)
                return size
        return None

    if streams:
        for _ in range(min(50, max_candidates)):
            size = take(streams[0])
            if size is None:
                break
            candidates.append(size)
    active = list(streams)
    while active and len(seen) < max_candidates:
        remaining = []
        for stream in active:
            size = take(stream)
            if size is not None:
                remaining.append(stream)
                candidates.append(size)
            if len(seen) >= max_candidates:
                break
        active = remaining
    return candidates


def rank_and_distance(
    candidates: list[tuple[int, int]], true_size: tuple[int, int],
) -> tuple[int | None, int | None]:
    """1-based exact rank and nearest Manhattan pixel distance."""
    try:
        rank = candidates.index(true_size) + 1
    except ValueError:
        rank = None
    nearest = (
        min(abs(w - true_size[0]) + abs(h - true_size[1])
            for w, h in candidates)
        if candidates else None
    )
    return rank, nearest


def peak_summary(peaks: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    return peaks[0] if peaks else (None, None)


def decode_from_candidates(
    received: Image.Image,
    candidates: list[tuple[int, int]],
    payload: bytes,
) -> tuple[str, int, str | None]:
    """Decode using Fourier-generated candidate sizes, never an oracle hint.

    This is a research-only search using the unchanged matched DWT decoder.
    Return the number of safe candidates actually attempted.
    """
    attempts = 0
    for size in candidates:
        if max(size) > robust.MAX_LONGEST or (
            size[0] * size[1] > robust.MAX_DECODE_PIXELS
        ):
            continue
        attempts += 1
        try:
            recovered = robust.decode_at_size(received, size)
        except ValueError:
            continue
        if recovered == payload:
            return "PASS", attempts, f"{size[0]}x{size[1]}"
        # A valid CRC32 but wrong payload is not success.
    return "FAIL:not_recovered", attempts, None


def parse_scales(value: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError("Invalid scale factors") from exc
    if not values or any(not math.isfinite(v) or not 0.2 <= v <= 1.0 for v in values):
        raise ValueError("Scale factors must be finite and between 0.2 and 1.0")
    return list(dict.fromkeys(values))


def parse_strengths(value: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError("Invalid pilot strengths") from exc
    if not values or any(not math.isfinite(v) or not 0 <= v <= 0.5 for v in values):
        raise ValueError("Pilot strengths must be finite and between 0 and 0.5")
    return list(dict.fromkeys(values))


def columns() -> list[str]:
    return [
        "source", "source_sha256", "source_width", "source_height",
        "encoded_width", "encoded_height", "received_width", "received_height",
        "scale", "observed_width_scale", "pilot_strength",
        "effective_pilot_strength", "delta", "repeat", "max_candidates",
        "status", "oracle", "marked_psnr_db", "marked_ssim_y",
        "standard_best_scale", "standard_best_score",
        "standard_candidate_count", "standard_true_size_rank",
        "standard_nearest_size_distance_px",
        "extended_best_scale", "extended_best_score",
        "extended_candidate_count", "extended_true_size_rank",
        "extended_nearest_size_distance_px",
        "blind_status", "blind_attempts", "blind_decoded_size",
        "extended_blind_status", "extended_blind_attempts",
        "extended_blind_decoded_size", "seconds",
    ]


def probe(
    source: Path,
    payload: bytes,
    strengths: list[float],
    scales: list[float],
    delta: float,
    repeat: int,
    max_candidates: int,
    run_blind: bool,
    run_extended_blind: bool = False,
) -> list[dict]:
    """One cover, several pilot strengths; matched DWT encoder/decoder."""
    with Image.open(source) as opened:
        source_size = opened.size
        reference = reference_image(opened)
    packet = pack(payload)
    zero_pilot = reference.convert("YCbCr").convert("RGB")
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_width": source_size[0],
        "source_height": source_size[1],
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "delta": delta,
        "repeat": repeat,
        "max_candidates": max_candidates,
    }
    rows = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            pilot = (
                zero_pilot if strength == 0 else
                robust._pilot_embed(reference, strength=strength)
            )
            try:
                marked = robust._feedback_embed(pilot, packet)
            except ValueError as exc:
                rows.extend({
                    **base, "pilot_strength": strength, "scale": scale,
                    "status": "SKIP:" + str(exc),
                } for scale in scales)
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
                row = {
                    **base,
                    "pilot_strength": strength,
                    "effective_pilot_strength": round(
                        effective_strength(reference, strength), 6
                    ),
                    "scale": scale,
                    "observed_width_scale": round(
                        received.width / marked.width, 8
                    ),
                    "received_width": received.width,
                    "received_height": received.height,
                    "status": "OK",
                    "blind_attempts": None,
                    "blind_decoded_size": None,
                    "extended_blind_status": "NOT_RUN",
                    "extended_blind_attempts": None,
                    "extended_blind_decoded_size": None,
                    "oracle": decode_known_at_size(
                        received, marked.size, payload
                    ),
                    "marked_psnr_db": metrics["psnr_db"],
                    "marked_ssim_y": metrics["ssim_y"],
                }
                standard_peaks = robust._peaks(received)
                standard = list(robust.candidate_sizes_priority50(
                    received, max_candidates=max_candidates
                ))
                extended_peaks = robust._peaks(
                    received, low=0.45, high=1.02
                )
                extended = priority_candidates_from_peaks(
                    received.size, extended_peaks, max_candidates
                )
                srank, sdist = rank_and_distance(standard, marked.size)
                erank, edist = rank_and_distance(extended, marked.size)
                sscale, sscore = peak_summary(standard_peaks)
                escale, escore = peak_summary(extended_peaks)
                row.update({
                    "standard_best_scale": sscale,
                    "standard_best_score": sscore,
                    "standard_candidate_count": len(standard),
                    "standard_true_size_rank": srank,
                    "standard_nearest_size_distance_px": sdist,
                    "extended_best_scale": escale,
                    "extended_best_score": escore,
                    "extended_candidate_count": len(extended),
                    "extended_true_size_rank": erank,
                    "extended_nearest_size_distance_px": edist,
                })
                if run_extended_blind:
                    (
                        row["extended_blind_status"],
                        row["extended_blind_attempts"],
                        row["extended_blind_decoded_size"],
                    ) = decode_from_candidates(received, extended, payload)
                if run_blind:
                    try:
                        result = robust.decode(
                            received, max_candidates=max_candidates
                        )
                        row["blind_status"] = (
                            "PASS" if result.payload == payload
                            else "FAIL:payload_mismatch"
                        )
                        row["blind_attempts"] = result.attempts
                        row["blind_decoded_size"] = (
                            f"{result.original_size[0]}x{result.original_size[1]}"
                        )
                    except ValueError as exc:
                        row["blind_status"] = "FAIL:" + type(exc).__name__
                else:
                    row["blind_status"] = "NOT_RUN"
                row["seconds"] = round(time.perf_counter() - started, 2)
                rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[],
                        help="Exact source filename; repeat to override defaults")
    parser.add_argument("--pilot-strengths", default="0,0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--max-candidates", type=int, default=160)
    parser.add_argument(
        "--blind", action="store_true",
        help="Also run slow unchanged production blind decode for every row",
    )
    parser.add_argument(
        "--extended-blind", action="store_true",
        help="Also decode using widened Fourier candidate list; research only",
    )
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep",
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        if not math.isfinite(args.delta) or not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be finite and between 8 and 128")
        if args.repeat < 1 or args.repeat > 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and between 1 and 31")
        if not 1 <= args.max_candidates <= 1000:
            raise ValueError("--max-candidates must be between 1 and 1000")
        paths = image_paths(args.directory, args.name or list(DEFAULT_NAMES))
        if not paths:
            raise ValueError("No supported input images found")
        if args.csv.exists():
            raise ValueError(f"Refusing to overwrite existing CSV: {args.csv}")
        payload = args.message.encode("utf-8")
        pack(payload)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(paths)} covers × {len(strengths)} pilot strengths × "
        f"{len(scales)} scales = {len(paths)*len(strengths)*len(scales)} "
        f"diagnostic rows; DELTA={args.delta:g}, REPEAT={args.repeat}, "
        f"production blind decode={'ON' if args.blind else 'OFF'}, "
        f"extended blind decode={'ON' if args.extended_blind else 'OFF'}.",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            rows = probe(
                source, payload, strengths, scales, args.delta,
                args.repeat, args.max_candidates, args.blind,
                args.extended_blind,
            )
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{i}/{len(paths)}] {row['source']} "
                    f"pilot={row['pilot_strength']} scale={row['scale']} "
                    f"oracle={row.get('oracle', '-')} "
                    f"rank={row.get('standard_true_size_rank', '-')} "
                    f"extended_rank={row.get('extended_true_size_rank', '-')} "
                    f"blind={row.get('blind_status', '-')} "
                    f"extended_blind={row.get('extended_blind_status', '-')} "
                    f"status={row['status']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)
    print(
        "The extended search only ranks candidates; it does not decode or "
        "alter production. Exact size rank=None does not prove that nearby "
        "dimensions cannot decode. Oracle success does not prove blind "
        "recovery. Use --blind and --extended-blind only for small targeted "
        "follow-ups; extended decoding never changes production."
    )


if __name__ == "__main__":
    main()
