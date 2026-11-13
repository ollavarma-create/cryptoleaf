
"""JPEG v0.3 burst-error-resistant bit interleaving."""


def interleave3(bits: list[int]) -> list[int]:
    """Store three copies in separate consecutive regions."""
    return bits * 3


def deinterleave3(bits: list[int]) -> list[int]:
    """Recover bits by majority vote across three regions."""
    if len(bits) % 3:
        raise ValueError("Interleaved bit count must be divisible by 3")

    n = len(bits) // 3

    return [
        int(bits[i] + bits[i + n] + bits[i + 2 * n] >= 2)
        for i in range(n)
    ]
