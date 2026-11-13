"""Image quality metrics for Cryptoleaf."""

import math
import numpy as np
from PIL import Image


def calculate_psnr(original: Image.Image, modified: Image.Image) -> float:
    """Calculate RGB PSNR without full-frame float64 temporaries.

    Sum exact integer squared differences in bounded image stripes.
    """
    if original.size != modified.size:
        raise ValueError("Image dimensions must match")

    width, height = original.size
    if width == 0 or height == 0:
        raise ValueError("Images must have nonzero dimensions")

    # Convert only when needed; never build full-frame float64 arrays.
    a_img = original if original.mode == "RGB" else original.convert("RGB")
    b_img = modified if modified.mode == "RGB" else modified.convert("RGB")
    try:
        # Keep each uint8/int32 stripe small even for very wide images.
        stripe_height = max(1, min(128, 1_000_000 // max(width, 1)))
        sum_squared = 0
        for y in range(0, height, stripe_height):
            box = (0, y, width, min(y + stripe_height, height))
            a = np.asarray(a_img.crop(box), dtype=np.int32)
            b = np.asarray(b_img.crop(box), dtype=np.int32)
            diff = a - b
            np.square(diff, out=diff)
            sum_squared += int(np.sum(diff, dtype=np.int64))
        mse = sum_squared / (width * height * 3)
        return math.inf if mse == 0 else 10 * math.log10((255 ** 2) / mse)
    finally:
        if a_img is not original:
            a_img.close()
        if b_img is not modified:
            b_img.close()
