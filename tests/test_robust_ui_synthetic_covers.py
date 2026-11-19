"""Unit tests for deterministic synthetic UI orientation control covers."""
import csv
import hashlib

import numpy as np
from PIL import Image
import pytest

from tools import robust_ui_synthetic_covers as synthetic


def _arrays(seed=20261119):
    return {
        name: np.asarray(image)
        for name, image in synthetic.make_covers(400, 400, seed).items()
    }


def test_seven_fixed_cases_and_reproducible_seed():
    first = _arrays()
    second = _arrays()
    assert list(first) == [case[0] for case in synthetic.CASES]
    for name in first:
        np.testing.assert_array_equal(first[name], second[name])
        assert first[name].shape == (400, 400, 3)


def test_single_orientation_and_grid_are_controlled():
    images = _arrays()
    flat = images["00-flat.png"]
    horizontal = images["01-horizontal.png"]
    vertical = images["02-vertical.png"]
    grid = images["03-grid.png"]
    hmask = np.any(horizontal != flat, axis=2)
    vmask = np.any(vertical != flat, axis=2)
    gmask = np.any(grid != flat, axis=2)
    assert hmask.any() and vmask.any()
    np.testing.assert_array_equal(gmask, hmask | vmask)
    # Lines are exactly the same grey and have no extra colour channel.
    assert np.all(grid[:, :, 0] == grid[:, :, 1])
    assert np.all(grid[:, :, 1] == grid[:, :, 2])


def test_colour_and_texture_are_separate_interventions():
    images = _arrays()
    grid = images["03-grid.png"]
    bars = images["04-grid-bars.png"]
    flat = images["00-flat.png"]
    texture = images["05-texture.png"]
    combined = images["06-grid-bars-texture.png"]
    assert np.any(bars != grid)
    assert np.any(bars[:, :, 0] != bars[:, :, 1])
    assert np.all(texture[:, :, 0] == texture[:, :, 1])
    assert np.all(texture[:, :, 1] == texture[:, :, 2])
    assert np.any(texture != flat)
    assert np.any(combined != bars)
    assert np.any(combined[:, :, 0] != combined[:, :, 1])


def test_seed_changes_only_textured_cases():
    a = _arrays(seed=17)
    b = _arrays(seed=18)
    for name, *flags in synthetic.CASES:
        if flags[-1]:
            assert np.any(a[name] != b[name])
        else:
            np.testing.assert_array_equal(a[name], b[name])


def test_manifest_and_byte_identical_control(tmp_path):
    control = tmp_path / "photo.jpg"
    Image.new("RGB", (48, 48), (32, 48, 64)).save(control)
    destination = tmp_path / "output"
    rows = synthetic.write_covers(
        destination, [control], width=400, height=400
    )
    assert len(rows) == 8
    assert (destination / control.name).read_bytes() == control.read_bytes()
    assert rows[0]["file"] == "00-flat.png"
    assert rows[0]["near_white_fraction"] == 1.0
    assert rows[0]["nearly_gray_fraction"] == 1.0
    assert rows[-1]["kind"] == "real_control"
    for row in rows:
        assert row["sha256"] == hashlib.sha256(
            (destination / row["file"]).read_bytes()
        ).hexdigest()
    with (destination / synthetic.MANIFEST).open(
        newline="", encoding="utf-8"
    ) as handle:
        saved = list(csv.DictReader(handle))
    assert len(saved) == len(rows)
    assert saved[-1]["file"] == control.name


def test_reject_nonempty_destination_and_duplicate_controls(tmp_path):
    destination = tmp_path / "output"
    destination.mkdir()
    (destination / "existing.txt").write_text("do not overwrite")
    with pytest.raises(ValueError, match="empty"):
        synthetic.write_covers(destination)
    assert (destination / "existing.txt").read_text() == "do not overwrite"

    control = tmp_path / "test.png"
    Image.new("RGB", (32, 32)).save(control)
    with pytest.raises(ValueError, match="Duplicate"):
        synthetic.write_covers(tmp_path / "another", [control, control])
    assert not (tmp_path / "another").exists()


def test_reject_unsupported_geometry():
    with pytest.raises(ValueError, match="256..1280"):
        synthetic.make_covers(100, 400)
    with pytest.raises(ValueError, match="capacity"):
        synthetic.make_covers(256, 256)
