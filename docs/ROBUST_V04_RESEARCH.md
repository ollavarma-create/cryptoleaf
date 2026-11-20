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

### Controlled four-arm pilot visibility experiment (next run)

The research-only script
`tools/robust_pilot_signal_probe.py` compares
the **same cover**, fixed payload, pilot strength
and received resize in four arms:

- `cover_only`: YCbCr-roundtripped cover, no
  Fourier pilot, no DWT packet.
- `dwt_only`: cover + DWT packet, **no pilot**.
- `pilot_only`: cover + Fourier pilot, **no DWT**.
- `pilot_dwt`: cover + Fourier pilot + DWT packet
  (the actual robust embedding pipeline).

All four arms use the same LANCZOS received size,
same 0.45–1.02 Fourier correlation search and
32-ring radial profile (0.38 cycles/pixel). For
each arm, record correlation at the **known true
resize factor**, score percentile, closest local
peak, local peak rank and best peak. The true
scale is used **only for diagnostic evaluation**;
neither a real decoder nor a blind candidate
selector can use it. In particular, the
`cover_only` and `dwt_only` images cannot
be assumed available to a blind receiver.

Compute paired differences:
`pilot_only - cover_only` (pilot score lift
before DWT) and
`pilot_dwt - dwt_only` (pilot score lift
after DWT). Also compare the two DWT effects
on correlation score. These are **differences
of normalized correlation scores**, not linear
estimates of pilot amplitude or statistical
significance. A negative score lift does not
prove the pilot vanished; a positive lift
does not prove blind synchronization works.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_pilot_cascade_probe.py \
  tests/test_robust_pilot_signal_probe.py -q

python tools/robust_pilot_signal_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pilot-strengths 0.12,0.18 \
  --scales 0.75,0.5 \
  --csv results/robust-v04-pilot-signal-four-arm-01.csv
```

Expect **20 rows** (five covers × two strengths ×
two resizes), each with **four matched spectral
measurements**. The goal is to distinguish
cover-content interference, DWT-related
distortion and adaptive pilot attenuation,
especially for CryptoLeaf screenshot, Aarne 50%
and Anna Maria 50% pilot .12. Compare against
P1000450 and AppFootprint successes as controls.

If pilot-only is detectable but pilot+DWT is
not, examine DWT interaction. If both are
masked by cover-only peaks, consider
cover-robust pilot redesign or a more
discriminative detector. If pilot+DWT has a
true-scale peak but its rank is too low,
investigate a better candidate scheduling
policy. **Do not modify the production
codec on these diagnostics alone**: validate
new blind recovery and visual quality on
held-out covers first.

### Four-arm Fourier pilot visibility results (20/20 completed)

The user supplied
`robust-v04-pilot-signal-four-arm-01.csv`:
**20 rows**, all `status=OK`, covering five
covers × pilot strengths .12/.18 × resizes
75%/50%. Each row compares the same received
geometry for **cover-only, DWT-only, pilot-only,
and pilot+DWT**. DWT uses DELTA38 / REPEAT13.

All **20/20 pilot+DWT** arms have a positive
true-scale normalized correlation *lift*
relative to DWT-only. This is **not**
equivalent to successful pilot detection or
blind decoding. Some positive lifts are
tiny relative to competing cover peaks.

| Cover and resize | Pilot | Lift: pilot+DWT minus DWT-only | True-scale local peak rank, pilot+DWT | DWT effect: pilot+DWT minus pilot-only |
| --- | ---: | ---: | ---: | ---: |
| **Aarne 50%** | .12 | **+.0132** | **22** | +.0033 |
| Aarne 50% | .18 | +.0170 | 22 | +.0033 |
| **CryptoLeaf screenshot 75%** | .12 | +.0931 | **29** | **−.0648** |
| Screenshot 75% | .18 | +.1458 | **17** | **−.0753** |
| **Screenshot 50%** | .12 | **+.0055** | **no peak within ±.01** | −.0286 |
| Screenshot 50% | .18 | +.0374 | **no peak within ±.01** | −.0521 |
| **Anna Maria 50%** | .12 | +.3151 | **9** | −.0044 |
| Anna Maria 50% | .18 | +.3913 | **6** | −.0628 |
| **P1000450 50%** | .12 | +.3016 | **1** | +.0095 |
| P1000450 50% | .18 | +.3926 | **1** | +.0047 |

**Interpretation by failure mechanism:**

- **Aarne 50%:** pilot signal is barely
  discriminable from natural cover spectrum
  (lift .013–.017), despite almost full
  nominal pilot amplitude (effective
  .11895/.17843). DWT is *not* the primary
  cause: its effect is slightly positive.
  Simply increasing peak count may be
  ineffective; true-scale local peaks rank 22.
- **CryptoLeaf screenshot:** adaptive
  attenuation sets effective pilot to
  **.07154** (nominal .12) or **.10731**
  (nominal .18), approximately **59.6%**
  of requested amplitude. At 75%,
  pilot-only ranks **14/11**, while
  pilot+DWT ranks **29/17**: DWT
  materially degrades visibility. At
  50%, neither pilot-only nor pilot+DWT
  produces a local peak within ±.01 of
  true scale; nearest local peak is .012
  away. DWT contributes additional
  degradation, but cannot be the only
  cause because pilot-only already fails
  the local-peak criterion.
- **Anna Maria 50% pilot .12:** strong
  pilot correlation lift **+.3151** and
  true-scale local peak rank **9**.
  The earlier 2-stage blind search
  nevertheless failed. This case is
  more suggestive of candidate scheduling
  / geometry / scale-estimate precision
  than of a wholly missing pilot.
- **P1000450:** true-scale peak ranks
  **1 in all four pilot+DWT tests**,
  and pilot lifts range +.302 to +.713.
  This is a useful positive control.
- **AppFootprint:** true-scale peak ranks
  1–4 in the four pilot+DWT tests;
  also a positive control.

Across all 20 rows, DWT changes the
true-scale score positively in **12** and
negatively in **8** cases. Thus "DWT
destroys the Fourier pilot" is **not**
a general explanation. The score is
normalized correlation, not linear
signal amplitude; a positive lift is
not proof of reliable scale estimation.

**Possible profile cutoff issue to isolate
later:** pilot ring radii span .055–.195
cycles/pixel. At exactly 50% resize,
outer radii appear near .39 cycles/pixel,
while the default radial detector profile
stops at .38; `np.interp` clamps
out-of-range frequencies. This can
degrade matched detection, but an
earlier .48-profile variant did not
rescue the measured hard-case LL2
coverage. It remains a hypothesis,
not an established primary cause.

**Next controlled amplitude experiment:**
the research-only
`tools/robust_pilot_adaptation_probe.py`
compares the existing **adaptive**
pilot amplitude against a **fixed**
amplitude using the same cover, DWT
payload, received resize, two-stage
blind search and oracle. It records
PSNR/SSIM, actual blind PASS and
attempts, true-scale peak rank and
four-arm pilot lift. The adaptive
setting is restored after each test;
no production code is changed.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_pilot_adaptation_probe.py \
  tests/test_robust_pilot_signal_probe.py \
  tests/test_robust_pilot_cascade_probe.py -q

# 8 paired searches for the most difficult screenshot:
python tools/robust_pilot_adaptation_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name cryptoleaf-robust.png \
  --pilot-strengths 0.12,0.18 \
  --scales 0.75,0.5 \
  --modes adaptive,fixed \
  --csv results/robust-v04-pilot-adaptation-screenshot-01.csv
```

Expected **8 rows** (one screenshot × two
amplitude modes × two strengths × two
resizes). **Do not select fixed amplitude
merely because it raises correlation**:
it may visibly distort flat UI regions.
Only a paired increase in actual blind
recoveries with acceptable marked-image
PSNR/SSIM and visual inspection can
justify further exploration. If fixed
amplitude still fails, prioritize a
new pilot detector or synchronization
signal over further strength increases.
Aarne 50% requires separate research:
its adaptive attenuation is negligible.

### Adaptive versus fixed pilot: screenshot remains 0/8 blind

The user supplied
`robust-v04-pilot-adaptation-screenshot-01.csv`:
**eight completed rows**, CryptoLeaf screenshot
720×697, two pilot strengths (.12/.18), two
received resizes (75%/50%), and both adaptive
and fixed pilot amplitude. All eight
oracle-known-size decodes **PASS**; all eight
actual two-stage blind searches
(`4:10,16:10`) **FAIL:not_recovered**.
DELTA=38, REPEAT=13, 160 candidates per stage.

| Received resize | Nominal pilot | Adaptive true-scale local peak rank | Fixed rank | Blind adaptive / fixed |
| --- | ---: | ---: | ---: | --- |
| 75% | .12 | 29 | **16** | FAIL / FAIL |
| 75% | .18 | 17 | **13** | FAIL / FAIL |
| 50% | .12 | no peak ±.01 | no peak ±.01 | FAIL / FAIL |
| 50% | .18 | no peak ±.01 | no peak ±.01 | FAIL / FAIL |

At 75%, fixed amplitude increases true-scale
pilot+DWT correlation score and improves the
local-peak rank, but **not** actual recovery.
At 50%, the closest local peak remains
**.012** away from the true scale in every
case, despite stronger pilot score. These
results rule out *adaptive attenuation alone*
as a sufficient explanation for the screenshot
failures under this detector and budget.

Image quality of the **encoded** (pre-received-
resize) marked images:

| Nominal pilot | Adaptive PSNR / SSIM-Y | Fixed PSNR / SSIM-Y |
| --- | --- | --- |
| .12 | **38.5107 dB / .962585** | 38.1912 dB / .961112 |
| .18 | **38.2882 dB / .961615** | 37.6504 dB / .957670 |

Thus fixed .18 incurs **−.6378 dB** PSNR and
**−.003945** SSIM-Y, with no blind recovery
gain on this cover. PSNR/SSIM do not establish
visual acceptability by themselves. Keep the
adaptive mode as the research baseline;
do **not** change production settings.

**Next discriminating hypothesis:** UI screenshots
have strong horizontal/vertical edge structure,
creating dominant Fourier energy along the
frequency axes. The current radial detector
averages all orientations and can bury a weak
isotropic pilot in axis-aligned cover energy.
A new **research-only** diagnostic
`tools/robust_pilot_angular_probe.py`
excludes 0°, 5°, 10° or 20° wedges near
the horizontal/vertical Fourier axes before
radial bin averaging. It compares both
`max_freq=.38` (exact original baseline
at 0° exclusion) and `.48` (includes outer
rings after 50% resizing).

For each variant, measure the true-scale
correlation and local peak rank on both
**pilot+DWT** and **DWT-only negative control**,
plus the first correct LL2-grid candidate
rank in the same 4:10,16:10 search. Known
scale/size are used only for diagnostics;
the detector and candidates do not use them.
No Fourier pilot embedding, packet encoding,
or production decoding changes.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_pilot_angular_probe.py \
  tests/test_robust_pilot_adaptation_probe.py -q

# Initial 32 rank-only variants, no costly blind decodes:
python tools/robust_pilot_angular_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name cryptoleaf-robust.png \
  --name P1000450.JPG \
  --pilot-strengths 0.18 \
  --scales 0.75,0.5 \
  --axis-exclusions 0,5,10,20 \
  --profile-max-freqs 0.38,0.48 \
  --csv results/robust-v04-pilot-angular-01.csv
```

Expected **32 rows** (two covers × one pilot
strength × two scales × four masks × two
frequency cutoffs). The successful P1000450
cover is an essential positive control:
a detector that improves the screenshot but
breaks P1000450 is not a general improvement.
The 0°/.38 variant should reproduce the
existing baseline ranks and score for the
same image. **These are candidate-ranking
diagnostics, not actual blind decodes.**
If a variant generates a correct LL2-grid
candidate in the screenshot, run a narrow
follow-up with `--blind` for actual packet
recovery, and then expand to held-out covers
and image-quality checks before considering
any production integration.

If angular masking does not improve the
screenshot without damaging the positive
control, stop tuning this radial detector
and consider a redesigned synchronization
signal or a fundamentally different
blind scale estimator. The outer-ring
cutoff remains only one hypothesis and
previous .48-profile-only experiments did
not rescue the hard cases.

### Angular-masked Fourier detector: first screenshot LL2 hits (rank-only)

The user supplied `robust-v04-pilot-angular-01.csv`:
**32 completed rank-only rows**, two covers
(`cryptoleaf-robust.png` and `P1000450.JPG`),
pilot .18, LANCZOS 75%/50%, profile cutoffs
.38/.48, and axis exclusion wedges 0°/5°/10°/20°.
All **32 oracle-known-size decodes PASS**,
all `status=OK`, and **all
`blind_status=NOT_RUN`**. The candidate
scheduler is the research-only two-stage
4:10,16:10 search, with up to 160 generated
sizes per stage (270 unique sizes observed
after cross-stage deduplication).

**New screenshot geometry discoveries:**

| Received resize | Profile cutoff | Axis exclusion | First safe matching LL2-grid rank | Pilot true-scale local peak rank | Pilot score lift over DWT-only |
| --- | ---: | ---: | ---: | ---: | ---: |
| 75% | .38 | **5°** | **168** | 12 | +.22317 |
| 75% | .48 | **5°** | **167** | 11 | +.20105 |
| 50% | .38 | **20°** | **175** | 7 | +.02281 |
| 50% | .48 | **20°** | **104** | 12 | +.01518 |

The unmasked .38 baseline had **no matching
LL2 grid** at either scale. These are the
first observed matching screenshot geometries
within this two-stage candidate budget.
**They do not yet prove packet recovery.**
A matching LL2 shape does not ensure
the resized QIM votes recover the payload.

The negative control is important:
at **75%**, the DWT-only true-scale peak
ranks **34** and **28** for the two
5° configurations, versus pilot+DWT
ranks **12** and **11**, with substantial
pilot score lift (+.223 and +.201).
This supports, but does not prove,
pilot-specific discrimination.

At **50%**, the 20° mask also gives a
true-scale local peak in the **DWT-only
negative control** (ranks **10** and
**14**, compared with pilot+DWT
ranks **7** and **12**), and the score
lift is small (+.0228 and +.0152).
The apparent gain may be due partly to
natural cover structure. Do **not**
claim a robust 50% pilot detector
from these rank-only results.

**Positive control:** `P1000450.JPG`
retains the correct LL2 grid in all
16 variants. At 50%, the first matching
grid ranks **1** throughout; at 75%,
the grid ranks range **1–11**, so some
angular masks slow down an already easy
case. No actual blind decoding was run
in this CSV.

**Next decisive experiment:** only four
actual blind decodes of the screenshot,
holding the pilot, DWT and search budget
fixed. Use two separate calls so the
successful rank-only masks are paired
with their corresponding resize:

```bash
git pull --ff-only

# Screenshot 75%: both 5-degree variants (2 blind decodes)
python tools/robust_pilot_angular_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name cryptoleaf-robust.png \
  --pilot-strengths 0.18 \
  --scales 0.75 \
  --axis-exclusions 5 \
  --profile-max-freqs 0.38,0.48 \
  --blind \
  --csv results/robust-v04-angular-blind-screenshot-75-01.csv

# Screenshot 50%: both 20-degree variants (2 blind decodes)
python tools/robust_pilot_angular_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --name cryptoleaf-robust.png \
  --pilot-strengths 0.18 \
  --scales 0.5 \
  --axis-exclusions 20 \
  --profile-max-freqs 0.38,0.48 \
  --blind \
  --csv results/robust-v04-angular-blind-screenshot-50-01.csv
```

If a screenshot variant actually returns
`blind_status=PASS`, record decoded
pixel size and safe attempts; then
verify the same detector on a wider,
held-out cover set and the positive
control before integrating anything
into production. If all four fail
despite matching LL2 grids, inspect
**which candidate pixel dimensions**
share the true LL2 shape, their order,
and whether DWT recovery depends on
sub-grid resampling offsets. A broader
candidate budget alone should not
be presumed sufficient.

### First confirmed screenshot blind recoveries with angular masks (4/4)

The user supplied two actual blind-decoding CSVs:
`robust-v04-angular-blind-screenshot-75-01.csv`
and `robust-v04-angular-blind-screenshot-50-01.csv`.
Together they contain **four completed rows**,
all `oracle=PASS`, all `status=OK`,
and **all four `blind_status=PASS`**. The
unchanged marked screenshot is 720×697,
pilot strength .18 (adaptive effective
strength **.107312**), DWT DELTA38/REPEAT13.
Only the Fourier *receiver* detector is
changed. This is the first actual blind
recovery of this hard screenshot in the
v0.4 experiments.

| Received resize | Mask | Profile max freq | First correct LL2 rank | Actual safe decoder attempts | Decoded size | Blind |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 75%, received 540×523 | 5° | .38 | 168 | **168** | **720×697** | **PASS** |
| 75% | 5° | .48 | 167 | **167** | **720×697** | **PASS** |
| 50%, received 360×348 | 20° | .38 | 175 | **175** | **719×697** | **PASS** |
| 50% | 20° | .48 | 104 | **104** | **719×697** | **PASS** |

The 719-pixel decoded width at 50%
has the same two-level Haar LL2 grid
as the true 720-pixel width; in these
actual tests, the decoded payload
matches the expected bytes. A matching
LL2 grid alone would not have sufficed
as proof.

**Critical research limitation:** the
5° detector was selected for the 75%
test and the 20° detector for the 50%
test *after* examining a known-scale
rank-only sweep on this screenshot.
Therefore **4/4 is a targeted,
post-hoc detector evaluation**, not
evidence that an operational blind
receiver can choose the correct mask
without knowing the scale or cover.
The two successful received sizes are
not representative of unseen covers,
JPEG recompression, cropping, or
combined transforms. The 50% pilot
lift against DWT-only is small
(+.022813 / +.015175), and its
negative control also has a
true-scale peak; do not claim robust
pilot-specific detection from that
comparison alone.

**Next honest blind experiment:**
the new research-only
`tools/robust_pilot_multimask_probe.py`
uses a **frozen, cover- and
scale-independent detector sequence**:
`0.38:0,0.38:5,0.48:20`. Each variant
uses the same 4:10,16:10 search.
The original unmasked detector runs
first, preserving easy-case behavior;
the 5° and 20° variants are attempted
only if the earlier masks fail.
Pixel-size candidates are deduplicated
globally across masks. No original
size, known scale, cover-only negative
control or previous outcome enters
the detector or candidate generation.
The oracle is run **after** the blind
search and used only for reporting.

This is a larger search: up to
**3 masks × 2 stages × 160 generated
sizes = 960** before deduplication,
compared with **320** for the prior
two-stage baseline. Compare actual
safe decoder attempts and runtime
as well as PASS/FAIL, and avoid
equal-budget claims. Because the
three masks were chosen using this
same five-cover exploratory set,
performance on these covers is
**not independent validation**.

```bash
git pull --ff-only
python -m pytest \
  tests/test_robust_pilot_multimask_probe.py \
  tests/test_robust_pilot_angular_probe.py \
  tests/test_robust_pilot_cascade_probe.py -q

# Full 20-case paired comparison against the existing
# robust-v04-blind-cascade-two-stage-01.csv:
python tools/robust_pilot_multimask_probe.py \
  /home/jari/Pictures/0-4-mosaic-in \
  --pilot-strengths 0.12,0.18 \
  --scales 0.75,0.5 \
  --variants 0.38:0,0.38:5,0.48:20 \
  --csv results/robust-v04-blind-multimask-01.csv
```

Expect **20 rows**, one per cover,
pilot strength and resize. The prior
unmasked cascade recovered **13/20**.
If the first detector reproduces its
baseline and the additional masks
recover the screenshot at .18,
**15/20 is a plausible target**, not
a measured result. Pilot .12 on
the screenshot and the other three
unrecovered cover/scale cases remain
unknown. Record which detector and
stage succeeded, the number of safe
decoder attempts, and recovered
dimensions.

Next, freeze the algorithm and test
**previously unseen covers** and
combined JPEG+resize transformations
before any production integration.
Do not merge research into the
production codec based on these
exploratory tests.

### Fixed multi-mask blind search: 18/20, five net recoveries

The user supplied
`robust-v04-blind-multimask-01.csv`
(**20 complete rows**). Compared case by case
against
`robust-v04-blind-cascade-two-stage-01.csv`
using the same five covers, two pilot
strengths (.12/.18), LANCZOS 75%/50%,
DELTA38/REPEAT13, source SHA256,
marked-image quality and oracle.
All **20/20 known-size oracle decodes PASS**,
all statuses `OK`, and all source hashes,
image sizes, effective strengths, marked
PSNR and SSIM match the baseline.

**Actual blind recovery: 18/20 (90%)**
versus **13/20 (65%)** with the
original two-stage unmasked detector.
**Five newly recovered cases, zero
regressions** in this fixed 20-case
exploratory corpus. The first
`0.38:0` variant reproduces all
**13 original successes**, with exactly
the same safe attempt counts and
decoded pixel sizes. Fixed detector
order (independent of received resize
and cover): `0.38:0,0.38:5,0.48:20`;
each uses 4:10 then 16:10, with
up to 160 candidate sizes per stage.
Pixel sizes are deduplicated globally.

| Newly recovered case | Resize | Pilot | Successful detector | Cumulative safe decoder attempts | Decoded dimensions |
| --- | ---: | ---: | --- | ---: | --- |
| Anna Maria Liikanen.jpg | 50% | .12 | `0.38:5` | 214 | 1280×867 |
| AarneArmeijassa.jpg | 50% | .12 | `0.48:20` | 332 | 273×391 |
| cryptoleaf-robust.png | 50% | .12 | `0.48:20` | 460 | 719×697 |
| cryptoleaf-robust.png | 75% | .18 | `0.38:5` | 351 | 720×697 |
| cryptoleaf-robust.png | 50% | .18 | `0.48:20` | 450 | 719×697 |

All decoded payloads match the expected
bytes; the 719×697 screenshot decodes
share the original 720×697 LL2 grid.
By received resize, recovery rises
from **8/10 to 9/10** at 75% and
**5/10 to 9/10** at 50%.
By pilot strength, recovery rises
from **6/10 to 9/10** at .12 and
**7/10 to 9/10** at .18.
The additional successful detectors
are `0.38:5` in two cases and
`0.48:20` in three cases.

**Two remaining blind failures:**

- `AarneArmeijassa.jpg`, 50%, pilot .18:
  **374** safe attempts, three detectors
  tried (207 + 84 + 83).
- `cryptoleaf-robust.png`, 75%, pilot .12:
  **594** safe attempts, three detectors
  tried (270 + 139 + 185).

Both oracle decodes PASS, so these
are still synchronization/search
failures, not proof of payload
destruction.

**Search cost is materially larger:**
across the 20 paired cases, cumulative
safe decoder attempts increase from
**2,374 to 3,475 (+46.4%)**; summed
measured blind-search durations from
**31.722 s to 48.667 s (+53.4%)**.
These are one-run measurements,
not replicated performance estimates.
The new 90% figure must **not** be
presented as an equal-budget comparison.
The two-stage baseline permits at most
320 generated candidates before
deduplication; the three-mask cascade
permits up to 960. Easy cases
exit early, often in 1–2 attempts;
hard cases can require hundreds
(e.g. 594 and 460).

**Scientific limitations:** masks
were selected after exploring these
five covers, so the 18/20 result
is *development-set performance*,
not independent generalization
evidence or a production-ready
success probability. Resizes were
separate LANCZOS transforms; no
combined JPEG+resize, crop,
platform recompression or screenshot
edits have been validated by this
result. Original embedding,
adaptive amplitude and DWT packet
are unchanged. No production codec
changes or merge are warranted yet.

**Recommended next phase:**
freeze this exact three-mask
detector and test previously
unseen covers of diverse dimensions,
content types, aspect ratios and
flat-region proportions. Run the
original two-stage cascade and
new multi-mask search on identical
input images and fixed payloads,
compare paired PASS/FAIL,
safe attempts and duration.
Use exact `--name` options to
select new filenames in each
tool; the default names select
the original five development
covers. Only after held-out
testing should further masks,
early stopping, cost caps or
combined JPEG+resize tests
be considered. Separate
exploratory rank-only diagnostics
on the two remaining failures
are useful, but any tuning based
on them must be evaluated on
a *different* untouched test set.

### Frozen multi-mask detector: independent 25-cover evaluation

After the fixed three-detector cascade was selected on five development
covers, it was evaluated on 25 new covers, 2 nominal pilot strengths
(.12/.18) and two separate LANCZOS resizes (75%/50%). Paired
source hashes and embedding settings matched between the old two-stage
unmasked cascade and the frozen multi-mask cascade. The small
`Leimasin.jpg` cover was capacity-ineligible for all four conditions,
leaving **96 eligible cases**. Known-size oracle decoding passed **96/96**.

- Original two-stage blind recovery: **68/96 (70.8%)**.
- Fixed three-mask blind recovery: **81/96 (84.4%)**.
- **13 additional successes, zero lost successes**, across eight covers.
- 75% resize: **44/48 -> 46/48**.
- 50% resize: **24/48 -> 35/48**.
- Total safe decoder attempts: **8,974 -> 13,882 (+54.7%)**.
- This is a **larger-search-budget comparison**, not equal-cost
  evidence. The two scripts' reported `seconds` use different
  timing boundaries, so they must not be compared directly.

The two white-background, axis-aligned UI screenshots
`kulutus-web-anal1.png` and `kulutus-web-vika.png`
remain difficult at 50% resizing, despite oracle PASS.
They are now **exploratory diagnostic controls**, not an
untouched validation set. Their failure is consistent with,
but does not prove, an axis-energy interference mechanism.
A fixed detector cannot be retuned on these cases and then
evaluated as though they were still independent.

### Deterministic synthetic UI orientation experiment

The research-only `tools/robust_ui_synthetic_covers.py` creates
seven same-size, seeded RGB covers (default 960x720):

1. Near-white flat background, RGB(248,248,248)
2. The same background plus horizontal grey lines
3. The same background plus vertical grey lines
4. The same background plus both line orientations
5. The same grid plus coloured bars
6. The same background plus spatially correlated greyscale texture
7. The grid and coloured bars plus the **same** texture

The added texture-only case is necessary to distinguish a
texture effect from the interaction of texture and grid/bars.
Optional `--control` files are copied **byte-for-byte** into
the output directory, with SHA256 hashes and basic white/grey
fractions in `synthetic-manifest.csv`. Never commit real user
images to the repository. The output directory must be empty.
No embedding or production-code change occurs in the generator.

Suggested independent positive controls:
`P1000450.JPG` and `appfootprint-main.png`.
Suggested difficult controls:
`kulutus-web-anal1.png` and `kulutus-web-vika.png`.
Only the two former were known to be comparatively easy in
previous pilot tests; none of the controls is an independent
held-out image after being selected for this experiment.

Generate covers, then run the existing
`robust_pilot_angular_probe.py` with 0/5/20-degree
exclusions and 0.38/0.48 maximum frequency, at strengths
.12/.18 and resize factors .75/.5. The angular probe
already embeds **pilot+DWT** and **DWT-only** negative
controls, measures true-scale scores and local peak rank,
and reports the first matching LL2 candidate-grid rank.
Use `--blind` only for bounded follow-up runs; a grid
rank is **not** successful packet recovery. Separately,
run the **frozen** `robust_pilot_multimask_probe.py`
for actual blind recovery with the exact fixed
`0.38:0,0.38:5,0.48:20` sequence.

For an orientation-only diagnostic, pass `--fixed-pilot` to
`robust_pilot_angular_probe.py`: this disables per-cover
pilot amplitude adaptation **only in that research process**,
and the CSV records `adaptive_pilot=False`. Without this
control, changing line density also changes the flat-area
fraction and thus the effective pilot strength, confounding
a causal orientation interpretation. The actual frozen
multi-mask blind benchmark must continue using the default
adaptive amplitude; fixed-amplitude tests are a separate
mechanism study, not directly comparable production results.

The causal question is whether adding axis-aligned
structures to a controlled cover reduces true-scale
pilot detectability, whether the effect differs by
orientation, and whether the 5/20-degree masks rescue
it. Also compare DWT-only controls to avoid attributing
naturally occurring FFT peaks to the pilot. Flat white
covers may have clipping or capacity/visibility problems;
record oracle and embedding status before interpreting
blind failures. Treat synthetic results as **mechanistic
development diagnostics**, not new generalization rates.

### Measured synthetic UI orientation controls (fixed vs adaptive)

Two user-supplied CSV files, `robust-v04-ui-orientation-fixed-01.csv`
and `robust-v04-ui-orientation-adaptive-01.csv`, each contain **264**
complete diagnostic rows: 11 covers, two nominal pilot strengths,
two independent resize factors, and six detector variants
(0/5/20 degrees at profile cutoffs .38/.48).
All rows report `status=OK`, `oracle=PASS`.
The matching source SHA256 hashes and geometry allow paired comparisons.
These are **rank-only** tests (`blind_status=NOT_RUN`), not 528
blind recovery attempts.

A positive `pilot_score_lift_vs_dwt_only` means the
true-scale spectral correlation exceeds the DWT-only negative control
at the **same scale**. It is **not** proof that the pilot alone
caused the strongest peak, and is not a recovered packet.
A non-null `safe_ll2_grid_rank` means a candidate matching
the encoded LL2 geometry occurs somewhere in that
detector's two-stage candidate list; actual decoding was not run.

**Mean true-scale score lift, fixed / adaptive, and LL2 coverage
of the four unique strength × resize conditions by at least one
of the six variants:**

| Cover | Lift fixed | Lift adaptive | LL2 cases fixed | LL2 cases adaptive |
| --- | ---: | ---: | ---: | ---: |
| 00-flat | +.000 | +.000 | 0/4 | 0/4 |
| 01-horizontal | -.053 | +.002 | 3/4 | 0/4 |
| 02-vertical | -.113 | -.051 | 3/4 | 3/4 |
| 03-grid | -.198 | -.082 | 2/4 | 3/4 |
| 04-grid-bars | +.076 | +.029 | 3/4 | 2/4 |
| 05-texture | +.307 | +.306 | 4/4 | 4/4 |
| 06-grid-bars-texture | +.228 | +.211 | 4/4 | 4/4 |
| appfootprint-main | +.341 | +.276 | 4/4 | 4/4 |
| kulutus-web-anal1 | +.324 | +.242 | 3/4 | 2/4 |
| kulutus-web-vika | +.290 | +.140 | 4/4 | 1/4 |
| P1000450 | +.570 | +.523 | 4/4 | 4/4 |

Total: **34/44** paired image conditions with an LL2 candidate
under fixed amplitude, **27/44** under adaptive amplitude,
when allowing *any* of six detectors. These are **not**
actual blind decode rates. Nine conditions had LL2 coverage
only with fixed amplitude, two only with adaptive amplitude;
therefore disabling adaptation is not a universally better
setting. The fixed-amplitude research run is not equivalent
to the current production embedding policy.

In the entirely flat 00-flat image, the pilot-vs-DWT
true-scale lift is exactly zero in all 24 detector/strength/
resize combinations, in **both** runs. This is consistent
with the Fourier-multiplicative pilot being unable to
create ring-frequency energy where the original image
has no such energy: a constant image has only DC before
the DWT embed. The known-size payload still decodes,
so this is a pilot/synchronisation limitation, not proof
of lost data.

At fixed amplitude, 01-horizontal, 02-vertical and 03-grid
have **negative** average pilot lift (-.053, -.113, -.198),
whereas adding correlated texture yields positive lift
(+.307 for texture only, +.228 for grid/bars/texture).
For 01-horizontal at fixed amplitude, the 20-degree
mask yields an LL2-grid candidate in **6/8** combinations
(two strengths × two scales × two frequency cutoffs),
versus **0/8** without an axis mask. For 04-grid-bars
the corresponding counts are **6/8** versus **0/8**.
This supports an axis-energy interference hypothesis
for these synthetic covers, but is not a universal
result; some real covers are worsened by masking.

The adaptive pilot reduces nominal .12 to .036 on the
flat image and to about .058 on kulutus-web-vika,
while textured 05-texture stays near .120.
This confirms amplitude adaptation is a substantial
confound in orientation comparisons; fixed-pilot
controls are therefore useful, but must be judged
against visible artifacts and real decoding before
being adopted. The negative control is essential:
the DWT-only image can itself show scale-like
Fourier correlations.

**Next experiment (actual blind decoding):**
run the unchanged three-mask sequence
`0.38:0,0.38:5,0.48:20` on these 11 covers
with both the default adaptive pilot and the
new research-only `--fixed-pilot` switch of
`tools/robust_pilot_multimask_probe.py`.
Both runs must use identical payload bytes,
`DELTA=38`, `REPEAT=13`, and separate CSVs.
The new `adaptive_pilot` CSV column records
the mode; neither switch changes production
codec source. Compare paired payload PASS/FAIL,
oracle, actual decoder attempts, and recovered
dimensions; do **not** infer blind success from
the current LL2 candidate ranks. Do not
reselect masks on these controls and call the
result independent validation.

### Paired UI blind decoding: adaptive versus fixed pilot

Two further CSVs supplied after the rank-only experiment,
`robust-v04-ui-blind-adaptive-01.csv` and
`robust-v04-ui-blind-fixed-01.csv`, contain **44 matched rows
each**: the same 11 covers × 2 strengths × 2 resize factors.
Source SHA256, encoded/received geometry, payload settings
(`DELTA=38`, `REPEAT=13`), three detector variants
(`0.38:0,0.38:5,0.48:20`), stage sequence
(`4:10,16:10`) and per-stage budget all match.
All 88 rows are `status=OK`, `oracle=PASS`.

| Metric | Adaptive (production research default) | Fixed (research-only) |
| --- | ---: | ---: |
| Blind payload PASS | **23/44 (52.3%)** | **30/44 (68.2%)** |
| 75% resize | 14/22 | 15/22 |
| 50% resize | 9/22 | 15/22 |
| Pilot strength .12 | 11/22 | 13/22 |
| Pilot strength .18 | 12/22 | 17/22 |
| Total safe decoder attempts | 13,724 | 11,268 |
| Blind search seconds (single run) | 249.875 | 192.165 |
| Mean marked PSNR | 40.927 dB | 39.827 dB |
| Mean marked SSIM-Y | .970908 | .959137 |

Pairwise contingency: **22 successes in both**, **13 failures
in both**, **8 fixed-only successes**, and **1 adaptive-only
success**. Net improvement **+7/44 = +15.9 percentage
points**. Total safe decoder attempts decreased **17.9%**;
measured search time decreased **23.1%**, in this one run
of the same tool with the same timing boundary. The
latency advantage is partly due to earlier successful
termination, not necessarily faster individual attempts.

| Cover | Adaptive PASS /4 | Fixed PASS /4 |
| --- | ---: | ---: |
| 00-flat.png | 0 | 0 |
| 01-horizontal.png | 0 | 1 |
| 02-vertical.png | 1 | 3 |
| 03-grid.png | 1 | 0 |
| 04-grid-bars.png | 2 | 3 |
| 05-texture.png | 4 | 4 |
| 06-grid-bars-texture.png | 4 | 4 |
| appfootprint-main.png | 4 | 4 |
| kulutus-web-anal1.png | 2 | 3 |
| kulutus-web-vika.png | 1 | 4 |
| P1000450.JPG | 4 | 4 |

The most striking real-screen case is
`kulutus-web-vika.png`: with the fixed pilot, all
four payloads decode, including both 50% resized
versions. At 50% and nominal strength .18 the
fixed case passes in **3** safe attempts versus
adaptive FAIL after **580**. The adaptive amplitude
on that cover is only .057954 at nominal .12 and
.086930 at nominal .18, versus the fixed .12/.18.
The only regression is `03-grid.png`, 75% resize,
nominal strength .18: adaptive PASS in 286 attempts,
fixed FAIL after 444.

The quality cost is measurable: mean marked PSNR
drops **1.10 dB** and mean SSIM-Y drops **.01177**
when fixed amplitude replaces adaptation. On
`03-grid.png`, strength .18, PSNR drops from
40.7305 to 37.7061 dB and SSIM-Y from .958981
to .917568. This is not evidence that such
changes are imperceptible. On the entirely
flat image, fixed and adaptive marked PSNR and
SSIM are identical, and neither recovers blindly:
the Fourier pilot is **multiplicative** in
frequency space, so it cannot create non-DC
frequencies in a perfectly constant image.

**Interpretation:** amplitude attenuation explains
part of the difficulty on flat/UI covers, but
simply disabling adaptation has an observable
fidelity cost and is not monotonic (one regression).
The present 11-cover experiment is a **mechanism
study selected after observing failures**, not
independent validation of a new production default.
Keep the adaptive production setting and frozen
three-mask search unchanged while investigating
decoder-only synchronization (robust radial
statistics, QIM-lattice candidate ranking) and
a more selective, perceptually constrained
amplitude rule. A later untouched image set and
JPEG+resize channel must validate any change.

### Decoder-only QIM synchronization hypothesis: predeclared rank probe

After the 11-cover adaptive-vs-fixed experiment, we freeze the
existing Fourier candidate generator (variants
`0.38:0,0.38:5,0.48:20`, stages `4:10,16:10`,
160 sizes per stage, cross-variant pixel-size deduplication)
and the **adaptive** encoder. The new research-only tool
`tools/robust_qim_sync_rank_probe.py` reranks only a
predeclared prefix of those *same* safe candidates. It
does not add candidates or change the codec.

**Two independent decoder-only candidate scores:**

- `lattice`: difference in mean
  `cos(2*pi*LL2/DELTA)` between the first
  `32*REPEAT` seeded QIM positions and the **last**
  `32*REPEAT` positions in the seeded permutation.
  This is a valid unembedded negative control **only
  if** LL2 capacity exceeds the maximum legal CLR1
  packet size, `(HEADER_BYTES+MAX_CODEWORD)*8*REPEAT`,
  plus the control sample size. Otherwise the lattice
  score is NaN and sorted last; `lattice_control_eligible_count`
  reports how many candidate sizes qualify. This
  conservative rule requires no known packet length
  or expected payload.
- `header`: centred Pearson correlation of
  `cos(pi*LL2/DELTA)` at the first `32*REPEAT`
  seeded positions with the publicly known four
  `CLR1` header bytes repeated `REPEAT` times.
  The centring prevents a constant white cover
  from scoring artificially high merely because
  the header contains more zero than one bits.
  The length and payload are **not** used to
  generate or rank candidates.

The tool also measures predeclared wrong-seed
(`SEED+1`) and wrong-delta (`DELTA*1.5`)
header controls. The **known original size is
used only after scoring** to calculate exact
and LL2-grid candidate ranks. An LL2-grid match
is **not** a recovered packet. `--blind`
enables three independent equal-decoder-call-budget
arms (baseline Fourier order, header rank,
lattice rank), each over the identical candidate
pool; rank calculation time is reported separately.
The tool does not run actual blind decoding by
default. CSVs refuse overwrite.

**First targeted experiment:** 4 covers
(`kulutus-web-anal1.png`,
`kulutus-web-vika.png`,
`appfootprint-main.png`,
`P1000450.JPG`), nominal strengths .12/.18,
scale .5, `DELTA=38`, `REPEAT=13`,
first 240 frozen candidates. This is a
*development diagnostic*, not an independent
test set. Inspect true-grid rank and both
negative controls before trying `--blind`
with a predeclared 40-call budget per arm.
Do not treat a better true-grid rank as
proof of better payload recovery, and include
scoring CPU time in end-to-end cost.

### QIM rank-only diagnostic, 4 covers × 2 strengths × 50% resize

User-supplied `robust-v04-qim-rank-adaptive-01.csv`
contains **8 OK rows**, all **oracle PASS**, all
`blind_budget=0` (no actual blind payload recovery).
Encoder remains adaptive, `DELTA=38`, `REPEAT=13`,
three frozen Fourier variants, stages `4:10,16:10`.
The tool generated **468–589** safe candidates per
case but scored only the **first 240**.

| Cover | Nominal strength | Fourier first true LL2 grid | CLR1-header rank | Lattice rank | Exact pixel-size Fourier → header |
| --- | ---: | ---: | ---: | ---: | --- |
| `kulutus-web-anal1.png` | .12 | absent in first 240 | absent | absent | absent → absent |
| `kulutus-web-anal1.png` | .18 | absent in first 240 | absent | absent | absent → absent |
| `kulutus-web-vika.png` | .12 | absent in first 240 | absent | absent | absent → absent |
| `kulutus-web-vika.png` | .18 | absent in first 240 | absent | absent | absent → absent |
| `appfootprint-main.png` | .12 | 50 | **1** | 1 | 130 → **1** |
| `appfootprint-main.png` | .18 | 48 | **1** | 1 | 129 → **1** |
| `P1000450.JPG` | .12 | 1 | 1 | 1 | 1 → 1 |
| `P1000450.JPG` | .18 | 1 | 1 | 1 | 1 → 1 |

At the first true grid, header correlation is
**.523021/.509629** for AppFootprint and
**.827150/.827385** for the photograph.
Wrong-seed header correlations on AppFootprint are
**−.052259/−.055032**; wrong-delta correlations
**.047901/.053125**. This supports a real
seeded-header signal, but not yet packet recovery.
The lattice score on AppFootprint is **negative**
(−.070983/−.056974) even though its rank is 1;
this rank alone does **not** establish positive
QIM-lattice contrast. The lattice control was
eligible for only **21–221** of 240 scored
candidates per case, which also biases
comparability across sizes.

Total Fourier candidate generation + 240-size
scoring time across eight rows: **36.685 s**,
mean **4.586 s** per row. This is **additional
ranking cost**; an eventual blind search must
include it in end-to-end latency comparisons.

**Key limitation:** no ranker can rescue a
correct size omitted from its candidate pool.
Four Kulutus-Web cases lack a matching LL2
grid among the first 240 sizes, but may have
it later in their frozen 580–589-size pools.
The next predeclared diagnostic is to rerun
the **same eight cases** with
`--max-ranked 640`, which covers the entire
frozen pool without changing its generation.
Only after confirming correct-grid inclusion
and negative-control separation should
`--blind --decode-budget 40` compare
independent equal-budget payload recovery
arms. Neither stage is independent validation:
these covers were chosen after earlier failures.

### Full frozen Fourier pool: QIM rank diagnostic

The user-supplied `robust-v04-qim-rank-fullpool-01.csv`
contains 8 complete rank-only rows. All are
`status=OK`, `oracle=PASS`,
`blind_budget=0`, `adaptive_pilot=True`.
The frozen three-mask Fourier search generated
**468–589** safe pixel-size candidates per row.
With `max_ranked=640`, **all 4,416 candidates**
were scored (mean **10.236 s** per row;
total **81.890 s** for the eight rows).

| Cover | Nominal strength | Full Fourier candidates | True LL2 grid in pool | Header exact-size rank |
| --- | ---: | ---: | --- | ---: |
| `kulutus-web-anal1.png` | .12 | 589 | NO | absent |
| `kulutus-web-anal1.png` | .18 | 582 | NO | absent |
| `kulutus-web-vika.png` | .12 | 588 | NO | absent |
| `kulutus-web-vika.png` | .18 | 580 | NO | absent |
| `appfootprint-main.png` | .12 | 585 | YES (Fourier grid rank 50) | **1** |
| `appfootprint-main.png` | .18 | 556 | YES (Fourier grid rank 48) | **1** |
| `P1000450.JPG` | .12 | 468 | YES (Fourier grid rank 1) | **1** |
| `P1000450.JPG` | .18 | 468 | YES (Fourier grid rank 1) | **1** |

The four Kulutus-Web 50%-resize cases cannot
be rescued by any reranking of the **unchanged**
Fourier candidate pool. This is a candidate
**recall** failure, not evidence that the QIM
header is incapable of recognizing the true
dimensions. The exact and LL2-grid sizes are
absent in all four cases. The AppFootprint
results still support header discrimination,
but no actual blind decoding has been run in
this experiment. The QIM lattice contrast
is not a validated substitute for the header.

**Predeclared next mechanism test:**
`tools/robust_qim_scale_bank_probe.py`
constructs a separate, deterministic,
Fourier-independent candidate bank from
received dimensions only, using common
enlargement factors `1,1.25,4/3,1.5,1.75,2`
and all ±2-pixel width/height offsets.
No true encoded dimensions, known resize
factor, oracle or expected payload are used
to generate or rank candidate sizes.
For 50% downsizing the 2× factor is
obviously relevant; this is an **explicit
scale-prior experiment**, not proof of
fully scale-agnostic recovery. The fixed
priors and offsets are applied to all four
covers, including two positive controls.

Compare raw scale-bank order with the
public CLR1-header rerank, and report the
wrong-seed and wrong-delta scores at the
exact true size. Independently score
unmarked source covers downscaled to the
same received dimensions to characterize
chance header correlations. The first run
is **rank-only**; only if true-size inclusion
and marked-vs-unmarked separation are
confirmed should `--blind --decode-budget 40`
be run with identical decoder-call budgets
for both arms. Candidate scoring and
unmarked-control CPU time are measured
separately. This selected dataset is
development-only, and the method must
later be tested on untouched covers and
unknown resize ratios. Production codec
and Fourier search are unchanged.

### Generic scale-prior bank: eight rank-only results

User-supplied `robust-v04-qim-scale-bank-01.csv`
contains **8 complete, rank-only** rows: four
selected covers × nominal strengths .12/.18 ×
50% LANCZOS resize. All are `status=OK`,
`oracle=PASS`, `blind_budget=0`, with
adaptive pilot, `DELTA=38`, `REPEAT=13`.
The deterministic bank uses enlargement priors
`1,1.25,1.333333333,1.5,1.75,2` and
±2 pixels in each dimension. Candidate counts
are 140–150; the bank includes the exact
original pixel dimensions in all eight cases.

| Cover | Strengths | Bank exact-size rank | CLR1-header exact-size rank | Header score at true size |
| --- | --- | --- | --- | --- |
| `kulutus-web-anal1.png` | .12/.18 | 129/129 | **1/1** | .902510/.893949 |
| `kulutus-web-vika.png` | .12/.18 | 130/130 | **1/1** | .932390/.932672 |
| `appfootprint-main.png` | .12/.18 | 129/129 | **1/1** | .706921/.710144 |
| `P1000450.JPG` | .12/.18 | 126/126 | **1/1** | .827150/.827385 |

The wrong-seed header score at the true size
ranges from **−.040912 to +.040328**; wrong
delta (1.5×) from **−.564778 to +.053029**.
On unmarked covers, the **maximum** header
score over the entire bank is **.100989–.141356**;
the minimum marked true-size score is
**.706921**. The unmarked control is the same
cover reused at two nominal strengths, so these
are **four distinct unmarked controls**, not
eight independent ones. The first experiment
therefore supports real CLR1-header discrimination
but does **not** establish blind packet recovery
or generalization to unseen images.

Mean candidate construction + scoring time:
**2.674 s per marked case**, or **21.394 s**
across eight rows. Separately computing the
unmarked control costs **2.611 s per row**;
this is research-only overhead, not required
by a future receiver.

**Crucial limitation:** the 50% resize is
exactly represented by the bank's 2×
enlargement prior, and the ±2-pixel jitter
covers odd original dimensions. This is an
explicit, favorable prior, not a solution
for arbitrary resize factors. The chosen
covers were previously used to investigate
failures. No held-out test has yet validated
the scale-bank method.

**Next predeclared blind comparison:** repeat
the identical eight cases with
`--blind --decode-budget 40`, keeping
the default prior order. Compare raw-bank
vs header-ranked decoder attempts, PASS/FAIL
and total cost including score time. In a
second, separate run reverse the scale-prior
order to `2,1.75,1.5,1.333333333,1.25,1`.
This retains the **same candidate set**
but puts the favorable 2× prior first, giving
a strong non-QIM baseline. A 40-call
default-order baseline cannot reach the
true size (bank ranks 126–130), so comparing
only against that baseline would be misleading.
Both comparisons are **development-set**
results; an untouched set and non-prior
resize factors are required before
production consideration. No codec changes.

### Paired blind scale-bank recovery: default vs 2×-first order

Two user-supplied CSVs, `robust-v04-qim-bank-blind-default-01.csv`
and `robust-v04-qim-bank-blind-2x-first-01.csv`,
contain eight rows each, paired by source and pilot strength.
Source SHA256, geometry, `DELTA=38`, `REPEAT=13`,
adaptive embedding, 50% LANCZOS resize, ±2-pixel
jitter, candidate count (140–150), oracle results,
and QIM-ranked exact dimensions are identical across runs.
All 16 oracle checks PASS. Both runs use 40 decoder
attempts per arm and omit unmarked controls (already
tested in the preceding rank-only experiment).

| Arm | Blind payload PASS | Decoder attempts (sum; mean) | Decoder seconds (sum; mean) |
| --- | ---: | ---: | ---: |
| Default prior order, no reranking | **0/8** | 320; 40.0 | 3.077; .385 |
| 2× prior first, no reranking | **8/8** | 28; 3.5 | **.908; .114** |
| QIM CLR1-header order, default bank | **8/8** | 8; 1.0 | .295; .037 |
| QIM CLR1-header order, 2×-first bank | **8/8** | 8; 1.0 | .293; .037 |

QIM scoring (which includes candidate-bank generation)
costs **20.935 s / 8 = 2.617 s** per case with
default ordering and **21.691 s / 8 = 2.711 s**
with 2× first. Thus full QIM-ranked recovery
costs **21.230 s / 8 = 2.654 s** or
**21.984 s / 8 = 2.748 s**, respectively.
In this selected 50%-resize test, the direct
2×-first decoder arm takes only **.114 s/case**,
about **24× less** than QIM scoring plus recovery
for that arm. Timings are from sequential runs,
not isolated paired CPU benchmarks; treat
differences as indicative, not exact speedup
guarantees.

Default-bank exact original dimensions appear
at positions **126–130**, beyond the fixed
40-attempt limit. In 2×-first bank they appear
at positions **1, 4 or 5**. All eight QIM-ranked
dimensions are at position **1**, and all eight
payloads recover on the first decode. These
results show **real blind packet recovery
conditional on a candidate bank containing the
true original size**, not blind recovery at an
arbitrary unknown resize factor.

**Important fairness point:** the 2×-first
baseline has a highly favorable prior because
every case was downscaled by exactly 50%.
This is a strong, legitimate control for this
test but cannot establish general performance
when the resize factor is unknown. Conversely,
the default-order baseline's 0/8 is a consequence
of a 40-attempt budget and its placement of
2× near the end; it is not evidence that
unranked exhaustive decoding would fail.
QIM's real benefit here is **candidate
discrimination**, not end-to-end speed.

**Next discriminating experiment:** the research tool
now supports `--baseline-only --blind
--decode-budget 200`, which runs an exhaustive
bank decode **without QIM scoring** and reports
`candidate_generation_seconds` separately from
`baseline_blind_seconds`. In this mode
`scoring_seconds` is null, and QIM columns
are intentionally unpopulated. In the normal
mode `scoring_seconds` retains its historical
meaning (bank generation **plus** QIM scoring),
while the new generation-only field is a
subset of that time: **do not add them together**.
Compare baseline-only total
(`candidate_generation_seconds + baseline_blind_seconds`)
with the previously measured QIM total
(`scoring_seconds + header_blind_seconds`).
Use the default bank order so the first
true-size candidate is at rank 126–130;
this tests exhaustive decoding rather than
the favorable 2×-first prior. Then evaluate
off-prior resize factors on untouched covers,
with a predeclared size-search strategy.
Avoid promoting the QIM method to production
until both search recall and end-to-end cost
are validated on an independent dataset.

### Baseline-only exhaustive scale bank: 8/8 payload recovery

User-supplied `robust-v04-bank-exhaustive-01.csv`:
8 complete rows, four selected covers × pilot strengths .12/.18,
50% LANCZOS resize, `DELTA=38`, `REPEAT=13`, adaptive pilot,
default six scale priors and ±2-pixel jitter. `--baseline-only --blind
--decode-budget 200` **does not calculate any QIM header scores**.
All eight oracle checks and all eight actual blind payload recoveries
PASS. Each decoded pixel size equals the encoded original size.
The first successful decode occurs exactly at the predeclared
bank's original-size rank, **126–130** (mean **128.5** attempts).

| Cover | Strengths | Exact-size rank / attempts | Decode seconds |
| --- | --- | --- | --- |
| `kulutus-web-anal1.png` | .12/.18 | 129/129 | 1.524/1.752 |
| `kulutus-web-vika.png` | .12/.18 | 130/130 | 2.495/2.519 |
| `appfootprint-main.png` | .12/.18 | 129/129 | 1.691/1.652 |
| `P1000450.JPG` | .12/.18 | 126/126 | 2.495/2.566 |

Total baseline-only decoder time: **16.694 s** over eight rows
(mean **2.08675 s/case**). Bank generation totals **.001104 s**,
so total generation + decode is **16.695104 s** (mean **2.086888 s**).
The previous default-order QIM header run required
**20.935 s** scoring + **.295 s** decoding =
**21.230 s** (mean **2.65375 s/case**). The separate 2×-first
direct decoder baseline needed **.908 s** total
(mean **.1135 s/case**), succeeding after 1–5 attempts.

Thus in these selected, **exactly 50%-resized** cases,
exhaustive unranked decoding is about **21% faster**
than the current full QIM-scored receiver
(`1 - 16.695104/21.230`), or equivalently QIM is
about **27% slower** (`21.230/16.695104 - 1`).
The 2×-first baseline is much faster still because the
scale prior is favorable. Runs were sequential, not
randomized/CPU-controlled, so timing ratios are indicative.
The QIM header remains a highly discriminating *signal*,
but scoring all 140–150 candidates is not currently
the best end-to-end strategy on this workload.

**Research direction:** test candidate recall and payload
recovery on **unknown, off-prior resize factors** using
untouched covers. Before implementing a coarse-to-fine
QIM scale search, characterize whether the soft CLR1
score is smooth near the correct dimensions or is a
narrow/discontinuous peak caused by the seeded LL2
permutation and wavelet grid. If it is discontinuous,
ordinary hill-climbing over image size is not justified;
investigate Fourier-assisted candidate generation,
QIM early-stop checks, or another scale-invariant
synchronization mechanism instead. Do not change
production defaults based on these selected-cover results.

### Predeclared local score landscape (oracle-assisted mechanism study)

The new research-only
`tools/robust_qim_local_landscape_probe.py`
samples `(2*radius+1)^2` candidate pixel sizes
in a neighborhood **centred on the known encoded
size** and records the public CLR1-header score,
wrong-seed and wrong-delta scores, QIM lattice
contrast, matching LL2-grid indicator and per-size
scoring time. It reports the exact true-size rank
within the local window and the best competing
wrong-size score. Unsafe candidates are explicitly
reported as skipped, not silently discarded.

**This is an oracle-assisted mechanism test, NOT
a blind candidate search.** The encoded size is
deliberately used to place the diagnostic window;
it is never used inside `qim.score_size`. Oracle
payload recovery is performed only *after* all
candidate scores have been computed. Do not use
its true-size rank as evidence of blind scale
recovery. Production code and frozen Fourier
candidate generation remain unchanged.

First run: the same four development covers,
pilot strengths .12/.18, resize factors
`.62,.75`, `DELTA=38`, `REPEAT=13`,
`--radius 4` (up to 81 sizes per condition).
The .62 resize is **off the six generic scale
priors**; .75 is an in-prior control.
Compare the true-size score with its adjacent
±1..4-pixel competitors and stratify by
whether the LL2-grid shape is unchanged.
If header correlation is a narrow peak or
discontinuous across grid boundaries,
simple hill-climbing in width/height is not
justified. If the score remains informative
over nearby wrong sizes, test a predeclared
coarse-to-fine blind candidate generator
on independent covers next. End-to-end
latency and negative controls remain required.

### Local QIM landscape at 62% and 75% resize: 16/16 oracle-centred peaks

User-supplied `robust-v04-qim-local-landscape-01.csv`:
four selected covers × two nominal strengths (.12/.18)
× two resize factors (.62/.75) × 81 pixel-size offsets
(±4 in both dimensions): **1,296 CSV rows**.
**1,008** sizes scored; **288** marked
`SKIP:unsafe_size` because of decoder size limits.
The 16 unique condition-level oracle checks PASS,
and the known exact original pixel size has
**strict rank 1 in all 16 oracle-centred windows**.
These are **not 1,296 independent oracle successes**.
All four source images are development covers.

CLR1 header score distributions:
| Candidate relative to known original | Scored sizes | Median | Range |
| --- | ---: | ---: | --- |
| Exact original | 16 | **.9215** | .7217–.9710 |
| Wrong pixel size, same LL2 shape | 240 | **.6544** | .1385–.9293 |
| Different LL2 shape | 752 | **−.0095** | −.1239–.1291 |

In **every one of 16 conditions**, even the
*lowest* score among same-LL2-grid sizes exceeds
the *highest* score from all tested neighboring
different-grid sizes. The smallest such
within-condition separation is ~**.057** (photo,
62% scale). The exact-size vs best wrong-size
margin is smaller: **.0014–.217**; Kulutus-Web
`vika` at 62% is especially close (.0014/.0028).
Thus the soft CLR1 score has a broad local
**within-grid basin** but a sharp boundary
when LL2 dimensions change and the seeded
coefficient permutation changes. A naive
continuous hill climb across grid boundaries
is not supported; searching LL2 grid shapes
and refining pixel dimensions *within a
promising grid* is a better motivated
mechanism to test. These local windows
are centred on the known original dimensions,
so their perfect rank **does not demonstrate
blind unknown-scale discovery**.

Mean scoring time for 1,008 safe sizes:
**.0343 s/size**; total **34.569 s**
across 16 condition-level windows (mean
**2.161 s/condition**). Wrong-seed header
scores at the exact size range −.0462…+.0652.
No independent unmarked controls were
included in this local-window CSV.

**Predeclared next experiment:** a blind
aspect-ratio-constrained sweep of all plausible
pixel widths from the received width up to
`min(MAX_LONGEST, received_width/.5)`,
and ±2 height pixels around the received
aspect ratio. Group candidate pixel sizes by
LL2 shape, score **one representative per
shape**, shortlist the top five grid shapes,
then score/refine all candidates within those
five grids. Generate/rank sizes **only from
received dimensions**, with no true size,
resize factor, oracle or expected payload
used for candidate selection. The known
original is used only to report rank and
for an independent post-ranking oracle.
This makes the **50% minimum-scale bound
and preserved-aspect-ratio assumption**
explicit. Test four development covers at
62% resize and one pilot strength first,
then independently held-out images and
unknown/cropped/anisotropic resizes.
Measure full coarse+refinement+decode
latency before considering production.

### Blind LL2-grid sweep: research implementation and first run

`tools/robust_qim_blind_grid_sweep.py` implements
the above predeclared blind geometry search.
`blind_grid_bank(received_size, min_scale=.5,
height_jitter=2)` enumerates all safe pixel
sizes on a preserved-aspect-ratio strip;
`blind_rank` has **no original_size parameter**.
The bank is grouped by LL2 grid shape,
one deterministic central representative
per grid is scored using the public CLR1
header, the top five grids are shortlisted,
and all sizes within those grids are
rescored/ranked (cached representatives
are not rescored). An optional `--blind`
calls the actual decoder on the ranked
shortlist. The oracle runs separately
**after** all scoring/decoding.

First run is deliberately **rank-only** on
the four development covers, one strength
(.12), and off-prior resize .62; `--min-scale
.5 --height-jitter 2 --top-grids 5`.
This is an explicit **uniform-resize and
aspect-ratio preservation** assumption,
not robustness to cropping, anisotropic
resizing, or scales below 50%. Expected
coarse search breadth is ~285–357 LL2
grids per cover at .62, so this test is
not expected to be fast. The main
question is whether the true grid ranks
within the top five **without** any
oracle-centred candidate window.
Measure coarse+refinement times and
do not run the 40-attempt blind decoder
until true-grid shortlist recall is known.
Next test on independent covers and
multiple off-prior scales; no production
changes.

### First genuinely blind LL2-grid candidate search: 62% resize

User-supplied `robust-v04-qim-blind-grid-062-01.csv`:
four **development** covers, nominal pilot strength
.12, 62% LANCZOS resize, adaptive pilot,
`DELTA=38`, `REPEAT=13`,
`--min-scale .5 --height-jitter 2 --top-grids 5`.
All four rows are `status=OK`, `oracle=PASS`,
`blind_budget=0`, `blind_status=NOT_RUN`.
The candidate bank and coarse/refined QIM scores
were generated without any original-size or
resize-factor oracle. Encoded dimensions are
used only **after** scoring for diagnostics and
the separate oracle verification.

| Cover | All pixel candidates | LL2 grids | Coarse true-grid rank | True-grid representative score | Best wrong-grid score | Refined sizes | Exact-size rank | Coarse+refine+bank seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `kulutus-web-anal1.png` | 2435 | 285 | **1** | .792332 | .133924 | 62 | **1** | 5.909442 |
| `kulutus-web-vika.png` | 2705 | 357 | **1** | .902162 | .151600 | 33 | **1** | 13.327079 |
| `appfootprint-main.png` | 2690 | 325 | **1** | .587984 | .136155 | 41 | **1** | 7.099049 |
| `P1000450.JPG` | 2435 | 305 | **1** | .254785 | .167170 | 49 | **1** | 10.108366 |

**4/4** original LL2 grids rank first in the
coarse sweep; **4/4** exact original pixel
sizes rank first in the selected-grid
refinement. The photo's coarse-grid margin
is only **.087615**, substantially smaller
than the screenshot margins (.451829–.750562);
its score rises to **.843953** at the exact
pixel size. Thus scoring one representative
per LL2 grid appears promising, but there
is **no demonstrated universal coarse-score
threshold** and no unmarked-image false
positive control for this wide grid search.

Bank generation takes ~**.0012 s/case**.
Across four cases, coarse scoring takes
**32.179 s** and within-grid refinement
**4.260 s**, total **36.444 s** (mean
**9.111 s/case**). Coarse scoring is
~**88.3%** of measured search time.
The run scored 1,272 grid representatives
plus the uncached portion of 185 refined
candidate sizes. The method is currently
substantially slower than the previous
50%-resize scale-bank QIM and direct
decoding baselines, which are **not**
directly comparable on recovery rate
because those experiments used a different
resize factor and candidate geometry.

**Next experiment:** rerun the same four
62%-resize cases with `--blind
--decode-budget 40`, keeping all geometry
and ranking parameters fixed. Report
actual payload recovery, decoder attempts,
and end-to-end time (bank + coarse + refine
+ decode). The 4/4 oracle outcomes are
**not** blind payload recoveries. After
confirmation, test predeclared off-prior
resize factors and untouched source
images, including unmarked controls, before
claiming general robustness. No production
code changes.

### Actual blind packet recovery after unknown 62% resize: 4/4

User-supplied `robust-v04-qim-blind-grid-062-decode-01.csv`:
the same four **development** covers as the preceding
rank-only 62% experiment, nominal pilot strength .12,
adaptive pilot, `DELTA=38`, `REPEAT=13`,
`--min-scale .5 --height-jitter 2 --top-grids 5`,
`--blind --decode-budget 40`.
All four are `status=OK`, `oracle=PASS`,
**`blind_status=PASS` with exactly one decoder
attempt**, and the independently decoded pixel
size exactly equals the encoded original size
in each case. The blind search uses only received
dimensions, aspect-ratio and scale-range
assumptions, and the public CLR1 header;
the original size is consulted only after ranking
for diagnostics and the separate oracle check.

| Cover | Grids scored | Coarse true-grid rank | Refined exact-size rank | Decoded size | Coarse s | Refine s | Decode s | End-to-end s |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| `kulutus-web-anal1.png` | 285 | 1 | 1 | 1280×577 | 4.973 | 1.230 | .039 | 6.243412 |
| `kulutus-web-vika.png` | 357 | 1 | 1 | 1193×976 | 13.128 | 1.008 | .045 | 14.182105 |
| `appfootprint-main.png` | 325 | 1 | 1 | 1198×677 | 6.659 | .845 | .026 | 7.531052 |
| `P1000450.JPG` | 305 | 1 | 1 | 1280×960 | 8.850 | 1.447 | .050 | 10.348377 |

Across four cases: bank generation **.004946 s**,
coarse scoring **33.610 s**, within-grid
refinement **4.530 s**, and actual decoder
**.160 s**; total **38.304946 s**, mean
**9.576237 s/case**. Coarse scoring takes
**87.74%** of total time. These are separate
sequential timing runs, not controlled CPU
benchmarks. Relative to the preceding
rank-only run (mean ~9.111 s), the measured
search time changed slightly with run
conditions; this is not a method regression.

This is the **first actual blind payload recovery**
at an **off-prior** 62% resize factor in the
QIM-grid experiment. It does **not** establish
scale-invariance: the candidate search explicitly
assumes isotropic resizing, preserved aspect
ratio, `min_scale=.5`, and the codec's
`MAX_LONGEST` cap. These four covers are
reused development cases, not independent
validation. No unmarked-image false-positive
controls were included in this CSV.

**Next predeclared validation:** freeze the
current algorithm and parameters; run an
independent cover set at multiple off-prior
scales, including .55, .68, .83, using the
same `--blind --decode-budget 40` setting.
Record oracle vs blind PASS separately,
candidate recall, grid shortlist rank,
decoder attempts and full time. Also
measure unmarked covers under the same
received-size conditions, checking both
max CLR1 scores and whether *any*
CRC-validated packet is accepted.
Only after these tests should coarse
scoring speed be optimized. No production
code changes.

### Matched unmarked controls for blind LL2-grid search (predeclared)

New research-only
`tools/robust_qim_blind_grid_negative_control.py`
runs the **same blind grid bank, one-representative
coarse QIM scoring, top-K grid refinement and
optional decoder** on the **unmarked** source
images resized to exactly the same received
dimensions as the marked images. It does not
call pilot embedding, payload embedding, or
an oracle. It records max coarse and refined
CLR1-header correlations and separate
coarse/refinement/decoder times.

Crucially, a false positive is counted if
`robust.decode_at_size` returns **any**
CRC-validated payload, *not* merely if the
result equals a known research message.
`--decode-budget 40` checks the same maximum
number of ranked sizes as the marked arm.
The controls are paired by source image and
resize factor, not statistically independent
covers. No score threshold is preselected;
report both raw maxima and packet validation
outcomes. The tests for this tool are
committed but require local Fedora execution.

First control run: four development covers
at .62 scale, `min_scale=.5`, `jitter=2`,
`top_grids=5`, `DELTA=38`, `REPEAT=13`,
40 decode attempts. Then repeat on untouched
covers and several off-prior scales. A clean
result on four negative controls is necessary
but far from sufficient to estimate the
false-positive rate in deployment.

### Matched unmarked controls at 62%: no validated false positives in four covers

User-supplied `robust-v04-qim-grid-unmarked-062-01.csv`:
four **unmarked development covers**, resized to
62%, with the same source SHA256 hashes, received
dimensions, `min_scale=.5`, `height_jitter=2`,
`top_grids=5`, `DELTA=38`, `REPEAT=13`
and maximum 40 decode attempts as the preceding
marked blind-recovery experiment. The four
negative-control rows all report
`decode_status=NO_VALID_PACKET`,
`any_valid_packet=False`, no decoded size
or payload length. **0/4 false positives**,
with **154 actual packet decode attempts**:
40/40/39/35, the last two exhausting their
shorter refined shortlists. No valid
CRC-checked payload was returned at any
attempted size.

| Unmarked source | Coarse max CLR1 | Refined max CLR1 | Decoder calls | Total s |
| --- | ---: | ---: | ---: | ---: |
| `kulutus-web-anal1.png` | .120458 | .148959 | 40 | 7.588322 |
| `kulutus-web-vika.png` | .128839 | .146908 | 40 | 16.527107 |
| `appfootprint-main.png` | .156581 | .171035 | 39 | 7.929079 |
| `P1000450.JPG` | .136206 | .137906 | 35 | 10.133369 |

The **paired marked** run recovered the exact
payload in **4/4**, with one decoder call each.
Across these four covers, the smallest marked
coarse true-grid score is **.254785** and the
largest unmarked coarse maximum is **.156581**
(gap **.098204**). The smallest marked refined
best score is **.721666**, while the largest
unmarked refined maximum is **.171035**
(gap **.550632**). These are **development-set
separations**, not calibrated false-positive
rates or safe production detection thresholds.
Note also that a marked image's *wrong* grid
can score above some unmarked maxima, so a
score threshold must be evaluated at the
whole-receiver decision level, not interpreted
as proof of a correct grid.

Total unmarked run time: **42.177877 s**
(mean **10.544469 s/case**), comprising
bank generation **.004877 s**, coarse QIM
**34.330 s**, refinement **3.948 s**,
and unsuccessful decoding **3.895 s**.
The marked run's four successful first-try
decodes took only **.160 s** in total.
Rejecting unmarked images cheaply is therefore
an important future latency problem, but
any score-gating threshold must first be
tested for **false rejection of valid payloads**.

**Predeclared next validation (no algorithm changes):**
use **four or more genuinely new covers not
used in QIM development**, preferably a mix
of screenshots, photographs, text-heavy and
smooth-gradient images. Freeze the current
`min_scale=.5`, `height_jitter=2`,
`top_grids=5`, `DELTA=38`,
`REPEAT=13`, nominal pilot .12,
and decode budget 40. Run marked and
matched unmarked arms at off-prior resize
factors **.55, .68, .83**, recording
per-case oracle PASS, actual blind payload
PASS, true-grid rank, refined exact-size
rank, max coarse/refined score, false
packet acceptance and full timing.
Report all failures, including cases where
the true size was absent from the aspect
strip or the true grid missed the shortlist.
Do **not** choose score thresholds or
change shortlist sizes after seeing the
new validation outcomes. If candidate
coverage fails, treat it as a separate
geometry-search problem rather than
adjusting the packet decoder.

### Six held-out covers × three off-prior resize factors: 18/18 blind recovery, 0/18 unmarked

User-supplied paired CSVs:
`robust-v04-qim-heldout-marked-01.csv` (18 rows)
and `robust-v04-qim-heldout-unmarked-01.csv` (18 rows).
Six **new, user-selected** covers, each tested at
LANCZOS resize factors **.55, .68, .83**.
Both arms match exactly on source SHA256,
received dimensions, and resize scale.
The source names and hashes are intentionally
**not published** in this repository.

Frozen parameters: nominal adaptive pilot
strength .12 (effective strengths vary by
image, .036–.119894), `DELTA=38`,
`REPEAT=13`, `min_scale=.5`,
`height_jitter=2`, `top_grids=5`,
and `decode_budget=40`.

**Marked:** 18/18 `status=OK`, 18/18
`oracle=PASS`, 18/18 `blind_status=PASS`.
The correct LL2 grid has **coarse rank 1**
in all 18 cases, the exact original pixel
size has **refined rank 1** in all 18, and
the actual CRC-validated payload is
recovered in **exactly one decoder call**
for each. All 18 decoded sizes equal
their original encoded dimensions.

**Unmarked:** 18/18
`decode_status=NO_VALID_PACKET`,
`any_valid_packet=False`, with **562**
total decoder calls. The unmarked
candidate lists can have fewer than 40
refined sizes; each test checks up to
40 candidates, not necessarily 40.

| Resize | Marked blind PASS | Unmarked valid packets | Mean marked end-to-end seconds |
| --- | ---: | ---: | ---: |
| .55 | 6/6 | 0/6 | 11.141 |
| .68 | 6/6 | 0/6 | 10.673 |
| .83 | 6/6 | 0/6 | 8.716 |
| **All** | **18/18** | **0/18** | **10.1765** |

**Separation in this frozen validation set:**
minimum marked correct-grid coarse CLR1
correlation **.245896** vs maximum unmarked
coarse maximum **.157595**, a **.088301**
gap. Minimum marked exact-size refined
correlation **.778426** vs maximum unmarked
refined maximum **.157692**, a **.620734**
gap. Minimum correct-grid-vs-best-wrong-grid
margin within a marked case is only
**.085257**, at the .83 resize of one
photograph. These are empirical
development/validation-set gaps, **not**
precalibrated universal decision thresholds.

Timing: marked bank generation **.019974 s**,
coarse scoring **159.120 s**, refinement
**23.062 s**, and actual decoder **.975 s**
over 18 cases: total **183.176974 s**,
mean **10.1765 s/case**. Coarse scoring
accounts for **86.9%** of marked total.
Unmarked total **190.634358 s** over
18 cases (mean **10.5908 s/case**),
including **16.046 s** spent in unsuccessful
decoder attempts.

**Interpretation and limits:** this is
strong evidence of blind payload recovery
with **unknown, off-prior isotropic resize
factors** under a predeclared geometry
search. There are **six distinct source
covers**, not 18 statistically independent
covers; resize outcomes are correlated.
The search assumes preserved aspect ratio,
minimum scale .5, and the codec's maximum
image size. Images were **not JPEG
recompressed after resize**, cropped,
nonuniformly resized, or processed by a
real social media service. Zero observed
false packets in 18 controls is not proof
of a zero false-positive probability.
Do not tune a CLR1 cutoff on this set and
then treat it as independent validation.

**Next predeclared experiment:** freeze
the QIM grid search and test **resize
followed by JPEG recompression** with
quality **85 and 70**, 4:2:0 chroma
subsampling, and the same .55/.68/.83
scales, recording oracle vs blind recovery
separately and matched unmarked false
packets. The six covers become a
JPEG-transform development set once this
test is run. Investigate failures by
separating payload survival (oracle)
from grid candidate selection (blind).
No production changes until robustness
and visual quality are assessed.

### JPEG-after-resize paired blind-grid probe (implementation, not yet run)

Research-only `tools/robust_qim_blind_grid_jpeg_probe.py`
and `tests/test_robust_qim_blind_grid_jpeg_probe.py`
have been added. The test harness has not been
executed in this environment; run pytest on Fedora
before using the probe.

Frozen experiment: six previously held-out
covers (now **JPEG-transform development**
covers), nominal adaptive pilot .12, scales
`.55,.68,.83`, JPEG quality `85,70`,
**4:2:0** chroma subsampling, fixed
transform order **LANCZOS resize → JPEG
recompression**, `DELTA=38`,
`REPEAT=13`, `min_scale=.5`,
`height_jitter=2`, `top_grids=5`,
40 decoder attempts. Each source/scale/
quality pair produces one marked row and
one unmarked row, totaling **72 rows** for
six covers. Both arms are JPEG recompressed
with the same geometry and quality. The
marked arm reports the separate oracle
result and blind payload recovery, including
true-grid rank and exact-size rank.
The unmarked arm treats **any** validated
packet as a false positive, regardless
of payload. No code changes to the
production codec.

**Interpret failures by stage:** if
`oracle != PASS`, payload did not
survive the simulated JPEG transform even
at the known original dimensions, so
optimizing size search cannot repair it.
If `oracle=PASS` but blind decode fails,
inspect grid shortlist and refined
exact-size ranks to identify search
failure. The experimental resize-then-JPEG
pipeline is **not** proof of compatibility
with any specific social-media platform;
actual platforms may crop, rescale,
recompress, strip metadata or apply
other transformations.

### Resize then JPEG 4:2:0 recompression: 36/36 blind recoveries, 0/36 controls

User-supplied `robust-v04-qim-jpeg-recompress-01.csv`:
**72 rows**, six previously held-out (now
JPEG-development) covers × three resize
factors (.55/.68/.83) × JPEG qualities
(85/70) × two paired arms. Exact pipeline:
RGB marked/unmarked → LANCZOS resize →
**one** JPEG encode/decode with 4:2:0
chroma subsampling. Source hashes and
received pixel dimensions match between
the marked and unmarked arms for every
source/scale/quality pair. No initial
JPEG encode of the marked upload before
resizing, no crop, no real social-media
processing.

Frozen algorithm: adaptive nominal pilot
strength .12 (effective .036–.119894),
QIM `DELTA=38`, `REPEAT=13`,
`min_scale=.5`, `height_jitter=2`,
`top_grids=5`, 40 decoder calls maximum.

| Resize | JPEG85 marked blind PASS | JPEG70 marked blind PASS | Matched unmarked false packets |
| --- | ---: | ---: | ---: |
| .55 | 6/6 | 6/6 | 0/12 |
| .68 | 6/6 | 6/6 | 0/12 |
| .83 | 6/6 | 6/6 | 0/12 |
| **All** | **18/18** | **18/18** | **0/36** |

All **36/36 marked** cases have
`oracle=PASS`, `decode_status=PASS`,
`coarse_true_grid_rank=1`,
`refined_exact_rank=1`,
`decode_attempts=1`, and decoded size
equal to the original encoded size.
All **36/36 unmarked** controls report
`NO_VALID_PACKET`, `any_valid_packet=False`.
The unmarked arm made **1,198 actual
decoder attempts** across its 36 cases.
The controls test acceptance of *any*
CRC-validated packet, not a specific
expected payload.

**Correlations and margins:** minimum
marked correct-grid coarse score
**.209527**; maximum unmarked coarse
score **.180757**; observed cross-arm
gap **.028770**. Minimum within-case
marked correct-vs-best-wrong-grid margin
**.057839** (a photograph at .68, Q70).
Minimum marked exact-size refined score
**.668504**; maximum unmarked refined
score **.180757** (gap **.487747**).
The weakest coarse case was one photo
at .68/Q70: correct grid **.209527**,
best wrong grid **.151688**, refined
exact-size **.788886**. Lower JPEG
quality 70 reduced the refined exact
score compared with quality 85 in
**all 18 paired source/scale cases**
(mean reduction **.049673**) but
none lost payload recovery. These
gaps are not calibrated decision
thresholds and do not justify
threshold selection on this set.

**Measured timing:** marked
bank **.040 s**, coarse QIM **315.996 s**,
refinement **46.669 s**, decoder
**1.757 s**; total **364.462 s**
(average **10.124 s/case**).
Coarse scoring is **86.7%** of total.
Unmarked total **385.313 s**
(average **10.703 s/case**), with
**34.550 s** spent on unsuccessful
decoder calls. Timing is not
a controlled benchmark.

**Interpretation:** substantial evidence
that the current blind LL2-grid search
and packet embedding survive this
**simulated resize→JPEG70/85 4:2:0
pipeline**, under the declared scale
and aspect-ratio constraints. These
are six distinct covers and 36
correlated transforms, not 36
independent source samples. Zero
false positives in 36 controls does
not prove a zero false-positive rate.
This experiment does **not** test
initial JPEG upload compression
followed by a second JPEG pass,
real social-media services,
crop/nonuniform resize, or
perceptual invisibility. In
particular, previous small-UI
screenshot testing exposed visible
pilot artifacts; recovery success
must not be mistaken for acceptable
visual quality.

**Next predeclared gate:** before
production integration or
score-based early exits, measure
image fidelity on the same
marked/unmarked paired transforms
and native marked images using
existing `quality_metrics` (PSNR,
mean Y-SSIM, 1st-percentile local
SSIM, worst 16×16 luminance tile,
fraction of pixels with >4 and >8
RGB-channel change). Inspect
unmodified, full-resolution
screenshot crops for structured
pilot artifacts. Only after
acceptable quality should a
second-pass JPEG pipeline and
runtime optimization be tested.
Do not change the production codec
or tune thresholds on these
development cases.

### JPEG visual-fidelity gate: implementation pending local execution

Research-only `tools/robust_qim_jpeg_fidelity_probe.py`
and `tests/test_robust_qim_jpeg_fidelity_probe.py`
were added after the 36/36 JPEG blind-recovery
result. The tests and probe **have not been run**
in this environment. This is a quality gate,
not a change to the receiver or codec.

For each source, it measures the **same
unmarked vs marked image** at native codec
reference size and after **identical**
LANCZOS resize + JPEG 4:2:0 compression
at quality 85 and 70. Reuse the six
JPEG-development covers and scales
.55/.68/.83, nominal adaptive pilot
.12, QIM DELTA38/REPEAT13, same payload.
Metrics are PSNR, mean luminance SSIM,
1st-percentile local luminance SSIM,
RGB MAE, fraction of pixels changed by
>4 and >8, 99th percentile RGB change,
new saturated pixel fraction, and worst
16×16 luminance tile with coordinates.
Because both images receive the same
transform, this comparison isolates
*incremental embedding distortion*;
it does not measure total quality loss
from the original JPEG/resizing chain.

Optional `--sample-dir` saves local
native side-by-side PNGs, received
side-by-side PNGs for one selected
scale/quality, and exaggerated
native RGB difference images. Inspect
the **unmodified native side-by-side
images at 100% zoom**, especially
small UI screenshots with flat fills,
fine text, and edges. Do not interpret
an amplified difference image as
the actual visible artifact. No
absolute PSNR/SSIM pass threshold
has been predeclared; report raw
metrics and a human visual inspection
before deciding whether to optimize
the pilot or integrate production.

### Visual artifact variability: JPEG fidelity CSV and predeclared ablation

User-supplied `robust-v04-qim-jpeg-fidelity-01.csv`:
**36** source/resize/JPEG-quality rows from **six**
distinct covers, each measured at .55/.68/.83
and JPEG85/JPEG70. The native-size metrics
are **repeated six times per source**, not
36 independent native measurements.
The user visually reports that structured
artifacts are obvious in some images but
not others, with no clear common denominator.
The CSV does **not** record which source
the user judged visible. Do not assign
subjective visibility labels from PSNR
or SSIM alone.

At native codec size across six sources:
PSNR **36.9527–38.9015 dB**, mean
luminance SSIM **.968722–.991911**,
and worst 1% local luminance SSIM
**.779638–.908420**. Pixel fraction
with any RGB channel changed by >4 is
**16.65–37.63%**. The cover with the
**lowest effective pilot strength .036**
has local SSIM p01 **.779638**; another
cover at effective strength **.119439**
has p01 **.908420**. Thus the global
adaptive pilot strength is **not**
a sufficient predictor of local
distortion, much less perceived
periodic artifacts. The screenshot
has the highest native PSNR
(**38.9015 dB**) but the lowest
mean luminance SSIM (**.968722**).
The received-image metrics are
incremental embedding distortion
after matching resize and JPEG
processing, **not** total JPEG
quality relative to the source.

**Mechanistic hypotheses, not yet
validated:** the global Fourier
radial pilot may cause coherent
low-contrast ringing on certain
source spectra; Haar LL2 QIM
can introduce local/block-structured
luminance changes; the two can
interact. The current adaptive pilot
uses the **global fraction** of
15×15 windows with luma variance
<4 to scale a **global** Fourier
modulation; it does not locally
mask flat regions. Perceptual
sensitivity to structure and local
contrast is not captured by
global PSNR/SSIM.

New **research-only** ablation
`tools/robust_qim_artifact_ablation_probe.py`
and unit tests were committed, but
**not executed** in this environment.
With the same payload, nominal
pilot .12 and DELTA38/REPEAT13,
it produces and compares:
(1) `PILOT_ONLY` vs original;
(2) `QIM_ONLY` vs original;
(3) `FULL` vs original;
(4) `QIM_AFTER_PILOT` vs
pilot-only, to isolate the
incremental QIM change. CSV
reports native PSNR, mean and
p01 local SSIM, worst 16×16
luma tile and fraction of changed
pixels, plus luma MAE and
change frequency separately on
**flat** and **textured** regions
using the encoder's own local
variance criterion. Optional
full-resolution original/pilot/QIM/
full PNGs and 2×2 comparison
panels remain on the user's
computer; x8 difference maps
are **diagnostics only**, not
evidence of visible artifacts.

**Required subjective check:**
view unamplified native images at
100% zoom on the same display
and record for each source whether
PILOT_ONLY, QIM_ONLY, and FULL
show artifacts (e.g. 0=invisible,
1=minor, 2=noticeable, 3=obvious).
Only then compare subjective
ratings to flat-region metrics
and local SSIM. A successful
blind decoder does not guarantee
acceptable visual quality.
Do not alter production code
or prematurely implement spatial
pilot gating: the current narrow
radial rings may be broadened by
spatial gating and lose geometric
synchronization.

### Visual ablation confirms LL2 QIM as primary visible-artifact source

User-supplied `robust-v04-artifact-ablation-01.csv`:
six sources × four native-resolution ablation
variants = **24 rows**. The user inspected
the unamplified images and reports that
`PILOT_ONLY` shows **no visible artifact**
in the examined covers, whereas the other
variants (`QIM_ONLY` and `FULL`) show
visible patterns. This is a qualitative
observation, not a numerical visibility
score for each individual cover.

| Variant | Native PSNR range (dB) | 1% local SSIM range | Mean pixels >4 RGB-channel units |
| --- | ---: | ---: | ---: |
| PILOT_ONLY | 40.8007–47.6754 | .961629–.995773 | 2.5457% |
| QIM_ONLY | 41.0164–42.1592 | .781179–.919932 | 5.4602% |
| FULL | 36.9527–38.9015 | .779638–.908420 | 30.3008% |
| QIM_AFTER_PILOT (vs PILOT_ONLY) | 40.7259–42.1841 | .781310–.921853 | 5.3815% |

The screenshot has 1% local SSIM
`PILOT_ONLY=.989516`,
`QIM_ONLY=.785203`,
`FULL=.786414`.
The near-equality of `QIM_ONLY` and
`FULL` local SSIM on multiple covers,
plus the user's direct visual assessment,
strongly implicates the **Haar LL2 QIM
payload embedding**, not the Fourier
pilot, as the primary cause of
structured visible artifacts under
the current parameters. The Fourier
pilot still contributes to total
distortion (FULL has lower PSNR)
but does not show the same visual
artifact in isolation. No new
payload-recovery test is implied
by this ablation.

**Mechanism hypothesis:** parity QIM
at `DELTA=38` changes LL2 coefficients
that reconstruct as roughly 4×4
luminance regions, potentially exposing
block structure on low-texture or
highly regular content. The data
do not prove that block quantization
is the sole cause; perception is
content-dependent.

**Predeclared, no-code-change parameter
experiment:** keep the same six covers,
payload, adaptive pilot nominal .12,
`REPEAT=13`, transform order and
decoder, and compare `DELTA=38`
baseline against **32, 26, 20**.
First run `robust_qim_artifact_ablation_probe.py`
at each delta, comparing full-size
`QIM_ONLY` and `FULL` images and
local SSIM. Record subjective
visibility 0–3 for each source/delta.
Only if a candidate improves visibility
should `robust_qim_blind_grid_jpeg_probe.py`
retest **all** six covers ×
.55/.68/.83 × JPEG85/70 with the
matching delta, retaining all 36
marked blind results, oracle results,
and 36 negative controls. Do not
treat visual improvement as proof
of JPEG robustness. Avoid changing
`REPEAT`, pilot amplitude, payload
or grid-search parameters in this
first sweep. If lowering DELTA does
not remove the pattern while
preserving recovery, consider
alternative distortion-aware QIM
coefficient embedding, with new
format/versioning and a new
held-out validation set.

### Visual QIM delta-only sweep: 20 is the best tested visual setting (not yet decode-validated)

User-supplied `robust-v04-ablation-d32-01.csv`,
`robust-v04-ablation-d26-01.csv`, and
`robust-v04-ablation-d20-01.csv`:
**24 rows each**, six identical covers ×
four ablation variants. Source hashes,
reference dimensions, payload, nominal
adaptive pilot strength .12, and
`REPEAT=13` match across all three
experiments. `PILOT_ONLY` metrics
are exactly invariant across DELTA
as expected. The user independently
inspected the images and reports
`PILOT_ONLY` visually clean and
**DELTA 20 the best-looking** among
the tested QIM variants. The user
has not claimed that DELTA 20 is
completely invisible.

| Metric, mean of six distinct covers | DELTA 32 | DELTA 26 | DELTA 20 |
| --- | ---: | ---: | ---: |
| FULL PSNR (dB) | 38.1419 | 38.5818 | 38.6974 |
| FULL 1% local luminance SSIM | .86217 | .89949 | **.93068** |
| FULL changed pixels >8 RGB units (%) | 1.5668 | 1.1775 | **.6721** |
| QIM_ONLY PSNR (dB) | 42.2792 | 43.4442 | **44.1095** |
| QIM_ONLY 1% local luminance SSIM | .8679 | .9121 | **.9467** |
| QIM_ONLY changed pixels >4 RGB units (%) | 4.4706 | 3.2017 | **1.8476** |
| PILOT_ONLY 1% local luminance SSIM | .9837 | .9837 | .9837 |

In **all six** covers, the `FULL`
and `QIM_ONLY` 1% local SSIM improves
monotonically from DELTA32 to 26 to 20.
For `QIM_ONLY`, PSNR, >4 RGB pixel
fraction, worst-tile luminance MAE,
and flat/textured luminance MAE also
improve monotonically on all six.
FULL global PSNR is not strictly
monotonic for every cover, but the
FULL local SSIM p01 is. These are
paired source-level comparisons,
not 72 independent observations.

The FULL fraction of pixels changed
by >8 RGB-channel units falls by
**57.1%** from DELTA32 to DELTA20,
while FULL local SSIM p01 improves
by **.06851** absolute. QIM_ONLY
pixels changed >4 units fall by
**58.7%**. This corroborates
the QIM artifact mechanism but
does not establish JPEG robustness,
packet recovery, security, or a
universal quality threshold.

**Predeclared next gate:** with
**no changes to search or codec
implementation**, run the existing
paired `robust_qim_blind_grid_jpeg_probe.py`
at **DELTA=20**, `REPEAT=13`,
pilot .12, six covers ×
.55/.68/.83 resize × JPEG85/70
4:2:0, `min_scale=.5`,
`height_jitter=2`, `top_grids=5`,
decode budget 40. Record all
36 marked oracle outcomes,
all 36 actual blind payload
outcomes and all 36 matched
unmarked controls. Compare with
DELTA38 baseline (36/36).
If DELTA20 degrades recovery,
test DELTA26 with the same frozen
protocol as a fidelity/robustness
trade-off. Avoid choosing an
unvalidated DELTA for production
or modifying the encoder yet.

### JPEG recovery gate at DELTA20: 19/36 blind, 20/36 oracle (fails robustness gate)

User-supplied `robust-v04-qim-jpeg-d20-01.csv`:
**72 rows** (six source covers ×
resize .55/.68/.83 × JPEG 85/70
4:2:0 × marked/unmarked).
All 36 pairs match on original
source SHA256, received size,
scale, quality, strength and
frozen search parameters.
Compared against the matching
`robust-v04-qim-jpeg-recompress-01.csv`
at DELTA38, which achieved
36/36 oracle and blind PASS
and 0/36 control packets.

| Resize | JPEG85 marked blind PASS | JPEG70 marked blind PASS | Marked oracle PASS (both qualities) |
| --- | ---: | ---: | ---: |
| .55 | 3/6 | 1/6 | 4/12 |
| .68 | 4/6 | 3/6 | 7/12 |
| .83 | 4/6 | 4/6 | 9/12 |
| **All** | **11/18** | **8/18** | **20/36** |

**Marked:** 19/36 actual
`decode_status=PASS`, each in
exactly **one** decoder attempt.
**17/36 blind failures**, of which
**16** also have
`oracle=FAIL:ValueError` at the
known original size. Thus
16 failures are not fixable by
search ranking alone under the
current decoder/packet parameters.
One case (a photograph at .83,
JPEG85) has **oracle PASS** but
blind failure because the true
LL2 grid ranks **70th**, outside
`top_grids=5`. The true grid
ranked first in **29/36**, was
shortlisted in **31/36**, and the
exact original size ranked first
in **29/36**. The true size
had a refined rank for 31/36
cases (not shortlisted in five).
No conclusion about failure
subtypes inside `ValueError`
can be drawn without instrumenting
decoder error codes.

**Controls:** 36/36
`NO_VALID_PACKET`,
`any_valid_packet=False`,
**1,159** decoder attempts total.
No observed false packet; this
does not prove zero false-positive
probability.

**Source dependence:** one
photograph 6/6 blind PASS; another
photograph 0/6; the screenshot
0/6; other three covers 4/6,
4/6 and 5/6. JPEG85 succeeds
11/18 and JPEG70 8/18. The
coarse correct-grid correlation
mean fell from **.650872**
(DELTA38) to **.382074**
(DELTA20), a mean paired
reduction of **.268798**.
The minimum marked correct-grid
score at DELTA20 is
**−.000145**, while maximum
unmarked coarse score is
**.176106**; unlike DELTA38,
there is no global score
separation in this set.
The refined exact-size mean
at DELTA20 (31 shortlisted)
is **.648562**, vs
**.901312** for all 36
DELTA38 cases; different
sample counts preclude a
fully matched 36-row mean
comparison. Marked total
time ~**378.567 s**
(**10.516 s/case**), with
coarse search **314.508 s**;
unmarked total ~**384.190 s**
(**10.672 s/case**).
Timing is not controlled
performance benchmarking.

**Decision:** DELTA20
was the visually best setting
in the prior ablation, with
improved local SSIM, but
**fails the frozen JPEG
robustness gate** (19/36 vs
36/36 at DELTA38). Do not
change production defaults.
The next predeclared candidate
is **DELTA26**, same six
covers, same pipeline and
frozen parameters, including
36 paired unmarked controls.
Compare oracle and blind
recovery and local fidelity.
If DELTA26 still falls short,
test DELTA32; if all lower
deltas degrade robustness,
explore distortion-aware LL2
coefficient selection/encoding
rather than relying only on
a global quantization step.
Any new scheme needs separate
format compatibility planning
and genuinely new holdout covers.
Do not tune parameters to
individual failures in these
development images.

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

## 2026-11-20 checkpoint: perceptual QIM reshaping (visually rejected)

**Status:** research-only post-embedding experiment, not a production codec or format change. Two new covers: Screenshot_20261120_110855.png (UI; encoded reference 1120 × 709 in the JPEG gate) and DSCN0032.JPG (natural photograph). Frozen experimental QIM parameters: DELTA=38, REPEAT=13. The reference codec uses Haar LL2, randomized repeated parity-QIM and an independently tested blind LL2-grid search.

**Research question:** can post-QIM spatial redistribution reduce conspicuous 4×4 artifacts while preserving the information-bearing LL2 coefficients? Test groups were reference, pilot_only, qim_only, full, qim_ycc_control (extra RGB/YCbCr conversion control), and four candidate spatial redistributions: opt_s0p8_g0p5, opt_s0p8_g1, opt_s1p4_g0p5, opt_s1p4_g1.

The local unit tests **passed 7/7 (0.70 s)**. The image probe produced 18 rows (nine for each cover), and all reported QIM-bearing versions passed exact-payload PNG recovery.

| Cover | Candidate | Local SSIM-Y p01 | 4×4 boundary metric | PNG |
| --- | --- | ---: | ---: | --- |
| UI | qim_ycc_control | 0.760614 | 1.07444 | PASS |
| UI | opt_s0p8_g1 | 0.771282 | **0.91812** | PASS |
| UI | opt_s1p4_g1 | **0.784056** | 0.92352 | PASS |
| Photograph | qim_ycc_control | 0.804460 | 1.04118 | PASS |
| Photograph | opt_s0p8_g1 | 0.807445 | **0.89904** | PASS |
| Photograph | opt_s1p4_g1 | **0.818283** | 0.93877 | PASS |

Relative to the matched QIM+color-roundtrip control, the best boundary metric was about 14.5% lower on UI and 13.6% lower on the photograph, but the highest local SSIM p01 belonged to a different candidate.

**Human visual verdict: FAIL.** Direct inspection of the real full-size PNGs revealed clearly recognizable blocks in every QIM-bearing image, including both covers; pilot_only was comparatively clean. The changes optimized surrogate measurements without making the image subjectively acceptable. This rejects the tested post-embedding redistribution family, not every conceivable Haar-based codec.

### Paired resize/JPEG gate: measured CSV

Source: user-run screenshot-jpeg-gate-01.csv (36 rows). Three marked variants × Lanczos scales 0.55/0.68/0.83 × JPEG quality 85/70, explicit 4:2:0; one unmarked control for each marked case; transform order **resize then JPEG**. 40 candidate blind-decode budget. These are research transformations, not an observed social-media provider pipeline.

| Variant | PNG oracle | Resized JPEG oracle (true size) | Blind exact payload | Negative control valid packets |
| --- | ---: | ---: | ---: | ---: |
| qim_only.png | 6/6 | 5/6 | 6/6 | 0/6 |
| opt_s0p8_g1.png | 6/6 | 5/6 | 6/6 | 0/6 |
| opt_s1p4_g1.png | 6/6 | 5/6 | 5/6 | 0/6 |
| **Total** | **18/18** | **15/18** | **17/18** | **0/18** |

The 18 negative rows are *paired runs, not 18 distinct unmarked covers*, and zero observed false positives is not a population risk bound.

**The hard case:** 0.55× Lanczos followed by JPEG70. All three variants FAIL when decoded at the actual encoded dimensions 1120 × 709. Baseline QIM and opt_s0p8_g1 nevertheless decode in blind search at **1120 × 710**; opt_s1p4_g1 fails within the 40-attempt budget. The correct LL2 grid coarse-ranked first in all 18 marked scenarios. A one-pixel alternative restored-size difference can therefore affect bit recovery. The exact failure stage inside ValueError was **not isolated**; no claim about the CLR1 header, RS8 exhaustion, or majority-bit faults is justified yet.

**Decision:** do not integrate the tested pixel-redistribution optimizations. They do not pass visual quality, and the best-SSIM candidate also has a blind recovery regression on the hardest case. Preserve the images, SHA-bearing CSV, deterministic packet and parameters as a negative research result.

**Mechanistic hypothesis, not proof:** two-level Haar LL2 induces 4×4 support; a mean-changing parity QIM can create locally structured luminance perturbations. White or low-texture regions cannot mask those changes well, while saturation/clipping may constrain pixel redistribution. The cleaner pilot_only control motivates studying the QIM payload carrier first, separately from Fourier sync.

### Predeclared next experiments — no implementation or test results yet

**H-A: a smoother transform basis improves visual appearance at comparable robustness.**

Compare the existing two-level Haar LL2 against db2 and a selected biorthogonal wavelet (bior). Keep the source, preprocessed size, deterministic packet, pilot configuration, repetition, color pipeline and test transforms fixed. Use a matching encoder/decoder basis, with wavelet boundary-extension mode and real coefficient capacity documented. Different wavelets have different synthesis gain, overlap and coefficient counts: comparing numerically identical DELTA alone is *not* a fair visual-vs-robustness test. Begin with nominally matched DELTA for diagnostics, then compare visual quality at empirically matched payload recovery.

- H-A1 (visible quality): blind randomized A/B at **100% zoom** on *both* new covers must find fewer intrusive blocks **without replacing them with visible ringing/halos**. Report flat-area artifact rate, 4×4 boundary metric, local SSIM p01 and high-percentile pixel changes, but human acceptability is the primary endpoint.
- H-A2 (recoverability): PNG exact payload first; successful candidates then undergo identical 0.55/0.68/0.83 × JPEG85/70 4:2:0 and 40-attempt blind search, plus true-size oracle and matched unmarked controls. Record error subtype, candidate rank and decoded dimensions. An exploratory six-case test per cover is not a reliability guarantee.
- H-A3 (capacity): count usable coefficients, replication footprint, clipping, runtime and edge-extension behavior. Reject a visually attractive basis that cannot encode the same payload within capacity.
- **Falsify H-A** if smoother bases still make obvious artifacts, or all visible gains require a material loss of known-size or blind recovery compared to frozen Haar baseline. A higher SSIM alone does not count.

**H-B: content-aware placement can avoid conspicuous embedding in flat/saturated regions.**

Treat this as a *separate* experiment from wavelet substitution; start with Haar so the effect is isolated.

- H-B1 (oracle upper bound): derive a region map from the **original unmarked cover**, selecting robust textured/non-saturated regions. Hold the packet, repetition, quantizer and effective capacity fixed relative to a random-location control. Supply this original map explicitly to the decoder. Measure visual improvement, region occupancy, PNG/oracle JPEG recovery. Label the result **oracle-map only**, not blind success.
- H-B2 (genuine blind map): after geometric resynchronization, derive the map again **from the received resized/JPEG image**, with no access to original coordinates/maps or expected payload. Measure map Jaccard overlap, exact ordered-index agreement, capacity and end-to-end CRC-verified decode; test 1–2 pixel reconstructed-size variation.
- H-B3 (side information): if a stable receiver map cannot be regenerated, account for a bootstrap/index-map cost in bits, embedding visibility and error correction. Any side information must itself survive JPEG/resize. Do not quietly fall back to filling forbidden flat regions when capacity is insufficient.
- **Falsify H-B as a blind robust design** if the independently regenerated locations disagree enough to lose packet alignment, even where an oracle-map experiment looks excellent. Explicit SKIP for insufficient capacity.

**H-C: investigate nearby-size decode anomaly (diagnostic hypothesis).**

Hypothesis: interpolation phase changes LL2 coefficients and voting margins, so the correct encoded size may fail while a nearby decoded size succeeds. On the *identical received 0.55× + JPEG70 bytes*, probe a bounded ±1–2-pixel size neighborhood around 1120 × 709 and record repetition errors, majority-bit errors, CLR1 header bits, RS8 codeword-byte errors, CRC outcome and grid ranks. Keep this separate from blind candidate selection: do not use oracle size or known payload to score candidate locations. A successful nearby size demonstrates empirical resampling tolerance, not geometric invariance.

### Go/no-go and experiment order

1. Freeze the baseline and record **FAIL (human visibility)** for reshaped candidates. Preserve both original covers and their output hashes; do not retune this development set for a prettier metric.
2. **H-A first:** research-only Haar/db2/bior ablation, both covers, no-pilot QIM-only control, matched encoding/decoding and visual assessment; only then run resize/JPEG with negative controls. Do not alter the production wire format.
3. **H-B separately:** matched random placement versus original-image oracle map, then attempt independently reconstructed receiver map. An oracle map cannot pass the blind gate.
4. Investigate H-C if the failure mechanism materially affects a candidate's assessment.
5. Before adoption, evaluate **additional unseen images** (UI and natural), capacity and time, and report recovery denominators and negative-control results. Crops, rotation and aspect-ratio distortion are separate future gates, not covered by these JPEG/resize tests. A new coefficient order/basis needs an explicit versioning and compatibility plan for existing v0.3/CLR1 images.

**Primary acceptance criterion:** actual normal-view images are not spoiled by recognizable blocks or halos **and** exact-packet recovery is at least competitive with the predeclared Haar baseline under identical transformations. Failing either condition means research-only, even if a numerical metric improves.

## 2026-11-20 H-A execution checkpoint — stage 1 prepared, results pending

The next controlled experiment is the predeclared **H-A Haar vs db2 vs bior2.2** basis comparison. A research-only stage-1 script, unit tests and instructions were prepared as a downloadable local test package; **they are not yet committed to this branch** and have not been run in the user's CryptoLeaf environment. Do not infer a PASS from their preparation.

Planned script paths after extracting the package into the repository root:

- `tools/robust_wavelet_basis_probe.py`: independent, basis-matched level-2 QIM embedding and oracle-size decoding; the Haar implementation should match `robust._feedback_embed` pixel-for-pixel.
- `tests/test_robust_wavelet_basis_probe.py`: regression for Haar parity and pixel identity, PNG round trips on all three bases, negative control and capacity checks.
- `docs/ROBUST_WAVELET_HA_TEST.md`: detailed method, controls, quality measures and visual stop/go rules.

Proposed first run with **two development covers**, unchanged fixed packet, `DELTA=38`, `REPEAT=13`, `periodization`, level 2, **pilot=0** to isolate the data carrier:

```bash
python -m pytest tests/test_robust_wavelet_basis_probe.py -q
python tools/robust_wavelet_basis_probe.py \
  /path/to/Screenshot_20261120_110855.png \
  /path/to/DSCN0032.JPG \
  --out results/wavelet-ha-01
```

Record normal-view (100%, unamplified) visual verdict **for each basis on each cover**; report block/halo/flat-area artifacts, PNG exact payload, LL2 capacity and QIM repetition errors, SSIM p01, 4-pixel boundary gradient and flat-region luma distortion. A common numerical DELTA is only a diagnostic; it does not equate basis-dependent spatial distortion or JPEG robustness.

**Stage-1 exit:** if neither smoother basis is clearly less intrusive on *both* image types, reject simple wavelet substitution before spending time on the expensive JPEG matrix. If a candidate passes human visual screening and PNG recovery, build the separately instrumented **basis-aware** 0.55/0.68/0.83 Lanczos × JPEG85/70 4:2:0 oracle+blind+unmarked gate. Existing blind LL2-grid scorer and `robust.decode_at_size` are Haar-specific; do not reuse them unchanged for db2/bior. Freeze settings and compare at *matched observed recovery*, then use genuinely unseen covers before any integration. No changes to production `src/robust_image.py` or CLR1 wire format are authorized by this stage.

**Reproducibility note:** this checkpoint records the plan and filenames, **not experimental outcomes**. After local tests, commit the actual research script/tests and attach the CSV/visual verdict to this document, or explicitly note why the run was abandoned.

## 2026-11-20 H-A stage 1 — measured results (two local development covers)

**Status: completed PNG/oracle and visual screen; JPEG/blind NOT tested.** This section supersedes the "results pending" state in the preceding execution checkpoint. The user ran the H-A research script locally and supplied `stage1.csv` plus full-size MirrorPilot reference/Haar/db2/bior2.2 screenshots. The user also inspected the nature-photo results and reported residual visibility there. Research script/tests are still local test-package artifacts, not yet committed to this branch. Raw CSV and original photos are not stored in the repository.

**Frozen setup:** `haar`, `db2`, `bior2.2`; two-level `periodization`; `DELTA=38`, `REPEAT=13`, fixed CLR1/RS8 payload/seed; Fourier pilot strength **0**. Development covers: `Screenshot_20261120_110855.png` (1120×709) and `DSCN0032.JPG` (1280×960 after preprocessing). All six basis-matched, **known-size PNG** payload recoveries returned `PASS`. These are not blind decodes.

| Cover | Basis | SSIM-Y | SSIM-Y p01 | 4px boundary/inside residual gradient | Flat luma MAE | QIM repeated-position parity errors | QIM margin p01 |
|---|---|---:|---:|---:|---:|---:|---:|
| UI | Haar | 0.976259 | 0.785203 | 1.03103 / 0.06323 | 0.78993 | 33 | 0.00000 |
| UI | db2 | 0.979549 | 0.805269 | 0.28059 / 0.48356 | 0.86036 | 193 | -10.58898 |
| UI | bior2.2 | **0.991360** | **0.925040** | **0.26288 / 0.28171** | **0.70995** | 217 | -13.66787 |
| Photo | Haar | 0.984115 | 0.803583 | 1.04911 / 0.37648 | 1.27334 | 0 | 13.25000 |
| Photo | db2 | 0.985440 | 0.825658 | 0.52550 / 0.64407 | 1.28072 | 0 | 14.05645 |
| Photo | bior2.2 | **0.993390** | **0.932823** | 0.49252 / 0.49851 | **1.17069** | 0 | 13.49963 |

**Interpretation and limitations:**

- Bior2.2 clearly improves numerical perceptual quality on **both** covers and removes much of Haar's periodic 4-pixel boundary signature. On the UI cover, boundary/inside gradient ratio falls from about **16.3** (Haar) to **0.93** (bior2.2). This does **not** mean the modified image is visually imperceptible: in the user's inspection, residual speckle/changes remain detectable in the UI and nature photo. The stage-1 visual acceptance criterion has **not** been met.
- On the UI cover, bior2.2 has **217** wrong individual repeated QIM positions versus Haar's **33** (of **6032** embedded repeated positions). The 1st-percentile margin is negative for db2/bior2.2. The majority vote and RS8 still recover the PNG packet, but there is less evidence of margin for later JPEG/resizing. **Do not equate these individual parity errors with packet/byte errors or conclude a JPEG failure without testing.** The photo has zero repeated-position errors for all bases.
- `SSIM-Y p01` and boundary metrics describe different distortions; neither substitutes for 100%-zoom human inspection. A nominally identical DELTA is not a basis-normalized spatial or robustness comparison. This is a tiny development sample, not statistical validation.
- **Decision:** H-A's *relative visual improvement* is supported, but **simple wavelet replacement is not approved**: the artifacts remain visible and post-processing robustness is unmeasured. Do not run the expensive basis-aware blind-grid × JPEG matrix yet.

**Proposed cheap falsification gate (optional, before further architectural work):** perform only a small, separately logged **basis-aware oracle-size** stress test on these two covers (e.g. resize 0.83 + JPEG85 and resize 0.68 + JPEG70, explicit 4:2:0) using each basis's matching decoder. Retain the frozen Haar arm and same packet. This is intended to determine whether bior2.2's improved visual quality comes with a large robustness loss; it is **not** a substitute for blind search, negative controls, or new-cover validation. If bior2.2 fails materially, return to the planned perceptual optimization/adaptive embedding rather than blindly increasing DELTA and repeating a large sweep. Preserve all failures and source hashes.

## 2026-11-20 H-A stage 2 — minimal paired oracle JPEG gate prepared (awaiting local run)

**No results yet.** Following the stage-1 evidence (all six PNGs decode; residual visible artifacts, especially on UI covers), a small, basis-matched *known-original-size* JPEG gate has been prepared as a separate local test package. It is **not** a production-codec change and the script/tests have **not** yet been committed to this branch.

- Local research script: `tools/robust_wavelet_ha_oracle_gate.py`.
- Local unit tests: `tests/test_robust_wavelet_ha_oracle_gate.py` (7/7 passed in a dependency-light local test environment; full CryptoLeaf/wavelet integration awaits the user's run).
- Usage note: `docs/ROBUST_WAVELET_HA_ORACLE_GATE.md`.
- Input: saved `results/wavelet-ha-01/stage1.csv` and its exact reference/marked PNG files; stage-1 image hashes, packet hashes, basis, DELTA=38, REPEAT=13 and pilot=0 are checked before processing. No re-embedding.
- Predeclared paired transforms: **0.83× Lanczos → JPEG85 4:2:0**, **0.68× Lanczos → JPEG70 4:2:0**. Not a 2×2 matrix.
- Design: 2 covers × 3 bases × 2 transforms = **12 marked known-size oracle** decodes, plus **12 paired unmarked controls** using the same matching basis and original encoded dimensions. CRC-valid *wrong* payloads are not counted as exact success; any CRC-valid unmarked payload is a false positive.
- Instrumentation: repeated-position QIM parity errors, majority-bit errors, CLR1 header bit errors, pre-RS8 codeword-byte errors, margin p01, decode exceptions and input/JPEG SHA-256 hashes. These diagnostics explicitly know the original packet and size and are **not** blind-receiver features.

```bash
python -m pytest tests/test_robust_wavelet_ha_oracle_gate.py -q
python tools/robust_wavelet_ha_oracle_gate.py \
  --stage1 results/wavelet-ha-01/stage1.csv \
  --out results/wavelet-ha-oracle-01
```

Outputs: `results/wavelet-ha-oracle-01/oracle_gate.csv`, `summary.json`, `settings.json`. **Decision deferred until measured results:** if smoother bases repeatedly lose recovery where Haar succeeds, reject simple wavelet substitution at fixed strength; if they match Haar, this only warrants further research, since visible artifacts remain and neither blind synchronization nor real social-media transforms have been validated. Do not increase DELTA opportunistically or claim a population false-positive bound from these paired controls.

## 2026-11-20 H-A stage 2 — measured oracle JPEG results

**Status: completed, 12/12 marked oracle-size JPEG payloads recovered; 0/12 paired unmarked controls produced a valid packet.** This measured section supersedes the earlier stage-2 "awaiting local run" checkpoint. Evidence: user-supplied `oracle_gate.csv` (24 rows, 31 columns). The separate `summary.json` was not supplied; all statements here are derived from the CSV. No basis-aware blind-size search was run.

The frozen predeclared conditions were **two covers** (UI `Screenshot_20261120_110855.png`, 1120×709; photo `DSCN0032.JPG`, 1280×960), **three bases** (Haar, db2, bior2.2), **DELTA=38**, **REPEAT=13**, **pilot=0**, and exactly two transforms: **Lanczos 0.83 → JPEG85 4:2:0** and **Lanczos 0.68 → JPEG70 4:2:0**. Every marked row reports `stage1_png_oracle=PASS`, `oracle_status=PASS`, `valid_packet=True`, `exact_payload=True`. Every unmarked row reports `oracle_status=NO_PACKET`, `valid_packet=False`, `exact_payload=False` and `Invalid CLR1 header`. The negative-control count is *paired trials*, not 12 statistically independent covers.

| Basis | UI: 0.83 / Q85 | UI: 0.68 / Q70 | Photo: 0.83 / Q85 | Photo: 0.68 / Q70 | Total exact payload | Paired unmarked valid packet |
|---|---|---|---|---|---:|---:|
| Haar | PASS | PASS | PASS | PASS | **4/4** | **0/4** |
| db2 | PASS | PASS | PASS | PASS | **4/4** | **0/4** |
| bior2.2 | PASS | PASS | PASS | PASS | **4/4** | **0/4** |
| **All** | | | | | **12/12** | **0/12** |

### Instrumented decoder margins

The per-repetition parity errors are **individual repeated-position errors, not message-bit errors**. `qim_majority_bit_errors` and `qim_codeword_byte_errors` are counted against the known original packet in this oracle diagnostic; they are not blind-receiver outputs.

| Cover | Basis | 0.83 / JPEG85: repeat errors | 0.68 / JPEG70: repeat errors | 0.68 / JPEG70: majority-bit errors | 0.68 / JPEG70: pre-RS8 byte errors | 0.68 / JPEG70: QIM margin p01 |
|---|---|---:|---:|---:|---:|---:|
| UI | Haar | 563 | 795 | 0 | 0 | -16.50000 |
| UI | db2 | 579 | 683 | 0 | 0 | -17.60356 |
| UI | bior2.2 | 676 | **1011** | **4** | **4** | -17.57112 |
| Photo | Haar | 2 | 68 | 0 | 0 | -0.42250 |
| Photo | db2 | 0 | **10** | 0 | 0 | **3.09322** |
| Photo | bior2.2 | 6 | 269 | 0 | 0 | -6.17262 |

All twelve marked rows report **zero CLR1 header bit errors**. The only nonzero `qim_majority_bit_errors` and `qim_codeword_byte_errors` are **4 and 4** respectively for the UI / bior2.2 / 0.68× JPEG70 case. The RS8 stage successfully repaired that case and recovered the exact payload. Assuming the existing RS8 configuration can correct up to four unknown erroneous codeword bytes, this particular test reached its nominal correction limit; an additional unknown byte error in the same protected codeword could defeat the current decoder. Do not infer a guaranteed failure probability from this single sample. The CSV does not prove the remaining robustness under other transforms or pixel-size guesses.

### Interpretation and decision

1. **H-A2 is not falsified by this small JPEG gate.** All three bases recovered 4/4 exact payloads at known original dimensions. Smoother wavelets did **not** necessarily lose JPEG recovery at fixed DELTA=38 in these conditions. This is a useful correction to the preliminary concern from stage-1 PNG repetition errors.
2. **Bior2.2 is more fragile on the hardest UI case**, even though its stage-1 perceptual scores were best: 1011 individual parity errors, four majority-bit errors and four pre-RS8 erroneous bytes, versus zero majority-bit and byte errors for Haar and db2. In the harder photo case db2 has the strongest repetition-error count (10), compared with Haar (68) and bior2.2 (269).
3. **The visibility requirement is still NOT met.** The user's earlier full-size visual inspection found visible artifacts in both covers even with bior2.2. A perfect 12/12 oracle score does not reverse that verdict.
4. **Blind sync, pilot interactions, real social-media recompression, crops, nonuniform scaling and unseen covers remain untested.** The gate is not a justification for replacing the production Haar carrier.

**Recommended next decision:** do **not** spend time on a broad blind wavelet search while the visible-artifact requirement remains unmet. Move to **H-B** (content-aware/texture- and saturation-aware placement), initially as an *oracle region-map* ablation with a frozen Haar carrier and matched capacity, then explicitly test whether a decoder can independently regenerate the same coefficient ordering after JPEG/resizing. Keep bior2.2 as a visual-quality reference and db2 as a robustness-relevant comparator. If future H-B results are promising, revisit basis selection at **matched measured recovery** and add blind synchronization then. Preserve `oracle_gate.csv`, the exact images and the predeclared settings; no production codec or CLR1 format change was made.



## H-B1.8 / H-B1.9 and H-B2.1 follow-up (2026-11-20)

Research-only frozen H-B1.5 inward carriers, Haar LL2, DELTA=38,
REPEAT=13, pilot off, original-cover oracle maps and known original
dimensions. No production codec change.

H-B1.8 separated native-resolution JPEG from Lanczos down/upscaling
with a paired 2x2 factorial design. The UI screenshot's balanced
placement was much more vulnerable to resize-only than JPEG-only:
at 0.83/JPEG85, 2,124 versus 409 repeated parity errors; combined
2,229. The texture placement also failed resize-only while JPEG-only
passed. Natural-photo cases passed packet decoding. These are
observations on two images, not a generalized social-media claim.
See `docs/ROBUST_CONTENT_AWARE_HB18.md`.

H-B1.9 swept JPEG-free down/up Lanczos scaling 1.00 to 0.60.
For the screenshot, balanced failed already at 0.95, texture at
0.90, while random passed throughout the sweep. The natural photo
passed throughout. Resize sensitivity is image-content-dependent;
the oracle upscaling step is part of the measured channel.
See `docs/ROBUST_CONTENT_AWARE_HB19.md`.

**Next hypothesis H-B2.1:** assess whether original-cover local
features predict position-level resize parity errors on a held-out
image. Train per strategy and scale on one source, evaluate on the
other (both directions). AUC and lowest-risk 20% error fractions
are *observational diagnostics*; they do not constitute a new
placement algorithm or packet recovery result. The new script
`tools/robust_content_aware_hb21.py` reads H-B1.9 results and
original sources; see `docs/ROBUST_CONTENT_AWARE_HB21.md`.

**Product fallback if no robust and visually clean placement emerges:**
consider a pre-embed warning for high-risk cover structure, based
on measured risk/visual diagnostics and further image diversity.
Do not assume all screenshots are risky or that all photographs
are safe. Avoid promising social-media resilience. Preserve
the option of a separate embedding method if H-B2 fails.


## H-B2.2 — Broader-cover replication before adaptive placement

H-B2.1 suggested that texture placement may admit an original-cover
error-risk ranking, but only two images were studied. H-B2.2
(`tools/robust_content_aware_hb22.py`) performs **fresh** fixed-packet
inward embedding on a user-supplied 6–10 image set, comparing random,
texture and balanced with the original oracle maps. It measures
full-reference quality, placement overlays, PNG recovery, JPEG-only,
resize-only and combined resize+JPEG channels. This separates actual
visibility from the colored map overlay and tests whether the earlier
image-type differences persist. DELTA=38, REPEAT=13, Haar LL2, pilot=0
remain fixed. Full procedure: `docs/ROBUST_CONTENT_AWARE_HB22.md`.

The warning-only fallback remains open if no visually acceptable,
reliably decodable placement is found. No blind/social-media claims
or production changes follow from this exploratory experiment.


## H-B2.3 — Capacity-aware texture placement / refusal experiment

H-B2.2 demonstrated a capacity failure on the sparse technical
drawing `mitat.jpg`, even though texture placement was often visually
better on detailed images. H-B2.3 tests strict saturation-safe,
texture-thresholded placement versus explicit capacity-preserving
fallback at local 4x4 luminance std thresholds 0, 2, 5 and 10.
It re-embeds the same fixed packet using H-B1.5 inward and evaluates
actual oracle-map decoding and quality on the same nine images.
Strict insufficient capacity is reported as SKIP, a candidate
pre-embed warning. This is an exploratory threshold sweep, **not**
a validated perceptual risk predictor. See
`docs/ROBUST_CONTENT_AWARE_HB23.md`.

No production changes, blind-decoding claims, or social-media
robustness claims.


## H-B2.4 — Spatial dispersion hypothesis

Following H-B2.3, test whether top-texture placement is overly
spatially concentrated. H-B2.4 (`tools/robust_content_aware_hb24.py`)
compares strict highest-texture placement against deterministic
round-robin selection across 8x8, 16x16 and 32x32 LL2-coefficient
tiles. Each arm embeds the same fixed packet with inward feedback
and evaluates actual decoding under H-B2.2 channels plus quality
and tile occupancy. No saturation-unsafe fallback: `mitat.jpg`
should remain an explicit capacity SKIP, not be forced into
visually risky placement. See `docs/ROBUST_CONTENT_AWARE_HB24.md`.
All outcomes are original-cover oracle experiments, not blind
or social-media resilience validation.


## H-B2.5 — Texture-first capped placement and decoder design constraint

H-B2.4 found that forced spatial round-robin dispersion can improve
specific decoding channels while reducing SSIM. H-B2.5 tests a
weaker intervention: select highest-texture safe positions first,
but cap the number of positions per 16x16 LL2 tile at
1.5x, 2x or 3x the uniform active-tile mean. Compare with the
uncapped texture baseline using the same fixed packet and channel
suite, with actual inward re-embedding and oracle decoding.
If the cap or texture eligibility prevents full packet placement,
report SKIP rather than forcing unsafe positions.
See `docs/ROBUST_CONTENT_AWARE_HB25.md`.

**Architectural constraint:** image-adaptive placement requires more
than a decoder-side strategy identifier. The decoder must reconstruct
the same ordered coefficient map after image processing. A future
bootstrap/header could identify method and parameters, but would
not by itself solve map synchronization. Investigate stable
content-derived maps or a protected map channel separately before
claiming blind or social-media decoding. No production changes.
