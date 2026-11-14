
import sys
from pathlib import Path

from PIL import Image

from src.image_encoder import (
    _embed_prepared_v03,
    _bits_from_bytes,
    _replicate3,
)
from src.image_decoder import (
    _extract_block_raw_bits,
    _majority_vote,
    _bits_to_bytes,
)
from src.error_correction import hamming_encode, hamming_decode
from src.jpeg_v03 import build_header, prepare_payload


cover = Path(sys.argv[1])
strength = int(sys.argv[2]) if len(sys.argv) > 2 else 50

payload = b"Cryptoleaf JPEG header diagnostic"
password = "diagnostic-password"

rs_payload = prepare_payload(payload, password)
header = build_header(len(rs_payload))

expected_bits = _replicate3(
    hamming_encode(_bits_from_bytes(header))
)

stego = _embed_prepared_v03(
    cover, rs_payload, strength=strength
)

with Image.open(cover) as original:
    pass

from io import BytesIO

buffer = BytesIO()
stego.save(buffer, format="JPEG", quality=85)
stego.close()
buffer.seek(0)

with Image.open(buffer) as jpeg:
    actual_bits = _extract_block_raw_bits(jpeg)[
        :len(expected_bits)
    ]

raw_errors = sum(
    a != b for a, b in zip(expected_bits, actual_bits)
)

voted = _majority_vote(actual_bits)
decoded = _bits_to_bytes(hamming_decode(voted))

header_errors = sum(
    (a ^ b).bit_count()
    for a, b in zip(header, decoded)
)

print(f"Strength: {strength}")
print(f"Raw bit errors: {raw_errors}/{len(expected_bits)}")
print(f"Header bit errors after correction: {header_errors}")
print(f"Expected header: {header.hex()}")
print(f"Decoded header:  {decoded.hex()}")



print("\nRaw error positions:")
print([
    i for i, (a, b) in enumerate(
        zip(expected_bits, actual_bits)
    )
    if a != b
])

print("\nDecoded header error positions:")
expected_header_bits = _bits_from_bytes(header)
decoded_header_bits = _bits_from_bytes(decoded)

print([
    i for i, (a, b) in enumerate(
        zip(expected_header_bits, decoded_header_bits)
    )
    if a != b
])
