
from pathlib import Path
from PIL import Image

from src.image_encoder import _embed_prepared_v03
from src.image_decoder import _decode_image_block
from src.jpeg_v03 import prepare_payload

cover = Path("test_photo.jpg")
output = Path("test_roundtrip.jpg")

password = "cryptoleaf-test-password"
message = b"Cryptoleaf JPEG v0.3 interleaving works!"

strength = 50
quality = 85

# Encrypt and add Reed-Solomon protection.
prepared = prepare_payload(message, password)

# Embed using the new interleaving.
stego = _embed_prepared_v03(
    cover,
    prepared,
    strength=strength,
)

stego.save(output, format="JPEG", quality=quality)
stego.close()

# Decode from the actual saved JPEG file.
with Image.open(output) as img:
    recovered = _decode_image_block(img, password)

print("Original:", message)
print("Recovered:", recovered)
print("Match:", recovered == message)

assert recovered == message
print("JPEG v0.3 ROUNDTRIP PASSED")
