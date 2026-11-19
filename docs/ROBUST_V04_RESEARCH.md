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

It generates one deterministic RS8 packet and saves YCbCr-only, pilot-only, DWT-only, **YCbCr-roundtrip-then-DWT (without pilot)** and full pilot+DWT images, plus amplified difference maps. The extra control distinguishes the effect of a second color roundtrip from the Fourier modulation itself. It measures each stage against the same original and checks exact packet recovery from DWT-only, YCbCr-then-DWT and full PNG and JPEG (quality 85, 75, 60) using **known-size** decoding. This does **not** test blind size synchronization; blind decoding and resizing need their own follow-up tests.

Each stage's color conversions can differ, so the test is a controlled *pipeline ablation*, not an exact physical separation of the pilot and DWT distortion. The script refuses to overwrite existing output images or reuse an existing CSV; use a fresh output folder and CSV name per run.

## Fourier pilot strength sweep

The second user-run ablation showed:

| Stage | PSNR | SSIM-Y | Pixels with RGB channel difference >4 |
| --- | ---: | ---: | ---: |
| DWT only | 43.0921 dB | 0.991425 | 3.5894% |
| YCbCr roundtrip then DWT | 40.6364 dB | 0.991233 | 5.506% |
| Pilot then DWT | 39.2891 dB | 0.982580 | 13.3695% |

A direct comparison of YCbCr-then-DWT with pilot-then-DWT produced PSNR 43.3608 dB and SSIM-Y 0.986399. These numbers support investigating pilot strength before changing DELTA or REPEAT. The user-reported known-size PNG and JPEG 85/75/60 tests passed for all three DWT-bearing stages; this is **not** proof of blind resized-image recovery.

Run a controlled strength sweep on a screenshot:

```bash
python tools/robust_pilot_sweep.py \
  /home/jari/Pictures/0-4-mosaic-in/appfootprint-main.png \
  --out /home/jari/Pictures/0-4-mosaic-out/pilot-sweep-01 \
  --csv results/robust-v04-pilot-sweep-01.csv
```

The default nominal pilot strengths are 0, 0.04, 0.08, 0.12 and 0.18. The codec's **image-level adaptive factor** still applies, so CSV reports nominal and effective strength. All candidates use the same deterministic packet, DWT parameters and number of color roundtrips. The zero-strength control deliberately includes the extra color roundtrip, avoiding the original `_pilot_embed(..., strength=0)` early-return confound. PNG and JPEG recovery checks use the known original size.

To additionally test blind synchronization after 75% resizing, use `--blind-scale 0.75` with a **new output folder and CSV filename**. This can be slow; do not interpret a known-size JPEG PASS as pilot success.

### Blind 75% resize results and next diagnostic

On the user's UI screenshot (1198×677), the nominal pilot strengths 0, 0.04, 0.08 all failed blind recovery after 0.75× resizing, while 0.12 passed after 54 candidates and 0.18 passed on the first candidate. Known-size PNG/JPEG85/75/60 decoding passed for all five strengths. The user reported **visible artifacts at every strength, including zero**, so lowering pilot strength alone does not resolve the DWT visibility issue.

The pilot sweep now reports `oracle@0.75` (resized image decoded with the **true original size**) and `rank` (position of the exact original size in the blind candidate search, or `None` if absent). This separates two failure classes:

- `oracle=FAIL`: bits do not survive resizing at the true size; changing pilot strength or search order alone cannot repair the payload.
- `oracle=PASS, rank=None`: packet survives but the true original size is absent from the bounded search; investigate Fourier peak detection, search budget and dimension estimation.
- `oracle=PASS, rank=N`: exact size is present; blind decode should normally recover, barring a distinct control-flow/candidate issue.

The 0.12 result (54 candidates) is a useful research point, **not** a safe default: robustness across images, crops, JPEG after resize, and other scales is unmeasured. Preserve a separate next test directory and CSV; the tool does not overwrite previous runs.

### Oracle-scale and blind-search result

On the 1198×677 screenshot scaled to 75%, the oracle-size recovery and exact original-size candidate rank were:

| Nominal Fourier strength | Oracle packet recovery | Exact-size candidate rank |
| ---: | :---: | ---: |
| 0.00 | FAIL | absent |
| 0.04 | FAIL | absent |
| 0.08 | FAIL | absent |
| 0.12 | PASS | 54 |
| 0.18 | PASS | 1 |

The `oracle` decoder restores the image to the original dimensions with Lanczos before reading LL2. Therefore a FAIL may reflect quantized bit damage after downsample+upsample, not just the Fourier size estimate. A missing rank means absent from the **bounded** candidate list, not necessarily absent from all possible scales.

Run `tools/robust_resize_diagnostics.py` against the existing pilot-sweep directory to count repeated QIM errors, majority-voted packet bit errors, header errors and Reed–Solomon codeword byte errors before correction. This diagnoses whether failures are dominated by header damage or codeword damage. It does not modify the codec or original files.

```bash
python tools/robust_resize_diagnostics.py \
  /home/jari/Pictures/0-4-mosaic-out/pilot-sweep-02 \
  --scale 0.75 \
  --csv results/robust-v04-resize-errors-01.csv
```

**Visual interpretation:** the user clarified that the original `pilot-sweep-reference.png` is clean; all `strength-*.png` outputs contain DWT embedding, and the black-background `*-vs-zero-diff.png` files amplify differences by 12×. Amplified diff visibility must not be confused with normal-view perceptibility.

### 75% resize: packet bit errors and vulnerable CLR1 header

The user's `robust-v04-resize-errors-01.csv` confirms that the three weak-pilot failures are dominated by **one corrupted bit in the unprotected 16-bit CLR1 codeword-length field**, not wholesale data loss. Only real encoded images count; the first diagnostics version accidentally included `*-vs-zero-diff.png` (12×-amplified visual difference maps), which are **not stego images** and yield meaningless packet-error rows. The tool now filters them.

| Pilot nominal | Repeated QIM errors after resize | Majority bit errors | Header bit errors | RS codeword byte errors | Oracle |
| ---: | ---: | ---: | ---: | ---: | :---: |
| 0.00 | 517 | 1 | 1 | 0 | FAIL |
| 0.04 | 516 | 2 | 1 | 1 | FAIL |
| 0.08 | 509 | 2 | 1 | 1 | FAIL |
| 0.12 | 499 | 1 | 0 | 1 | PASS |
| 0.18 | 500 | 1 | 0 | 1 | PASS |

RS8 corrects up to four **codeword byte** errors but does not cover the 6-byte CLR1 header. A single majority-voted length-bit error causes `Invalid CLR1 length` and prevents attempting Reed–Solomon recovery, even when the codeword is otherwise intact or within RS8's correction capability.

The diagnostics tool now offers a **one-bit length repair probe**, limited to the oracle-size scenario. It flips one of the 16 observed length bits, tries bounded plausible packet lengths, and accepts a candidate only if RS8 decoding plus CRC32 validates and the payload matches the known test message. This is research instrumentation, **not** a production decoder change. A PASS would support a backward-compatible header recovery strategy. It cannot by itself solve weak-pilot blind size estimation: the true size was absent from the bounded search for strengths 0–0.08.

```bash
python -m pytest tests/test_robust_resize_diagnostics.py -q
python tools/robust_resize_diagnostics.py \
  /home/jari/Pictures/0-4-mosaic-out/pilot-sweep-02 \
  --scale 0.75 \
  --csv results/robust-v04-resize-errors-02.csv
```

### Validated one-bit CLR1 length recovery (decoder-only change)

The second diagnostic run on **encoded images only** reported `length_repair=PASS:len=52,bit=11` for nominal pilot strengths 0, 0.04 and 0.08. The measured post-resize majority-voted packet had only 1–2 bit errors, of which one was in the unprotected 16-bit length field. Flipping bit 11 changed the observed length 2100 back to 52. All three packets passed RS8+CRC32 validation after that correction.

`src/robust_image.py:decode_at_size` now has a bounded **single-bit length recovery fallback**. The normal decode path is unchanged. When the CLR1 magic is intact but the length is invalid or the codeword fails RS8/CRC32 validation, the fallback tries at most 16 one-bit length variants within the 12..255-byte codeword bound and the available DWT capacity. It accepts only a packet whose RS8+CRC32 validation succeeds. The encoder, CLR1 wire format, seed, QIM parameters and stored images are unchanged. Synthetic regression tests are in `tests/test_robust_header_repair.py`.

**Important limitations:**
- The previous `oracle=FAIL` measurements were made with the *old* decoder. Rerunning the diagnostics after this fix will naturally change `oracle` and `length_repair` to PASS/NOT_NEEDED; preserve the previous CSV as baseline.
- Recovery of the packet at the **known original size** does not solve blind original-size discovery. For strengths 0–0.08 the true original size was absent from the bounded Priority50 candidate list. The next separate problem is Fourier pilot synchronization.
- This fallback does not recover a damaged CLR1 magic or two or more corrupted length bits. It does not guarantee success for other covers, scales, crops or JPEG recompression.
- Run unit tests and the oracle-scale test on the user's machine before considering the decoder change validated end-to-end.

### Multi-cover validation plan (30 local PNG/JPEG files)

The user assembled 30 diverse PNG/JPEG files in
/home/jari/Pictures/0-4-mosaic-in. They include UI screenshots, smaller
JPEGs and multi-megabyte camera JPEGs. Actual content and dimensions must be
measured rather than inferred from filenames.

Use tools/robust_batch_matrix.py to run the same deterministic packet and
DWT settings across **all** covers at nominal pilot strengths 0, 0.12 and 0.18.
Each marked image is tested via PNG-equivalent in-memory RGB, JPEG quality
85/75/60 (4:4:4, subsampling=0), and Lanczos resize to 75%/50% followed
by oracle-size decode. PSNR/SSIM and local distortion metrics are measured
against the codec-preprocessed RGB reference (maximum dimension 1280).
Small images that cannot hold the packet are recorded as SKIP, not
silently omitted. Results are streamed into a new CSV file after each cover.

**First, a three-image smoke test:**

```bash
python -m pytest tests/test_robust_batch_matrix.py -q
python tools/robust_batch_matrix.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name appfootprint-main.png \
  --name P1000450.JPG \
  --name AarneArmeijassa.jpg \
  --csv results/robust-v04-multicover-smoke-01.csv \
  --images-out /home/jari/Pictures/0-4-mosaic-out/multicover-preview-01
```

**Then all 30 images (CSV only by default):**

```bash
python tools/robust_batch_matrix.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --csv results/robust-v04-multicover-01.csv
```

The tool refuses to overwrite existing CSV files and nonempty image output
directories. It never writes to the source directory. The input JPEGs are
already lossy; JPEG q85/q75/q60 tests apply **additional compression after
embedding**. Saving marked PNGs is optional to avoid creating dozens of
large files. If interrupted, completed rows remain in the CSV; reruns need
a new output filename.

**Interpretation:** all scale results in this matrix are *oracle-size*,
not blind. Even pilot strength 0 may pass when the true size is provided.
Blind original-size estimation and pilot synchronization should be evaluated
as a separate stage, based on this matrix's cover/quality failures and
representative cases. A 5/5 result on one cover does not generalize.

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
