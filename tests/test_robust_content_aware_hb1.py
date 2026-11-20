import numpy as np
import pytest
from PIL import Image
from src.robust_packet import pack
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_content_aware_hb1 import (
    coefficient_scores, select_positions, embed_with_map, oracle_decode,
)


def test_scores_and_seeded_map_deterministic():
    a = np.tile(np.arange(128, dtype=np.uint8), (128, 1))
    im = Image.fromarray(np.stack((a, a, a), axis=-1), "RGB")
    assert coefficient_scores(im).size == 1024
    assert np.array_equal(select_positions(im, 20, "random"),
                          select_positions(im, 20, "random"))


def test_texture_capacity_refuses_without_fallback():
    im = Image.new("RGB", (128, 128), (255, 255, 255))
    with pytest.raises(ValueError, match="Insufficient eligible"):
        select_positions(im, 1, "texture")


def test_random_arm_matches_existing_feedback():
    from src import robust_image as robust
    a = np.random.default_rng(5).integers(25, 230, (256, 256, 3), dtype=np.uint8)
    image = Image.fromarray(a, "RGB")
    packet = pack(b"test")
    carrier = image.convert("YCbCr").convert("RGB")
    with codec_parameters(38, 13):
        pos = select_positions(image, len(packet) * 8 * 13, "random")
        baseline = robust._feedback_embed(carrier, packet)
        candidate = embed_with_map(carrier, packet, pos)
        assert np.array_equal(np.asarray(baseline), np.asarray(candidate))
        assert oracle_decode(candidate, candidate.size, pos, len(packet)) == b"test"


def test_texture_oracle_png_roundtrip():
    rng = np.random.default_rng(42)
    im = Image.fromarray(rng.integers(40, 215, (256, 256, 3), dtype=np.uint8), "RGB")
    packet = pack(b"test")
    with codec_parameters(38, 13):
        pos = select_positions(im, len(packet) * 8 * 13, "texture")
        marked = embed_with_map(im.convert("YCbCr").convert("RGB"), packet, pos)
        assert oracle_decode(marked, marked.size, pos, len(packet)) == b"test"
