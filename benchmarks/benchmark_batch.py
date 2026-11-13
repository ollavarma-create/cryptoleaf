
import csv
import sys
import time
from collections import Counter
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from src.jpeg_v03 import prepare_payload
from src.image_encoder import _embed_prepared_v03, CapacityError
from src.image_decoder import _decode_image_block
from src.image_quality import calculate_psnr


folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("benchmark_images")
strengths = (10, 15, 20, 30)
repeats = 5
quality = 85
password = "benchmark-password"
message = b"Cryptoleaf JPEG v0.3 batch benchmark"

fields = [
    "image", "width", "height", "strength", "run",
    "success", "psnr", "error_type", "error_message",
    "elapsed_s",
]

images = sorted(
    p for p in folder.iterdir()
    if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")
)

if not images:
    sys.exit(f"No JPEG images found in {folder}")

print(f"Found {len(images)} images")

results = []

for index, path in enumerate(images, 1):
    print(f"\n[{index}/{len(images)}] {path.name}")
    counts = Counter()

    try:
        with Image.open(path) as img:
            original = img.convert("RGB")

        width, height = original.size
        print(f"  Resolution: {width}x{height}")

        # Prepare once to check capacity before running repetitions.
        sample = prepare_payload(message, password)
        required = (32 + len(sample)) * 42
        available = (width // 8) * max(0, height // 8 - 1)

        if required > available:
            print(f"  SKIP: capacity {available} < required {required}")
            results.append({
                "image": path.name,
                "width": width,
                "height": height,
                "strength": "",
                "run": "",
                "success": False,
                "psnr": "",
                "error_type": "CapacityError",
                "error_message": f"Requires {required}, available {available}",
                "elapsed_s": 0,
            })
            original.close()
            continue

        for strength in strengths:
            for run in range(1, repeats + 1):
                started = time.perf_counter()
                success = False
                psnr = ""
                error_type = ""
                error_message = ""

                try:
                    prepared = prepare_payload(message, password)

                    stego = _embed_prepared_v03(
                        path,
                        prepared,
                        strength=strength,
                        cover_image=original,
                    )

                    buffer = BytesIO()
                    stego.save(buffer, format="JPEG", quality=quality)
                    stego.close()
                    buffer.seek(0)

                    with Image.open(buffer) as jpeg:
                        recovered = _decode_image_block(jpeg, password)
                        final = jpeg.convert("RGB")

                    success = recovered == message
                    if not success:
                        error_type = "PayloadMismatch"
                        error_message = "Recovered payload differs"

                    psnr = round(calculate_psnr(original, final), 3)
                    final.close()

                except Exception as exc:
                    error_type = type(exc).__name__
                    error_message = str(exc)[:200]

                elapsed = time.perf_counter() - started
                counts[(strength, success)] += 1

                results.append({
                    "image": path.name,
                    "width": width,
                    "height": height,
                    "strength": strength,
                    "run": run,
                    "success": success,
                    "psnr": psnr,
                    "error_type": error_type,
                    "error_message": error_message,
                    "elapsed_s": round(elapsed, 3),
                })

            ok = counts[(strength, True)]
            print(f"  Strength {strength:>2}: {ok}/{repeats} OK")

        original.close()

    except (OSError, UnidentifiedImageError, ValueError) as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")

output = Path("benchmark_results.csv")
with output.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(results)

print(f"\nSaved {len(results)} results to {output}")
