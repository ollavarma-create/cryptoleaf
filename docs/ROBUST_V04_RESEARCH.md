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

### Fourier blind-size ranking on five representative covers

The user supplied `robust-v04-blind-sync-rank-01.csv`:
**30/30 oracle-size decodes PASS**, with five covers × three nominal
pilot strengths (0, 0.12, 0.18) × two Lanczos resize scales
(75%, 50%), fixed DWT **38/13**. The *actual* blind decoder was
**not run** in this CSV (`blind_status=NOT_RUN` for every row).

Exact encoded dimensions among the first 160 Fourier candidates:

| Received resize | Production .70–1.02 | Experimental .45–1.02 |
| --- | ---: | ---: |
| 75% | 6/15 | 6/15 |
| 50% | 0/15 | 2/15 |
| Total | 6/30 | 8/30 |

For both searches, pilot=0 had **0/10** exact-size hits;
pilot=0.12 and 0.18 each had **3/5** hits at 75% in the
production search. Those covers were AppFootprint, Anna Maria
Liikanen and P1000450; the small Aarne and CryptoLeaf screenshot
never had an exact 75%-size hit. The widened search recovered
the exact 50% size only for **P1000450.JPG** at both nonzero
strengths, rank **1**. AppFootprint at 50% came within **one
Manhattan pixel** of the correct dimensions with both nonzero
strengths, but exact size was not in the list. Anna Maria at
50% was at least 92 pixels away at strength .12, Aarne 113
pixels away and CryptoLeaf screenshot 18 pixels away.

The pilot also has a material quality cost on some covers:
Anna Maria PSNR **43.6895 dB** at pilot=0, **38.4070 dB**
at pilot=.12 and **35.6958 dB** at pilot=.18. On Aarne
pilot=.18 reduced PSNR only from 32.7727 to 32.5496 dB,
yet did not improve the candidate rank. More pilot power
is not a general fix. The fixed pilot=0 controls are important
because image-content peaks can mimic a pilot.

The production Fourier search cannot rank true 50% scales
because its minimum scale is .70. Simply extending the scale
range to .45 is **insufficient**: exact-size hit rate is only
2/15 at 50%. The pilot frequency rings near 0.195 cyc/pixel
also move near 0.39 cyc/pixel after 50% reduction, above the
current profile's 0.38 upper bound. This is a hypothesis for
further controlled signal-processing analysis, not a proven
cause of every miss. A size candidate not exactly matching
the original dimensions may still decode; the rank test
does not establish actual blind success or failure.

**Next narrow gate:** verify that the matched DWT decoder
actually recovers a message when Fourier ranks the exact
dimensions, before changing pilot/size estimation. The
research probe now supports `--extended-blind`, which
attempts decoding only from the widened Fourier candidates;
it never uses the known original size as a hint or modifies
the production decoder. Run one 75% production case and one
50% extended case:

```bash
git pull --ff-only
python -m pytest tests/test_robust_blind_sync_probe.py -q

python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name appfootprint-main.png \
  --pilot-strengths 0.12 --scales 0.75 --blind \
  --csv results/robust-v04-blind-actual-75-01.csv

python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name P1000450.JPG \
  --pilot-strengths 0.12 --scales 0.5 --extended-blind \
  --csv results/robust-v04-blind-actual-50-01.csv
```

If both succeed, pilot size ranking is the principal
remaining limitation in these selected cases; do not
generalize from two successes to all covers. Next examine
pilot peak scores and alternative scale estimators at 50%
and investigate the one-pixel AppFootprint miss. Do not
change the CLR1 format, production parameters or adaptive
pilot strength based on this diagnostic alone.

### First two actual blind decoding successes (2026-11-19)

The user supplied two **single-row** actual blind-decode CSVs, both
using **DELTA=38, REPEAT=13**, pilot strength 0.12, with matched
experimental codec parameters. These are **actual decodes**, not merely
size-rank diagnostics:

| CSV | Cover | Resize | Search | True embedded size | Decoded size | Attempts | Outcome |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| `robust-v04-blind-actual-75-01.csv` | appfootprint-main.png | 75% (898×508) | Existing production-size search, .70–1.02 | 1198×677 | 1198×677 | 1 | PASS |
| `robust-v04-blind-actual-50-01.csv` | P1000450.JPG | 50% (640×480) | Research-only extended-size search, .45–1.02 | 1280×960 | 1280×960 | 1 | PASS |

Both also have oracle PASS. Recorded case runtimes are
0.17 and 0.16 seconds respectively. For the 75% AppFootprint
case, the unchanged production peak search's best scale is
**0.750**, and the true size ranks **1**; the widened peak
search instead ranks a false scale **0.558** first and places
the true size at **rank 54**. For the 50% P1000450 case,
the production peak search's best scale is **0.712** and
does not contain the true size in 160 candidates; the widened
search ranks **0.500** and the true size **first**.

The original camera image P1000450.JPG is 4000×3000, but
the codec resampled it to **1280×960 before embedding**.
The decoder correctly discovers the latter, not the camera
source dimensions.

**Interpretation:** 38/13 can genuinely decode blind to the
*encoded* image dimensions in both a 75% and a 50% example,
with a nonzero Fourier pilot. The 50% result required a
**research-only** widened search; production has NOT gained
general 50% blind support. Neither example establishes
performance across the corpus, and the current production
on-image 32/9 format remains unchanged. Naively widening
the peak range can degrade candidate ordering for 75% cases.

**Next discriminating tests using the existing tool** (no
codec change): examine whether a low-ranked exact size can
still decode and whether a one-pixel-near size is sufficient.

```bash
git pull --ff-only
python -m pytest tests/test_robust_blind_sync_probe.py -q

# Anna Maria at 75%: true size ranked 107/160 with pilot .12
python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name "Anna Maria Liikanen.jpg" \
  --pilot-strengths 0.12 --scales 0.75 --blind \
  --csv results/robust-v04-blind-anna-75-01.csv

# AppFootprint at 50%: widened list is within one pixel,
# but the exact encoded size is not in the first 160
python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name appfootprint-main.png \
  --pilot-strengths 0.12 --scales 0.5 --extended-blind \
  --csv results/robust-v04-blind-appfootprint-50-01.csv
```

These may require up to 160 DWT decodes each and take
longer than the first two one-attempt cases. If the
one-pixel-near case fails, a **bounded** ±1-pixel neighborhood
test can be added to the research tool, with strict budgets
and no oracle-size hint. In parallel, compare a two-band
pilot peak strategy or a wider radial profile (0.38 currently
truncates the outermost pilot ring after 50% resize), while
measuring false peaks and visual distortion. Do not simply
increase pilot amplitude: the prior rank CSV shows it can
degrade PSNR substantially without recovering more covers.

### Blind recovery without exact pixel dimensions: two successes

The user supplied `robust-v04-blind-anna-75-01.csv` and
`robust-v04-blind-appfootprint-50-01.csv`. Both have one
`status=OK`, `oracle=PASS` row. The **actual** blind
decodes also **PASS** at matched DELTA=38, REPEAT=13,
pilot strength 0.12:

| Cover | Resize | Fourier search | True encoded dimensions | Successful decoded dimensions | Attempt | Elapsed |
| --- | --- | --- | --- | --- | ---: | ---: |
| Anna Maria Liikanen.jpg | 75% (960×650) | Current production-size search | 1280×867 | **1280×868** | 85 | 2.57 s |
| appfootprint-main.png | 50% (599×338) | Experimental widened search | 1198×677 | **1200×677** | 146 | 2.94 s |

In Anna Maria, the exact encoded size ranked **107/160** but
decoding succeeded earlier, at a candidate **one pixel taller**.
In AppFootprint, the exact encoded size did **not** appear in
the 160 widened candidates, yet a candidate **two pixels
wider** successfully decoded. This establishes that *exact
size rank* is an insufficient proxy for **actual blind
recoverability**. The decoded payload must match exactly,
validated by RS8 and CRC32; candidate-size equality is
not required.

**Plausible mechanism grounded in the implementation:**
The two-level Haar DWT uses `mode='periodization'`; its LL2
grid is `ceil(height/4) × ceil(width/4)`. In both successful
wrong-size cases the grid dimensions are unchanged:

- Anna Maria: 1280×867 and 1280×868 both give **217×320** LL2.
- AppFootprint: 1198×677 and 1200×677 both give **170×300** LL2.

The seeded permutation of LL2 coefficient positions therefore
stays identical; slight differences in image resampling can
remain within QIM voting and RS8 correction margins.
This is a strong *mechanistic hypothesis*, **not** proof that
all candidates sharing the LL2 shape can decode or that a
different LL2 shape always fails.

The research tool now emits for both blind methods:
`*_width_error_px`, `*_height_error_px`, and
`*_same_ll2_shape`, with empty values for unsuccessful
or unattempted decodes. Regression tests cover the two
observed size pairs and the four-pixel LL2 grid boundaries.

**Next: actual blind-recovery matrix** on the same five
representative covers, at pilot strengths 0.12 and 0.18.
At 75%, compare the existing search and the widened search
side-by-side; at 50%, use only the widened search (production
does not search near 0.50). These are separate, reproducible
experiments, and no oracle hint is fed to blind decoding:

```bash
git pull --ff-only
python -m pytest tests/test_robust_blind_sync_probe.py -q

# 5 covers × 2 pilot strengths = 10 rows, 20 blind searches
python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pilot-strengths 0.12,0.18 \
  --scales 0.75 --blind --extended-blind \
  --csv results/robust-v04-blind-matrix-75-01.csv

# 5 covers × 2 pilot strengths = 10 rows, 10 blind searches
python tools/robust_blind_sync_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pilot-strengths 0.12,0.18 \
  --scales 0.5 --extended-blind \
  --csv results/robust-v04-blind-matrix-50-01.csv
```

This is **20 encoded images and 30 actual blind searches**,
each bounded to 160 Fourier candidates (plus the production
decoder's two fallback candidates at 75%). A test may take
minutes when many candidates fail. Compare actual PASS rate,
successful size offsets/LL2-grid agreement, search attempts,
and pilot-induced image quality. These five covers were
chosen for diagnostic diversity, not as an unbiased random
sample. No claim of universal blind recoverability or
invisibility follows from two or twenty tests.

### Actual blind 5-cover matrix: 20 oracle passes, 10 blind passes

The user supplied `robust-v04-blind-matrix-75-01.csv` and
`robust-v04-blind-matrix-50-01.csv`: five selected covers ×
pilot strengths 0.12/0.18 × resize factors 75%/50%, matched
DWT **38/13**, four independent received images per cover.

- **20/20 oracle-size PASS**: the message survived all tested
  transforms when the encoded dimensions were supplied.
- **75%: production-size blind search 6/10 PASS; widened
  research-size search also 6/10 PASS**, on the exact same
  cases. Both strengths pass AppFootprint, Anna Maria and
  P1000450; both fail AarneArmeijassa and cryptoleaf-robust.
- **50%: widened research-size blind search 4/10 PASS**,
  both strengths for AppFootprint and P1000450; both fail
  Anna Maria, AarneArmeijassa and cryptoleaf-robust.
  The production-size blind decoder was **NOT_RUN** at 50%.
- Across the **20 distinct cases, 10/20 blind PASS** with
  the relevant search variant. The 75% standard/extended
  outcomes are two methods applied to the same ten cases,
  **not** ten additional independent images.

All ten successful widened blind decodes had **identical
LL2 grid dimensions** to the true encoded image, even when
pixel dimensions differed. Four successes were at non-exact
pixel sizes: Anna Maria 75% at 1280×868 instead of 1280×867
for both pilot strengths; AppFootprint 50% at 1200×677
(strength .12) or 1200×678 (strength .18) instead of
1198×677. The observed results support the *LL2 shape
hypothesis*, but identical shape is not sufficient evidence
of successful QIM voting.

| Cover | 75% actual blind, .12/.18 | 50% extended blind, .12/.18 |
| --- | --- | --- |
| AppFootprint | PASS 1/1 attempts | PASS 146/120 attempts |
| Anna Maria Liikanen | PASS 85/1 attempts (production); 72/1 extended | FAIL 74/82 extended attempts |
| AarneArmeijassa | FAIL both | FAIL both |
| cryptoleaf-robust | FAIL both | FAIL both |
| P1000450 | PASS 2/2 attempts | PASS 1/1 attempts |

The difference between an exact-size **candidate rank**
and actual **decode attempt count** is important: candidates
with dimensions exceeding MAX_LONGEST=1280 or the pixel cap
are skipped, and decoding can succeed on a nearby non-exact
size before the exact candidate. E.g. P1000450 at 75%
has exact candidate rank 20 but decodes in two safe attempts.
AppFootprint at 75% strength .12 has extended true-size
rank 54 despite succeeding in one safe attempt.

Increasing pilot strength from .12 to .18 makes Anna
Maria 75% succeed in one attempt instead of 85 with the
production search, but its PSNR falls from **38.4070**
to **35.6958 dB**; both strengths still fail at 50%.
Increasing strength does not rescue Aarne or CryptoLeaf.
Do not change production pilot strength on this evidence.

**Next discriminating experiment:** the strongest pilot
peak often lies far from the true scale on the failed
covers (Aarne .894 instead of ~.75; CryptoLeaf .912
instead of .75). The outermost Fourier ring at .195
cycles/pixel moves to ~.39 after 50% resizing, beyond
the current .38 profile limit. Test whether false peaks
are caused by frequency truncation and/or interference
from outer pilot rings. The new **research-only**
`tools/robust_pilot_spectral_ablation.py` compares four
detectors on identical marked/received images:

| Variant | Pilot rings correlated | Profile max frequency |
| --- | --- | --- |
| all38 | All 32 (baseline widened search) | .38 cyc/pixel |
| inner38 | Only original radii <=.16 | .38 |
| all48 | All 32 | .48 |
| inner48 | Only original radii <=.16 | .48 |

All variants use the same 0.45–1.02 scale search,
Priority50 ordering, max 160 candidates, pilot strengths
and **unchanged on-image embedding**. The ablation
reports true-scale correlation, peak ranking, exact-size
rank and the first safe candidate with the same LL2
grid. A grid hit is a diagnostic, **not a successful
decode**. It performs an independent oracle-size
control but **no blind decode**. A true-size label is
used only in metrics, not to reorder candidates.

```bash
git pull --ff-only
python -m pytest tests/test_robust_pilot_spectral_ablation.py -q

python tools/robust_pilot_spectral_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --csv results/robust-v04-pilot-spectral-01.csv
```

The expected output is **80 rows** (five covers ×
two strengths × two resize scales × four detectors).
Compare each variant against all38 **on the same cases**.
If a variant substantially increases same-LL2-grid
coverage without degrading controls, validate it
with actual blind decoding before touching production.
If not, investigate a more discriminative pilot
template or coarse-to-fine scale estimator instead of
simply enlarging the candidate budget or amplitude.

### Pilot spectral ablation results: 80/80 oracle PASS, no coverage gain

The user supplied `robust-v04-pilot-spectral-01.csv`:
five representative covers × pilot strengths .12/.18 ×
75%/50% resizing × four spectral detectors = **80 rows**,
all `status=OK`, all `oracle=PASS`. No actual blind
decoding was performed in this experiment.

Number of received-image cases with **at least one safe
candidate matching the true encoded LL2 grid** among the
first 160 Fourier candidates:

| Detector | 75% | 50% | Total (20 unique images) |
| --- | ---: | ---: | ---: |
| all38 (widened baseline) | 6/10 | 4/10 | **10/20** |
| inner38 | 5/10 | 4/10 | 9/20 |
| all48 | 5/10 | 4/10 | 9/20 |
| inner48 | 6/10 | 4/10 | **10/20** |

The same two hard covers, **AarneArmeijassa.jpg** and
**cryptoleaf-robust.png**, have zero LL2 grid hits in
either resize condition for all four detectors. Anna
Maria at 50% also has zero. Changing the frequency
ceiling from .38 to .48 or removing outer rings is
**not** sufficient to improve coverage. For AppFootprint
at 50% pilot .18, all48/inner48 move the first matching
LL2 grid from safe candidate **88** to **10**, a useful
per-case ordering gain but not a coverage gain. On
Anna Maria 75% pilot .12, all48/inner38 lose a grid
hit that all38/inner48 retain; detector improvements
are not monotonic.

For all38, the true-scale correlation percentile
on Aarne at 75% is **91.26–92.66** (plausibly pruned
by top-four-peak selection), but at 50% only
**64.34–65.73**. CryptoLeaf at 50% is **40.91–47.20**,
and its true-scale correlation is negative. These
percentiles do NOT establish that the true scale is
a local correlation maximum; increasing the number
of selected peaks might help 75% Aarne but cannot
be assumed to help 50% cases. A weak or absent
true-scale peak is a distinct problem from candidate
budgeting.

**Next controlled diagnostic, without changing
production:** the spectral tool now supports
`--peak-counts` (e.g. 4,8,12) and `--variants`,
and reports the true scale's **local-peak rank**
(if a peak is within ±.01 scale units) and distance
to the nearest local peak. It also accepts
`--pilot-strengths 0,0.12,0.18` with a matched
YCbCr roundtrip for the zero-pilot negative control.
The encoded dimensions are only used to label
the output, never to generate candidate sizes.
All peak budgets use the same total 160-candidate
cap, so this measures peak selection rather than
unbounded brute force.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_pilot_spectral_ablation.py -q

python tools/robust_pilot_spectral_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --variants all38 \
  --pilot-strengths 0,0.12,0.18 \
  --scales 0.75,0.5 \
  --peak-counts 4,8,12 \
  --csv results/robust-v04-pilot-topk-01.csv
```

Expected **90 rows** (5 covers × 3 pilot strengths ×
2 resize factors × 3 peak budgets × 1 detector).
First check whether 8/12 peaks add LL2-grid hits on
the hard covers, and whether the corresponding
true-scale peak is distinguishable from the pilot=0
control. Then decide whether a focused real blind
test is warranted. The zero-pilot control may have
nonzero correlations due to cover structure and
DWT modifications; do not interpret a high raw
score as pilot proof without comparing controls.

### Top-K Fourier peak results: a budget-allocation problem

The user supplied `robust-v04-pilot-topk-01.csv`:
five covers × pilot strengths **0, .12, .18** ×
75%/50% × 4/8/12 correlation peaks = **90 rows**,
all `oracle=PASS` and `status=OK`. There are
**30 distinct received-image cases**, repeated across
three peak budgets; **20** have a nonzero pilot.
This experiment ranks candidate LL2 geometries and
does **not** perform actual blind packet decoding.

Same-LL2-grid coverage among 160 total Fourier candidates
for the 20 nonzero-pilot cases:

| Selected peaks | 75% (10) | 50% (10) | Total (20) |
| --- | ---: | ---: | ---: |
| 4 (current research baseline) | 6 | 4 | **10** |
| 8 | 6 | 5 | **11** |
| 12 | 5 | 4 | **9** |

**New possible recovery:** Anna Maria 50%, pilot .18
has no LL2 match with four peaks, but has a match at
safe candidate **4** with eight and twelve peaks. Its
true-scale local correlation peak ranks **6**. This
is a candidate-grid hit only, **not a demonstrated
blind decode**.

**Budget dilution:** with twelve peaks, Anna Maria
75% pilot .12 loses its previous grid hit (safe
rank 72 at four peaks, 85 at eight), and AppFootprint
50% pilot .12 also loses its hit (90 at four peaks,
126 at eight). AppFootprint 50% pilot .18 moves from
safe rank **88** (four peaks) to **124** (eight)
and **160** (twelve). More peaks are not monotonic
under the unchanged 160-candidate cap and Priority50
allocation.

**Zero-pilot negative control:** P1000450 at 50%,
pilot=0, gains an *exact-size and LL2-grid hit* at
candidate **61** with twelve peaks, even though
no Fourier pilot was embedded. This is not a blind
payload recovery, but demonstrates that an apparently
correct size can be ranked from cover-content
correlations alone. Compare real pilot against
the zero control rather than treating high correlation
as pilot evidence.

**Hard covers and local peak ranks:** at 75% Aarne's
true-scale local peak ranks **15** (pilot .12) and
**14** (.18), outside all tested top-K budgets;
at 50% the ranks are **22** for both strengths.
CryptoLeaf screenshot at 75% ranks **29** (.12)
and **17** (.18); at 50% it has **no local
correlation maximum within ±.01 scale units**
for either strength. Simply increasing top-K
is therefore not a general solution, even before
accounting for budget dilution.

**Next experiment: first-peak quota vs peak count.**
The research-only helper
`priority_candidates_from_peaks` now accepts
`first_peak_quota` (default **50**, unchanged
behavior). The spectral ablation tool accepts
`--first-peak-quotas` and reports the number of
**distinct safe LL2 grids** in the candidate list.
All variants use the same fixed 160-candidate budget.
The exact original dimensions remain oracle/metrics
only; they are never supplied to candidate generation.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_blind_sync_probe.py \
  tests/test_robust_pilot_spectral_ablation.py -q

python tools/robust_pilot_spectral_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --variants all38 \
  --pilot-strengths 0,0.12,0.18 \
  --scales 0.75,0.5 \
  --peak-counts 4,8,16,24 \
  --first-peak-quotas 0,10,25,50 \
  --csv results/robust-v04-pilot-quota-01.csv
```

Expected **480 rows** (5 covers × 3 strengths ×
2 scales × 4 peak budgets × 4 first-peak quotas).
The four-peaks/50-quota slice is an exact reproduction
control for the prior all38 baseline. Compare:
(a) LL2 coverage across **nonzero-pilot** cases,
(b) successful grid's safe attempt rank, (c) number
of distinct LL2 grids searched, (d) zero-pilot
false-size hits, and (e) whether the 14th/15th
Aarne peak ever receives a viable candidate.

If no candidate-allocation setting improves the hard
covers, pivot to a more discriminative synchronization
signal or a scale-estimation method that does not rely
on the strongest raw Fourier peaks. If a setting
improves grid coverage, validate its **actual blind
payload recovery** before any production change.

### First-peak quota matrix: 480-row result, new Aarne candidates

The user supplied `robust-v04-pilot-quota-01.csv`.
**480 rows**, all `oracle=PASS`, all `status=OK`:
five covers × pilot strengths **0, .12, .18** ×
resizes **75%, 50%** × **4,8,16,24** peak counts ×
first-peak quotas **0,10,25,50**. The same 30
received-image conditions are repeated across 16
search strategies. There are **20 distinct nonzero
pilot cases**. The reported outcomes below are
candidate geometry hits, **not blind decodes**.

| Peaks / first quota | 75% LL2 hit | 50% LL2 hit | Total of 20 |
| --- | ---: | ---: | ---: |
| 4 / 50 (baseline) | 6/10 | 4/10 | **10/20** |
| 8 / 10 | 6/10 | 5/10 | **11/20** |
| **16 / 10** | **7/10** | **5/10** | **12/20** |
| 16 / 25 | 7/10 | 3/10 | 10/20 |
| 16 / 50 | 7/10 | 3/10 | 10/20 |
| 24 / 10 | 5/10 | 3/10 | 8/20 |

The **16 peaks / first-peak quota 10** strategy gains
three LL2 grid hits relative to baseline, but loses
one, yielding a net gain of two. Newly recovered
candidate geometries:

- **AarneArmeijassa.jpg, 75%**, pilot .12:
  exact encoded size in candidate list; first matching
  safe LL2 candidate at **25**. The true-scale local
  correlation peak ranks **15**.
- **AarneArmeijassa.jpg, 75%**, pilot .18:
  exact encoded size in candidate list; first matching
  safe LL2 candidate at **24**. The local peak ranks **14**.
- **Anna Maria Liikanen.jpg, 50%**, pilot .18:
  exact encoded size; first matching LL2 at **4**;
  local peak ranks **6**.

The regression is **Anna Maria, 75%, pilot .12**:
baseline LL2 at safe candidate 72, but no matching
grid at 16/10. The 16/10 strategy also pushes
AppFootprint 50% LL2 matches to **158/160** (.12)
and **156/160** (.18), near the candidate budget.
For P1000450 75%, a matching grid moves from
safe attempt **2** to **74**. Thus 16/10 improves
*coverage*, not typical *latency*. Mean safe rank
among successful hits is 45.08 vs baseline 25.90.
A new adaptive/combined strategy would be needed
to preserve easy first-peak successes.

Average distinct safe LL2 grids per nonzero-pilot
case increase from **21.55** (4/50) to **36.55**
(16/10), but many candidate pixel sizes map to
the same LL2 grid. Deduplicating grids outright
would be unsafe because slightly different resampling
dimensions within one grid may change QIM decoding.
Any grid-aware scheduling should retain multiple
nearby pixel-size hypotheses and verify payloads.

**Zero-pilot control:** at 16/10, one of ten
no-Fourier-pilot conditions has an LL2 grid hit
(P1000450 at 50%, safe rank 21). A zero-pilot
grid hit is not a CRC false positive: the DWT
payload was still embedded, so a fortuitously
correct size *might* genuinely decode. It
demonstrates that Fourier candidate geometry
alone does not prove the pilot was detected.

**Next decisive step: actual blind validation of
the new candidate lists.** The spectral research
tool now has an explicit `--blind` switch,
using the existing matched `decode_from_candidates`
helper. It records blind PASS/FAIL, attempts,
decoded dimensions and LL2 agreement. Default
(no `--blind`) remains rank-only. To avoid
hundreds of expensive decodes, run only these
targeted cases:

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_blind_sync_probe.py \
  tests/test_robust_pilot_spectral_ablation.py -q

# Aarne: first actual test of new candidate coverage, two strengths
python tools/robust_pilot_spectral_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name AarneArmeijassa.jpg \
  --pilot-strengths 0.12,0.18 --scales 0.75 \
  --variants all38 --peak-counts 16 \
  --first-peak-quotas 10 --blind \
  --csv results/robust-v04-blind-quota-aarne-75-01.csv

# Anna Maria: newly found candidate at 50%, pilot .18
python tools/robust_pilot_spectral_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name "Anna Maria Liikanen.jpg" \
  --pilot-strengths 0.18 --scales 0.5 \
  --variants all38 --peak-counts 8,16 \
  --first-peak-quotas 10 --blind \
  --csv results/robust-v04-blind-quota-anna-50-01.csv

# Regression control: baseline 4/50 should pass at 75%,
# while 16/10 loses the LL2 grid in this same case.
python tools/robust_pilot_spectral_ablation.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name "Anna Maria Liikanen.jpg" \
  --pilot-strengths 0.12 --scales 0.75 \
  --variants all38 --peak-counts 4,16 \
  --first-peak-quotas 10,50 --blind \
  --csv results/robust-v04-blind-quota-anna-75-01.csv
```

The first two tests each contain **two actual blind
searches**; the third contains **four** and exposes
the regression. The original dimensions are used
only in oracle and diagnostic fields; the actual
blind search sees only the received pixels and
Fourier-ranked candidates. None of these runs
changes production behavior.

A candidate with the exact encoded dimensions
and `oracle=PASS` is a strong predictor of a
blind PASS, but it should be confirmed end-to-end
before claiming improved actual recoverability.
The CryptoLeaf screenshot still has no grid hit
under any tested strategy, and Aarne at 50%
still lacks a grid hit: those remain open
synchronization-signal research problems.

### Confirmed actual blind recovery with 16/10 and 8/10 (four successful searches)

The user supplied two CSVs:
`robust-v04-blind-quota-aarne-75-01.csv` (2 rows) and
`robust-v04-blind-quota-anna-50-01.csv` (2 rows).
**All four** have `status=OK`, `oracle=PASS`,
and, crucially, **`blind_status=PASS`** with
the research-only 0.45–1.02 Fourier search,
matched DWT **DELTA=38 / REPEAT=13**, and 160
maximum candidate sizes. All used first-peak quota 10.
These are **three distinct received-image conditions**
(Aarne .12/.18 and Anna Maria .18), because the
Anna Maria case was searched with both 8 and 16 peaks.

| Cover / received resize / pilot | Peaks | Blind attempts | Decoded dimensions | Actual encoded dimensions |
| --- | ---: | ---: | --- | --- |
| AarneArmeijassa / 75% / .12 | 16 | **25** | **273×389** | 273×391 |
| AarneArmeijassa / 75% / .18 | 16 | **24** | **273×389** | 273×391 |
| Anna Maria / 50% / .18 | 8 | **38** | **1280×867** | 1280×867 |
| Anna Maria / 50% / .18 | 16 | **86** | **1280×867** | 1280×867 |

The two Aarne successes are **new actual blind
recoveries**: the previous four-peak detector failed
on this cover at 75%. Both succeeded at a size two
pixels shorter than the encoded height, preserving
the exact **69×98 LL2 coefficient grid**. The true
size was in the candidate list at unfiltered ranks
89 (.12) and 88 (.18), but the decoder returned
the packet earlier at 273×389. This confirms that
identical LL2 geometry can support a non-exact-size
decode, but does not guarantee it in every case.

Anna Maria at 50% pilot .18 had its first matching
LL2 grid at safe candidate **4** for both peak budgets.
Yet actual recovery required **38** (8 peaks) or
**86** (16 peaks) safe attempts, and both decoded at
the **exact 1280×867** dimensions. This shows why
LL2-grid hit rank is only a diagnostic: resampling
and pixel-level QIM voting still matter. The exact
size appeared at unfiltered ranks 64 and 112,
respectively; unsafe candidates are skipped.

The 8-peak search was substantially more efficient
than 16 peaks for Anna Maria (38 vs 86 attempts)
without changing the embedded image. Thus optimizing
LL2 coverage alone is insufficient: compare actual
PASS rates and attempts on a fixed matrix.

**Open regression control:** Anna Maria 75%, pilot
.12 passed with the old 4/50 strategy, but the
16/10 candidate list had no matching LL2 grid
in the preceding rank-only matrix. Run the
four-search paired control from the preceding
section before proposing a new default. The
CryptoLeaf screenshot and Aarne 50% remain
unsolved by the measured candidate lists.

**Status:** new search is **research-only**; no
production codec change or blind recovery guarantee
has been established for unseen covers, JPEG+resize
combinations, cropping or unknown transformations.

### Anna Maria 75% regression confirmed; staged blind search experiment

The user supplied `robust-v04-blind-quota-anna-75-01.csv`:
**four actual blind decodes** of the same encoded/received
image, Anna Maria Liikanen, pilot .12, 75% resize,
DELTA 38 / REPEAT 13, oracle PASS in every case.

| Fourier peaks / first-peak quota | Blind result | Safe attempts | Recovered dimensions | First matching LL2 safe rank |
| --- | --- | ---: | --- | ---: |
| **4/10** | **PASS** | **38** | 1280×868 | 38 |
| 4/50 | PASS | 72 | 1280×868 | 72 |
| 16/10 | **FAIL** | 75 | — | — |
| 16/50 | **FAIL** | 97 | — | — |

True encoded size was **1280×867**; the
successful one-pixel height mismatch retains the
same LL2 coefficient grid. The actual-scale local
correlation peak ranks **2**, so adding many
other peaks displaced the correct-size candidate
under the 160-candidate budget. The number of
*safe* decoding attempts can be smaller than 160
because oversized hypotheses are skipped.

Rechecking the earlier 480-row quota matrix:
**4/10 and 4/50 both have exactly the same 10/20
nonzero-pilot LL2-hit cases** (not just equal totals).
The mean first safe grid rank for the successful
cases is **15.10** at 4/10 vs **25.90** at 4/50.
This does not establish equal *actual blind* success
on all 20 cases: different pixel dimensions sharing
one LL2 grid can still decode differently.

The **union** of 4/10, 4/50 and 16/10 LL2-hit cases
is **13/20**. The three additions over four-peak
search are Aarne 75% pilots .12 and .18, and Anna
Maria 50% pilot .18; all three have separately
demonstrated real blind recovery. The union does
not mean one 160-candidate strategy achieves 13/20.

A new **research-only** tool,
`tools/robust_pilot_cascade_probe.py`, implements
a fixed fallback order:

1. **4 peaks / quota 10**, up to 160 candidate sizes.
2. If no valid packet, **4 peaks / quota 50**, the
   previous widened research baseline.
3. If still no valid packet, **16 peaks / quota 10**
   to recover additional weaker-scale peaks.

The decoder stops on a packet matching the fixed
payload and skips pixel-size candidates already
tried in an earlier stage. It does **not** deduplicate
by LL2 shape because resizing within a shape can
change packet voting. All three stages use the
same Fourier profile, peak search interval and
marked pixels. Original dimensions are used only
for the separate oracle and output diagnostics.
The fallback increases the **maximum** budget
from 160 to **480 candidate sizes before
cross-stage deduplication**; this is a
coverage/latency/memory tradeoff, **not** a
fixed-budget superiority claim.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_pilot_cascade_probe.py \
  tests/test_robust_blind_sync_probe.py \
  tests/test_robust_pilot_spectral_ablation.py -q

# 20 distinct received-image conditions, actual blind search
python tools/robust_pilot_cascade_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pilot-strengths 0.12,0.18 \
  --scales 0.75,0.5 \
  --csv results/robust-v04-blind-cascade-01.csv
```

Expected **20 rows**. Report **actual blind PASS
count**, successful stage, cumulative safe attempts,
stage-by-stage safe attempts, and actual decoded
dimensions. Compare the results with the earlier
10/20 baseline under its single-stage 160-candidate
limit. If the cascade recovers 13/20, investigate
how to reduce its additional work while retaining
those successes. If fewer than 13/20, inspect the
individual candidate lists and decode ordering,
not only LL2 grid geometry.

**Not yet addressed:** CryptoLeaf screenshot
at either scale and Aarne at 50% have no
corresponding LL2 grid hits in the measured
candidate lists; a new synchronization estimator
may be necessary. No production change should
follow until measured blind recovery, latency and
image quality justify it.

### Actual staged blind search: 13/20 recovered, second stage redundant on these covers

The user supplied `robust-v04-blind-cascade-01.csv`:
**20 rows**, five covers × two nonzero pilot strengths
(.12/.18) × two LANCZOS resizes (75%/50%), with
DWT **DELTA=38, REPEAT=13** and fixed
`4:10,4:50,16:10` research-only cascade.
Every `status=OK` and every oracle-known-size
decode **PASS**.

**Actual blind recovery: 13/20 (65%)**, including
**8/10 at 75%** and **5/10 at 50%**. This
confirms the prior 13/20 *union of LL2-grid hits*
as real packet recovery on this particular
five-cover, two-strength, two-resize test matrix.

| Successful stage | Recovered cases | Safe decoder attempts |
| --- | ---: | --- |
| **4/10** | **10** | median **2**, mean **23.9** (1–106) |
| **4/50** | **0 additional** | **0 additional** across all 20 rows |
| **16/10** | **3 additional** | cumulative **129**, **157**, **175** |
| Unrecovered | **7** | **184–270** safe attempts |

The 16/10 stage rescues **Aarne 75%** pilots
.12/.18 (decoded **273×389**, encoded **273×391**)
and **Anna Maria 50%** pilot .18 (decoded exact
**1280×867**). These three are the only additional
blind recoveries over 4/10. Across all 13 successes,
the median cumulative number of safe decoder calls
is **7** (mean **53.85**), because three rescued
cases are expensive. Total measured time across
the 20 rows is **32.887 seconds** on the user's
machine; this is an exploratory local measurement,
not a benchmark across systems.

**Critical redundancy finding:** the 4/50 stage
made **zero new safe decoder calls** in every row.
Its generated candidates were either already seen
at 4/10 or unsafe. For Anna Maria 50% pilot .18,
4/50 generated 28 additional pixel dimensions but
all were unsafe; otherwise it generated no new
dimensions. It therefore did not improve
recoverability in this matrix. This does not prove
4/50 is globally redundant on unseen covers.

**Seven unrecovered cases** (all oracle PASS):

- **CryptoLeaf screenshot** at both resize factors
  and both pilot strengths: **4 failures**.
- **Aarne** at 50% with both strengths:
  **2 failures**.
- **Anna Maria** at 50% with pilot .12:
  **1 failure**.

The screenshot is the most persistent failure;
the 16-peak search does not produce a correct
LL2 geometry in the preceding rank-only sweep.
Do not conflate its failure with DWT data loss:
all four oracle-known-size tests pass.

**Next minimal simplification experiment:** run
the same 20 images with `--stages 4:10,16:10`,
holding the 160-candidate-per-stage budget and
all other variables fixed. Compare
`blind_status`, `blind_decoded_size`,
`blind_attempts` and `successful_stage`
row-by-row against the three-stage CSV. Expect
the same recoveries and safe-attempt counts in
this dataset, since the removed stage made no
safe decoder calls. `stages_run`,
`unique_pixel_candidates_generated` and
`new_candidates_by_stage` will differ by design.

```bash
git pull --ff-only
python -m pytest tests/test_robust_pilot_cascade_probe.py -q
python tools/robust_pilot_cascade_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pilot-strengths 0.12,0.18 \
  --scales 0.75,0.5 \
  --stages 4:10,16:10 \
  --csv results/robust-v04-blind-cascade-two-stage-01.csv
```

If the two-stage version matches, make it the
research default, retain 4/50 as an optional
control, and begin investigating a more
discriminative Fourier pilot/synchronization
estimator for the seven unresolved cases. No
production change is justified by these
five covers alone; neither JPEG+resize,
crop, platform recompression nor broad unseen
cover diversity is covered by this matrix.

### Two-stage cascade reproduces all 20 three-stage results exactly

The user supplied `robust-v04-blind-cascade-two-stage-01.csv`.
It was compared row-by-row against
`robust-v04-blind-cascade-01.csv` using
`source`, `resize_scale`, and `pilot_strength`
as a unique composite key. Both have 20 rows and
identical source hashes, encoded dimensions,
received dimensions, pilot strengths, and DWT
settings. The **two-stage 4:10,16:10 cascade
reproduces all 20 actual blind statuses,
safe-attempt counts, decoded dimensions, decoded
dimension errors, LL2-shape matches and oracle
outcomes exactly**.

| Metric | Three stages (4:10,4:50,16:10) | Two stages (4:10,16:10) |
| --- | ---: | ---: |
| Blind packet recovery | **13/20** | **13/20** |
| 75% resize recovery | 8/10 | 8/10 |
| 50% resize recovery | 5/10 | 5/10 |
| First-stage successes | 10 | 10 |
| Extended-stage successes | 3 | 3 |
| Failed searches | 7 | 7 |
| Oracle-known-size successes | 20/20 | 20/20 |
| Total measured seconds | 32.887 | 31.722 |

The measured runtime difference is **1.165 s**
(approximately 3.54%) across all 20 cases, but
these are unreplicated timings on a local system;
do **not** treat the percentage as a statistically
established speedup. The removed 4:50 stage made
zero new safe decoder calls in the previous matrix.

**Decision:** research-only
`tools/robust_pilot_cascade_probe.py` now
defaults to **4:10,16:10**. The optional 4:50
stage is retained for regression controls via
`--stages 4:10,4:50,16:10`. The maximum
nominal budget is now **320 generated candidate
pixel sizes** (160 per stage), before deduplication
and safe-size filtering. Observed failure cases
required 184–270 safe decoding attempts.

**Remaining research:** four screenshot failures,
two Aarne 50% failures, one Anna Maria 50% pilot
.12 failure. All seven oracle-known-size decodes
succeed. Investigate whether Fourier pilot
signal is masked by cover-content spectral
structure, attenuated by adaptation, or damaged
by the DWT embedding and resize, before changing
pilot strength or production decoding.

A useful next controlled ablation is to measure
the *same cover* at fixed resize and payload
with **no Fourier pilot, pilot only, DWT only,
and pilot+DWT**, comparing the true-scale
correlation score, its local-peak rank and the
difference relative to DWT-only. This uses the
original source as an **oracle diagnostic** only;
a practical blind decoder cannot subtract a
cover-only reference. A zero-pilot control is
essential to distinguish a real pilot signal
from a natural Fourier peak. If pilot contrast
is weak or absent, broadening the search is
unlikely to be an effective general fix.

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
