# H-B1.3 — LL2 margin and channel-instability diagnosis

**Goal:** explain the H-B1.2 paradox: balanced looks much better on UI
covers but fails even PNG oracle recovery, while the natural photo passes.

This experiment does **not** modify the encoder, coefficient selection,
packet, strength, or prior results. It reads the existing H-B1.2
`*-random.png`, `*-texture.png`, `*-balanced.png` and their exact
`*-positions.npy` maps. Repeating H-B1.2 is unnecessary.

For each of 2 covers × 3 strategies × 3 channels, measure:
- **PNG parity errors**: wrong repeated positions in the stored marked PNG.
  These expose embed/feedback/color-roundtrip failures before JPEG.
- **Received parity errors** and **parity flips** relative to marked PNG.
  The difference separates initial embedding errors from channel changes.
- **Lattice rounding margin**: distance from observed LL2 coefficient to
  the nearest decision boundary, in coefficient units, range [0, DELTA/2].
  This is *not* a guarantee of correct parity; a confidently wrong
  coefficient can have a large margin.
- **Absolute LL2 drift** under resizing/JPEG and distributions by
  directional-edge, flat, other, header, codeword, low-margin groups.
- Per-majority-bit repeat error counts, edge/flat occupancy, margin,
  and drift. `majority_wrong` uses the actual strict majority threshold.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb13.py -q
python tools/robust_content_aware_hb13.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --marked-dir results/content-aware-hb12-01 \
  --out results/content-aware-hb13-01
```

**Outputs:** `margin_summary.csv` (126 group rows),
`bit_diagnostics.csv` (one row per message bit per arm/channel),
`settings.json` with source paths and marked PNG SHA256 hashes.
New output directory required; existing results are never overwritten.

**Hypotheses:**
- H13-A: balanced PNG failures are already present before channel
  degradation (feedback/roundtrip saturation or selected positions).
- H13-B: JPEG channel flips concentrate among low-margin positions,
  with stronger drift on directional edges than on other regions.
- H13-C: header and codeword errors differ, and the limiting mechanism
  is not explained by overall SSIM.

**Decision gate:** if H13-A holds, diagnose the embedding feedback
algorithm before adding JPEG-robust selection. If only H13-B holds,
test a reliability-aware selector in a *separate* controlled ablation.
The map and dimensions are oracle-known. This does not test blind
reconstruction, real social-media pipelines, or security.

**Interpretation caution:** groups overlap (header/edge/low-margin);
do not sum group counts. Edge labels are heuristic. The existing
production decoder has bounded header recovery; a simple count of
header errors does not reproduce its entire recovery path.
