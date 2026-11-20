# H-B1.2 — capacity-aware, edge-penalized placement

**Research question:** Can a third placement strategy retain the photo
quality improvement of H-B1 while avoiding screenshot JPEG failures?

This is a paired, original-map **oracle** ablation, not a blind decoder.
Three arms on identical covers, packet and fixed Haar LL2 settings:
1. `random`: seeded baseline permutation (unchanged).
2. `texture`: original H-B1 local-std ranking (unchanged).
3. `balanced`: log(1 + 4×4 luma std), penalizing directional edges,
   very flat blocks and saturated blocks, with a soft 8×8 LL2-tile quota
   (50% occupancy by default). Quota fallback is counted, never hidden.
   It always uses exactly the same number of LL2 coefficients.

**No parameter fitting on these two covers.** This is one predeclared
heuristic. The edge labels are the exploratory Sobel/std labels from
H-B1.1, not a validated perceptual segmentation model.

Each arm produces an embedded PNG, colored position-map overlay, ordered
`positions.npy`, and three oracle decodes: PNG, Lanczos 0.83→JPEG85
4:2:0, and Lanczos 0.68→JPEG70 4:2:0. `metrics.csv` contains quality
metrics, QIM parity/majority/CLR1/RS8 diagnostics, edge/flat/saturation
selection fractions, SHA256 hashes and quota fallback counts.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb12.py -q
python tools/robust_content_aware_hb12.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --out results/content-aware-hb12-01
```

**Preflight:** output directory must not exist. No source image or old
H-B1/H-B1.1 result is overwritten. Compare random/texture hashes to
H-B1 (same source, packet, DELTA/REPEAT) before interpreting differences.
At 100% zoom, inspect the *embedded PNGs*, not the deliberately colored
`*-map.png` overlays. Do not interpret overlays as embedding artifacts.

**Decision criteria:** balanced must (a) retain exact oracle packet
recovery on both JPEG gates, (b) improve visual quality in the UI
without introducing concentrated local damage, and (c) not sacrifice
the natural-photo advantage. A higher mean SSIM alone is insufficient.
If it fails, inspect error distribution and reject/modify the
hypothesis rather than raising DELTA. Negative unmarked controls and
blind independent map regeneration are separate later gates (H-B2).

**Scope:** pilot=0, original cover and ordered map supplied to the
decoder, original dimensions and packet length known. No CLR1 wire,
production decoder, or GUI changes. A pass does not establish social
media robustness.
