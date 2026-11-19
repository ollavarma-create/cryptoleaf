# CryptoLeaf v0.4 research branch — first checkpoint

Branch: `feature/v0.4-robust-mosaic`. The stable `main` branch is untouched.

## What changed

- `src/robust_image.py` is the **user-supplied experimental version** (symmetric nearest-parity QIM, image-level adaptive Fourier pilot). It has **not yet passed a full paired robustness benchmark**. This is not a released v0.4 codec.
- `tools/robust_quality_compare.py` compares an unmarked reference and a marked image without modifying either. It records full-reference quality metrics and can generate a magnified difference image.
- `tests/test_robust_quality_compare.py` checks the diagnostic metric implementation.

No mosaic implementation, adaptive DELTA/REPEAT negotiation, or new wire format has been added yet.

## First experiment: image quality

From the repository root with your venv active:

```bash
python tools/robust_quality_compare.py \
  /home/jari/Pictures/blogiin/appfootprint-main.png \
  /path/to/marked.png \
  --label screenshot-dwt-01 \
  --csv results/robust-v04-quality.csv \
  --diff results/screenshot-dwt-01-diff.png
```

The reference and marked image must have the same pixel dimensions. If the encoder downscaled a larger original to its output size, add `--resize-reference` **only** when this reproduces the encoder's preprocessing. Otherwise, a resize will contaminate the quality measurements.

Metrics include:

- **PSNR** and **SNR**, in dB (null for a zero-error comparison).
- **SSIM on luminance** (mean and 1st percentile).
- RGB mean absolute error, maximum absolute error and 99th-percentile per-pixel difference.
- Percentage of pixels changed at all, by more than 4, and by more than 8 intensity units.
- Signed luminance change, and the percentages of pixels brightened or darkened.
- The location and mean luminance error of the **worst 16×16 tile**.
- Newly saturated output pixels (0 or 255). **This is not a measurement of internal clipping before the codec's clamp**; that requires instrumenting the encoder.
- Optional 12× magnified RGB difference image for human review.

Keep original and encoded images for side-by-side viewing at 100% zoom. The human assessment is the primary judgment of objectionable artifacts; these numbers are diagnostic evidence, not a substitute for it.

## Controlled pilot / DWT ablation

The first three manual comparisons on a 1198×677 UI screenshot found:

| Pair | PSNR | SSIM-Y | Pixels with RGB channel difference >4 |
| --- | ---: | ---: | ---: |
| Original vs YCbCr roundtrip | 46.3015 dB | 0.999916 | 0% |
| Original vs pilot-only | 42.7988 dB | 0.990689 | 2.1724% |
| YCbCr control vs pilot-only | 45.2567 dB | 0.990764 | 0.226% |

These are user-reported metrics from the manually generated images; the exact provenance of the pilot-only image must still be confirmed. SSIM on flat UI regions is particularly sensitive to weak structured perturbations. Pixel percentages and PSNR values are not additive across stages.

To remove ambiguity about how each test image was created, run this reproducible experiment from the repository root:

```bash
python tools/robust_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in/appfootprint-main.png \
  --out /home/jari/Pictures/0-4-mosaic-out/ablation-01 \
  --csv results/robust-v04-ablation-01.csv
```

It generates one deterministic RS8 packet and saves YCbCr-only, pilot-only, DWT-only and full pilot+DWT images, plus amplified difference maps. It measures each stage against the same original and checks exact packet recovery from DWT-only/full PNG and JPEG (quality 85, 75, 60) using **known-size** decoding. This does **not** test blind size synchronization; blind decoding and resizing need their own follow-up tests.

Each stage's color conversions can differ, so the test is a controlled *pipeline ablation*, not an exact physical separation of the pilot and DWT distortion. The script refuses to overwrite existing output images or reuse an existing CSV; use a fresh output folder and CSV name per run.

## Fair comparison rules

1. Freeze the original image, preprocessing dimensions, payload bytes and output format.
2. Change **one variable at a time**; preserve the old algorithm as a control.
3. Measure image quality **and** exact payload recovery separately (PNG, JPEG quality 85/75/60, and scaling where applicable).
4. For DELTA/REPEAT experiments, the decoder must use matching values. Changing only encoder constants does not establish a valid new format. A self-describing header or fixed bootstrap decoder is future work.
5. The existing `CLR1` format is unchanged. Never silently introduce a new parameter scheme that breaks v0.3 decoding.
6. Use the same packet bytes for paired image-quality comparisons; encryption with a random nonce otherwise changes the bit pattern between runs.
7. Keep a CSV row for every trial, including failures. A successful saved PNG round trip does **not** imply JPEG or crop robustness.

## Next tasks (not implemented yet)

1. Run the existing regression suite on this branch; diagnose any encoder/decoder regressions.
2. Investigate the feedback loop: on a wrong bit, recomputing the nearest parity from an observed coefficient may return the same QIM index. Instrument iteration counts and pre-clamp luminance.
3. Build a controlled parameter sweep of DELTA, REPEAT, feedback and pilot strength with identical packet bytes, capacity checks and explicit decode outcomes.
4. Choose a reproducible image-level adaptation policy and a backward-compatible decoder signaling strategy.
5. Add a versioned mosaic transport layer above the image codec, including image-loss recovery tests.
