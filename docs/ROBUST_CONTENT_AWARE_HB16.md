# H-B1.6 — original-cover predictors of JPEG coefficient instability

H-B1.5 repaired all 242 balanced screenshot PNG parity errors, but the
JPEG channel still breaks recovery. This **diagnostic** asks which
properties of original 4×4 luminance blocks correlate with those
channel errors, comparing random, texture and balanced placement.

**No new embedding or placement.** Read existing H-B1.2 ordered maps and
H-B1.5 inward PNGs. Preserve packet, pilot=0, Haar LL2, DELTA=38,
REPEAT=13, and the three frozen channels.

Features computed solely from the **original unmarked cover**:
4×4 luminance mean, standard deviation, clipping headroom, directional
edge, flat classification, texture eligibility, and cover QIM
decision-boundary margin. PNG lattice margin is recorded separately:
it is known to the encoder only **after** embedding and must not be
misrepresented as an original-cover feature.

For every selected repetition position, report received parity error,
PNG parity error, parity flip relative to PNG, and absolute LL2 drift.
Feature quintiles report error and flip fractions for each
cover/strategy/channel; ties use stable rank ordering and quintiles
are descriptive, not trained classifiers.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb16.py -q
python tools/robust_content_aware_hb16.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --maps-dir results/content-aware-hb12-01 \
  --hb15-dir results/content-aware-hb15-01 \
  --out results/content-aware-hb16-01
```

Output:
- `channel_summary.csv`: baseline oracle decode and errors
- `feature_quintiles.csv`: 5 quantiles per feature/cover/strategy/JPEG channel
- `position_features.csv`: individual positions for further offline analysis
- `settings.json`: provenance and fixed parameters

**Decision gate:** If original-cover headroom/texture consistently
separate high- and low-error positions *within both images*, propose
a new selection ablation that uses only original-cover features. If
separation is weak, investigate JPEG block alignment, coefficient
geometry, and packet-bit interleaving before changing the selector.

Caveats: 4×4 DWT blocks and 8×8 JPEG blocks are not aligned in a
trivially independent way. Position-level errors are spatially and
bitwise dependent, so do not interpret the 6,032 repeated positions
as independent statistical samples. No blind map reconstruction,
social-media validation, or steganalysis claims. Do not change
`src/robust_image.py` or CLR1 framing.
