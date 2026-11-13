
from pathlib import Path
from io import BytesIO
import sys

import numpy as np
from PIL import Image

from src.image_encoder import (
    _bits_from_bytes,
    _embed_block_luminance,
)
from src.image_decoder import (
    _extract_block_raw_bits,
    _bits_to_bytes,
)
from src.error_correction import hamming_encode, hamming_decode
from src.jpeg_v03 import build_header, parse_header


cover = Path(sys.argv[1])
strength = int(sys.argv[2]) if len(sys.argv) > 2 else 50

header = build_header(141)
original_bits = _bits_from_bytes(header)
hamming_bits = hamming_encode(original_bits)

# Three separate copies instead of adjacent triplets.
interleaved_bits = hamming_bits * 3
n = len(hamming_bits)

with Image.open(cover) as img:
    rgb = img.convert("RGB")

ycbcr = np.array(rgb.convert("YCbCr"), dtype=np.uint8)
_embed_block_luminance(ycbcr, interleaved_bits, strength)

stego = Image.fromarray(ycbcr, mode="YCbCr").convert("RGB")

buffer = BytesIO()
stego.save(buffer, format="JPEG", quality=85)
stego.close()
buffer.seek(0)

with Image.open(buffer) as jpeg:
    extracted = _extract_block_raw_bits(jpeg)[:3*n]

# Reconstruct each Hamming bit using separated copies.
voted = [
    int(extracted[i] + extracted[i+n] + extracted[i+2*n] >= 2)
    for i in range(n)
]

decoded_bits = hamming_decode(voted)
decoded_header = _bits_to_bytes(decoded_bits)

errors = sum(
    (a ^ b).bit_count()
    for a, b in zip(header, decoded_header)
)

print(f"Strength: {strength}")
print(f"Header bit errors: {errors}")

try:
    parsed_length = parse_header(decoded_header)
    print(f"CRC OK — payload length: {parsed_length}")
except ValueError as exc:
    print(f"CRC FAILED: {exc}")
