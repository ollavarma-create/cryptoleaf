#!/usr/bin/env python3
"""Research-only JPEG-after-resize blind QIM-grid experiment with paired controls.

For each source, create the same marked and unmarked reference dimensions.
Apply LANCZOS resize THEN JPEG recompression (4:2:0) to both arms.
The marked arm runs the frozen blind LL2-grid ranker and actual packet
decoder, followed by a separate known-size oracle diagnostic.
The unmarked arm uses the same ranker and flags ANY CRC-validated
packet, regardless of payload. Neither arm uses original dimensions
in the candidate generator. This is NOT a real social-media pipeline.

CSV is append-as-you-go but refuses to overwrite an existing file.
Input files are never modified. This tool does not change the codec.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_batch_matrix import image_paths
from tools.robust_blind_sync_probe import (
    parse_scales, parse_strengths,
)
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_pilot_sweep import (
    decode_known_at_size, effective_strength, reference_image,
)
from tools import robust_qim_blind_grid_sweep as sweep
from tools import robust_qim_blind_grid_negative_control as neg


def parse_qualities(value: str) -> list[int]:
    try:
        result = list(dict.fromkeys(
            int(part.strip()) for part in value.split(",")
        ))
    except ValueError as exc:
        raise ValueError("JPEG qualities must be comma-separated integers") from exc
    if not result or any(q < 1 or q > 100 for q in result):
        raise ValueError("JPEG qualities must be integers from 1 to 100")
    return result


def jpeg_roundtrip_420(image: Image.Image, quality: int) -> Image.Image:
    """Recompress with explicit 4:2:0 chroma subsampling."""
    if not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be 1..100")
    buffer = BytesIO()
    image.convert("RGB").save(
        buffer, format="JPEG", quality=quality, subsampling=2
    )
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        return decoded.convert("RGB")


def columns() -> list[str]:
    return [
        "source", "source_sha256", "arm",
        "pilot_strength", "effective_pilot_strength", "adaptive_pilot",
        "resize_scale", "jpeg_quality", "jpeg_subsampling",
        "transform_order", "delta", "repeat",
        "encoded_width", "encoded_height",
        "received_width", "received_height",
        "min_scale", "height_jitter", "top_grids",
        "status", "oracle", "candidate_count", "grid_count",
        "refined_count", "coarse_true_grid_rank",
        "coarse_true_grid_score", "coarse_best_wrong_grid_score",
        "true_grid_shortlisted", "refined_exact_rank",
        "refined_true_score", "coarse_max_header_score",
        "refined_max_header_score", "bank_seconds",
        "coarse_seconds", "refine_seconds", "decode_budget",
        "decode_status", "decode_attempts", "decoded_size",
        "any_valid_packet", "decoded_payload_length",
        "decode_seconds",
    ]


def probe(
    source: Path, payload: bytes,
    strengths: list[float], scales: list[float],
    qualities: list[int], min_scale: float = 0.5,
    height_jitter: int = 2, top_grids: int = 5,
    delta: float = 38.0, repeat: int = 13,
    decode_budget: int = 40,
) -> list[dict]:
    """Returns paired MARKED/UNMARKED rows for every transform."""
    with Image.open(source) as opened:
        reference = reference_image(opened)
    packet = pack(payload)
    base = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "adaptive_pilot": robust.ADAPTIVE_PILOT,
        "delta": delta, "repeat": repeat,
        "encoded_width": reference.width,
        "encoded_height": reference.height,
        "min_scale": min_scale,
        "height_jitter": height_jitter,
        "top_grids": top_grids,
        "jpeg_subsampling": "4:2:0",
        "transform_order": "resize_then_jpeg",
        "decode_budget": decode_budget,
    }
    rows: list[dict] = []
    with codec_parameters(delta, repeat):
        for strength in strengths:
            marked = robust._feedback_embed(
                robust._pilot_embed(reference, strength=strength),
                packet,
            )
            for scale in scales:
                size = tuple(
                    max(32, round(d * scale)) for d in reference.size
                )
                resized_marked = marked.resize(
                    size, Image.Resampling.LANCZOS
                )
                resized_unmarked = reference.resize(
                    size, Image.Resampling.LANCZOS
                )
                for quality in qualities:
                    received_marked = jpeg_roundtrip_420(
                        resized_marked, quality
                    )
                    received_unmarked = jpeg_roundtrip_420(
                        resized_unmarked, quality
                    )
                    common = {
                        **base,
                        "pilot_strength": strength,
                        "effective_pilot_strength": round(
                            effective_strength(reference, strength), 6
                        ),
                        "resize_scale": scale,
                        "jpeg_quality": quality,
                        "received_width": size[0],
                        "received_height": size[1],
                        "status": "OK",
                    }

                    marked_result = sweep.evaluate(
                        received_marked, marked.size, payload,
                        min_scale, height_jitter, top_grids,
                        delta, repeat, decode_budget,
                    )
                    marked_oracle = decode_known_at_size(
                        received_marked, marked.size, payload
                    )
                    rows.append({
                        **common,
                        "arm": "MARKED",
                        "oracle": marked_oracle,
                        "candidate_count": marked_result["candidate_count"],
                        "grid_count": marked_result["grid_count"],
                        "refined_count": marked_result["refined_count"],
                        "coarse_true_grid_rank": marked_result["coarse_true_grid_rank"],
                        "coarse_true_grid_score": marked_result["coarse_true_grid_score"],
                        "coarse_best_wrong_grid_score": marked_result["coarse_best_wrong_grid_score"],
                        "true_grid_shortlisted": marked_result["true_grid_shortlisted"],
                        "refined_exact_rank": marked_result["refined_exact_rank"],
                        "refined_true_score": marked_result["refined_true_score"],
                        "coarse_max_header_score": (
                            marked_result["coarse"][0][1]
                            if "coarse" in marked_result else None
                        ),
                        "refined_max_header_score": marked_result["refined_best_score"],
                        "bank_seconds": marked_result["bank_seconds"],
                        "coarse_seconds": marked_result["coarse_seconds"],
                        "refine_seconds": marked_result["refine_seconds"],
                        "decode_status": marked_result["blind_status"],
                        "decode_attempts": marked_result["blind_attempts"],
                        "decoded_size": marked_result["blind_decoded_size"],
                        "any_valid_packet": None,
                        "decoded_payload_length": None,
                        "decode_seconds": marked_result["blind_seconds"],
                    })

                    control = neg.evaluate(
                        received_unmarked, min_scale,
                        height_jitter, top_grids,
                        delta, repeat, decode_budget,
                    )
                    rows.append({
                        **common,
                        "arm": "UNMARKED",
                        "oracle": "NOT_APPLICABLE",
                        "candidate_count": control["candidate_count"],
                        "grid_count": control["grid_count"],
                        "refined_count": control["refined_count"],
                        "coarse_true_grid_rank": None,
                        "coarse_true_grid_score": None,
                        "coarse_best_wrong_grid_score": None,
                        "true_grid_shortlisted": None,
                        "refined_exact_rank": None,
                        "refined_true_score": None,
                        "coarse_max_header_score": control["coarse_max_header_score"],
                        "refined_max_header_score": control["refined_max_header_score"],
                        "bank_seconds": control["bank_seconds"],
                        "coarse_seconds": control["coarse_seconds"],
                        "refine_seconds": control["refine_seconds"],
                        "decode_status": control["decode_status"],
                        "decode_attempts": control["decode_attempts"],
                        "decoded_size": control["decoded_size"],
                        "any_valid_packet": control["any_valid_packet"],
                        "decoded_payload_length": control["decoded_payload_length"],
                        "decode_seconds": control["decode_seconds"],
                    })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--pilot-strengths", default="0.12")
    parser.add_argument("--scales", default="0.55,0.68,0.83")
    parser.add_argument("--jpeg-qualities", default="85,70")
    parser.add_argument("--min-scale", type=float, default=0.5)
    parser.add_argument("--height-jitter", type=int, default=2)
    parser.add_argument("--top-grids", type=int, default=5)
    parser.add_argument("--delta", type=float, default=38.0)
    parser.add_argument("--repeat", type=int, default=13)
    parser.add_argument("--decode-budget", type=int, default=40)
    parser.add_argument(
        "--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep"
    )
    args = parser.parse_args()
    try:
        strengths = parse_strengths(args.pilot_strengths)
        scales = parse_scales(args.scales)
        qualities = parse_qualities(args.jpeg_qualities)
        if not strengths or any(not 0 < x <= 0.5 for x in strengths):
            raise ValueError("Pilot strengths must be in (0, 0.5]")
        if not 8 <= args.delta <= 128:
            raise ValueError("DELTA must be 8..128")
        if not 1 <= args.repeat <= 31 or args.repeat % 2 == 0:
            raise ValueError("REPEAT must be odd and 1..31")
        if not 1 <= args.top_grids <= 20:
            raise ValueError("top_grids must be in 1..20")
        if not 1 <= args.decode_budget <= 200:
            raise ValueError("decode-budget must be in 1..200")
        # Validate the public search geometry before any expensive work.
        sweep.blind_grid_bank(
            (64, 64), args.min_scale, args.height_jitter
        )
        if args.csv.exists():
            raise ValueError("Refusing to overwrite CSV: " + str(args.csv))
        sources = image_paths(args.directory, args.name or None)
        if not sources:
            raise ValueError("No PNG/JPEG source images found")
        pack(args.message.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"JPEG-after-resize paired test: {len(sources)} sources x "
        f"{len(strengths)} strengths x {len(scales)} scales x "
        f"{len(qualities)} qualities x 2 arms; "
        f"4:2:0, blind budget {args.decode_budget}",
        flush=True,
    )
    with args.csv.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns())
        writer.writeheader()
        for index, source in enumerate(sources, 1):
            try:
                rows = probe(
                    source, args.message.encode("utf-8"),
                    strengths, scales, qualities,
                    args.min_scale, args.height_jitter,
                    args.top_grids, args.delta,
                    args.repeat, args.decode_budget,
                )
            except ValueError as exc:
                print(f"[{index}/{len(sources)}] SKIP {source.name}: {exc}",
                      flush=True)
                continue
            for row in rows:
                writer.writerow(row)
                print(
                    f"[{index}/{len(sources)}] {row['source']} "
                    f"scale={row['resize_scale']} "
                    f"JPEG={row['jpeg_quality']} "
                    f"{row['arm']} oracle={row['oracle']} "
                    f"decode={row['decode_status']} "
                    f"grid_rank={row['coarse_true_grid_rank']}",
                    flush=True,
                )
            handle.flush()
    print("CSV:", args.csv)


if __name__ == "__main__":
    main()
