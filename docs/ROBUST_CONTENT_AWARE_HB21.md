# H-B2.1 — Can original-cover features predict resize errors?

**Question:** Can local features of the unmarked cover predict which
frozen inward-embedded Haar LL2 coefficients flip after Lanczos
down/upscaling? This is a *diagnostic feasibility* experiment, not a
new encoder, decoder, or deployable classifier.

Inputs: H-B1.9 `scale_positions.csv` and the two original images.
Recompute original-cover features using H-B1.6, never the marked or
received image: local standard deviation, mean, headroom, directional
edge, flat-region indicator and texture eligibility.

For each scale (95..60%) and strategy, fit a standardized ridge
least-squares risk score on one image and evaluate on the **other
image**. Repeat in the reverse direction. Do not randomly split
positions from the same image; such a split would leak spatial
structure and greatly overstate generalization.

Report held-out AUC (0.5 = chance, 1 = perfect; undefined if one class
only), overall error fraction, and the observed error fraction among
the lowest-scored 20% of the *already embedded* positions. The latter
is a **counterfactual diagnostic ranking only**: it does not
demonstrate that choosing those positions would yield an actual
decodable packet, sufficient capacity, low visual distortion or
valid payload order. In particular, the original repeated bits and
their map are frozen; no packet is reconstructed from a subset.

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb21.py -q
python tools/robust_content_aware_hb21.py \
  /home/jari/Pictures/Screenshot_20261120_110855.png \
  /home/jari/Pictures/DSCN0032.JPG \
  --hb19-positions results/content-aware-hb19-01/scale_positions.csv \
  --out results/content-aware-hb21-01
```

Outputs: `heldout_summary.csv`, `heldout_predictions.csv`,
`settings.json`. Original source files and all previous results are
read-only; the output directory must be new.

**Decision rule:** A model that performs well only when trained and
tested on the same image type is not enough to justify adaptive
placement. With just two covers, even cross-image validation is
preliminary. If transfer fails, investigate additional cover images,
more appropriate image-type warning heuristics, or a different
embedding domain. Any user-facing warning must be based on
validated artifact detection, not solely file extension or the label
"screenshot". Production `src/robust_image.py` and CLR1 unchanged.
