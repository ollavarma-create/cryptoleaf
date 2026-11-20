# H-B2.2 — Multi-image validation before new placement

## Objective

Extend H-B1.9/H-B2.1 beyond the original screenshot and natural photo.
Evaluate the same **fixed payload**, **DELTA=38**, **REPEAT=13**,
Haar LL2, no pilot, and H-B1.5 **inward** feedback on a broader
set of original covers. Compare texture, random and balanced on
actual newly embedded images and the same oracle-map decoder.
This is a replication/validation test, not a trained placement
algorithm.

Suggested dataset: 6–10 diverse PNG/JPEG images, including UI screenshots,
diagrams, text/line art, natural scenes, detailed photographs and
high-contrast edges. Preserve the original files; avoid duplicates
and near-identical crops. Do not treat screenshots as inherently
unsafe or photographs as inherently safe.

From repo root, with venv active:

```bash
git pull --ff-only
python -m pytest tests/test_robust_content_aware_hb22.py -q
python tools/robust_content_aware_hb22.py \
  /path/to/image1.png /path/to/image2.jpg /path/to/image3.png \
  --out results/content-aware-hb22-01
```

The command accepts any number of input images, including all
six-to-ten files in one invocation. Every file must have a unique
filename stem; the output directory must not exist. A strategy is
marked SKIP when there are too few eligible texture LL2 positions;
no reduction of packet size is silently made.

Output:
- `metrics.csv`: per-image/strategy/channel packet recovery, repeated
  parity errors, majority and header errors, RS8 codeword byte errors,
  quality metrics, selected edge/flat/saturation fractions.
- `feedback_trace.csv`: inward feedback iteration diagnostics.
- `*-inward.png`, `*-positions.npy`, `*-map.png`: reproducible
  marked carriers, exact original-cover oracle maps and placement
  visualizations.
- `settings.json`: configuration and source SHA256.

Channels: identity, Lanczos down/up 95/90/80/70/60%, native JPEG85,
resize083+JPEG85, resize068+JPEG70. Combined resize/JPEG channels
are restored to original size by the oracle decoder. Identity PNG
should pass for usable images; record any failure rather than hiding
it. Quality metrics are measured against the unmarked original,
not the amplified placement overlay.

### Interpretation and next step

First inspect original and `*-inward.png` side by side at 100% zoom.
The `*-map.png` files are **colored placement overlays**, not marked
carriers or evidence of actual visible embedding distortion.

Compare packet PASS/FAIL and visual artifacts per image and strategy.
Avoid optimizing for average success if any category consistently
fails. A positive result supports more diverse hold-out testing
(H-B2.3); it does not establish blind decoding, safe social-media
resilience or a deployable classifier. If a cover-warning approach
becomes necessary, calibrate it against measured distortion and
channel failures rather than file type alone.

No production code, wire format or previous experiment is modified.
