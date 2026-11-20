from tools.robust_content_aware_hb17 import jpeg_footprint, aggregate, conditioned


def test_unscaled_phase_and_block_crossing():
    # For 16x16 at scale 1.0 each 4x4 DWT cell stays inside 8x8.
    for i in range(16):
        g = jpeg_footprint(i, 16, 16, 1.0)
        assert g["jpeg_block_crossing"] == 0
        assert g["dwt_phase_x"] == (i % 4) % 2
        assert g["dwt_phase_y"] == (i // 4) % 2


def test_resize_can_cross_jpeg_boundary():
    g = jpeg_footprint(1, 16, 16, 1.5)
    assert g["jpeg_block_crossing"] == 1


def test_aggregate_rates():
    rows = [
        {"source": "a", "strategy": "balanced", "transform": "resize083_jpeg85",
         "dwt_phase": "00", "received_wrong": 0, "channel_flip": 0,
         "abs_ll2_drift": 1, "png_lattice_margin": 12, "cover_std": 2},
        {"source": "a", "strategy": "balanced", "transform": "resize083_jpeg85",
         "dwt_phase": "00", "received_wrong": 1, "channel_flip": 1,
         "abs_ll2_drift": 3, "png_lattice_margin": 14, "cover_std": 4},
    ]
    groups = aggregate(rows, "dwt_phase")
    assert len(groups) == 1
    assert groups[0]["error_fraction"] == 0.5
    assert groups[0]["median_drift"] == 2


def test_conditioning_keeps_all_rows():
    rows = []
    for i in range(32):
        rows.append({"source": "a", "strategy": "balanced",
                     "transform": "resize083_jpeg85", "cover_std": i,
                     "png_lattice_margin": i / 2, "dwt_phase": str(i % 4),
                     "jpeg_block_crossing": i % 2,
                     "received_wrong": i % 2, "channel_flip": i % 2})
    grouped = conditioned(rows)
    assert sum(r["n"] for r in grouped if r["feature"] == "dwt_phase") == 32
    assert sum(r["n"] for r in grouped if r["feature"] == "jpeg_block_crossing") == 32


def test_aggregate_accepts_csv_string_numbers():
    # csv.DictReader returns strings even for numeric fields.
    rows = [
        {"source": "a", "strategy": "balanced", "transform": "resize083_jpeg85",
         "dwt_phase": "00", "received_wrong": "0", "channel_flip": "0",
         "abs_ll2_drift": "1.0", "png_lattice_margin": "12.0", "cover_std": "2.0"},
        {"source": "a", "strategy": "balanced", "transform": "resize083_jpeg85",
         "dwt_phase": "00", "received_wrong": "1", "channel_flip": "1",
         "abs_ll2_drift": "3.0", "png_lattice_margin": "14.0", "cover_std": "4.0"},
    ]
    result = aggregate(rows, "dwt_phase")
    assert result[0]["median_drift"] == 2.0
    assert result[0]["median_png_margin"] == 13.0
    assert result[0]["median_cover_std"] == 3.0
