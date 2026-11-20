import numpy as np
from PIL import Image
from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_content_aware_hb1 import embed_with_map, select_positions
from tools.robust_content_aware_hb15 import feedback_step, ARMS
from tools.robust_dwt_parameter_sweep import codec_parameters


def test_modes_and_input_validation():
    assert ARMS == ("baseline", "inward", "outward", "adaptive")
    carrier = Image.new("RGB", (128, 128), (127, 127, 127))
    packet = pack(b"x")
    positions = select_positions(carrier, len(packet) * 8 * 13, "random")
    with codec_parameters(38, 13):
        try:
            feedback_step(carrier, packet, positions, 38, 13, "bad")
        except ValueError:
            pass
        else:
            raise AssertionError("Unknown arm accepted")


def test_trace_and_output_are_bounded():
    rng = np.random.default_rng(33)
    carrier = Image.fromarray(rng.integers(20, 235, (256, 256, 3),
                                         dtype=np.uint8), "RGB")
    packet = pack(b"x")
    with codec_parameters(38, 13):
        pos = select_positions(carrier, len(packet) * 8 * 13, "random")
        for arm in ARMS[1:]:
            marked, trace = feedback_step(carrier, packet, pos, 38, 13, arm)
            assert marked.size == carrier.size
            assert 1 <= len(trace) <= robust.FEEDBACK_ITERATIONS + 1
            assert trace[-1]["stepped_coefficients"] <= len(pos)
            assert all(step["position_errors"] >= 0 for step in trace)
