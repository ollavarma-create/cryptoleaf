
"""Automatic JPEG v0.3 embedding strength optimization."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from .image_encoder import _encode_image_block_v03
from .image_decoder import BadMagicError, _decode_image_block
from .error_correction import ReedSolomonError
from .image_quality import calculate_psnr
from .jpeg_v03 import prepare_payload
from .image_encoder import _embed_prepared_v03


DEFAULT_STRENGTHS = (10, 15, 20, 30, 40, 50, 60, 80)


@dataclass(frozen=True)
class OptimizationResult:
    strength: int
    quality: int
    attempts: int
    output_path: Path
    psnr: float


def optimize_jpeg(
    cover_path: str | Path,
    output_path: str | Path,
    payload: bytes,
    password: str,
    *,
    quality: int = 85,
    strengths: tuple[int, ...] = DEFAULT_STRENGTHS,
    mode: str = "first_success",
    
) -> OptimizationResult:
    """Find the first strength that survives JPEG compression."""

        
    cover_path = Path(cover_path)
    output_path = Path(output_path)

    
    if not password:
        raise ValueError("JPEG v0.3 requires a password")

    if not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")

    if not strengths or any(not 1 <= s <= 255 for s in strengths):
        raise ValueError("Invalid embedding strengths")

    if cover_path.resolve() == output_path.resolve():
        raise ValueError("Cover and output paths must differ")

    if mode not in {"first_success", "best_psnr"}:
        raise ValueError(f"Unknown optimization mode: {mode}")

    candidates = sorted(set(strengths))
    # Encrypt and RS-encode exactly once for all candidates.
    rs_payload = prepare_payload(payload, password)

    with Image.open(cover_path) as img:
        original_image = img.convert("RGB")

    best_psnr = float("-inf")
    best_strength = None    
    
    
    with TemporaryDirectory() as tmp:
        candidate_path = Path(tmp) / "candidate.jpg"

        for attempt, strength in enumerate(candidates, start=1):
            stego = _embed_prepared_v03(
                cover_path,
                rs_payload,
                strength=strength,
            )

            stego.save(
                candidate_path,
                format="JPEG",
                quality=quality,
            )
            stego.close()

            # Verify that the JPEG really contains recoverable data.
            try:
                with Image.open(candidate_path) as img:
                    recovered = _decode_image_block(img, password)

                if recovered != payload:
                    continue

            except (ValueError, BadMagicError, ReedSolomonError) as exc:
                print(
                f"Strength {strength}: "
                f"{type(exc).__name__}: {exc}"
                )
                continue

            # Measure quality from the actual JPEG file.
            with Image.open(candidate_path) as img:
                final_image = img.convert("RGB")

            psnr = calculate_psnr(original_image, final_image)
            print(
            f"DEBUG mode={mode}, strength={strength}, "
            f"psnr={psnr}, best_psnr={best_psnr}"
)

            if mode == "first_success":
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(candidate_path.read_bytes())

                return OptimizationResult(
                    strength=strength,
                    quality=quality,
                    attempts=attempt,
                    output_path=output_path,
                    psnr=psnr,
                )

            # Keep the successful candidate with the highest PSNR.
            if psnr > best_psnr:
                best_psnr = psnr
                best_strength = strength
                best_data = candidate_path.read_bytes()

        print(f"Strength {strength}: decoding OK")
        
        # The loop has finished: save the best candidate.
        if best_strength is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(best_data)

            return OptimizationResult(
                strength=best_strength,
                quality=quality,
                attempts=len(candidates),
                output_path=output_path,
                psnr=best_psnr,
            )

    raise ValueError(
        "No embedding strength survived JPEG compression"
    )         