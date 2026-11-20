# H-B2.3 — Texture capacity vs visible distortion and robustness

H-B2.2 showed texture placement has promising visual quality but
fails the eligibility/capacity test on `mitat.jpg`. This experiment
compares **strict** eligibility (skip if insufficient capacity) against
**fill** (rank saturation-safe, texture-qualified 4x4 LL2 blocks first,
then fill from other blocks). Original-cover local standard deviation
thresholds are 0, 2, 5, 10; they are **not calibrated safety limits**.

For each input image and threshold, run fresh inward embedding at
Haar LL2, DELTA=38, REPEAT=13, fixed CLR1/RS8 packet, pilot off,
original-cover oracle map. Evaluate PNG identity, Lanczos resize-only,
JPEG85 and combined resize/JPEG channels as in H-B2.2. Record actual
PASS/FAIL, selected saturation/edge/flat fractions, SSIM/PSNR and
feedback diagnostics. Strict SKIP is an explicit **capacity warning**
rather than a silent unsafe fallback.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb23.py -q
python tools/robust_content_aware_hb23.py \
  /home/jari/Pictures/04-texture-in/teksti.png \
  /home/jari/Pictures/04-texture-in/kallio.JPG \
  /home/jari/Pictures/04-texture-in/kontrastit.png \
  /home/jari/Pictures/04-texture-in/meri.JPG \
  /home/jari/Pictures/04-texture-in/mitat.jpg \
  /home/jari/Pictures/04-texture-in/mvkuva.jpg \
  /home/jari/Pictures/04-texture-in/mvkuva2.jpg \
  /home/jari/Pictures/04-texture-in/puhelin.JPG \
  /home/jari/Pictures/04-texture-in/taivas.JPG \
  --out results/content-aware-hb23-01
```

Outputs: `metrics.csv`, `settings.json`, marked PNGs and oracle
position maps. The output folder must not exist. If the full run
takes too long, use a two-image pilot (`mitat.jpg` and `teksti.png`)
with a different output folder, then run all nine images.

**Important:** thresholds affect candidate *eligibility*, not a
validated image quality risk score. Strict and fill may select the
same positions if capacity suffices; compare map equality and metrics
before treating repeated measurements as independent evidence.
A fallback can increase clipping and visual artifacts. Neither
successful oracle decoding nor a high SSIM proves social-media
robustness or blind extraction. Evaluate marked PNGs against
reference images visually at 100% zoom; the original H-B2.2
reference_image preprocessor can resize large sources.

Next decision: if strict rejects a cover but fill makes visible
artifacts or fails under resize, prefer a user warning/decline rather
than forced embedding. Production source and prior experiments
remain unchanged.
