import numpy as np
from PIL import Image
from src import robust_image as robust
from src.robust_packet import pack
from tools.robust_content_aware_hb1 import embed_with_map, select_positions
from tools.robust_content_aware_hb14 import counts, parity, trace_feedback
from tools.robust_dwt_parameter_sweep import codec_parameters


def test_counts_separates_repetition_and_majority():
    target = np.zeros(16 * 3, dtype=np.uint8)
    observed = target.copy()
    observed[:2] = 1
    result = counts(observed, target, 3)
    assert result["position_errors"] == 2
    assert result["majority_bit_errors"] == 1
    assert result["header_bit_errors"] == 1


def test_replay_matches_original_feedback():
    rng = np.random.default_rng(19)
    image = Image.fromarray(rng.integers(40, 210, (256, 256, 3),
                                        dtype=np.uint8), "RGB")
    carrier = image.convert("YCbCr").convert("RGB")
    packet = pack(b"test")
    with codec_parameters(38, 13):
        positions = select_positions(image, len(packet) * 8 * 13, "random")
        expected = embed_with_map(carrier, packet, positions)
        actual, trace = trace_feedback(carrier, packet, positions, 38, 13)
    assert np.array_equal(np.asarray(expected), np.asarray(actual))
    assert 1 <= len(trace) <= robust.FEEDBACK_ITERATIONS + 1
    assert all(row["target_lattice_errors"] == 0 for row in trace)


def test_parity_boundary():
    assert parity(np.array([0, 18, 20, 38, 56, 58]), 38).tolist() == [0, 0, 1, 1, 1, 0]
