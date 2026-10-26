# Copyright (c) 2026 Jari Hiltunen / Codeberg hiltsu
#
# Steganography Tool v0.2.1 – shared utilities
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

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

try:
    import piexif
    _PIEXIF_AVAILABLE = True
except ImportError:
    _PIEXIF_AVAILABLE = False

logger = logging.getLogger(__name__)

_FORMAT_BY_SUFFIX = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".bmp": "BMP",
    ".webp": "WEBP",
}


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a standard formatter.

    Args:
        level: Logging level (e.g. logging.DEBUG, logging.INFO).
    """
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)


def detect_format(path: str | Path) -> str:
    """Return the canonical format string for a given file path.

    Checks suffix first; if unrecognised, asks Pillow to sniff the format.

    Args:
        path: Path to the image file.

    Returns:
        One of "PNG", "JPEG", "BMP", "WEBP".

    Raises:
        ValueError: If the format cannot be determined or is unsupported.
    """
    p = Path(path)
    fmt = _FORMAT_BY_SUFFIX.get(p.suffix.lower())
    if fmt:
        return fmt

    # Pillow sniff as fallback
    try:
        with Image.open(p) as img:
            pillow_fmt = img.format
    except Exception as exc:
        raise ValueError(f"Cannot determine image format for '{path}': {exc}") from exc

    if pillow_fmt in {"PNG", "JPEG", "BMP", "WEBP"}:
        return pillow_fmt

    raise ValueError(
        f"Unsupported image format '{pillow_fmt}' for '{path}'. "
        "Supported: PNG, JPEG, BMP, WEBP."
    )


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------


def _dms_to_dec(dms: tuple, ref: bytes) -> float:
    """Convert EXIF DMS rational tuples to decimal degrees.

    Args:
        dms: Tuple of three (numerator, denominator) pairs for degrees, minutes, seconds.
        ref: Reference byte string, e.g. b'N', b'S', b'E', b'W'.

    Returns:
        Decimal degrees (negative for S/W).
    """
    d = dms[0][0] / dms[0][1]
    m = dms[1][0] / dms[1][1]
    s = dms[2][0] / dms[2][1]
    dec = d + m / 60.0 + s / 3600.0
    if ref in (b"S", b"W"):
        dec = -dec
    return dec


def read_exif_tags(image_path: str | Path) -> str:
    """Return a formatted one-line string of key EXIF fields, or '' if none.

    Args:
        image_path: Path to the image file.

    Returns:
        Formatted string like '📷 Canon EOS R5 | 📅 2024-03-15 | 📍 60.17° N, 24.94° E',
        or empty string if no EXIF data is available or piexif is not installed.
    """
    if not _PIEXIF_AVAILABLE:
        logger.debug("piexif not available – skipping EXIF read")
        return ""
    try:
        exif = piexif.load(str(image_path))
    except Exception as exc:
        logger.debug("Could not load EXIF from '%s': %s", image_path, exc)
        return ""

    parts: list[str] = []

    # Camera make + model
    try:
        ifd0 = exif.get("0th", {})
        make_raw = ifd0.get(piexif.ImageIFD.Make, b"")
        model_raw = ifd0.get(piexif.ImageIFD.Model, b"")
        make = make_raw.decode("utf-8", errors="replace").strip().rstrip("\x00")
        model = model_raw.decode("utf-8", errors="replace").strip().rstrip("\x00")
        camera = " ".join(filter(None, [make, model]))
        if camera:
            parts.append(f"📷 {camera}")
    except Exception as exc:
        logger.debug("EXIF camera field error: %s", exc)

    # Date taken
    try:
        exif_ifd = exif.get("Exif", {})
        date_raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal, b"")
        if date_raw:
            date_str = date_raw.decode("utf-8", errors="replace").strip().rstrip("\x00")
            # Format: "YYYY:MM:DD HH:MM:SS" → "YYYY-MM-DD"
            date_part = date_str.split(" ")[0].replace(":", "-")
            if len(date_part) == 10:
                parts.append(f"📅 {date_part}")
    except Exception as exc:
        logger.debug("EXIF date field error: %s", exc)

    # GPS coordinates
    try:
        gps_ifd = exif.get("GPS", {})
        if gps_ifd:
            lat_dms = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
            lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
            lon_dms = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
            lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef, b"E")
            if lat_dms and lon_dms:
                lat = _dms_to_dec(lat_dms, lat_ref)
                lon = _dms_to_dec(lon_dms, lon_ref)
                lat_card = "N" if lat >= 0 else "S"
                lon_card = "E" if lon >= 0 else "W"
                parts.append(f"📍 {abs(lat):.2f}° {lat_card}, {abs(lon):.2f}° {lon_card}")
    except Exception as exc:
        logger.debug("EXIF GPS field error: %s", exc)

    result = " | ".join(parts)
    logger.debug("EXIF tags for '%s': %s", image_path, result or "(none)")
    return result


def copy_exif(src_path: str | Path, dst_img: object) -> Optional[bytes]:
    """Copy EXIF data from *src_path* and return it as bytes for Pillow save.

    Args:
        src_path: Path to the source image whose EXIF to copy.
        dst_img: Destination PIL Image (unused directly; kept for future use).

    Returns:
        Raw EXIF bytes suitable for passing to ``img.save(exif=...)``,
        or ``None`` if copying fails (logged as a warning, not fatal).
    """
    if not _PIEXIF_AVAILABLE:
        logger.debug("piexif not available – cannot copy EXIF")
        return None
    try:
        exif_dict = piexif.load(str(src_path))
        return piexif.dump(exif_dict)
    except Exception as exc:
        logger.warning("Could not copy EXIF from '%s': %s", src_path, exc)
        return None
