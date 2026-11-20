import numpy as np
from PIL import Image
from tools.robust_content_aware_hb16 import cover_features, bins


def test_features_have_ll2_grid_shape():
    rng = np.random.default_rng(7)
    image = Image.fromarray(rng.integers(0, 256, (19, 21, 3),
                                        dtype=np.uint8), "RGB")
    features = cover_features(image)
    assert all(v.shape == (30,) for v in features.values())
    assert np.all(features["cover_std"] >= 0)


def test_quintiles_count_and_zero_flip():
    rows = [{"source": "x", "strategy": "balanced",
             "transform": "resize083_jpeg85", "received_wrong": 0,
             "channel_flip": 0, "abs_ll2_drift": float(i),
             **{k: float(i) for k in (
                 "cover_mean", "cover_std", "cover_headroom",
                 "cover_lattice_margin", "png_lattice_margin")}}
            for i in range(20)]
    result = bins(rows)
    assert len(result) == 25
    assert all(r["n"] == 4 for r in result)
    assert all(r["channel_flip_fraction"] == 0 for r in result)
