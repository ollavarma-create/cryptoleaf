import numpy as np
from tools.robust_content_aware_hb21 import auc, fit_ridge, score_ridge, top_fraction


def test_auc_perfect_and_reverse_and_ties():
    y = np.array([0, 0, 1, 1])
    assert auc(y, [0, 1, 2, 3]) == 1.
    assert auc(y, [3, 2, 1, 0]) == 0.
    assert auc(y, [1, 1, 1, 1]) == .5
    assert auc([0, 0], [1, 2]) is None


def test_ridge_deterministic_constant_feature():
    x = np.array([[1, 2], [2, 2], [3, 2], [4, 2]], dtype=float)
    y = np.array([0, 0, 1, 1])
    model = fit_ridge(x, y)
    a = score_ridge(model, x)
    assert np.isfinite(a).all()
    assert a[-1] > a[0]
    assert np.array_equal(a, score_ridge(model, x))


def test_low_risk_selection():
    fraction, n = top_fraction([1, 0, 1, 0, 1], [4, 0, 3, 1, 2], .4)
    assert n == 2
    assert fraction == 0.
