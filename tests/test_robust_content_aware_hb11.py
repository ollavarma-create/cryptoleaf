import numpy as np
from PIL import Image
from src.robust_packet import pack
from tools.robust_dwt_parameter_sweep import codec_parameters
from tools.robust_content_aware_hb1 import embed_with_map, select_positions
from tools.robust_content_aware_hb11 import diagnostics, region_types


def test_region_labels_have_ll2_shape():
    im = Image.new("RGB", (129, 133), (100, 100, 100))
    edge, flat = region_types(im)
    assert edge.shape == flat.shape == (34 * 33,)
    assert not edge.any()
    assert flat.all()


def test_png_diagnostics_exact_packet():
    rng = np.random.default_rng(100)
    image = Image.fromarray(rng.integers(30, 220, (256, 256, 3),
                                        dtype=np.uint8), "RGB")
    packet = pack(b"test")
    with codec_parameters(38, 13):
        pos = select_positions(image, len(packet) * 8 * 13, "random")
        marked = embed_with_map(image.convert("YCbCr").convert("RGB"),
                                packet, pos)
        result = diagnostics(marked, marked.size, pos, packet, 13, 38)
    assert result["status"] == "PASS"
    assert result["majority_bit_errors"] == 0
    assert result["codeword_byte_errors"] == 0


def test_corrupt_map_detects_errors():
    rng = np.random.default_rng(22)
    image = Image.fromarray(rng.integers(30, 220, (256, 256, 3),
                                        dtype=np.uint8), "RGB")
    packet = pack(b"test")
    with codec_parameters(38, 13):
        pos = select_positions(image, len(packet) * 8 * 13, "random")
        marked = embed_with_map(image.convert("YCbCr").convert("RGB"),
                                packet, pos)
        corrupted = np.roll(pos, 13)
        result = diagnostics(marked, marked.size, corrupted, packet, 13, 38)
    assert result["status"] == "FAIL"
    assert result["majority_bit_errors"] > 0
