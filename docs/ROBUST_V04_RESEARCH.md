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

### Four failed-cover types at 50% resize: working hypothesis

In the 30-cover CSV, 531/540 oracle-size tests passed. The nine failures
were limited to four covers: Anna Maria Liikanen.jpg, Anna Pitkänen 1864.jpg,
appfootprint-main.png, and cryptoleaf-robust.png. All but one failure occurred
at 50% Lanczos resize; the exception was pilot-free cryptoleaf-robust.png
at 75%. All four covers have fine high-contrast lines/text and substantial
uniform regions, but that visual similarity is not a proven cause: other
covers with sharp edges passed. Failures were not monotonic in pilot strength,
and no common source dimension threshold is evident.

The CSV stores only FAIL:ValueError; it cannot distinguish damaged CLR1 magic,
multiple header bit errors, RS8 codeword corruption exceeding four bytes, or
other decode failures. Do not modify the pilot or DWT parameters on this
evidence alone.

To reproduce the failing covers and compare **passing controls on the same
covers** at both 75% and 50%, without saving any marked images:

```bash
git pull --ff-only
python -m pytest tests/test_robust_multicover_diagnostics.py -q
python tools/robust_multicover_diagnostics.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --matrix results/robust-v04-multicover-01.csv \
  --csv results/robust-v04-multicover-errors-01.csv
```

This reproduces 4 covers × 3 pilot strengths × 2 resize scales = 24
diagnostic rows and records raw QIM errors, majority bit errors, CLR1
magic and length bit errors, and codeword byte errors. RS8 can correct
up to four corrupted codeword bytes. The reported oracle result is based
on the current production decoder (including the one-bit length fallback).
The test is deterministic but requires the original input images, not
messaging-service resized copies.

### Measured 24-case diagnostics: eight magic errors and one RS8 failure

The user's robust-v04-multicover-errors-01.csv reproduced **all 24**
expected outcomes (four covers, three pilot strengths, two scales).
Of nine failures, **eight** had damaged CLR1 magic and one had intact
header but five erroneous RS codeword bytes. The 16-bit length was
correct in all nine failures.

- cryptoleaf-robust.png: four failures (one at 75%, three at 50%);
  **one magic bit** wrong, 0–1 codeword bytes wrong
- Anna Pitkänen 1864.jpg: one failure at 50%, strength 0.18;
  **one magic bit** wrong, two codeword bytes wrong
- appfootprint-main.png: one failure at 50%, strength 0;
  intact magic and length, **five codeword bytes** wrong
- Anna Maria Liikanen.jpg: three failures at 50%;
  **two magic bits** wrong, **22–24 codeword bytes** wrong;
  33–34 majority-voted bits wrong overall

A **bounded one-bit CLR1 magic recovery** was added to the decoder, analogous
to the previously validated one-bit length repair. If the observed magic
differs by exactly one bit from CLR1, the decoder substitutes CLR1 only as
a candidate, then requires RS8 correction and CRC32 validation. The fast
path, encoder, stored format, seed, DWT, and Fourier pilot are unchanged.
The decoder still rejects two-bit magic damage. This should recover the
five cases with one magic-bit error and <=4 codeword-byte errors, yielding
**536/540** oracle-size successes if verified on the user's machine.
It cannot repair the four cases that exceed the RS8 budget.

Run regression tests and rerun the *same* multicover matrix with a new CSV
name to verify the prediction. Do not compare the new matrix's failures
as though they were independent trials; the covers, packet, and transformations
are deliberately identical:

```bash
git pull --ff-only
python -m pytest tests/test_robust_header_repair.py tests/test_robust_multicover_diagnostics.py -q
python tools/robust_multicover_diagnostics.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --matrix results/robust-v04-multicover-01.csv \
  --csv results/robust-v04-multicover-errors-02.csv
```

In the rerun, five improved cases should show oracle PASS and
reproduced=False because reproduced compares to the **old** matrix.
All other outcomes should match. Keep the original CSVs as baseline.
These experiments still do not test blind original-size synchronization.

### One-bit magic repair verified on real covers (2026-11-19)

The user reran `tools/robust_multicover_diagnostics.py` and supplied
`robust-v04-multicover-errors-02.csv`. All **five predicted** single-bit
magic recoveries succeeded. Of 24 targeted cases, 20 now pass (15 old passes
plus five repairs). No previously passing targeted case regressed.

The full 30-cover matrix's implied updated result is **536/540 (99.26%)**,
up from 531/540 (98.33%), *assuming the unchanged 516 cases retain their
previous outcomes*. The entire 540-case matrix has **not** been rerun yet.
All figures refer to **oracle-size** decoding and do not establish blind
Fourier synchronization.

The remaining four failures, all at 50% Lanczos resizing, are:

| Cover | Pilot | Magic bit errors | Codeword byte errors | Majority bit errors | Near-tie votes |
| --- | ---: | ---: | ---: | ---: | ---: |
| appfootprint-main.png | 0.00 | 0 | 5 | 5 | 21 |
| Anna Maria Liikanen.jpg | 0.00 | 2 | 24 | 33 | 89 |
| Anna Maria Liikanen.jpg | 0.12 | 2 | 22 | 33 | 88 |
| Anna Maria Liikanen.jpg | 0.18 | 2 | 23 | 34 | 88 |

The 50% appfootprint failure is only **one codeword byte beyond RS8's
four-byte error-correction budget**, with intact header. A future
*diagnostic-only* RS erasure-confidence probe may be worthwhile, but a
correctable erasure pattern must be demonstrated, not assumed. A versioned
packet change would be required before shipping a different parity scheme.

Anna Maria Liikanen.jpg has 22–24 damaged codeword bytes and two damaged
magic bits at 50% resize; RS8 erasures alone cannot recover that many
bytes. The raw repeated-QIM errors after resizing are 1114–1128 and
near-tie votes 88–89, much worse than the appfootprint failure
(619 raw QIM errors, 21 near ties). Investigate stronger/repeated
embedding or content-dependent robustness using paired quality and
decode measurements; do not assume increasing the Fourier pilot helps.
For all four cases the initial embedded packet had zero majority-bit
errors before resizing.

Next: freeze this result, investigate the four remaining 50%-resize
failures with controlled encoder/decoder-matched DWT parameters, then
separately test **blind** original-size search on representative covers.
Do not merge an experimental parameter change into production without
a backwards-compatible signaling/format plan.

### Fixed-pilot DELTA/REPEAT ablation: two residual 50%-resize covers

A dedicated **research-only** tool,
`tools/robust_dwt_parameter_sweep.py`, tests the two remaining failing
covers (`appfootprint-main.png` and `Anna Maria Liikanen.jpg`) using
the exact same deterministic 40-byte message and RS8 packet as the
previous matrix. The Fourier pilot is fixed at **0.0** by default and
all candidates use the same cover preprocessing and RGB/YCbCr roundtrip.

The baseline is **DELTA=32, REPEAT=9**. Two independent sweeps vary only
one factor at a time:

- DELTA: 24, 28, 32, 36, 40, 48, 56, 64; REPEAT fixed at 9
- REPEAT: 5, 7, 9, 11, 13, 15, 17; DELTA fixed at 32

The baseline appears only once, so there are **14 parameter pairs per
cover (28 encodes)**. Every case evaluates PNG, JPEG q60, 75% and 50%
Lanczos resize, all with **oracle original size**; it records PSNR,
SSIM, worst local luma distortion, raw QIM/majority-vote errors before
and after 50% resizing, CLR1 magic/length errors, RS8 codeword-byte
errors, DWT capacity and timing. The encoder and decoder use the **same**
DELTA and REPEAT for each case; temporary global parameter changes are
restored even on exceptions. No source images or production constants
are changed. CSV is written incrementally and never overwritten.

Run a short six-encode smoke test first:

```bash
git pull --ff-only
python -m pytest tests/test_robust_dwt_parameter_sweep.py -q
python tools/robust_dwt_parameter_sweep.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --deltas 32,40 \
  --repeats 9,11 \
  --csv results/robust-v04-dwt-smoke-01.csv
```

If that works, run the full fixed-pilot one-axis sweep:

```bash
python tools/robust_dwt_parameter_sweep.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --csv results/robust-v04-dwt-sweep-01.csv
```

Do not interpret a single 50%-resize PASS as a suitable new default.
First check that the baseline reproduces the two earlier failures,
that PNG/JPEG60/75% still pass, and that PSNR/SSIM/local artifacts are
acceptable. If a promising pair is found, validate it across all 30
covers and more image transformations. Only then investigate blind
original-size discovery, initially with a representative subset.

**Compatibility caveat:** changing DELTA or REPEAT changes the on-image
QIM layout. The current CLR1 packet does not encode these parameters.
The experiment is therefore NOT a backwards-compatible codec update;
shipping a new setting requires a versioned signaling/bootstrap plan
or a carefully bounded compatible decoder search. Do not merge parameter
changes into production on the basis of this sweep alone.

### DWT one-axis sweep results and next paired experiment

The user supplied `robust-v04-dwt-sweep-01.csv`: **28 rows** covering
two residual problem images, seven nonbaseline DELTA settings, six
nonbaseline REPEAT settings, and one baseline per image. The test uses
fixed pilot 0.0, identical payload, matched decoder parameters and
known original image size.

- `appfootprint-main.png`: baseline DELTA=32/REPEAT=9 fails at 50%
  resize (five erroneous RS8 bytes). **32/11 passes** all four
  PNG/JPEG60/75%/50% tests with PSNR 40.2962 dB vs baseline 40.5537.
  REPEAT 13/15/17 also pass. DELTA=64/REPEAT=9 passes but PSNR falls
  to 37.5162 and SSIM to 0.971494. DELTA 28/36 at REPEAT 9 fail even
  unmodified PNG; parameter changes are non-monotonic.
- `Anna Maria Liikanen.jpg`: baseline 32/9 fails 50% resize
  (24 erroneous RS8 bytes). **48/9 passes** all four tests with
  three erroneous RS8 bytes at 50% resize, PSNR 43.8292 dB and SSIM
  0.993027 vs baseline 47.0953 dB and 0.996427. DELTA 56/64 also
  pass. REPEAT increases up to 17 at DELTA 32 do **not** pass 50%.
- The **only parameter pair tested and shown to pass both covers** is
  DELTA=64/REPEAT=9. That pair substantially worsens visual quality.
  The best per-cover pairs are *different*. This is not yet evidence
  that one good universal pair exists, nor that adaptive per-cover
  parameter choice is decodable without explicit signaling.

The tool now accepts explicit paired combinations via `--pairs` and
all 30 local covers via `--all-covers`. Next, search a small
two-dimensional DELTA/REPEAT neighborhood on the **two** problem covers
to find a possible common pair with less visual damage:

```bash
git pull --ff-only
python -m pytest tests/test_robust_dwt_parameter_sweep.py -q
python tools/robust_dwt_parameter_sweep.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pairs 32:9,32:11,40:11,40:13,44:11,44:13,48:9,48:11,48:13,64:9 \
  --csv results/robust-v04-dwt-pairs-01.csv
```

This runs 20 encodes (10 matched pairs × two covers), each with four
oracle-size checks and quality metrics. If one or two lower-distortion
pairs pass both covers, validate them **across all 30 images** with
`--all-covers --pairs <candidate1>,<candidate2>` using a new CSV
name, then separately test blind size discovery. Do not modify the
production DELTA/REPEAT constants or assume that candidate pairs are
backward-compatible with the existing format.

### Matched two-axis DWT sweep: 20 real-cover encodes

The user supplied `robust-v04-dwt-pairs-01.csv` with **20 OK rows**,
two covers × ten explicit DELTA:REPEAT pairs, fixed pilot 0.0.
Of 80 oracle-size decoding attempts, **61 passed** (PNG 20/20,
JPEG q60 16/20, 75% resize 15/20, 50% resize 10/20).

Only **DELTA=64, REPEAT=9** passes all four transformations on **both**
covers. It produces zero codeword-byte errors after 50% resize on both,
but compared with 32/9 the quality cost is large:

| Cover | PSNR 32/9 → 64/9 | SSIM 32/9 → 64/9 | Worst local luma MAE |
| --- | --- | --- | --- |
| appfootprint-main.png | 40.5537 → 37.5162 dB | 0.990218 → 0.971494 | 4.7184 → 8.3684 |
| Anna Maria Liikanen.jpg | 47.0953 → 40.9657 dB | 0.996427 → 0.987796 | 1.7917 → 5.2083 |

The **32/11** pair passes all four for AppFootprint, but fails Anna Maria
at 50% (16 codeword-byte errors). Conversely, **40/11** passes Anna Maria
at 50% (3 erroneous codeword bytes, one correctable magic bit), but fails
AppFootprint at 50% (9 erroneous codeword bytes). All 44/48 combinations
tested fail AppFootprint at 50%, some even at JPEG q60 or 75% resize.
This non-monotonic behavior warrants a narrow follow-up search; do not
adopt 64/9 as a production default yet.

A focused 13-pair experiment includes the four control pairs
32:11, 40:11, 48:9, 64:9 and nine untested intermediate pairs
34:11, 36:11, 38:11, 34:13, 36:13, 38:13, 52:9, 56:9, 60:9:

```bash
git pull --ff-only
python tools/robust_dwt_parameter_sweep.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pairs 32:11,34:11,36:11,38:11,40:11,34:13,36:13,38:13,48:9,52:9,56:9,60:9,64:9 \
  --csv results/robust-v04-dwt-pairs-02.csv
```

This is 26 encodes (13 pairs × two covers) and 104 known-size
transformation checks. If any lower-distortion pair passes both
covers, verify it against the full 30-cover corpus using
`--all-covers --pairs ...` before moving to blind original-size
discovery. A candidate passing these two images is not a universal
result. The blind decoder will also need a nonzero pilot and a
parameter-discovery or version-signaling strategy.

### Narrow two-axis sweep: a lower-distortion shared candidate

The user supplied `robust-v04-dwt-pairs-02.csv` with **26 OK
encodes** (13 parameter pairs × two covers). There were **81/104
successful oracle-size decodes**: PNG 24/26, JPEG q60 23/26, 75%
resize 23/26, 50% resize 11/26. These are separate transformations,
not a combined resize+JPEG test.

**DELTA=38, REPEAT=13, pilot=0** passes all four transformations
on both previously failing covers (8/8). So does DELTA=64/REPEAT=9,
but 38/13 has better PSNR, SSIM and worst local luminance distortion:

| Cover | PSNR 38/13 vs 64/9 | SSIM 38/13 vs 64/9 | Worst local luma MAE 38/13 vs 64/9 | RS8 codeword byte errors after 50% |
| --- | --- | --- | --- | --- |
| appfootprint-main.png | 39.4615 vs 37.5162 dB | 0.982019 vs 0.971494 | 3.9880 vs 8.3684 | 0 vs 0 |
| Anna Maria Liikanen.jpg | 43.6895 vs 40.9657 dB | 0.990911 vs 0.987796 | 2.9961 vs 5.2083 | 1 vs 0 |

Compared to the original 32/9 baseline, 38/13 still costs
**1.0922 dB** PSNR on AppFootprint and **3.4058 dB** on Anna Maria.
The new setting uses **13/9 ≈ 1.44×** as many DWT coefficients for the
same packet; capacity constraints on small covers must be measured.
At 50% resize Anna Maria has two majority-vote bit errors in one
codeword byte, recovered by RS8+CRC32; AppFootprint has zero.

Other paired candidates do not pass both covers at 50%:
38/11 passes AppFootprint but fails Anna Maria (six codeword bytes
and two magic bits), while 40/11 passes Anna Maria but fails
AppFootprint (nine codeword bytes). The successful 38/13 point is
therefore a discrete empirical result, not proof of monotonicity.

**Next gate: whole-corpus validation**, without modifying production
constants or adding the pilot yet:

```bash
git pull --ff-only
python -m pytest tests/test_robust_dwt_parameter_sweep.py -q
python tools/robust_dwt_parameter_sweep.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --all-covers \
  --pairs 32:9,38:13,64:9 \
  --csv results/robust-v04-dwt-fullcover-01.csv
```

This is **30 covers × 3 pairs = 90 encodes**, with four independent
oracle-size transforms per successful encode (up to 360 checks).
Check capacity skips, image-quality distributions, all four decode
statuses, and whether 38/13 introduces new failures elsewhere.
The zero-pilot sweep cannot test blind size discovery.

If 38/13 passes the corpus with acceptable quality, the next phase
must reintroduce a *nonzero* Fourier pilot, distinguish oracle
recoverability from blind synchronization, and solve decoder
parameter discovery. Changing DELTA/REPEAT is **not compatible**
with the current CLR1 format unless signaled or searched safely.

### Whole-corpus DWT 38/13 validation and blind-sync entry point

The user supplied `robust-v04-dwt-fullcover-01.csv`:
**90/90 successful encodes**, three matched parameter pairs × 30
covers, fixed pilot 0.0. The four independent known-size recovery
checks produced:

| DELTA/REPEAT | PNG | JPEG q60 | 75% resize | 50% resize | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| 32/9 | 30/30 | 30/30 | 30/30 | 28/30 | 118/120 |
| **38/13** | **30/30** | **30/30** | **30/30** | **30/30** | **120/120** |
| 64/9 | 30/30 | 30/30 | 30/30 | 30/30 | 120/120 |

Across all 30 covers, mean PSNR (dB) is **39.178 (32/9)**,
**38.160 (38/13)** and **36.871 (64/9)**. Mean luma SSIM is
**0.988**, **0.978** and **0.965**, respectively. The 38/13
candidate has higher PSNR **and** SSIM than 64/9 on *every* cover
in this corpus, not merely on average. These numbers do not prove
visual invisibility, robustness to combined transformations or
steganalytic resistance.

The capacity and quality worst case for 38/13 is
`AarneArmeijassa.jpg`, encoded at **273×391**: it uses **89.20%**
of LL2 coefficients for this fixed 58-byte packet; PSNR **32.7727 dB**,
SSIM **0.866180**. Longer messages may not fit this cover. The
DWT 38/13 parameter pair is a *candidate*, not a production default:
it still lacks a backward-compatible signaling scheme.

**Important blind-search limitation:** the production Fourier peak
search currently uses `_peaks(low=.70, high=1.02)`, so a genuine
**0.50×** downscale lies outside its supported pilot-scale search
window. The oracle success at 50% does NOT imply blind success.
The 75% case is within that window, but candidate ranking may
still fail to include the exact encoded dimensions. Additionally,
the pilot's highest ring at 0.195 cycles/pixel maps to about 0.39
cycles/pixel after 50% scaling, slightly beyond the current radial
profile's 0.38 upper bound; simply widening the scale search may
not be enough.

A new **research-only** tool
`tools/robust_blind_sync_probe.py` probes five representative covers:
the two hard covers, the small-capacity worst case, the
CryptoLeaf UI screenshot and a camera photo. It holds **DELTA=38,
REPEAT=13** fixed, tests pilot strengths **0/0.12/0.18** and resize
factors **0.75/0.50**. It records (a) oracle recovery, (b) the
true original size's rank in the **unchanged** Priority50 candidate
search, and (c) its rank in an *experimental widened*
`_peaks(low=.45, high=1.02)` search. It also records candidate
counts, best peak scores, nearest size distance and PSNR/SSIM.
The widened search **only ranks** candidates; it never feeds them
to the production decoder. Thus no algorithm change is smuggled
into a result.

First run the fast rank-only diagnostic (30 rows; **no blind
decoding**):

```bash
git pull --ff-only
python -m pytest tests/test_robust_blind_sync_probe.py -q
python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --csv results/robust-v04-blind-sync-rank-01.csv
```

After reviewing whether the true size is in the 160-candidate budget
and whether the pilot causes any oracle regression, run a **small**
actual blind decode with `--blind`, for example on one cover and
one pilot strength at 75%:

```bash
python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name appfootprint-main.png \
  --pilot-strengths 0.12 \
  --scales 0.75 \
  --blind \
  --csv results/robust-v04-blind-sync-actual-01.csv
```

This still uses *known DWT parameters* for the decoder; it is
blind only with respect to the original image dimensions. No
production parameters or on-image format have been changed.
Do not claim 50% blind support until it is actually demonstrated
with a validated widened-search decoder and independent controls.

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
