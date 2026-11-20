# H-B2.5 — Texture-first placement with bounded spatial concentration

H-B2.4 showed that round-robin spreading can improve some decode
cases, but reduced SSIM on all three pilot covers. Hypothesis:
**retain highest-texture candidates wherever possible**, while
limiting concentration in any single tile. This is distinct from
H-B2.4's equalizing round-robin.

For each source image, compute original-cover saturation-safe
4x4 texture scores. Divide Haar LL2 coefficients into 16x16
coefficient tiles (~64x64 pixels). Rank eligible positions by
texture, with the existing seeded tie-breaker. Select greedily,
rejecting a position only if its tile has reached its cap.

Compare baseline (no cap) to factors 1.5, 2, 3. The cap per tile is
`ceil(factor * required_positions / active_eligible_tiles)`.
A capped arm with insufficient total eligible slots is SKIP
(`SPATIAL_CAPACITY`), not silently relaxed. `mitat.jpg` still
fails texture capacity and must not be forcibly embedded.

Hold constant: fixed CLR1/RS8 payload, Haar LL2, DELTA=38,
REPEAT=13, inward feedback, pilot=0, original-cover oracle map.
Perform fresh embedding for each arm and measure true decode under
H-B2.2 channels, SSIM/PSNR, local quality and tile occupancy.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb25.py -q
python tools/robust_content_aware_hb25.py \
  /home/jari/Pictures/04-texture-in/teksti.png \
  /home/jari/Pictures/04-texture-in/kallio.JPG \
  /home/jari/Pictures/04-texture-in/kontrastit.png \
  --out results/content-aware-hb25-pilot
```

Outputs: `metrics.csv`, `settings.json`, marked PNGs and
ordered oracle `*-positions.npy` maps. Compare paired outcomes
within each image. Check whether caps actually change maps before
interpreting unchanged quality/decoding as independent evidence.

## Decoder architecture: separate research question

Knowing the chosen method is **not enough** for blind extraction:
the decoder also needs the exact coefficient order. Original-cover
texture ranks may change after JPEG/resizing or after embedding.

Possible future architectures:
1. A fixed-location, strongly protected bootstrap header carrying
   method/version/parameters, **plus** a recoverable map or a
   reproducible content-invariant placement rule.
2. A deterministic image-independent candidate map with a robust
   image-derived *selection* signal, subject to blind validation.
3. Explicit sidecar/manifest storing the map (not standalone
   steganography; must be labeled accordingly).

Do not implement or claim a blind decoder based only on a method
identifier. A bootstrap also needs synchronization, dimensions,
capacity, authentication/integrity and collision handling. The
present experiment remains oracle-only and makes no social-media
robustness claims.


## Results — 2026-11-20, three-cover pilot

Source: user-run `metrics(6).csv` (108 rows: 3 covers x 4
strategies x 9 channels); settings supplied in conversation
(DELTA=38, REPEAT=13, 16x16 LL2 tiles, factors 1.5/2/3,
original-cover oracle, pilot off). No independent local
reproduction of embedding has been performed.

| Cover | Baseline PASS | Cap 1.5 | Cap 2 | Cap 3 |
|---|---:|---:|---:|---:|
| teksti.png | 5/9 | 5/9 | 5/9 | 5/9 |
| kallio.JPG | 7/9 | 7/9 | 7/9 | 7/9 |
| kontrastit.png | 7/9 | 7/9 | 7/9 | 7/9 |
| **Total** | **19/27** | **19/27** | **19/27** | **19/27** |

No PASS/FAIL differences **in any individual source/channel pair**.
The four strategies nevertheless produced distinct marked PNG
SHA-256 values for every cover. Hence the intervention did
change the actual carrier, without changing binary outcomes
in this pilot.

SSIM-Y (baseline / cap 1.5 / cap 2 / cap 3):
- teksti.png: 0.998014 / 0.988725 / 0.993393 / 0.997952
- kallio.JPG: 0.999204 / 0.999175 / 0.999196 / 0.999206
- kontrastit.png: 0.988839 / 0.986464 / 0.987789 / 0.988513

Worst-tile luminance MAE (baseline / cap 1.5 / cap 2 / cap 3):
- teksti.png: 5.2726 / 8.0243 / 8.0243 / 4.9123
- kallio.JPG: 5.3377 / 4.2127 / 4.6874 / 5.3377
- kontrastit.png: 6.0887 / 6.1136 / 6.1753 / 6.5261

Max positions in a 16x16 LL2 tile (baseline / cap 1.5 /
cap 2 / cap 3):
- teksti.png: 125 / 42 / 55 / 83
- kallio.JPG: 68 / 31 / 41 / 61
- kontrastit.png: 183 / 35 / 47 / 70

Interpretation: the cap substantially reduced concentration, but
did not improve binary decoding on these covers. Strict caps
reduced SSIM-Y especially for the screenshot; the effect on
worst-tile error is mixed, and the rock photo has very small
SSIM differences. The observed results do **not** justify
selecting a cap as a universal production default. These are
paired measurements on three images, not 108 independent covers.

## Next research handover — H-B2.6

**Question:** can the receiver reconstruct the exact ordered
placement map from a received, possibly resized/JPEG-processed
image *without* the original cover?

Suggested isolated experiments:
1. Measure overlap (Jaccard), ordered-index agreement and
   displacement of selected LL2 positions when recomputed from
   the original cover, marked image, JPEG85 and resized variants.
   Normalize dimensions consistently; avoid using original
   image data in receiver-side selection.
2. Separately test whether an image-independent deterministic
   base map can survive transformations; distinguish *map
   agreement* from successful bit recovery.
3. Only if a stable placement mechanism exists, investigate
   a fixed-location protected bootstrap header for strategy,
   version and parameters. A strategy ID alone is insufficient.
4. Use the same cover/channel pairs, log hashes and
   non-independence, include explicit negative controls.

No blind decoder exists yet; oracle recovery does not establish
social-media robustness. Preserve all production code unchanged
until receiver-side map synchronization is validated.
