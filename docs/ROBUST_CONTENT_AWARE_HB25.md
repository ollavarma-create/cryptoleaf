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
