# H-B1: original-cover oracle-map placement ablation

Research only. This experiment isolates coefficient placement with frozen
two-level periodized Haar, DELTA=38, REPEAT=13, fixed CLR1/RS8 packet, pilot=0.

The two arms embed exactly the same packet in the same number of LL2 positions:
- **random** uses the current seeded coefficient permutation, and should match
  the existing feedback embed pixel-for-pixel;
- **texture** ranks 4×4 original-cover blocks by luminance standard deviation,
  excludes near-black/white blocks, and selects exactly the required number
  using seeded tie-breaking. If capacity is insufficient, it SKIPs. It does
  not silently spill into flat or saturated regions.

Both arms use the **original-cover oracle map**, supplied directly to the
decoder along with original dimensions and packet length. PNG, Lanczos 0.83
→ JPEG85 4:2:0 and Lanczos 0.68 → JPEG70 4:2:0 are measured at known
dimensions. This is **not** a blind map, not a Fourier-sync test, and not
a production codec. It does not establish robustness under map regeneration.

Run (local source files are intentionally not committed):

```bash
python -m pytest tests/test_robust_content_aware_hb1.py -q
python tools/robust_content_aware_hb1.py \
  /home/jari/Pictures/0-4-mosaic-in/Screenshot_20261120_110855.png \
  /home/jari/Pictures/0-4-mosaic-in/DSCN0032.JPG \
  --out results/content-aware-hb1-01
```

Inspect the saved random and texture PNGs at **100% zoom**, especially
uniform UI surfaces, text, edges, and natural texture. Report artifacts,
halos, and any conspicuous concentrated noise. A higher SSIM alone is
insufficient. Preserve output hashes, metrics.csv and settings.json.

**Limitations:** Original-cover texture selection is an oracle upper-bound
experiment, not proof of a workable receiver map. JPEG results use the
same original index map even after resampling. The texture heuristic is
deliberately simple, and its high-score regions can still show visible
artifacts. A positive H-B1 result requires independent H-B2 map
regeneration tests, exact ordered-index agreement, CRC-validated blind
decode and unseen covers before any codec change.

**Go/no-go:** If texture placement fails to improve normal-view quality
without reducing oracle recovery, reject this simple selector; do not
increase DELTA to conceal failure. No changes to src/robust_image.py or
CLR1 framing are authorized.
