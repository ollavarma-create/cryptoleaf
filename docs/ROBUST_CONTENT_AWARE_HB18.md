# H-B1.8 — isolate resizing and JPEG compression

H-B1.7 found geometric associations but did not isolate JPEG quantization
from Lanczos resizing. H-B1.8 is a controlled **2×2 factorial channel
experiment**, reusing exactly the H-B1.5 **inward** PNGs and H-B1.2
ordered oracle maps. No embedding, codec or packet modifications.

For each original cover, placement strategy and parameter pair:
- identity (unmodified PNG)
- resize_only (Lanczos to 0.83 or 0.68, then Lanczos back for oracle decode)
- jpeg_only (JPEG85 or JPEG70 at full original resolution)
- resize_jpeg (Lanczos to 0.83 or 0.68, JPEG85 or JPEG70, then Lanczos
  back for oracle decode)

JPEG uses Pillow `subsampling=2`. The combined arm reproduces the
existing H-B1 JPEG channel. The original-cover oracle dimensions and
ordered map are explicitly provided to the decoder. This is not a
blind robustness or social-media claim.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb18.py -q
python tools/robust_content_aware_hb18.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --maps-dir results/content-aware-hb12-01 \
  --hb15-dir results/content-aware-hb15-01 \
  --out results/content-aware-hb18-01
```

Output:
- `channel_summary.csv`: PASS/FAIL, repetition, majority, header, RS8
  errors for all four arms in both parameter pairs.
- `factorial_interactions.csv`: error fractions and paired per-position
  overlap, including positions correct in both single channels but wrong
  after the combined channel.
- `position_errors.csv`: per-position parity and LL2 drift for further
  diagnostics.
- `settings.json`: provenance, transforms and frozen parameters.

**Interpretation:** If jpeg_only fails without resizing, JPEG alone is
sufficient to break the present scheme. If resize_only fails, resizing
alone is sufficient. If each passes but resize_jpeg fails, their
combination creates a failure not explained by either individually.
Even when both single arms fail, the factorial contrast and paired
error overlaps help characterize interactions. Decode PASS/FAIL is
nonlinear due to repetition voting and RS8 correction; do not infer
causality solely from total repetition errors.

Keep production codec `src/robust_image.py`, packet CLR1, maps and
earlier experiments unchanged. No new output folder is overwritten.
