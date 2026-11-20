# H-B1.7 — JPEG grid geometry versus QIM error

This is a **post-processing diagnostic** of H-B1.6 results, not a new
embedding experiment. Original-cover features and PNG QIM margins
are stratified alongside geometric position relative to JPEG's 8×8
blocks.

**Crucial distinction:** after Lanczos resizing by 0.83 or 0.68, an
original Haar LL2 4×4 cell does **not** map exactly to one JPEG 8×8
block. We approximate the source cell's rectangular footprint in the
resized image. Lanczos interpolation has wider support, so geometry
is a proxy, not an exact causal mapping. We also report the original
DWT 2×2 phase within an 8×8 source region.

The analysis compares random, texture and balanced separately for
each cover and JPEG channel, and further conditions phase/crossing
on cover-texture and post-embed PNG-margin quartiles. These
stratified groups are descriptive; no claims of independence or
statistical significance from repeated bit positions.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb17.py -q
python tools/robust_content_aware_hb17.py \
  --positions results/content-aware-hb16-01/position_features.csv \
  --sources /home/jari/Pictures/Screenshot_20261120_110855.png \
            /home/jari/Pictures/DSCN0032.JPG \
  --out results/content-aware-hb17-01
```

Outputs:
- `geometry_positions.csv` — per-repetition geometry and original
  H-B1.6 features/errors (JPEG channels only)
- `geometry_groups.csv` — unadjusted DWT phase, approximate JPEG
  block crossing, texture and PNG-margin group error rates
- `conditional_groups.csv` — phase and crossing within texture and
  PNG-margin quartiles, with sample sizes
- `settings.json` — exact input paths and geometry assumptions

**Decision rules:** If a strong phase/crossing effect remains within
texture and margin strata, follow up with a separately controlled
geometry ablation (and test JPEG without resizing to isolate the
8×8 grid). If not, avoid adding geometry heuristics and prioritize
a joint visual-quality/robustness objective. Sparse conditional
cells are inconclusive. No codec, maps, or packet changes.
