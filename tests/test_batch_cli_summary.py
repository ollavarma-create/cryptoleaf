"""Regression tests for the batch command-line summary."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

import batch_encode_v2


def test_summary_counts_statuses(tmp_path, capsys):
    results = [SimpleNamespace(status=s, image=f"{i}.jpg", format="JPEG", strength=None,
                               attempts=None, error="")
               for i, s in enumerate(["OK", "SKIPPED", "OK", "FAIL"])]
    args = ["batch_encode_v2.py", str(tmp_path / "input"), str(tmp_path / "output"),
            "--message", "test", "--password", "secret"]
    with patch.object(sys, "argv", args), \
         patch.object(batch_encode_v2, "process_batch", return_value=results), \
         patch.object(batch_encode_v2, "write_report", return_value=tmp_path / "report.csv"):
        batch_encode_v2.main()
    assert "Completed: 2 OK, 1 SKIPPED, 1 FAILED (4 total)" in capsys.readouterr().out


def test_dry_run_summary_unchanged(tmp_path, capsys):
    results = [SimpleNamespace(status="DRY_RUN", image="test.jpg", format="JPEG",
                               strength=None, attempts=None, error="")]
    args = ["batch_encode_v2.py", str(tmp_path / "input"), str(tmp_path / "output"),
            "--message", "test", "--password", "secret", "--dry-run"]
    with patch.object(sys, "argv", args), \
         patch.object(batch_encode_v2, "process_batch", return_value=results), \
         patch.object(batch_encode_v2, "write_report") as report:
        batch_encode_v2.main()
    assert "Planned: 1/1 images; 0 processed" in capsys.readouterr().out
    report.assert_not_called()
