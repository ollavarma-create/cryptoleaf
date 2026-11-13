
from pathlib import Path
from PIL import Image

from src.jpeg_v03 import prepare_payload
from src.image_encoder import _embed_prepared_v03
from src.image_decoder import _decode_image_block
from src.image_quality import calculate_psnr

cover = Path("test_photo.jpg")
password = "benchmark-password"
message = b"Cryptoleaf JPEG v0.3 benchmark"

strengths = (10, 15, 20, 30, 40, 50, 60, 80)
quality = 85

prepared = prepare_payload(message, password)

with Image.open(cover) as img:
    original = img.convert("RGB")

print(f"{'Strength':>8} {'Decode':>10} {'PSNR (dB)':>12}")
print("-" * 34)

for strength in strengths:
    stego = _embed_prepared_v03(
        cover,
        prepared,
        strength=strength,
        cover_image=original,
    )

    output = Path(f"/tmp/cryptoleaf_bench_{strength}.jpg")
    stego.save(output, format="JPEG", quality=quality)
    stego.close()

    with Image.open(output) as img:
        try:
            recovered = _decode_image_block(img, password)
            success = recovered == message
        except (ValueError, Exception):
            success = False

        final = img.convert("RGB")

    psnr = calculate_psnr(original, final)

    print(
        f"{strength:>8} "
        f"{'OK' if success else 'FAIL':>10} "
        f"{psnr:>12.2f}"
    )
