"""Regression tests for Cryptoleaf batch progress and GUI counters."""

import os
from pathlib import Path

import pytest

from src.batch_processor import process_batch


def test_batch_progress_callback_dry_run(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("b.jpg", "a.png", "c.webp"):
        (source / name).write_bytes(b"not a real image")
    calls = []
    output = tmp_path / "output"
    results = process_batch(
        source, output, b"hello", "password", dry_run=True,
        on_progress=lambda item, done, total: calls.append((item, done, total)),
    )
    assert [item.image for item in results] == ["a.png", "b.jpg", "c.webp"]
    assert [item.status for item in results] == ["DRY_RUN"] * 3
    assert [(done, total) for _, done, total in calls] == [(1, 3), (2, 3), (3, 3)]
    assert [item for item, _, _ in calls] == results
    assert not output.exists()


def test_batch_progress_callback_skip_existing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.png").write_bytes(b"not a real image")
    output = tmp_path / "output"
    output.mkdir()
    existing = output / "a_cryptoleaf.png"
    existing.write_bytes(b"keep me")
    calls = []
    results = process_batch(source, output, b"hello", "password", skip_existing=True,
                            on_progress=lambda item, done, total: calls.append((item.status, done, total)))
    assert [r.status for r in results] == ["SKIPPED"]
    assert calls == [("SKIPPED", 1, 1)]
    assert existing.read_bytes() == b"keep me"


def test_batch_progress_callback_empty_directory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    calls = []
    assert process_batch(source, tmp_path / "output", b"hello", "password", dry_run=True,
                         on_progress=lambda *args: calls.append(args)) == []
    assert calls == []


def test_batch_gui_progress_counters(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication
    from src.batch_processor import BatchResult
    from src.gui import BatchTab

    app = QApplication.instance() or QApplication([])
    tab = BatchTab(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    items = [
        BatchResult("a.png", "", "PNG", "OK"),
        BatchResult("b.jpg", "", "JPEG", "SKIPPED", error="CapacityError"),
        BatchResult("c.jpg", "", "JPEG", "FAIL", error="Verification failed"),
        BatchResult("d.webp", "", "WEBP", "DRY_RUN"),
    ]
    for n, item in enumerate(items, 1):
        tab._on_progress(item, n, len(items))
    assert tab._progress.value() == 4
    assert tab._counts == {"OK": 1, "SKIPPED": 1, "FAIL": 1, "DRY_RUN": 1}
    assert "4/4 images" in tab._summary.text()
    assert "CapacityError" in tab._results.toPlainText()
    tab.close()
