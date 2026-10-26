# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – PyQt6 GUI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""PyQt6 tabbed GUI for image and audio steganography.

Layout
------
MainWindow
  ├── QTabWidget
  │     ├── ImageTab  – cover/stego image operations
  │     └── AudioTab  – cover/stego audio operations
  └── QStatusBar     – non-critical messages

Each tab runs its encoder/decoder in a QThread worker so the GUI
thread is never blocked.  Signals carry results back to the main thread.
"""

import logging
from pathlib import Path

import numpy as np
import soundfile as sf
from reedsolo import ReedSolomonError
from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audio_decoder import decode_audio, BadAudioMagicError
from .audio_encoder import encode_audio, capacity_bits_audio
from .image_decoder import decode_image, BadMagicError
from .image_encoder import encode_image, capacity_bits

logger = logging.getLogger(__name__)

def _friendly_decode_error(exc: Exception, has_password: bool) -> str:
    """Translate a low-level decode exception to a user-readable string."""
    if isinstance(exc, (BadMagicError, BadAudioMagicError)):
        return "No hidden message found, or the file is corrupt."
    if isinstance(exc, ReedSolomonError):
        if has_password:
            return "Decoding failed – wrong password, or the file is corrupt."
        return "No hidden message found, or the file is corrupt."
    msg = str(exc)
    if any(k in msg.lower() for k in ("decrypt", "padding", "unpad")):
        return "Decryption failed – check your password."
    return msg


_APP_ORG = "hiltsu"
_APP_NAME = "Cryptoleaf"
_VERSION = "v0.2.1"

# Alpha slider: int values 1–50 map to 0.1–5.0 (multiply by 0.1).
_SLIDER_DEFAULT = 10  # → 1.0

_ALPHA_TOOLTIP = (
    "Higher values embed data more robustly but may cause\n"
    "visible or audible artefacts.\n\n"
    "PNG / lossless:  1.0–2.0 recommended\n"
    "JPEG (lossy):    4.0 or higher needed"
)


# ---------------------------------------------------------------------------
# Background worker threads
# ---------------------------------------------------------------------------


class _ImageEncodeWorker(QThread):
    """Runs encode_image in a background thread.

    Signals:
        finished: Emits the resulting PIL Image on success.
        error: Emits a human-readable error string on failure.
    """

    finished = pyqtSignal(object)  # PIL.Image.Image
    error = pyqtSignal(str)

    def __init__(
        self,
        cover_path: str,
        payload: bytes,
        password: str,
        alpha: float,
        output_format: str,
    ) -> None:
        super().__init__()
        self._cover_path = cover_path
        self._payload = payload
        self._password = password
        self._alpha = alpha
        self._output_format = output_format

    def run(self) -> None:
        """Entry point for the worker thread."""
        try:
            img, actual_format = encode_image(
                self._cover_path,
                self._payload,
                self._password,
                self._alpha,
                self._output_format,
            )
            self.finished.emit((img, actual_format))
        except Exception as exc:
            logger.error("Image encoding failed: %s", exc)
            self.error.emit(str(exc))


class _ImageDecodeWorker(QThread):
    """Runs decode_image in a background thread.

    Signals:
        finished: Emits raw payload bytes on success.
        error: Emits a human-readable error string on failure.
    """

    finished = pyqtSignal(bytes)
    error = pyqtSignal(str)

    def __init__(self, stego_path: str, password: str) -> None:
        super().__init__()
        self._stego_path = stego_path
        self._password = password

    def run(self) -> None:
        try:
            data = decode_image(self._stego_path, self._password)
            self.finished.emit(data)
        except Exception as exc:
            logger.error("Image decoding failed: %s", exc)
            self.error.emit(_friendly_decode_error(exc, bool(self._password)))


class _AudioEncodeWorker(QThread):
    """Runs encode_audio in a background thread.

    Signals:
        finished: Emits ``(np.ndarray, samplerate)`` tuple on success.
        error: Emits a human-readable error string on failure.
    """

    finished = pyqtSignal(object)  # tuple[np.ndarray, int]
    error = pyqtSignal(str)

    def __init__(
        self,
        cover_path: str,
        payload: bytes,
        password: str,
        alpha: float,
    ) -> None:
        super().__init__()
        self._cover_path = cover_path
        self._payload = payload
        self._password = password
        self._alpha = alpha

    def run(self) -> None:
        try:
            stego, sr = encode_audio(
                self._cover_path,
                self._payload,
                self._password,
                self._alpha,
            )
            self.finished.emit((stego, sr))
        except Exception as exc:
            logger.error("Audio encoding failed: %s", exc)
            self.error.emit(str(exc))


class _AudioDecodeWorker(QThread):
    """Runs decode_audio in a background thread.

    Signals:
        finished: Emits raw payload bytes on success.
        error: Emits a human-readable error string on failure.
    """

    finished = pyqtSignal(bytes)
    error = pyqtSignal(str)

    def __init__(self, stego_path: str, password: str) -> None:
        super().__init__()
        self._stego_path = stego_path
        self._password = password

    def run(self) -> None:
        try:
            data = decode_audio(self._stego_path, self._password)
            self.finished.emit(data)
        except Exception as exc:
            logger.error("Audio decoding failed: %s", exc)
            self.error.emit(_friendly_decode_error(exc, bool(self._password)))


# ---------------------------------------------------------------------------
# Drag-and-drop file picker widget
# ---------------------------------------------------------------------------


class _DropArea(QFrame):
    """QFrame that accepts file drops and emits file_dropped(path).

    Args:
        accept_suffixes: Lower-case extensions to accept (e.g. [".png"]).
            Pass an empty list to accept any file.
    """

    file_dropped = pyqtSignal(str)

    def __init__(self, accept_suffixes: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accept_suffixes = [s.lower() for s in accept_suffixes]
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._label = QLabel("Drop file here")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(self._label)

    def set_filename(self, name: str) -> None:
        """Display *name* as the currently selected file."""
        self._label.setText(name or "Drop file here")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if self._acceptable(path):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        path = event.mimeData().urls()[0].toLocalFile()
        if self._acceptable(path):
            self.file_dropped.emit(path)

    def _acceptable(self, path: str) -> bool:
        if not self._accept_suffixes:
            return True
        return Path(path).suffix.lower() in self._accept_suffixes


# ---------------------------------------------------------------------------
# Image tab
# ---------------------------------------------------------------------------


class ImageTab(QWidget):
    """Tab that handles image steganography encode and decode.

    Args:
        settings: Shared QSettings for reading and persisting preferences.
    """

    status_message = pyqtSignal(str)

    _IMAGE_SUFFIXES = [".png", ".jpg", ".jpeg", ".bmp", ".webp"]
    _IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
    _FORMAT_OPTIONS = ["PNG", "JPEG", "BMP", "WEBP"]
    _FMT_SUFFIX = {"PNG": ".png", "JPEG": ".jpg", "BMP": ".bmp", "WEBP": ".webp"}
    _FMT_FILTER = {
        "PNG": "PNG files (*.png)",
        "JPEG": "JPEG files (*.jpg)",
        "BMP": "BMP files (*.bmp)",
        "WEBP": "WebP files (*.webp)",
    }

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._file_path: str = ""
        self._pending_out_path: str = ""
        self._pending_fmt: str = "PNG"
        self._worker: QThread | None = None
        self._current_capacity: int = 0
        self._build_ui()

    # --- UI construction --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # ---- Left panel: file picker + thumbnail + capacity --------------------
        left = QVBoxLayout()
        left.setSpacing(6)

        left.addWidget(QLabel("Cover / stego image:"))

        self._drop_area = _DropArea(self._IMAGE_SUFFIXES)
        self._drop_area.file_dropped.connect(self._on_file_selected)
        left.addWidget(self._drop_area)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_file)
        left.addWidget(browse_btn)

        self._thumbnail = QLabel()
        self._thumbnail.setFixedSize(200, 200)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail.setFrameShape(QFrame.Shape.StyledPanel)
        self._thumbnail.setText("No image selected")
        left.addWidget(self._thumbnail)

        self._capacity_label = QLabel("Capacity: –")
        self._capacity_label.setWordWrap(True)
        left.addWidget(self._capacity_label)

        self._exif_label = QLabel("")
        self._exif_label.setWordWrap(True)
        self._exif_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        self._exif_label.setVisible(False)
        left.addWidget(self._exif_label)

        left.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(224)

        # ---- Right panel: controls + result ------------------------------------
        right = QVBoxLayout()
        right.setSpacing(6)

        right.addWidget(QLabel("Message to hide:"))
        self._message_edit = QPlainTextEdit()
        self._message_edit.setPlaceholderText("Enter the secret message to embed…")
        self._message_edit.textChanged.connect(self._update_remaining)
        right.addWidget(self._message_edit)

        self._remaining_label = QLabel("– bytes remaining")
        self._remaining_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._remaining_label)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Leave empty for no encryption")
        form.addRow("Password:", self._password_edit)

        self._format_combo = QComboBox()
        self._format_combo.addItems(self._FORMAT_OPTIONS)
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        form.addRow("Output format:", self._format_combo)

        self._jpeg_warning = QLabel(
            "JPEG-kuva tallennetaan laadulla 85. Käytetään lohkopohjaista "
            "luminanssimenetelmää joka on optimoitu JPEG-pakkaukselle."
        )
        self._jpeg_warning.setWordWrap(True)
        self._jpeg_warning.setStyleSheet("color: #b85c00;")
        self._jpeg_warning.setVisible(False)
        form.addRow("", self._jpeg_warning)

        right.addLayout(form)

        # Alpha slider (hidden when JPEG is selected – strength is fixed for Method B)
        alpha_row = QHBoxLayout()
        self._alpha_lbl = QLabel("Embedding strength:")
        self._alpha_lbl.setToolTip(_ALPHA_TOOLTIP)
        alpha_row.addWidget(self._alpha_lbl)
        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(1, 50)
        saved = self._settings.value("image/alpha_int", _SLIDER_DEFAULT, int)
        self._alpha_slider.setValue(saved)
        self._alpha_slider.setToolTip(_ALPHA_TOOLTIP)
        self._alpha_val_label = QLabel(f"{saved * 0.1:.1f}")
        self._alpha_slider.valueChanged.connect(self._on_alpha_changed)
        alpha_row.addWidget(self._alpha_slider)
        alpha_row.addWidget(self._alpha_val_label)
        right.addLayout(alpha_row)

        # Progress bar (indeterminate; hidden when idle)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        right.addWidget(self._progress)

        # Action buttons
        btn_row = QHBoxLayout()
        self._hide_btn = QPushButton("Hide Message")
        self._hide_btn.clicked.connect(self._hide_message)
        self._extract_btn = QPushButton("Extract Message")
        self._extract_btn.clicked.connect(self._extract_message)
        btn_row.addWidget(self._hide_btn)
        btn_row.addWidget(self._extract_btn)
        right.addLayout(btn_row)

        # Result area
        right.addWidget(QLabel("Extracted message:"))
        self._result_edit = QPlainTextEdit()
        self._result_edit.setReadOnly(True)
        self._result_edit.setPlaceholderText("Extracted message will appear here…")
        right.addWidget(self._result_edit)

        right_widget = QWidget()
        right_widget.setLayout(right)

        root.addWidget(left_widget)
        root.addWidget(right_widget, stretch=1)

    # --- File selection ---------------------------------------------------------

    def _browse_file(self) -> None:
        last_dir = self._settings.value("last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select image", last_dir, self._IMAGE_FILTER
        )
        if path:
            self._on_file_selected(path)

    def _on_file_selected(self, path: str) -> None:
        self._file_path = path
        self._settings.setValue("last_dir", str(Path(path).parent))
        self._drop_area.set_filename(Path(path).name)
        self._update_thumbnail(path)
        self._update_capacity(path)
        self._update_exif(path)

    def _update_thumbnail(self, path: str) -> None:
        px = QPixmap(path)
        if not px.isNull():
            px = px.scaled(
                200,
                200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumbnail.setPixmap(px)
        else:
            self._thumbnail.clear()
            self._thumbnail.setText("Preview unavailable")

    def _update_capacity(self, path: str) -> None:
        try:
            fmt = self._format_combo.currentText()
            bits = capacity_bits(path, output_format=fmt)
            # JPEG Method B: 32-byte header overhead (no RS).
            # Lossless LSB: ~64 bytes (RS-encoded 32-byte header).
            header_overhead = 32 if fmt == "JPEG" else 64
            usable = max(0, bits // 8 - header_overhead)
            self._current_capacity = usable
            self._capacity_label.setText(f"Capacity: ~{usable:,} bytes available")
        except Exception as exc:
            self._current_capacity = 0
            self._capacity_label.setText("Capacity: unknown")
            logger.warning("Capacity check failed for '%s': %s", path, exc)
        self._update_remaining()

    def _update_exif(self, path: str) -> None:
        from .utils import read_exif_tags
        tags = read_exif_tags(path)
        self._exif_label.setText(tags)
        self._exif_label.setVisible(bool(tags))

    def _update_remaining(self) -> None:
        used = len(self._message_edit.toPlainText().encode("utf-8"))
        cap = self._current_capacity
        left = cap - used
        self._remaining_label.setText(f"{left:,} bytes remaining")
        if cap == 0:
            color = ""
        elif left / cap > 0.20:
            color = "color: #2d6a4f;"
        elif left / cap > 0.05:
            color = "color: #b85c00;"
        else:
            color = "color: #e63946;"
        self._remaining_label.setStyleSheet(color)

    # --- Alpha slider -----------------------------------------------------------

    def _on_format_changed(self, fmt: str) -> None:
        is_jpeg = fmt == "JPEG"
        self._jpeg_warning.setVisible(is_jpeg)
        # JPEG Method B uses a fixed strength (25); alpha slider has no effect
        self._alpha_lbl.setVisible(not is_jpeg)
        self._alpha_slider.setVisible(not is_jpeg)
        self._alpha_val_label.setVisible(not is_jpeg)
        if self._file_path:
            self._update_capacity(self._file_path)
        else:
            self._update_remaining()

    def _on_alpha_changed(self, value: int) -> None:
        self._alpha_val_label.setText(f"{value * 0.1:.1f}")
        self._settings.setValue("image/alpha_int", value)

    def _alpha_float(self) -> float:
        return self._alpha_slider.value() * 0.1

    # --- Encode / decode actions ------------------------------------------------

    def _hide_message(self) -> None:
        if not self._file_path:
            self.status_message.emit("Select a cover image first.")
            return
        message = self._message_edit.toPlainText()
        if not message.strip():
            self.status_message.emit("Enter a message to hide.")
            return

        fmt = self._format_combo.currentText()
        last_dir = self._settings.value("last_dir", "", str)
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save stego image as",
            last_dir,
            self._FMT_FILTER[fmt],
        )
        if not out_path:
            return

        # Lisätään tiedostopääte automaattisesti mikäli puuttuu
        suffix = self._FMT_SUFFIX[fmt]
        if not out_path.lower().endswith(suffix):
            out_path += suffix

        self._pending_out_path = out_path
        self._pending_fmt = fmt

        self._set_busy(True)
        self.status_message.emit("Embedding message…")
        self._worker = _ImageEncodeWorker(
            self._file_path,
            message.encode("utf-8"),
            self._password_edit.text(),
            self._alpha_float(),
            fmt,
        )
        self._worker.finished.connect(self._on_encode_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_encode_done(self, result: object) -> None:
        self._set_busy(False)
        img, actual_fmt = result  # type: ignore[misc]
        out_path = self._pending_out_path
        requested_fmt = self._pending_fmt

        # If JPEG fell back to PNG, adjust the output path extension
        if requested_fmt == "JPEG" and actual_fmt == "PNG":
            out_path = str(Path(out_path).with_suffix(".png"))
            self.status_message.emit(
                "Kuva liian pieni JPEG-embeddingille – tallennettu PNG:nä."
            )

        try:
            save_kwargs: dict = {"format": actual_fmt}
            if actual_fmt == "JPEG":
                save_kwargs["quality"] = 85
            elif actual_fmt == "WEBP":
                save_kwargs["lossless"] = True
            img.save(out_path, **save_kwargs)  # type: ignore[union-attr]
            if requested_fmt == actual_fmt:
                self.status_message.emit(f"Saved: {Path(out_path).name}")
            else:
                self.status_message.emit(
                    f"Saved as PNG (JPEG too small): {Path(out_path).name}"
                )
        except Exception as exc:
            logger.error("Failed to save stego image: %s", exc)
            self.status_message.emit(f"Error saving image: {exc}")

    def _extract_message(self) -> None:
        if not self._file_path:
            self.status_message.emit("Select a stego image first.")
            return
        self._result_edit.clear()
        self._set_busy(True)
        self.status_message.emit("Extracting message…")
        self._worker = _ImageDecodeWorker(
            self._file_path, self._password_edit.text()
        )
        self._worker.finished.connect(self._on_decode_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_decode_done(self, data: bytes) -> None:
        self._set_busy(False)
        try:
            text = data.decode("utf-8")
            self._result_edit.setPlainText(text)
            self.status_message.emit(f"Extracted {len(data):,} bytes.")
        except UnicodeDecodeError:
            # Partial recovery: show text with replacement chars if corruption is minor.
            # High corruption (>5 %) likely means binary/encrypted data, not text.
            text_replaced = data.decode("utf-8", errors="replace")
            n_bad = text_replaced.count("\ufffd")
            if n_bad / max(1, len(text_replaced)) < 0.05:
                self._result_edit.setPlainText(
                    text_replaced
                    + f"\n\n[{n_bad} character(s) could not be decoded – "
                    "likely caused by lossy compression artefacts (shown as \ufffd).]"
                )
                self.status_message.emit(
                    f"Extracted {len(data):,} bytes "
                    f"({n_bad} character(s) corrupted by compression)."
                )
            else:
                hint = (
                    " The file may be encrypted – enter a password and try again."
                    if not self._password_edit.text()
                    else ""
                )
                self._result_edit.setPlainText(
                    f"[Binary data – {len(data):,} bytes, cannot display as text.{hint}]"
                )
                self.status_message.emit(f"Extracted {len(data):,} bytes (binary).")

    def _on_worker_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_message.emit(f"Error: {message}")

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._hide_btn.setEnabled(not busy)
        self._extract_btn.setEnabled(not busy)


# ---------------------------------------------------------------------------
# Audio tab
# ---------------------------------------------------------------------------


class AudioTab(QWidget):
    """Tab that handles audio steganography encode and decode.

    Args:
        settings: Shared QSettings for reading and persisting preferences.
    """

    status_message = pyqtSignal(str)

    _AUDIO_SUFFIXES = [".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif"]
    _AUDIO_FILTER = "Audio files (*.wav *.flac *.ogg *.mp3 *.aiff *.aif)"
    _OUT_FORMATS = ["FLAC", "WAV"]
    _OUT_FILTER = {
        "FLAC": "FLAC files (*.flac)",
        "WAV": "WAV files (*.wav)",
    }
    _OUT_SUFFIX = {"FLAC": ".flac", "WAV": ".wav"}
    _SF_FORMAT = {"FLAC": "FLAC", "WAV": "WAV"}
    _SF_SUBTYPE = {"FLAC": "PCM_24", "WAV": "PCM_16"}

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._file_path: str = ""
        self._pending_out_path: str = ""
        self._pending_out_fmt: str = "FLAC"
        self._worker: QThread | None = None
        self._current_capacity: int = 0
        self._build_ui()

    # --- UI construction --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # ---- Left panel: file picker + info ------------------------------------
        left = QVBoxLayout()
        left.setSpacing(6)

        left.addWidget(QLabel("Cover / stego audio:"))

        self._drop_area = _DropArea(self._AUDIO_SUFFIXES)
        self._drop_area.file_dropped.connect(self._on_file_selected)
        left.addWidget(self._drop_area)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_file)
        left.addWidget(browse_btn)

        self._capacity_label = QLabel("Capacity: –")
        self._capacity_label.setWordWrap(True)
        left.addWidget(self._capacity_label)

        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        left.addWidget(self._info_label)

        left.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(224)

        # ---- Right panel: controls + result ------------------------------------
        right = QVBoxLayout()
        right.setSpacing(6)

        right.addWidget(QLabel("Message to hide:"))
        self._message_edit = QPlainTextEdit()
        self._message_edit.setPlaceholderText("Enter the secret message to embed…")
        self._message_edit.textChanged.connect(self._update_remaining)
        right.addWidget(self._message_edit)

        self._remaining_label = QLabel("– bytes remaining")
        self._remaining_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._remaining_label)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Leave empty for no encryption")
        form.addRow("Password:", self._password_edit)

        self._out_format_combo = QComboBox()
        self._out_format_combo.addItems(self._OUT_FORMATS)
        form.addRow("Output format:", self._out_format_combo)

        right.addLayout(form)

        # Alpha slider – not used by LSB method, kept hidden for API compatibility.
        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(3, 20)
        self._alpha_slider.setValue(7)
        self._alpha_val_label = QLabel("0.7")
        self._alpha_slider.setVisible(False)
        self._alpha_val_label.setVisible(False)

        # Progress bar (indeterminate; hidden when idle)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        right.addWidget(self._progress)

        # Action buttons
        btn_row = QHBoxLayout()
        self._hide_btn = QPushButton("Hide Message")
        self._hide_btn.clicked.connect(self._hide_message)
        self._extract_btn = QPushButton("Extract Message")
        self._extract_btn.clicked.connect(self._extract_message)
        btn_row.addWidget(self._hide_btn)
        btn_row.addWidget(self._extract_btn)
        right.addLayout(btn_row)

        # Result area
        right.addWidget(QLabel("Extracted message:"))
        self._result_edit = QPlainTextEdit()
        self._result_edit.setReadOnly(True)
        self._result_edit.setPlaceholderText("Extracted message will appear here…")
        right.addWidget(self._result_edit)

        right_widget = QWidget()
        right_widget.setLayout(right)

        root.addWidget(left_widget)
        root.addWidget(right_widget, stretch=1)

    # --- File selection ---------------------------------------------------------

    def _browse_file(self) -> None:
        last_dir = self._settings.value("last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select audio file", last_dir, self._AUDIO_FILTER
        )
        if path:
            self._on_file_selected(path)

    def _on_file_selected(self, path: str) -> None:
        self._file_path = path
        self._settings.setValue("last_dir", str(Path(path).parent))
        self._drop_area.set_filename(Path(path).name)
        self._update_info(path)
        self._update_capacity(path)

    def _update_info(self, path: str) -> None:
        try:
            info = sf.info(path)
            self._info_label.setText(
                f"{info.samplerate:,} Hz · {info.channels} ch · {info.duration:.1f} s"
            )
        except Exception:
            try:
                from pydub import AudioSegment
                seg = AudioSegment.from_file(path)
                self._info_label.setText(
                    f"{seg.frame_rate:,} Hz · {seg.channels} ch · {seg.duration_seconds:.1f} s"
                )
            except Exception:
                self._info_label.setText("")

    def _update_capacity(self, path: str) -> None:
        try:
            bits = capacity_bits_audio(path)
            # Subtract RS-encoded header overhead (96 bytes) and estimate
            # remaining capacity after payload RS overhead (factor 191/255).
            raw_payload_bytes = max(0, bits // 8 - 96)
            usable = max(0, int(raw_payload_bytes * 191 / 255) - 32)
            self._current_capacity = usable
            self._capacity_label.setText(f"Capacity: ~{usable:,} bytes available")
        except Exception as exc:
            self._current_capacity = 0
            self._capacity_label.setText("Capacity: unknown")
            logger.warning("Capacity check failed for '%s': %s", path, exc)
        self._update_remaining()

    def _update_remaining(self) -> None:
        used = len(self._message_edit.toPlainText().encode("utf-8"))
        cap = self._current_capacity
        left = cap - used
        self._remaining_label.setText(f"{left:,} bytes remaining")
        if cap == 0:
            color = ""
        elif left / cap > 0.20:
            color = "color: #2d6a4f;"
        elif left / cap > 0.05:
            color = "color: #b85c00;"
        else:
            color = "color: #e63946;"
        self._remaining_label.setStyleSheet(color)

    # --- Alpha slider -----------------------------------------------------------

    def _on_alpha_changed(self, value: int) -> None:
        self._alpha_val_label.setText(f"{value * 0.1:.1f}")
        self._settings.setValue("audio/alpha_int", value)

    def _alpha_float(self) -> float:
        return self._alpha_slider.value() * 0.1

    # --- Encode / decode actions ------------------------------------------------

    def _hide_message(self) -> None:
        if not self._file_path:
            self.status_message.emit("Select a cover audio file first.")
            return
        message = self._message_edit.toPlainText()
        if not message.strip():
            self.status_message.emit("Enter a message to hide.")
            return

        out_fmt = self._out_format_combo.currentText()
        last_dir = self._settings.value("last_dir", "", str)
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save stego audio as",
            last_dir,
            self._OUT_FILTER[out_fmt],
        )
        if not out_path:
            return

        # Garantoi oikea päätyte
        if not out_path.lower().endswith(self._OUT_SUFFIX[out_fmt]):
            out_path += self._OUT_SUFFIX[out_fmt]

        self._pending_out_path = out_path
        self._pending_out_fmt = out_fmt

        self._set_busy(True)
        self.status_message.emit("Embedding message…")
        self._worker = _AudioEncodeWorker(
            self._file_path,
            message.encode("utf-8"),
            self._password_edit.text(),
            self._alpha_float(),
        )
        self._worker.finished.connect(self._on_encode_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_encode_done(self, result: object) -> None:
        self._set_busy(False)
        stego, sr = result  # type: ignore[misc]
        out_path = self._pending_out_path
        out_fmt = self._pending_out_fmt
        try:
            sf.write(
                out_path,
                stego,
                sr,
                format=self._SF_FORMAT[out_fmt],
                subtype=self._SF_SUBTYPE[out_fmt],
            )
            self.status_message.emit(f"Saved: {Path(out_path).name}")
        except Exception as exc:
            logger.error("Failed to save stego audio: %s", exc)
            self.status_message.emit(f"Error saving audio: {exc}")

    def _extract_message(self) -> None:
        if not self._file_path:
            self.status_message.emit("Select a stego audio file first.")
            return
        self._result_edit.clear()
        self._set_busy(True)
        self.status_message.emit("Extracting message…")
        self._worker = _AudioDecodeWorker(
            self._file_path, self._password_edit.text()
        )
        self._worker.finished.connect(self._on_decode_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_decode_done(self, data: bytes) -> None:
        self._set_busy(False)
        try:
            text = data.decode("utf-8")
            self._result_edit.setPlainText(text)
            self.status_message.emit(f"Extracted {len(data):,} bytes.")
        except UnicodeDecodeError:
            # Partial recovery: show text with replacement chars if corruption is minor.
            text_replaced = data.decode("utf-8", errors="replace")
            n_bad = text_replaced.count("\ufffd")
            if n_bad / max(1, len(text_replaced)) < 0.05:
                self._result_edit.setPlainText(
                    text_replaced
                    + f"\n\n[{n_bad} character(s) could not be decoded – "
                    "likely caused by lossy compression artefacts (shown as \ufffd).]"
                )
                self.status_message.emit(
                    f"Extracted {len(data):,} bytes "
                    f"({n_bad} character(s) corrupted by compression)."
                )
            else:
                hint = (
                    " The file may be encrypted – enter a password and try again."
                    if not self._password_edit.text()
                    else ""
                )
                self._result_edit.setPlainText(
                    f"[Binary data – {len(data):,} bytes, cannot display as text.{hint}]"
                )
                self.status_message.emit(f"Extracted {len(data):,} bytes (binary).")

    def _on_worker_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_message.emit(f"Error: {message}")

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._hide_btn.setEnabled(not busy)
        self._extract_btn.setEnabled(not busy)


# ---------------------------------------------------------------------------
# About tab
# ---------------------------------------------------------------------------

_ABOUT_TEXT = """\
<h2>Cryptoleaf v0.2.1</h2>
<p>Copyright &copy; 2026 Jari Hiltunen / Codeberg hiltsu</p>

<h3>WHAT IS CRYPTOLEAF?</h3>
<p>Cryptoleaf is a steganography tool that hides encrypted messages inside image and audio files in such a way that the files still look and sound completely normal.</p>

<h3>USE CASES</h3>
<ul>
  <li><b>Secure communication</b> – hide a message inside an image</li>
  <li><b>Watermarking</b> – embed ownership information into images</li>
  <li><b>Metadata embedding</b> – add hidden contextual information to images</li>
  <li><b>Digital evidence</b> – embed a timestamp or identifier into an image</li>
</ul>

<h3>TECHNICAL METHODS</h3>
<ul>
  <li><b>Image (PNG/BMP/WEBP):</b> DWT + spread spectrum + Reed-Solomon error correction</li>
  <li><b>Image (JPEG):</b> Block-based luminance method + Hamming(7,4) + 3× replication</li>
  <li><b>Audio (WAV/MP3/FLAC):</b> Spread spectrum with frequency filtering + Reed-Solomon</li>
  <li><b>Encryption:</b> AES-256-CBC + PBKDF2-HMAC-SHA256 (200,000 iterations)</li>
</ul>

<h3>NOTE ABOUT JPEG IMAGES</h3>
<p>JPEG compression is lossy. It is always recommended to open an encrypted JPEG file and verify successful extraction before sending the file.</p>

<h3>OLD VERSION</h3>
<p>Old working version (v0.1.1) with binaries:<br>
  <a href="https://codeberg.org/hiltsu/old_v0.1_steganography_encrypter_decrypter">https://codeberg.org/hiltsu/old_v0.1_steganography_encrypter_decrypter</a></p>

Finnish / Suomi:

<h2>Cryptoleaf v0.2.1</h2> <p>Copyright © 2026 Jari Hiltunen / Codeberg hiltsu</p> <h3>MIKÄ ON CRYPTOLEAF?</h3> <p>Cryptoleaf on steganografiatyökalu, joka piilottaa salattuja viestejä kuva- ja äänitiedostoihin siten, että tiedostot näyttävät ja kuulostavat täysin normaaleilta.</p> <h3>KÄYTTÖTARKOITUKSET</h3> <ul> <li><b>Turvallinen viestintä</b> – piilota viesti kuvan sisään</li> <li><b>Vesileimaus</b> – merkitse kuvat omistajuustiedoilla</li> <li><b>Metatietojen upotus</b> – lisää piilotettua kontekstitietoa kuviin</li> <li><b>Digitaalinen todistusaineisto</b> – piilota aikaleima tai tunniste kuvaan</li> </ul> <h3>TEKNISET MENETELMÄT</h3> <ul> <li><b>Kuva (PNG/BMP/WEBP):</b> DWT + spread spectrum + Reed-Solomon virheenkorjaus</li> <li><b>Kuva (JPEG):</b> Lohkopohjainen luminanssimenetelmä + Hamming(7,4) + 3× replikointi</li> <li><b>Ääni (WAV/MP3/FLAC):</b> Spread spectrum taajuussuodatuksella + Reed-Solomon</li> <li><b>Salaus:</b> AES-256-CBC + PBKDF2-HMAC-SHA256 (200 000 iteraatiota)</li> </ul> <h3>HUOMIO JPEG-KUVISTA</h3> <p>JPEG-pakkaus on häviöllistä. Suositellaan aina avaamaan salattu JPEG-tiedosto ja varmistamaan purun onnistuminen ennen tiedoston lähettämistä.</p> <h3>VANHA VERSIO</h3> <p>Vanha toimiva versio (v0.1.1) binääreineen:
 <a href="https://codeberg.org/hiltsu/old_v0.1_steganography_encrypter_decrypter"> https://codeberg.org/hiltsu/old_v0.1_steganography_encrypter_decrypter</a></p>



"""


class AboutTab(QWidget):
    """Static About tab with application description and technical details."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        label = QLabel(_ABOUT_TEXT)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setContentsMargins(12, 12, 12, 12)

        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)


# ---------------------------------------------------------------------------
# Application-wide QSS stylesheet
# ---------------------------------------------------------------------------

_QSS = """
QPushButton {
    background-color: #2d6a4f;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #40916c; }
QPushButton:pressed { background-color: #1b4332; }
QPushButton:disabled { background-color: #adb5bd; color: #6c757d; }

QProgressBar {
    border-radius: 4px;
    background: #e9ecef;
}
QProgressBar::chunk {
    background-color: #2d6a4f;
    border-radius: 4px;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #dee2e6;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #2d6a4f;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
"""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Application main window with Image and Audio tabs.

    Persists window geometry, last-used directory, and alpha slider values
    via QSettings so preferences survive across sessions.
    """

    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings(_APP_ORG, _APP_NAME)
        self.setStyleSheet(_QSS)
        self._build_ui()
        self._restore_geometry()

    # --- UI construction --------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(f"Cryptoleaf - a Steganography Tool {_VERSION}")
        self.setMinimumSize(720, 540)

        tabs = QTabWidget()

        self._image_tab = ImageTab(self._settings)
        self._image_tab.status_message.connect(self._show_status)
        tabs.addTab(self._image_tab, "Image")

        self._audio_tab = AudioTab(self._settings)
        self._audio_tab.status_message.connect(self._show_status)
        tabs.addTab(self._audio_tab, "Audio")

        tabs.addTab(AboutTab(), "About")

        self.setCentralWidget(tabs)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._show_status("Ready.")

    # --- Geometry persistence ---------------------------------------------------

    def _restore_geometry(self) -> None:
        geometry = self._settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self._settings.setValue("window/geometry", self.saveGeometry())
        # Ensure any running background workers are stopped before Qt tears
        # down the event loop.  Without this, Python's thread finaliser can
        # raise KeyboardInterrupt inside enum.py when the interpreter exits
        # while a QThread is still alive.
        for tab in (self._image_tab, self._audio_tab):
            worker = getattr(tab, "_worker", None)
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(3000)  # wait up to 3 s; then proceed anyway
        super().closeEvent(event)

    # --- Status bar -------------------------------------------------------------

    def _show_status(self, message: str) -> None:
        """Display *message* in the status bar for 10 seconds."""
        self.statusBar().showMessage(message, 10_000)
        logger.info("Status: %s", message)
