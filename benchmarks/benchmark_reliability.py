
from pathlib import Path
from io import BytesIO
from collections import Counter
import csv
import sys
import time

from PIL import Image

from src.jpeg_v03 import prepare_payload
from src.image_encoder import _embed_prepared_v03
from src.image_decoder import _decode_image_block

cover = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_photo.jpg")

password = "benchmark-password"
message = b"Cryptoleaf JPEG v0.3 reliability test"

strengths = (10, 15, 20, 30)
repeats = 20
quality = 85

results = []

with Image.open(cover) as img:
    original = img.convert("RGB")

print(f"Image: {cover.name} ({original.width}x{original.height})")
print(f"JPEG quality: {quality}, repetitions: {repeats}")

for strength in strengths:
    successes = 0
    failures = Counter()
    started = time.perf_counter()

    for run in range(1, repeats + 1):
        prepared = prepare_payload(message, password)

        stego = _embed_prepared_v03(
            cover,
            prepared,
            strength=strength,
            cover_image=original,
        )

        buffer = BytesIO()
        stego.save(buffer, format="JPEG", quality=quality)
        stego.close()
        buffer.seek(0)

        try:
            with Image.open(buffer) as jpeg:
                recovered = _decode_image_block(jpeg, password)

            success = recovered == message

            if not success:
                failures["PayloadMismatch"] += 1

        except Exception as exc:
            success = False
            failures[type(exc).__name__] += 1

        successes += int(success)

        results.append({
            "image": cover.name,
            "strength": strength,
            "run": run,
            "success": success,
        })

    elapsed = time.perf_counter() - started
    rate = 100 * successes / repeats

    print(
        f"Strength {strength:>2}: "
        f"{successes:>2}/{repeats} OK "
        f"({rate:5.1f}%), "
        f"{elapsed:.1f} s"
    )

    if failures:
        print(f"  Failures: {dict(failures)}")

with open("jpeg_reliability.csv", "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=["image", "strength", "run", "success"]
    )
    writer.writeheader()
    writer.writerows(results)

print("\nResults saved to jpeg_reliability.csv")
