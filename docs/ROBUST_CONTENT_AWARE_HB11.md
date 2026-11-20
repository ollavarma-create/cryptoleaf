# H-B1.1 — placement maps and QIM error diagnostics

**Purpose:** explain why the screenshot's texture arm passes PNG but
fails the paired Lanczos/JPEG gates while the natural-photo texture arm
passes. No algorithm/production changes; original-cover oracle map only.

Use the SAME source covers, original saved H-B1 marked PNGs, packet,
DELTA=38, REPEAT=13 and transforms. The output includes:
- `diagnostics.csv`: repeated-position parity errors, majority-bit
  errors, header bit/byte errors, codeword byte errors, near-tie votes,
  region statistics and SHA256 fingerprints.
- `*-map.png`: original image with selected 4×4 LL2 positions
  highlighted (red: directional edge candidate, yellow: other selected).
- `*-positions.npy`: exact ordered coefficient index map for repeatability.
- `settings.json`: provenance and fixed parameters.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb11.py -q
python tools/robust_content_aware_hb11.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --marked-dir results/content-aware-hb1-01 \
  --out results/content-aware-hb11-01
```

The map labels are **heuristic**: edge = local std > 6 and directional
Sobel gradient concentration > .85; flat = local std < 2. They do not
establish true semantic edge categories or a perceptual threshold.

**Important:** The source image must match the one used for H-B1, and
the original marked PNG must not have been edited. This diagnostic
reconstructs maps deterministically from the original image; it does
not infer the map from JPEG. The decoder is given the correct map,
dimensions and packet length. The PNG arm is a sanity check; the JPEG
arms use the same transforms as H-B1. A failed packet is never accepted
without RS8 + CRC validation.

**Interpretation:** compare random/texture and screenshot/photo in
both raw parity and majority/byte errors. RS8 corrects up to four
codeword-byte errors, but an unprotected CLR1 header bit error can
prevent a standard decode. Distinguish these mechanisms before trying
a new edge-aware selector or blind H-B2.

**Caution:** A strong concentration of selected positions on UI edges
would support, but not prove, the edge-instability hypothesis. Review
map images at 100% and consider controlled selectors only after
observing the measured error distribution.
