
from io import BytesIO

from PIL import Image

from src.jpeg_interleave import interleave3, deinterleave3
from src.image_encoder import _embed_prepared_v03
from src.image_decoder import _decode_image_block
from src.jpeg_v03 import prepare_payload


def test_interleaving_recovers_burst_errors():
    bits = [i % 2 for i in range(448)]
    encoded = interleave3(bits)

    for pos in (579, 581, 582, 583):
        encoded[pos] ^= 1

    assert deinterleave3(encoded) == bits


def test_jpeg_v03_interleaved_roundtrip():
    image = Image.new("RGB", (768, 768), (120, 150, 180))
    message = b"Cryptoleaf JPEG v0.3 regression test"
    password = "regression-test-password"

    prepared = prepare_payload(message, password)

    stego = _embed_prepared_v03(
        None,
        prepared,
        strength=50,
        cover_image=image,
    )

    buffer = BytesIO()
    stego.save(buffer, format="JPEG", quality=85)
    stego.close()
    buffer.seek(0)

    with Image.open(buffer) as jpeg:
        recovered = _decode_image_block(jpeg, password)

    assert recovered == message
