"""Robust image transport smoke/regression tests (no GUI)."""
import io
import unittest

import numpy as np
from PIL import Image

from src.robust_image import encode, decode_at_size, decode


class RobustImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(1234)
        cls.cover = Image.fromarray(rng.integers(0, 256, (512, 768, 3), dtype=np.uint8), 'RGB')
        cls.message = b'Cryptoleaf robust test message'
        cls.marked = encode(cls.cover, cls.message)

    def test_oracle_roundtrip(self):
        self.assertEqual(decode_at_size(self.marked, self.marked.size), self.message)

    def test_blind_roundtrip(self):
        self.assertEqual(decode(self.marked).payload, self.message)

    def test_jpeg85_oracle(self):
        stream = io.BytesIO()
        self.marked.save(stream, 'JPEG', quality=85, subsampling=0)
        stream.seek(0)
        received = Image.open(stream).convert('RGB')
        self.assertEqual(decode_at_size(received, self.marked.size), self.message)

    def test_small_capacity_rejected(self):
        with self.assertRaises(ValueError):
            encode(Image.new('RGB', (64, 64), 'gray'), self.message)


if __name__ == '__main__':
    unittest.main()
