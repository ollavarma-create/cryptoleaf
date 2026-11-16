# Testing Cryptoleaf's experimental Robust image mode

Cryptoleaf v0.3 alpha includes an **experimental** short-message image transport based on a Fourier synchronization pilot, Haar DWT/QIM embedding, repetition, Reed–Solomon error correction and password-protected AES-256-GCM payloads. Its goal is to explore whether hidden messages can remain recoverable after some ordinary image transformations. **It does not guarantee survival of social-media processing, concealment from steganalysis, or protection of image metadata.**

## Quick reproducible test

1. Start with an image you own or have permission to use. Record its dimensions, format and approximate file size. Avoid sensitive photos and real secrets.
2. In the **Image** tab, choose **Robust – short encrypted messages** and enter a short test message and a test password.
3. Save a new output file, preferably using a different filename. Confirm Cryptoleaf can extract the message from the **saved output** before making further changes.
4. Make a **copy** of the stego image. Apply **one** transformation (for example JPEG recompression, resizing or a format conversion), or upload and download it through a platform you want to evaluate.
5. Attempt extraction from the transformed/downloaded image with the same password. Compare the extracted message with the original **exactly**. Record success, failure or an error message.
6. Repeat with different images and transformations. Keep the untouched original stego file as the control.

The application may be able to recover some resized or recompressed images, but success depends on image content, message size, output format and transformation. A local JPEG quality setting is not equivalent to every social platform's processing pipeline.

## Suggested test matrix

| Variable | Examples |
| --- | --- |
| Carrier | Photograph, illustration, detailed texture, smooth gradients |
| Dimensions | Original; 75%, 50%, 150%, 200% resizing |
| Recompression | JPEG quality 95, 85, 75, 60 (note software and encoder) |
| Format | JPEG, PNG, WebP; convert only one step at a time |
| Platform | A named messaging or social service, including the exact upload/download workflow |
| Payload | Short and longer messages within the displayed capacity |
| Result | Exact match, authentication/decoding failure, or another reported error |

These are **suggested experiments**, not claimed passing results or a compatibility matrix.

## Reporting a result

Please include:

- Cryptoleaf version, OS and how the application was installed (release ZIP, AppImage, or source).
- Original carrier format, pixel dimensions and approximate file size (no need to share private photographs).
- Output stego format and approximate message length in **UTF-8 bytes**; do **not** disclose the password or a sensitive message.
- Exact transformation sequence and tools/settings, or platform and upload/download method.
- Transformed file dimensions and format, if known.
- Whether the unmodified stego file decoded successfully, and whether the transformed copy decoded **exactly**.
- Any error text and steps to reproduce.

Share reports via the repository's [GitHub Issues](https://github.com/ollavarma-create/cryptoleaf/issues). Please avoid uploading private photos, passwords, personal location data or other confidential material.

## Interpreting results

- **Round-trip success before transformation** confirms only that the saved carrier could be decoded under the tested conditions.
- **A single successful transformation** is encouraging but does not establish a reliable success rate.
- **A failure** is useful evidence: record the input and exact processing sequence, and compare it with a control.
- **Dry run** in the Batch tab estimates processing and reports capacity-related skips; it does not create stego output or demonstrate successful encoding.
- Image **EXIF metadata** can retain GPS coordinates, camera model and capture time independently of the hidden message. Cryptoleaf's message encryption does not protect this metadata.

## Scope and security

Robust mode is research-oriented, not an independently audited secure communication channel. Steganography does not guarantee undetectability. Do not depend on the experimental transport for irreplaceable information or high-risk secrecy.

Cryptoleaf is developed with substantial assistance from OpenAI's ChatGPT (GPT-6); project direction and acceptance testing remain human-led. External reproducible test reports are especially valuable for challenging assumptions and identifying failures.
