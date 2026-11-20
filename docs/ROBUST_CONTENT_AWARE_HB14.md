# H-B1.4 — feedback-loop instrumentation

**Goal:** determine why H-B1.2 balanced placement looks visually clean but
fails screenshot PNG oracle recovery. No production changes.

Replays each existing H-B1.2 image from its ORIGINAL source and ordered
coefficient map. The replayed RGB pixels **must exactly equal** the saved
marked PNG; a mismatch aborts before writing any results.

Each executed feedback iteration records:
- parity errors at reconstructed floating-point Y (before clipping);
- parity errors after Y clipping and after 8-bit rounding;
- parity errors after YCbCr → RGB → YCbCr round-trip;
- majority/header/RS8 byte errors;
- repaired vs newly broken positions compared with the previous iteration;
- clipped pixel fraction and mean RGB-roundtrip Y discrepancy.

Final region error rates are grouped by H-B1.1 directional-edge, flat and
other masks. This is an oracle-map experiment, not blind decoding.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb14.py -q
python tools/robust_content_aware_hb14.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --marked-dir results/content-aware-hb12-01 \
  --out results/content-aware-hb14-01
```

Outputs: `feedback_iterations.csv`, `final_region_errors.csv`,
`settings.json`. Existing results are untouched.

**Predeclared decision tree:** If errors appear before clipping, inspect
inverse transform/quantization and coefficient boundaries. If errors
appear only after clipping, clipping contributes. If errors appear only
after RGB round-trip, color conversion contributes. If feedback repairs
and creates errors simultaneously, inspect oscillation/stalling before
changing its update rule. PNG failure and JPEG instability are separate
failure mechanisms; this experiment primarily isolates the former.

Stage masks and region groups overlap; don't sum their counts. This
test does not validate JPEG resilience, independent map regeneration,
blind synchronization, or steganalysis resistance.
