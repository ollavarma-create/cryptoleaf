#!/usr/bin/env python3
"""Research-only angular-masked Fourier synchronization ablation.

Hypothesis: UI screenshots contain strong axis-aligned edges whose FFT
energy masks the isotropic radial pilot. Exclude selected narrow angular
wedges around the horizontal/vertical Fourier axes BEFORE radial
averaging, leaving the original pilot and DWT payload unchanged.

For each detector variant, measure both pilot+DWT and DWT-only negative
control using exactly the same received size. Record true-scale score,
local peak rank and a fixed two-stage candidate list's LL2-grid hit.
The known scale/size is ONLY used for post-hoc diagnostics and oracle.
Optional --blind performs actual packet decoding using the detector's
candidates; it can be expensive. No production codec is modified.
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
from scipy.ndimage import gaussian_filter1d

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    DEFAULT_NAMES, parse_scales, parse_strengths,
    priority_candidates_from_peaks, decode_from_candidates,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_spectral_ablation import (
    nearest_peak_diagnostic, score_spectrum, select_peaks,
    first_safe_grid_rank,
)
from tools.robust_pilot_sweep import (
    reference_image, effective_strength, decode_known_at_size,
)


DEFAULT_ANGLES = (0.0, 5.0, 10.0, 20.0)
DEFAULT_FREQS = (0.38, 0.48)
STAGES = ((4, 10), (16, 10))
MAX_CANDIDATES = 160


def parse_angles(value: str) -> list[float]:
    try:
        values = [float(x.strip()) for x in value.split(",")]
    except ValueError as exc:
        raise ValueError("Angles must be comma-separated degrees") from exc
    if not values or any(not np.isfinite(v) or not 0 <= v < 45 for v in values):
        raise ValueError("Axis exclusion angles must be 0 <= degrees < 45")
    return list(dict.fromkeys(values))


def parse_freqs(value: str) -> list[float]:
    try:
        values = [float(x.strip()) for x in value.split(",")]
    except ValueError as exc:
        raise ValueError("Frequencies must be comma-separated numbers") from exc
    if not values or any(not np.isfinite(v) or not 0.25 <= v <= 0.50 for v in values):
        raise ValueError("Maximum profile frequencies must be 0.25..0.50")
    return list(dict.fromkeys(values))


def fft_workspace(image: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """FFT radial magnitude and angle, matching robust._profile preprocessing."""
    y = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = y.shape
    window = np.hanning(h)[:, None] * np.hanning(w)[None, :]
    fft = np.fft.rfft2((y - y.mean()) * window)
    magnitude = np.log1p(np.abs(fft)).astype(np.float32)
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    radius = np.hypot(fy, fx)
    angle = np.rad2deg(np.arctan2(np.abs(fy), fx))
    return radius, angle, magnitude


def masked_profile(
    workspace: tuple[np.ndarray, np.ndarray, np.ndarray],
    max_freq: float, axis_exclusion_deg: float,
) -> np.ndarray:
    """Exclude dominant axis directions before radial bin averaging.

    At 0 degrees, this reproduces robust._profile for the same max_freq
    and bin count, including Gaussian baseline subtraction.
    """
    if not 0.25 <= max_freq <= 0.50:
        raise ValueError("max_freq must be 0.25..0.50")
    if not 0 <= axis_exclusion_deg < 45:
        raise ValueError("axis_exclusion_deg must be 0..45 (exclusive)")
    radius, angle, magnitude = workspace
    bins = round(1800 * max_freq / 0.38)
    idx = np.floor(radius / max_freq * bins).astype(np.int32)
    good = idx < bins
    if axis_exclusion_deg > 0:
        good &= (
            (angle >= axis_exclusion_deg)
            & (angle <= 90.0 - axis_exclusion_deg)
        )
    sums = np.bincount(
        idx[good].ravel(),
        weights=magnitude[good].ravel(),
        minlength=bins,
    )
    counts = np.bincount(idx[good].ravel(), minlength=bins)
    profile = sums / np.maximum(counts, 1)
    return profile - gaussian_filter1d(profile, sigma=13)


def detect(
    workspace: tuple[np.ndarray, np.ndarray, np.ndarray],
    max_freq: float, axis_exclusion_deg: float,
    true_scale: float,
) -> tuple[dict, list[tuple[float, float]]]:
    profile = masked_profile(workspace, max_freq, axis_exclusion_deg)
    scales, scores = score_spectrum(profile, max_freq, False)
    all_peaks = select_peaks(scales, scores, max_peaks=len(scales))
    local_rank, local_distance = nearest_peak_diagnostic(
        all_peaks, true_scale
    )
    true_score = float(np.interp(true_scale, scales, scores))
    return {
        "true_scale_score": round(true_score, 8),
        "true_scale_percentile": round(
            100 * float(np.mean(scores <= true_score)), 4
        ),
        "true_scale_peak_rank": local_rank,
        "true_scale_peak_distance": local_distance,
        "best_peak_scale": all_peaks[0][0] if all_peaks else None,
        "best_peak_score": all_peaks[0][1] if all_peaks else None,
    }, all_peaks


def staged_candidates(
    received_size: tuple[int, int],
    peaks: list[tuple[float, float]],
    limit: int = MAX_CANDIDATES,
) -> list[tuple[int, int]]:
    """Exact pixel-size union/order of the measured 4:10,16:10 cascade."""
    seen: set[tuple[int, int]] = set()
    result = []
    for count, quota in STAGES:
        candidates = priority_candidates_from_peaks(
            received_size, peaks[:count], limit, first_peak_quota=quota,
        )
        for size in candidates:
            if size not in seen:
                seen.add(size)
                result.append(size)
    return result


def columns() -> list[str]:
    return [
        "source", "source_sha256", "encoded_width", "encoded_height",
        "received_width", "received_height", "resize_scale",
        "actual_width_scale", "pilot_strength", "effective_pilot_strength",
        "delta", "repeat", "oracle", "status", "profile_max_freq",
        "axis_exclusion_deg", "candidate_limit_per_stage",
        "candidate_count", "safe_ll2_grid_rank",
        "pilot_true_scale_score", "pilot_true_scale_percentile",
        "pilot_true_scale_peak_rank", "pilot_true_scale_peak_distance",
        "pilot_best_peak_scale", "pilot_best_peak_score",
        "control_true_scale_score", "control_true_scale_percentile",
        "control_true_scale_peak_rank", "control_true_scale_peak_distance",
        "control_best_peak_scale", "control_best_peak_score",
        "pilot_score_lift_vs_dwt_only",
        "blind_status", "blind_attempts", "blind_decoded_size",
    ]


def probe(
    source: Path, payload: bytes, strengths: list[float],
    scales: list[float], angles: list[float] | None = None,
    freqs: list[float] | None = None,
    delta: float = 38.0, repeat: int = 13,
    run_blind: bool = False,
) -> list[dict]:
    if angles is None:
        angles = list(DEFAULT_ANGLES)
    if freqs is None:
        freqs = list(DEFAULT_FREQS)
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
        "candidate_limit_per_stage": MAX_CANDIDATES,
    }
    rows = []
    with codec_parameters(delta, repeat):
        cover = reference.convert("YCbCr").convert("RGB")
        dwt_only = robust._feedback_embed(cover, packet)
        for strength in strengths:
            if strength <= 0:
                raise ValueError("Pilot strengths must be positive")
            marked = robust._feedback_embed(
                robust._pilot_embed(reference, strength=strength),
                packet,
            )
            for scale in scales:
                size = tuple(max(32, round(d * scale)) for d in marked.size)
                actual_scale = size[0] / marked.width
                received = marked.resize(size, Image.Resampling.LANCZOS)
                control = dwt_only.resize(size, Image.Resampling.LANCZOS)
                oracle = decode_known_at_size(received, marked.size, payload)
                marked_fft = fft_workspace(received)
                control_fft = fft_workspace(control)
                for freq in freqs:
                    for angle in angles:
                        pilot, peaks = detect(
                            marked_fft, freq, angle, actual_scale
                        )
                        negative, _ = detect(
                            control_fft, freq, angle, actual_scale
                        )
                        candidates = staged_candidates(received.size, peaks)
                        grid_rank, _ = first_safe_grid_rank(
                            candidates, marked.size
                        )
                        if run_blind:
                            blind_status, attempts, decoded = (
                                decode_from_candidates(
                                    received, candidates, payload
                                )
                            )
                        else:
                            blind_status, attempts, decoded = (
                                "NOT_RUN", None, None
                            )
                        row = {
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
                            "profile_max_freq": freq,
                            "axis_exclusion_deg": angle,
                            "candidate_count": len(candidates),
                            "safe_ll2_grid_rank": grid_rank,
                            "pilot_score_lift_vs_dwt_only": round(
                                pilot["true_scale_score"]
                                - negative["true_scale_score"], 8
                            ),
                            "blind_status": blind_status,
                            "blind_attempts": attempts,
                            "blind_decoded_size": decoded,
                        }
                        for prefix, data in (("pilot", pilot), ("control", negative)):
                            for key, value in data.items():
                                row[f"{prefix}_{key}"] = value
                        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12,0.18")
    parser.add_argument("--scales", default="0.75,0.5")
    parser.add_argument("--axis-exclusions", default="0,5,10,20")
    parser.add_argument("--profile-max-freqs", default="0.38,0.48")
    parser.add_argument(
        "--blind", action="store_true",
        help="Actually decode each candidate list; use narrow filters",
    )
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        angles = parse_angles(args.axis_exclusions)
        freqs = parse_freqs(args.profile_max_freqs)
        if not strengths or any(s <= 0 for s in strengths):
            raise ValueError("Pilot strengths must be strictly positive")
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
        f"{len(scales)} resizes × {len(freqs)} profile cutoffs × "
        f"{len(angles)} angular masks = "
        f"{len(paths)*len(strengths)*len(scales)*len(freqs)*len(angles)} "
        f"candidate-rank tests; blind={'ON' if args.blind else 'OFF'}",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for index, source in enumerate(paths, 1):
            try:
                rows = probe(
                    source, payload, strengths, scales, angles, freqs,
                    args.delta, args.repeat, args.blind,
                )
            except ValueError as exc:
                print(f"[{index}/{len(paths)}] {source.name}: SKIP: {exc}", flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{index}/{len(paths)}] {row['source']} "
                    f"pilot={row['pilot_strength']} "
                    f"scale={row['resize_scale']} "
                    f"cutoff={row['profile_max_freq']} "
                    f"axis={row['axis_exclusion_deg']} "
                    f"rank={row['pilot_true_scale_peak_rank']} "
                    f"grid={row['safe_ll2_grid_rank']} "
                    f"lift={row['pilot_score_lift_vs_dwt_only']:+.4f} "
                    f"blind={row['blind_status']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
