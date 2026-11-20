import numpy as np
from tools.robust_content_aware_hb13 import position_metrics, summarise


def test_exact_lattice_has_half_delta_margin():
    packet = bytes([0])
    positions = np.arange(8)
    # One repeat per bit, all expected packet bits are zero.
    x = np.zeros(8, dtype=float)
    m = position_metrics(x, x.copy(), positions, packet, 38., 1)
    assert np.allclose(m["png_margin"], 19)
    assert not m["png_error"].any()
    assert not m["received_error"].any()
    assert not m["changed_parity"].any()


def test_boundary_crossing_changes_parity():
    packet = bytes([0])
    positions = np.arange(8)
    x = np.zeros(8, dtype=float)
    y = x.copy()
    y[0] = 20.
    m = position_metrics(x, y, positions, packet, 38., 1)
    assert m["changed_parity"][0]
    assert m["received_error"][0]
    assert m["abs_drift"][0] == 20.


def test_empty_group_and_nonempty_group():
    packet = bytes([0])
    x = np.zeros(8)
    m = position_metrics(x, x, np.arange(8), packet, 38., 1)
    assert summarise(np.zeros(8, dtype=bool), m)["n"] == 0
    assert summarise(np.ones(8, dtype=bool), m)["n"] == 8
