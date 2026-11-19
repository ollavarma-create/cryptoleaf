#!/usr/bin/env python3
"""Research-only paired adaptive vs fixed Fourier-pilot ablation.

Uses the SAME cover, payload, DWT parameters, received resize and blind
two-stage candidate search for both pilot-amplitude policies. Measures:
- actual oracle and blind packet recovery, with safe decoder attempts
- marked-image PSNR and luminance SSIM
- true-scale Fourier correlation and peak rank in four-arm controls

The true size/scale and cover-only negative controls are used ONLY for
diagnostics. They never enter blind candidate generation. Changing
ADAPTIVE_PILOT is scoped and restored, including on exceptions.
No production codec setting or source file is changed.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, parse_scales, parse_strengths,
)
from tools import robust_pilot_cascade_probe as cascade
from tools import robust_pilot_signal_probe as signal


MODES = ("adaptive", "fixed")
SPECTRAL_COLUMNS = (
    "pilot_only_true_score",
    "pilot_only_true_scale_local_peak_rank",
    "pilot_dwt_true_score",
    "pilot_dwt_score_percentile",
    "pilot_dwt_true_scale_local_peak_rank",
    "pilot_dwt_nearest_local_peak_distance",
    "pilot_lift_without_dwt",
    "pilot_lift_with_dwt",
    "dwt_effect_with_pilot",
)


def parse_modes(value: str) -> tuple[str, ...]:
    modes = tuple(part.strip() for part in value.split(","))
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError("Modes must be adaptive,fixed or a subset")
    if len(set(modes)) != len(modes):
        raise ValueError("Duplicate pilot modes are not allowed")
    return modes


@contextmanager
def pilot_mode(mode: str):
    if mode not in MODES:
        raise ValueError(f"Invalid pilot mode: {mode}")
    previous = robust.ADAPTIVE_PILOT
    robust.ADAPTIVE_PILOT = mode == "adaptive"
    try:
        yield
    finally:
        robust.ADAPTIVE_PILOT = previous


def columns() -> list[str]:
    return ["pilot_mode", *cascade.columns(), *SPECTRAL_COLUMNS]


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    modes: tuple[str, ...] = MODES,
    stages: tuple[tuple[int, int], ...] = cascade.DEFAULT_STAGES,
    delta: float = 38.0, repeat: int = 13,
    per_stage_candidates: int = 160,
) -> list[dict]:
    rows = []
    for mode in modes:
        with pilot_mode(mode):
            spectral = signal.probe(
                source, payload, strengths, scales, delta=delta, repeat=repeat,
            )
            blind = cascade.probe(
                source, payload, strengths, scales, stages=stages,
                delta=delta, repeat=repeat,
                per_stage_candidates=per_stage_candidates,
            )
        spectral_by_key = {
            (row["source"], row["pilot_strength"], row["resize_scale"]): row
            for row in spectral
        }
        if len(spectral_by_key) != len(spectral) or len(spectral) != len(blind):
            raise ValueError("Four-arm and blind test cases do not align")
        for result in blind:
            key = (
                result["source"], result["pilot_strength"],
                result["resize_scale"],
            )
            diagnostic = spectral_by_key.get(key)
            if diagnostic is None:
                raise ValueError(f"Missing four-arm diagnostic for {key}")
            rows.append({
                "pilot_mode": mode,
                **result,
                **{name: diagnostic[name] for name in SPECTRAL_COLUMNS},
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument(
        "--name", action="append", default=[],
        help="Exact source filename; repeatable; defaults to five covers",
    )
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--modes", default="adaptive,fixed")
    parser.add_argument("--stages", default="4:10,16:10")
    parser.add_argument("--max-candidates-per-stage", type=int, default=160)
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        modes = parse_modes(args.modes)
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        stages = cascade.parse_stages(args.stages)
        if not strengths or any(strength <= 0 for strength in strengths):
            raise ValueError("Pilot strengths must be strictly positive")
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
        f"{len(paths)} covers × {len(modes)} pilot modes × "
        f"{len(strengths)} strengths × {len(scales)} scales = "
        f"{len(paths)*len(modes)*len(strengths)*len(scales)} blind searches "
        "and matched four-arm diagnostics",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for index, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, payload, strengths, scales, modes, stages,
                    args.delta, args.repeat,
                    args.max_candidates_per_stage,
                )
            except ValueError as exc:
                print(
                    f"[{index}/{len(paths)}] {source.name}: SKIP: {exc}",
                    flush=True,
                )
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{index}/{len(paths)}] {row['source']} "
                    f"mode={row['pilot_mode']} "
                    f"pilot={row['pilot_strength']} "
                    f"resize={row['resize_scale']} "
                    f"effective={row['effective_pilot_strength']} "
                    f"oracle={row['oracle']} "
                    f"blind={row['blind_status']} "
                    f"stage={row['successful_stage']} "
                    f"attempts={row['blind_attempts']} "
                    f"PSNR={row['marked_psnr_db']} "
                    f"rank={row['pilot_dwt_true_scale_local_peak_rank']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
