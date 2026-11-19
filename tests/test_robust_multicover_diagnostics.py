"""Tests for targeted multicover bit-error diagnostics."""
import csv

from tools.robust_multicover_diagnostics import selected_rows, header_errors


def test_selected_rows_includes_passing_controls(tmp_path):
    matrix = tmp_path / "matrix.csv"
    with matrix.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["source", "nominal_strength",
                                 "scale_0.75_oracle", "scale_0.5_oracle"]
        )
        writer.writeheader()
        writer.writerows([
            {"source": "bad.png", "nominal_strength": 0,
             "scale_0.75_oracle": "PASS", "scale_0.5_oracle": "FAIL:ValueError"},
            {"source": "bad.png", "nominal_strength": 0.12,
             "scale_0.75_oracle": "PASS", "scale_0.5_oracle": "PASS"},
            {"source": "good.jpg", "nominal_strength": 0,
             "scale_0.75_oracle": "PASS", "scale_0.5_oracle": "PASS"},
        ])
    rows = selected_rows(matrix)
    assert len(rows) == 2
    assert all(row["source"] == "bad.png" for row in rows)


def test_header_error_counts_and_length():
    original = b"CLR1" + (52).to_bytes(2, "big")
    corrupted = b"CLR1" + (52 ^ (1 << 11)).to_bytes(2, "big")
    report = header_errors(corrupted, original)
    assert report == {
        "magic_bit_errors": 0,
        "length_bit_errors": 1,
        "observed_length": 2100,
        "expected_length": 52,
    }


def test_magic_error_distinct_from_length_error():
    original = b"CLR1" + (52).to_bytes(2, "big")
    corrupted = b"BLR1" + (52).to_bytes(2, "big")
    report = header_errors(corrupted, original)
    assert report["magic_bit_errors"] == 1
    assert report["length_bit_errors"] == 0
