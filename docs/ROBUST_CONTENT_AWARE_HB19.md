# H-B1.9 — JPEG-free Lanczos scale sensitivity

H-B1.8 showed that resizing/upscaling alone can break the screenshot
texture and balanced strategies. H-B1.9 sweeps the **scale factor**,
holding embedding and all other variables fixed.

- Input: original H-B1.5 **inward** marked PNG files, H-B1.2 ordered
  original-cover oracle coefficient maps.
- Scales: 1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60.
- Channel: Lanczos downsample then Lanczos upscale to original size;
  **no JPEG**, no re-embedding, no pilot.
- Haar LL2, DELTA=38, REPEAT=13, original CLR1/RS8 packet.
- Three strategies: random, texture, balanced. Two original images.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb19.py -q
python tools/robust_content_aware_hb19.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --maps-dir results/content-aware-hb12-01 \
  --hb15-dir results/content-aware-hb15-01 \
  --out results/content-aware-hb19-01
```

Outputs: `scale_summary.csv` (decode, repetition, majority, RS8,
median/p90 absolute LL2 drift), `scale_positions.csv` (per-position
errors, cover local standard deviation, drift), `settings.json`
(reproducibility).

Interpretation: plot repetition errors and majority-bit errors against
scale separately per source and strategy. Identify whether errors rise
gradually or show a threshold, and whether the affected original-cover
texture groups differ. Correlation does not establish a generalizable
scale-invariant placement rule; only two covers are studied. Scale 1.0
is an identity control. The down/up chain is deliberately the same
oracle-size restoration used by the decoder, not a claim about
downsampling in isolation.

This script never modifies production code or earlier results and
refuses to overwrite existing output.
