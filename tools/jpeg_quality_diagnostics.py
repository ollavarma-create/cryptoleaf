
#!/usr/bin/env python3
"""Measure JPEG header bit errors after GIMP recompression."""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.image_decoder import _extract_block_raw_bits
from src.jpeg_interleave import deinterleave3
from src.error_correction import hamming_decode

TEST_DIR = Path("/home/jari/Pictures/Pakkaustesti")
QUALITIES = (95, 85, 75, 60, 50, 40)
HEADER_BLOCKS = 1344


def extract_header(path):
    with Image.open(path) as img:
        bits = _extract_block_raw_bits(img)
    return bits[:HEADER_BLOCKS]


def differences(a, b):
    return sum(x != y for x, y in zip(a, b))


def decoded_header(raw):
    voted = deinterleave3(raw)
    return hamming_decode(voted)


def analyze(original, modified):
    a = extract_header(original)
    b = extract_header(modified)

    if len(a) != HEADER_BLOCKS or len(b) != HEADER_BLOCKS:
        raise ValueError("JPEG image is too small for the header")

    n = HEADER_BLOCKS // 3

    copy_errors = [
        differences(a[i*n:(i+1)*n], b[i*n:(i+1)*n])
        for i in range(3)
    ]

    raw_errors = differences(a, b)

    voted_a = deinterleave3(a)
    voted_b = deinterleave3(b)
    voted_errors = differences(voted_a, voted_b)

    decoded_a = decoded_header(a)
    decoded_b = decoded_header(b)
    decoded_errors = differences(decoded_a, decoded_b)

    return raw_errors, copy_errors, voted_errors, decoded_errors


def main():
    if not TEST_DIR.is_dir():
        raise SystemExit(f"Directory not found: {TEST_DIR}")

    originals = sorted(
        p for p in TEST_DIR.glob("*_cryptoleaf.jpg")
        if p.is_file()
    )

    if not originals:
        raise SystemExit("No original Cryptoleaf JPEG images found")

    print(f"Test directory: {TEST_DIR}")
    print(f"Original images: {len(originals)}")

    for original in originals:
        print(f"\n{original.name}")
        print("-" * 100)
        print(
            f"{'Q':>3} {'Raw':>7} {'Raw %':>8} "
            f"{'Copy 1':>8} {'Copy 2':>8} {'Copy 3':>8} "
            f"{'Voted':>8} {'Decoded':>9}"
        )

        stem = original.stem

        for quality in QUALITIES:
            modified = TEST_DIR / f"{stem}_q{quality}.jpg"

            if not modified.exists():
                print(f"{quality:>3}  MISSING")
                continue

            try:
                raw, copies, voted, decoded = analyze(
                    original, modified
                )
                print(
                    f"{quality:>3} {raw:>7} "
                    f"{raw / HEADER_BLOCKS * 100:>7.2f}% "
                    f"{copies[0]:>8} {copies[1]:>8} "
                    f"{copies[2]:>8} {voted:>8} "
                    f"{decoded:>9}"
                )
            except Exception as exc:
                print(f"{quality:>3}  ERROR: {exc}")


if __name__ == "__main__":
    main()
