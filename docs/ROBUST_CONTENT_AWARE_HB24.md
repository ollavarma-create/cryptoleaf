# H-B2.4 — Texture placement with spatial dispersion

**Hypothesis:** H-B2.2/H-B2.3 show that texture eligibility alone
does not guarantee robustness or visual acceptability. Strongest
texture coefficients can cluster spatially. Does distributing the
*same number of selected coefficients* among image regions improve
perceptual quality without sacrificing successful decoding?

This is an actual re-embedding experiment, not a retrospective
selection of already embedded bits.

Arms:
- `texture_baseline`: highest-scoring saturation-safe LL2
  coefficients, with seeded deterministic tie-breaking.
- `spread_8`, `spread_16`, `spread_32`: partition the LL2 grid
  into tiles of 8, 16, 32 coefficients per side (roughly 32, 64,
  128 original pixels per side). Within each tile rank candidates
  by texture, then select candidates round-robin among tiles.
  Do not silently include saturation-unsafe candidates. If the
  eligible count is insufficient, mark all arms SKIP.

Hold fixed: original-cover oracle, inward feedback, Haar LL2,
DELTA=38, REPEAT=13, fixed CLR1/RS8 packet, pilot off.
For every marked carrier, run identity, resize-only, JPEG85,
and resize+JPEG channels from H-B2.2. Record recovery,
PSNR/SSIM, spatial occupancy, clipping and selected edge/flat
fractions. Save marked PNGs and position maps.

Pilot:

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb24.py -q
python tools/robust_content_aware_hb24.py \
  /home/jari/Pictures/04-texture-in/teksti.png \
  /home/jari/Pictures/04-texture-in/kallio.JPG \
  /home/jari/Pictures/04-texture-in/kontrastit.png \
  --out results/content-aware-hb24-pilot
```

Full nine-image sweep: provide all original images from H-B2.2
with a *different* output directory. `mitat.jpg` is intentionally
expected to SKIP under all arms: spreading cannot create eligible
texture capacity. The strict-capacity warning is preserved.

Interpretation: compare each spread arm to its **own source's**
baseline, rather than treating many channels of the same carrier
as independent images. Inspect marked PNGs against original images
at 100% zoom; spatial coverage alone is not perceptual improvement.
Check whether dispersion changes PASS/FAIL, error counts, and
SSIM/PSNR; negative outcomes are informative. This experiment
does not establish blind recovery or social-media robustness.
