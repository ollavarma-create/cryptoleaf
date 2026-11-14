
"""Simulate JPEG burst errors with and without interleaving."""

from src.error_correction import hamming_encode, hamming_decode
from src.image_encoder import _bits_from_bytes
from src.jpeg_v03 import build_header


ERROR_POSITIONS = [579, 581, 582, 583]


def replicate_adjacent(bits):
    return [bit for b in bits for bit in (b, b, b)]


def replicate_interleaved(bits):
    return bits * 3


def majority_vote(bits):
    return [
        int(sum(bits[i:i + 3]) >= 2)
        for i in range(0, len(bits), 3)
    ]


def majority_vote_interleaved(bits):
    n = len(bits) // 3
    return [
        int(bits[i] + bits[i+n] + bits[i+2*n] >= 2)
        for i in range(n)
    ]


def inject_errors(bits):
    damaged = bits.copy()
    for pos in ERROR_POSITIONS:
        damaged[pos] ^= 1
    return damaged


def bit_errors(a, b):
    return sum(x != y for x, y in zip(a, b))


header = build_header(141)
original = _bits_from_bytes(header)
encoded = hamming_encode(original)

# Current arrangement
adjacent = replicate_adjacent(encoded)
damaged_adjacent = inject_errors(adjacent)
recovered_adjacent = hamming_decode(
    majority_vote(damaged_adjacent)
)

# Proposed arrangement
interleaved = replicate_interleaved(encoded)
damaged_interleaved = inject_errors(interleaved)
recovered_interleaved = hamming_decode(
    majority_vote_interleaved(damaged_interleaved)
)

print("Current arrangement:")
print("  Header bit errors:", bit_errors(original, recovered_adjacent))

print("Interleaved arrangement:")
print("  Header bit errors:", bit_errors(original, recovered_interleaved))

assert recovered_interleaved == original
print("\nInterleaving simulation PASSED")
