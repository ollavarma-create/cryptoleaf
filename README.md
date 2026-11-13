# Cryptoleaf — Steganography Tool

**Published release:** v0.2.1 · **In development:** JPEG v0.3 (`feature/jpeg-v03`)

Hide messages inside image and audio files, with optional password-based encryption.
The published v0.2.1 release and the in-development JPEG v0.3 branch have
different capabilities; features under **JPEG v0.3 development** are not claimed
to be included in the published binaries. Do not treat steganography alone as a
guarantee of confidentiality or undetectability.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)

> **This tool may only be used for lawful purposes.**
> It is intended for privacy protection, digital watermarking, and research.
> The author does not condone illegal use.

---

## Download

**Published v0.2.1 binaries (not JPEG v0.3 builds):**
Releases are available in the `/Distit` directory.

1. **Windows** — unzip and run `Cryptoleaf.exe`:
   https://github.com/ollavarma-create/cryptoleaf/tree/main/Distit/Cryptoleaf-0.2.1-windows-x64.zip.zip
2. **Linux (legacy)** — for older systems (gcc10, Python 3.11), use `legacy.AppImage`:
   https://github.com/ollavarma-create/cryptoleaf/tree/main/Distit/cryptoleaf-legacy.AppImage
3. **Linux (modern)** — for newer systems (gcc14, Python 3.12), use `modern.AppImage`:
   https://github.com/ollavarma-create/cryptoleaf/tree/main/Distit/cryptoleaf-modern.AppImage

**Linux notes:**
- Run `chmod +x` on the downloaded file before launching.
- If `fuse` and `libfuse2` are not already installed, install them via `apt`/`dnf`.

---

## Features

- **Image support**
  - PNG, BMP, WEBP → LSB method (lossless, high capacity)
  - JPEG → Block-based luminance (Method B): survives JPEG compression at quality ≥ 75
- **Audio support**
  - WAV, FLAC → 1-bit LSB in int16 samples, inaudible, high capacity
- **Encryption**: AES-256-CBC, key derived with PBKDF2-HMAC-SHA256 (200,000 iterations)
- **Error correction**
  - Lossless images: Reed-Solomon RSCodec(32)
  - JPEG: Hamming(7,4) + 3× repetition — tolerates ~20% bit-stream errors
  - Audio: Reed-Solomon RSCodec(64) for header and payload
- **Format conversion**
  - Images can be saved in a different format than the source: e.g. JPG → PNG, WEBP, or BMP
  - Audio can be saved in a different format than the source: e.g. MP3 → WAV or FLAC
  - Conversion happens automatically at save time — simply choose the desired output format
- **GUI**: PyQt6, separate tabs for images and audio, drag-and-drop, capacity meter,
  remaining-space counter, EXIF display, image preview, About tab

---

## Installation

**Requirements:** Python 3.10+

```bash
git clone https://github.com/ollavarma-create/cryptoleaf.git
cd cryptoleaf
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python Cryptoleaf.py
```

> **Note:** If you are using Python 3.13+, add `audioop-lts` to `requirements.txt`.

### Dependencies

| Package | Purpose |
|---------|---------|
| pillow | Image read/write |
| piexif | EXIF metadata reading |
| pyqt6 | Graphical user interface |
| pycryptodome | AES encryption |
| numpy | Array computation |
| scipy | Signal processing |
| PyWavelets | DWT (legacy decoder) |
| pydub | Audio I/O (MP3) |
| reedsolo | Reed-Solomon error correction |
| soundfile | WAV/FLAC I/O |
| audioop-lts | *(Python 3.13+ only)* Python 3.13+ compatibility |

---

## Usage

### Graphical Interface

```bash
python Cryptoleaf.py
```

**Hiding a message (image):**

1. Select an image file (PNG/JPG/BMP/WEBP) by drag-and-drop or file browser
2. Enter your message — the remaining capacity counter updates in real time
3. Enter a password (optional — without a password the message is stored unencrypted)
4. Choose the output format — **you can select a different format than the source**,
   e.g. a JPG image can be saved as PNG, WEBP, or BMP
5. Click **Hide Message** and save the file with a new name

**Hiding a message (audio):**

1. Select an audio file (WAV, FLAC, or MP3)
2. Enter your message and password
3. Choose the output format — **an MP3 file can be saved as WAV or FLAC**,
   embedding the message into a lossless format
4. Click **Hide Message**

**Extracting a message:**

1. Open the stego file
2. Enter the password (if one was used)
3. Click **Extract Message**

### Command Line (published v0.2.1)

The published version is GUI-based. Direct module use is available for developers:

```python
from src.image_encoder import encode_image
from src.image_decoder import decode_image

# Hiding
stego = encode_image("cover.png", b"secret message", password="passphrase")
stego.save("stego.png", format="PNG")

# Extracting
data = decode_image("stego.png", password="passphrase")
print(data.decode("utf-8"))
```

### Test Files

The `testitiedostoja/` directory contains original and stego files.
The password for all stego files is `qwerty`.

---

## Technical Description

### Image Hiding — Lossless Images (PNG, BMP, WEBP)

The current image feature list identifies LSB embedding for lossless image formats.
The decoder also supports a legacy DWT-based method. The precise encoding path
and compatibility of older stego files should be verified against the source
before making stronger implementation guarantees. Reed–Solomon protection is
documented for the lossless image payload.

- Capacity: depends on image size and alpha value
- Lossless format: change is visually imperceptible
- Does not survive lossy compression

### Image Hiding — Method B (JPEG, published v0.2.1)

Block-based luminance method, optimised for JPEG's 8×8 DCT grid:

1. Image is converted to YCbCr colour space
2. Each 8×8 block carries one bit: the centre pixel is shifted above or below the
   edge-average (strength ±50 luma units)
3. Error correction: Hamming(7,4) + 3× repetition → 42 raw blocks per data byte
4. Extraction: majority voting + Hamming decoding

Survives JPEG compression at quality ≥ 75 on natural photographs.

- Capacity: `(width÷8 × height÷8) × 4 ÷ 21` bits
- Example: 1920×1080 → approximately 700 bytes of user message

### Audio Hiding (WAV, FLAC)

1-bit LSB method in int16 samples (channel 0):

- Error correction: Reed-Solomon RSCodec(64) for header (32 bytes) and payload
- Capacity: one bit per sample — e.g. 1 min stereo 44100 Hz WAV ≈ 320 KB
- No audible change — LSB modification is ±1 sample value, below the hearing threshold
- Output formats: WAV (PCM_16), FLAC (PCM_24)

### Encryption

- Algorithm: AES-256-CBC (PyCryptodome)
- Key derivation: PBKDF2-HMAC-SHA256, 200,000 iterations, 32-byte key
- Salt: 16 random bytes, stored at the beginning of the payload
- Encryption is applied **before** error correction and embedding
- Without a password, the message is stored unencrypted but protected by error correction

---

## JPEG v0.3 development

The `feature/jpeg-v03` branch introduces a more robust JPEG workflow and a
command-line batch encoder. **These are development-branch features, not features
of the published v0.2.1 installers.**

### JPEG encoding and reliability

- Uses 8×8-block luminance embedding with error protection involving
  Reed–Solomon coding, Hamming(7,4), and 3× interleaving.
- Tries multiple embedding strengths and selects the first strength whose
  **saved JPEG** can be decoded successfully (`first_success`).
- Candidate strengths currently include `10, 15, 20, 30, 40, 50, 60, 80`.
- Reports the selected strength and number of attempts; JPEG output quality
  defaults to 85 in the batch CLI.
- Some images do not have enough usable 8×8 blocks for the protected payload.
  These are classified as **SKIPPED**, rather than as unexpected failures.
- JPEG re-encoding, resizing, cropping, or editing after embedding may damage
  the hidden message. Successful decoding of the saved output does not imply
  survival of arbitrary later transformations.

### Batch encoding CLI

From the repository root, after installing dependencies:

```bash
python batch_encode.py input_images output_images \
  --message "Secret message" \
  --password "choose-a-strong-password"
```

The batch encoder supports JPEG, PNG, BMP, and WEBP inputs. Available options:

```text
--message TEXT     Message to embed (required)
--password TEXT    Password (required)
--quality N        JPEG output quality (default: 85)
--dry-run          Preview the batch without encoding
--skip-existing    Skip files with existing output
```

Each image receives an **OK**, **SKIPPED**, or **FAIL** status. JPEG results
include strength and attempt counts where available. A `batch_report.csv`
file is written to the output directory for non-dry-run batches.

For example, a ten-image JPEG test batch completed with **8 OK, 2 SKIPPED,
0 FAILED**; both skips were caused by insufficient JPEG block capacity. This
is an example result, not a promised success rate for other image collections.

The batch CLI is an **encoder**, not a separate batch extraction command. Use
the appropriate image decoder or GUI extraction workflow to recover messages.

### Development tests

```bash
python -m pytest tests/ -q
```

At the time of this documentation update, **94 tests passed** on the
development branch. This test result is not a security audit or a guarantee
that every image can carry every payload.

---

## Project Structure

```
Cryptoleaf.py          # GUI entry point
batch_encode.py        # Development-branch batch encoding CLI
src/
  image_encoder.py    # Image hiding: LSB (PNG/BMP/WEBP) + Method B (JPEG)
  image_decoder.py    # Image extraction: LSB / DWT (legacy) / JPEG
  jpeg_optimizer.py   # Development-branch JPEG strength optimization
  batch_processor.py  # Development-branch batch engine and CSV reports
  image_quality.py    # Image quality metrics (including PSNR)
  audio_encoder.py    # Audio hiding: 1-bit LSB
  audio_decoder.py    # Audio extraction
  crypto.py           # AES-CBC encryption/decryption, PBKDF2 key derivation
  error_correction.py # Reed-Solomon + Hamming(7,4) error correction
  gui.py              # PyQt6 GUI — main window, tabs, worker threads
  utils.py            # Shared utilities (logging, format detection, EXIF)
benchmarks/             # Performance and reliability experiments
scripts/                # Manual diagnostics
tests/
  test_image_codec.py # Image codec unit and integration tests
  test_audio_codec.py # Audio codec tests
assets/
  application icons and usage screenshots
testitiedostoja/
  original and stego test files (password: qwerty)
```

---

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Test coverage includes:

- DWT/Method B image codec round-trip tests (encode → decode → compare)
- JPEG survival at quality 75 and 85
- LSB audio codec round-trip tests (WAV and FLAC)
- Stereo: only channel 0 is modified
- Wrong password → error raised
- Capacity exceeded → clear error message

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v0.1.1 | April 2025 | Initial release: LSB+DCT images, LSB+RS audio, PyQt6 GUI |
| v0.2.1 | March 2026 | Method B JPEG, MP3 support, EXIF display, QSS styles, About tab |
| JPEG v0.3 (development) | Unreleased | JPEG error protection and strength optimization, batch CLI, reporting and tests |

---

## Documentation notes

The legacy technical sections above describe the published v0.2.1 release.
Before publishing a v0.3 release, verify the encryption parameters, legacy
DWT/LSB compatibility, JPEG capacity formula, binary download paths, and GUI
feature parity against the release commit. The v0.3 branch is not presented
as a completed release here.

---

## License

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
