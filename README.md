# Cryptoleaf

**Cryptoleaf v0.3-dev** — an open-source image and audio steganography application for Linux and Windows, written in Python with a PyQt6 interface.

**Status:** active development. The current development build is **not** a stable v0.3 release. The older v0.2.1 release predates the robust image and batch features described below.

Cryptoleaf hides short messages in images or audio. Some modes support password-based encryption. **Steganography is not a guarantee of secrecy or undetectability**, and a successful save does not guarantee survival of subsequent editing, recompression, or resizing.

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> Use Cryptoleaf only for lawful purposes. It is intended for privacy, experimentation, and research. Do not rely on it for high-risk secrecy without independent security review.

## Downloads and development builds

- **Source code:** [GitHub repository](https://github.com/ollavarma-create/cryptoleaf).
- **Linux x86-64 development AppImage:** open the [AppImage GitHub Actions workflow](https://github.com/ollavarma-create/cryptoleaf/actions/workflows/appimage.yml), choose a successful run, and download the `cryptoleaf-v0.3-dev-linux-x86_64` artifact. Extract the ZIP downloaded from Actions, then make the `.AppImage` executable.
- **Published releases:** check [GitHub Releases](https://github.com/ollavarma-create/cryptoleaf/releases) for any formally published versions. A successful development workflow run does **not** create a release.

Run a downloaded AppImage on Linux:

```bash
chmod +x Cryptoleaf-v0.3-dev-x86_64.AppImage
./Cryptoleaf-v0.3-dev-x86_64.AppImage
```

The AppImage is currently built on Ubuntu 22.04 with Python 3.11 and packaged using PyInstaller and appimagetool. It is tested automatically under Xvfb and has also been manually exercised on Fedora KDE. Compatibility with every Linux distribution has not been established.

The former `Distit/` binary directory is no longer maintained in the development tree. Build artifacts belong in GitHub Actions or, when a release is ready, GitHub Releases.

## Features

| Mode | Inputs / outputs | Description |
| --- | --- | --- |
| **Image → Robust** | Images; output PNG, JPEG, WebP or BMP | Short **password-required** messages using authenticated AES-256-GCM, a Fourier synchronization pilot, Haar DWT/QIM embedding, repetition and Reed–Solomon protection. Saved output is verified before being accepted. |
| **Image → Capacity** | PNG, BMP, lossless WebP | Higher-capacity LSB embedding; optional legacy AES-CBC encryption. Legacy image extraction remains available. |
| **JPEG compatibility / optimization** | JPEG | Legacy block-based JPEG extraction and the JPEG v0.3 strength-optimization path. A saved JPEG candidate must decode successfully before it is accepted. JPEG capacity and reliability depend on the image. |
| **Batch** | JPEG, PNG, BMP, WebP | Encode a message into multiple images, verify each saved result, report OK / SKIPPED / FAIL, and export a CSV report. |
| **Audio** | WAV / FLAC, with MP3 input support through conversion | LSB embedding in PCM audio, optional legacy password encryption, and WAV/FLAC output. |

The GUI has **Image**, **Batch**, **Audio**, and **About** tabs. It also provides file selection, previews and background workers for lengthy operations.

### Important limits

- Robust mode is designed for **short** messages; its payload limit and usable capacity are image-dependent. It is experimental and is not a claim of resistance to steganalysis.
- Robust decoding includes a search for image-size changes; success on a particular resized image does not establish reliability under arbitrary cropping, filters, social-media recompression or transformations.
- The Capacity/LSB mode is not designed to survive lossy recompression.
- The JPEG optimizer checks the JPEG it actually saves. Editing the resulting JPEG later may destroy its payload.
- For important data, retain the original message and verify extraction from the final carrier before sharing it.

## Install from source

Use a supported Python version; **Python 3.11** is the version used by the Linux CI build.

```bash
git clone https://github.com/ollavarma-create/cryptoleaf.git
cd cryptoleaf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python Cryptoleaf.py
```

On Windows, activate the environment with `.venv\Scripts\activate` and run `python Cryptoleaf.py`. Some audio conversion workflows may additionally require FFmpeg. On Python 3.13+, older pydub installations may need the `audioop-lts` compatibility package.

Runtime dependencies are listed in [requirements.txt](requirements.txt), including PyQt6, Pillow, PyCryptodome, NumPy, SciPy, PyWavelets, reedsolo, pydub and soundfile.

## Using the application

### Image: robust mode

1. Open **Image** and select **Robust – short encrypted messages**.
2. Choose the source image, enter a short message and a nonempty password.
3. Select an output format and save to a **different filename**.
4. Allow the application to verify the saved image. For extraction, open the resulting file, select the corresponding mode, enter the password and extract the message.

### Image: capacity mode

Select **Capacity – lossless LSB / legacy decode** for a higher-capacity, lossless carrier. Password encryption is optional in this mode. Use a lossless output format to avoid destroying LSB payload bits.

### Batch GUI

Choose separate input and output folders, enter the message and password, and start batch encoding. You can also request a dry run or skip files that already have outputs. The GUI displays per-file results and saves a CSV report.

**Verification is part of batch processing:** for PNG/BMP/WebP, the program decodes the saved temporary file and compares the result byte-for-byte with the original message. For JPEG, the optimizer saves and decodes candidate JPEGs, trying another strength when needed. A result marked **OK** therefore means the saved candidate passed its round-trip check. Published JPEG outputs are hard links to the verified temporary files.

### Batch command line

```bash
python batch_encode.py input_images output_images \
  --message "Example message" \
  --password "choose-a-strong-password"
```

Options include `--quality N` (default 85 for JPEG), `--dry-run` and `--skip-existing`. The CLI reports per-image results and normally writes `batch_report.csv`. It performs encoding, not bulk extraction. Output files are not silently overwritten.

### Audio

Select the **Audio** tab, choose an input file, enter the message and optional password, then save a supported lossless output. Use the extraction controls to read it back. The audio codec uses one channel's PCM least-significant bits and Reed–Solomon protection.

## Encryption and compatibility

Cryptoleaf currently contains **two distinct encryption formats**:

- **Legacy Capacity/image and audio encryption:** AES-256-CBC with a 16-byte salt, 16-byte IV and PBKDF2-HMAC-**SHA1**, 200,000 iterations. This derivation is deliberately retained for compatibility with existing files. CBC encryption does not provide authenticated encryption.
- **Robust image encryption:** AES-256-GCM with PBKDF2-HMAC-**SHA256**, 200,000 iterations, a 16-byte salt, 12-byte nonce and 16-byte authentication tag. The payload is authenticated, so an incorrect password or altered ciphertext is rejected.

Do not confuse these formats or assume all old stego files can be decoded with every new mode. Neither the application nor these parameters constitute an independent cryptographic security audit.

## Tests and continuous integration

Install development dependencies and run:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The suite covers image/audio codecs, JPEG optimization, batch behavior, encryption and robust image transport. Test counts change as development continues; refer to the current CI run rather than a fixed historical number.

The [AppImage workflow](.github/workflows/appimage.yml) runs pytest before building the Linux package, checks Qt XCB dependencies, smoke-tests GUI startup under Xvfb, and uploads an AppImage artifact when successful.

The packaging script is [packaging/build-appimage.sh](packaging/build-appimage.sh). It uses [assets/icon.png](assets/icon.png) for the Linux application icon; [assets/icon.ico](assets/icon.ico) is available for Windows packaging.

## Repository layout

```text
Cryptoleaf.py             GUI entry point
batch_encode.py           Batch CLI
src/                      Image, audio, encryption and robust codecs; GUI
tests/                    Automated tests
benchmarks/               Performance and reliability experiments
scripts/, tools/          Development diagnostics and benchmarks
assets/                   Application icons
packaging/                Linux AppImage build script
.github/workflows/        CI and AppImage build workflow
requirements.txt          Runtime Python dependencies
requirements-dev.txt      Test/development dependencies
```

The old `Distit/` and `testitiedostoja/` directories are removed from the development tree. Local test images and generated binaries should not be committed. Test fixtures needed by automated tests belong under `tests/`.

## Project status and history

- **v0.1.1 (2025):** initial image/audio steganography GUI.
- **v0.2.1 (2026):** legacy JPEG and audio/image feature development.
- **v0.3-dev (unreleased):** JPEG optimization, batch processing, experimental Fourier/DWT robust mode, authenticated encryption for robust messages, and automated Linux AppImage builds.

This README describes the current development code, **not** a claim that these features exist in previously published v0.2.1 binaries.

## License

Cryptoleaf is distributed under the **MIT License**. See the repository's license notice and source-file headers for the applicable terms.
