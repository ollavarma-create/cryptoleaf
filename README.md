# Cryptoleaf – Steganography Tool v0.2.1

Hide encrypted messages inside image and audio files. Messages are AES-256-CBC
encrypted before embedding, so inspecting the file alone reveals nothing without
the password.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)

> **This tool may only be used for lawful purposes.**
> It is intended for privacy protection, digital watermarking, and research.
> The author does not condone illegal use.

---

## Download

**Cryptoleaf — pre-built binaries for multiple platforms:**
Releases are available in the `/Distit` directory.

1. **Windows** — unzip and run `Cryptoleaf.exe`:
   https://codeberg.org/hiltsu/cryptoleaf/src/branch/main/Distit/Cryptoleaf-0.2.1-windows-x64.zip.zip
2. **Linux (legacy)** — for older systems (gcc10, Python 3.11), use `legacy.AppImage`:
   https://codeberg.org/hiltsu/cryptoleaf/src/branch/main/Distit/cryptoleaf-legacy.AppImage
3. **Linux (modern)** — for newer systems (gcc14, Python 3.12), use `modern.AppImage`:
   https://codeberg.org/hiltsu/cryptoleaf/src/branch/main/Distit/cryptoleaf-modern.AppImage

**Linux notes:**
- Run `chmod +x` on the downloaded file before launching.
- If `fuse` and `libfuse2` are not already installed, install them via `apt`/`dnf`.

**Previous version (v0.1.1) with binaries:**
https://codeberg.org/hiltsu/old_v0.1_steganography_encrypter_decrypter

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
git clone https://github.org/ollavarma-create/cryptoleaf
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

### Command Line

The tool is GUI-based. Direct module use is available for developers:

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

### Image Hiding — Method A (PNG, BMP, WEBP)

DWT + spread spectrum: the message is embedded into the 2D Discrete Wavelet Transform
domain of the image (PyWavelets, `db1`, level 2) in the LH and HL subbands. Each bit
is spread across multiple coefficients using a PRNG (seed = password).
Reed-Solomon error correction (RSCodec(32)) protects the payload.

- Capacity: depends on image size and alpha value
- Lossless format: change is visually imperceptible
- Does not survive lossy compression

### Image Hiding — Method B (JPEG)

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

## Project Structure

```
Cryptoleaf.py          # Entry point
src/
  image_encoder.py    # Image hiding: LSB (PNG/BMP/WEBP) + Method B (JPEG)
  image_decoder.py    # Image extraction: LSB / DWT (legacy) / Method B
  audio_encoder.py    # Audio hiding: 1-bit LSB
  audio_decoder.py    # Audio extraction
  crypto.py           # AES-CBC encryption/decryption, PBKDF2 key derivation
  error_correction.py # Reed-Solomon + Hamming(7,4) error correction
  gui.py              # PyQt6 GUI — main window, tabs, worker threads
  utils.py            # Shared utilities (logging, format detection, EXIF)
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
