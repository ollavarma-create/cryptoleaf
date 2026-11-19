#!/usr/bin/env python3
"""Diagnose Fourier pilot visibility against the SAME cover's own spectrum.

Research only; no production codec changes. Each cover, pilot strength and
resize is evaluated in four matched arms:

  cover_only: YCbCr-roundtripped source, no pilot and no DWT payload
  dwt_only:   same cover + DWT payload, no Fourier pilot
  pilot_only: same cover + Fourier pilot, no DWT payload
  pilot_dwt:  same cover + Fourier pilot + DWT payload

All four arms are resized with identical LANCZOS geometry. Compare the
known-scale normalized Fourier correlation scores, local peak ranks and
score differences. The cover-only and DWT-only arms are NEGATIVE CONTROLS.
True encoded size is used ONLY to label and evaluate these diagnostics;
a blind decoder cannot use an unmarked reference or known scale.

The score is a normalized correlation, so a difference between two arms
is not a linear estimate of Fourier pilot amplitude. Do not equate a
positive difference with a proven reliable pilot detector. The four-arm
comparison isolates hypotheses for later blind validation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, parse_scales, parse_strengths,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_spectral_ablation import (
    nearest_peak_diagnostic, score_spectrum, select_peaks,
)
from tools.robust_pilot_sweep import effective_strength, reference_image


ARMS = ("cover_only", "dwt_only", "pilot_only", "pilot_dwt")


def spectrum_diagnostic(image: Image.Image, true_scale: float) -> dict:
    """Return measured score/peak rank; never select a size using true_scale."""
    profile = robust._profile(image)
    scales, scores = score_spectrum(profile, 0.38, False)
    peaks = select_peaks(scales, scores, max_peaks=len(scales))
    local_rank, distance = nearest_peak_diagnostic(peaks, true_scale)
    true_score = float(np.interp(true_scale, scales, scores))
    return {
        "true_score": round(true_score, 8),
        "score_percentile": round(
            100.0 * float(np.mean(scores <= true_score)), 4
        ),
        "true_scale_local_peak_rank": local_rank,
        "nearest_local_peak_distance": distance,
        "best_peak_scale": round(peaks[0][0], 6) if peaks else None,
        "best_peak_score": round(peaks[0][1], 8) if peaks else None,
    }


def columns() -> list[str]:
    base = [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "actual_width_scale", "pilot_strength", "effective_pilot_strength",
        "delta", "repeat", "status",
    ]
    suffixes = (
        "true_score", "score_percentile",
        "true_scale_local_peak_rank", "nearest_local_peak_distance",
        "best_peak_scale", "best_peak_score",
    )
    for arm in ARMS:
        base.extend(f"{arm}_{suffix}" for suffix in suffixes)
    base.extend([
        "pilot_lift_without_dwt", "pilot_lift_with_dwt",
        "dwt_effect_without_pilot", "dwt_effect_with_pilot",
    ])
    return base


def probe(
    source: Path,
    payload: bytes,
    strengths: list[float],
    scales: list[float],
    delta: float = 38.0,
    repeat: int = 13,
) -> list[dict]:
    if not strengths or any(strength <= 0 for strength in strengths):
        raise ValueError("Pilot strengths must be strictly positive")
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
    }
    rows: list[dict] = []
    with codec_parameters(delta, repeat):
        # A consistent YCbCr round trip matches the zero-pilot control
        # used in the previous spectral and cascade experiments.
        cover = reference.convert("YCbCr").convert("RGB")
        dwt = robust._feedback_embed(cover, packet)
        for strength in strengths:
            if strength <= 0:
                raise ValueError(
                    "Pilot strength must be positive; cover_only/dwt_only "
                    "are already zero-pilot controls"
                )
            pilot = robust._pilot_embed(reference, strength=strength)
            pilot_dwt = robust._feedback_embed(pilot, packet)
            arms = {
                "cover_only": cover,
                "dwt_only": dwt,
                "pilot_only": pilot,
                "pilot_dwt": pilot_dwt,
            }
            for scale in scales:
                size = tuple(max(32, round(d * scale)) for d in cover.size)
                actual_scale = size[0] / cover.width
                diagnostics = {
                    arm: spectrum_diagnostic(
                        image.resize(size, Image.Resampling.LANCZOS),
                        actual_scale,
                    )
                    for arm, image in arms.items()
                }
                row = {
                    **base,
                    "received_width": size[0],
                    "received_height": size[1],
                    "resize_scale": scale,
                    "actual_width_scale": round(actual_scale, 8),
                    "pilot_strength": strength,
                    "effective_pilot_strength": round(
                        effective_strength(reference, strength), 6
                    ),
                    "status": "OK",
                }
                for arm, values in diagnostics.items():
                    row.update({
                        f"{arm}_{key}": value
                        for key, value in values.items()
                    })
                score = {
                    arm: diagnostics[arm]["true_score"] for arm in ARMS
                }
                row.update({
                    "pilot_lift_without_dwt": round(
                        score["pilot_only"] - score["cover_only"], 8
                    ),
                    "pilot_lift_with_dwt": round(
                        score["pilot_dwt"] - score["dwt_only"], 8
                    ),
                    "dwt_effect_without_pilot": round(
                        score["dwt_only"] - score["cover_only"], 8
                    ),
                    "dwt_effect_with_pilot": round(
                        score["pilot_dwt"] - score["pilot_only"], 8
                    ),
                })
                rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument(
        "--name", action="append", default=[],
        help="Exact source filename, repeatable; defaults to five covers",
    )
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        if not strengths or any(strength <= 0 for strength in strengths):
            raise ValueError("Specify strictly positive pilot strengths")
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
        f"{len(paths)*len(strengths)*len(scales)} four-arm comparisons",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for i, source in enumerate(paths, 1):
            try:
                rows = probe(source, payload, strengths, scales)
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
                    f"resize={row['resize_scale']} "
                    f"lift(no-DWT)={row['pilot_lift_without_dwt']:+.4f} "
                    f"lift(DWT)={row['pilot_lift_with_dwt']:+.4f} "
                    f"peak-rank={row['pilot_dwt_true_scale_local_peak_rank']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
