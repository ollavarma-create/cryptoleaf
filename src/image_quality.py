
"""Image quality metrics for Cryptoleaf."""

import math

import numpy as np
from PIL import Image


def calculate_psnr(
    original: Image.Image,
    modified: Image.Image,
) -> float:
    """Calculate RGB peak signal-to-noise ratio in dB."""

    if original.size != modified.size:
        raise ValueError("Image dimensions must match")

    a = np.asarray(original.convert("RGB"), dtype=np.float64)
    b = np.asarray(modified.convert("RGB"), dtype=np.float64)

    mse = np.mean((a - b) ** 2)

    if mse == 0:
        return math.inf

    return 10 * math.log10((255 ** 2) / mse)
