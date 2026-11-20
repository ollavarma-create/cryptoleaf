# H-B1.5 — bounded feedback correction, paired oracle test

H-B1.4 isolated luminance clipping and RGB conversion as major PNG parity
error sources; feedback failed to improve them. This is a controlled
mechanism test, **not** a new production codec.

The same original covers, packet, Haar LL2, DELTA=38, REPEAT=13,
pilot=0 and original-cover ordered coefficient maps are retained.

Four arms for each random, texture and balanced placement:
- **baseline:** exact H-B1.4 replay, pixel-equal to saved H-B1.2 PNG
  (mandatory gate).
- **inward:** for wrong coefficients, one step of **two QIM lattice
  indices** toward the available 0–255 luminance headroom.
- **outward:** same magnitude, opposite direction; a negative control.
- **adaptive:** explicitly uses the per-coefficient original LL2
  luminance mean to choose the headroom direction. At this stage
  inward and adaptive deliberately implement the **same rule**; they
  are a reproducibility control, not independent algorithms.

Each coefficient can move at most once, by 2*DELTA in LL2 (19 luma
units for an isolated Haar LL2 coefficient at DELTA=38). This
preserves its target lattice parity before clipping, but can produce
visible distortion and does not guarantee recovery after conversion.
The repeated attempts after a step observe, but do not keep stepping.
No image inversion, blur, or quality degradation is applied globally.

Test both covers × three placement strategies × four feedback arms ×
three receive channels (PNG, Lanczos 0.83→JPEG85 4:2:0,
Lanczos 0.68→JPEG70 4:2:0). Results contain exact CRC-checked
oracle packet status, parity/majority/header/RS8 diagnostics,
quality metrics, clipping fraction and feedback traces.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb15.py -q
python tools/robust_content_aware_hb15.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --marked-dir results/content-aware-hb12-01 \
  --out results/content-aware-hb15-01
```

Review **marked PNGs** at 100% zoom (not earlier color map overlays).
Compare with the balanced baseline; look especially at horizontal UI
rules, text, flat regions and localized halos. Better PNG recovery
without JPEG robustness and visual quality is not success.

**Hypotheses:** H15-A inward shift reduces PNG parity failures;
H15-B outward shift performs worse; H15-C improving PNG correctness
does not necessarily improve JPEG resilience; H15-D any correction
may compromise balanced's excellent visual quality.

**Scope limitations:** This does not test blind map recovery, real
social-media processing, negative controls or steganalysis. Avoid
selecting a method solely by fitting these two images. Keep
src/robust_image.py and CLR1 unchanged.
