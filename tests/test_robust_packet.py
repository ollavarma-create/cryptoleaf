"""First-stage robust transport tests; no image dependencies."""

import unittest

from src.robust_packet import MAX_PAYLOAD, pack, unpack


class RobustPacketTests(unittest.TestCase):
    def test_roundtrip(self):
        for payload in (b"", b"hello", bytes(range(50)), bytes(range(MAX_PAYLOAD))):
            with self.subTest(length=len(payload)):
                self.assertEqual(unpack(pack(payload)), payload)

    def test_four_corrupt_symbols_are_corrected(self):
        expected = bytes(range(50))
        damaged = bytearray(pack(expected))
        for offset in (6, 11, 21, 40):
            damaged[offset] ^= 0x5A
        self.assertEqual(unpack(bytes(damaged)), expected)

    def test_rejects_bad_header(self):
        packet = pack(b"hello")
        with self.assertRaises(ValueError):
            unpack(b"XXXX" + packet[4:])
        with self.assertRaises(ValueError):
            unpack(packet[:-1])
        with self.assertRaises(ValueError):
            unpack(packet + b"x")

    def test_rejects_excessive_payload(self):
        with self.assertRaises(ValueError):
            pack(b"x" * (MAX_PAYLOAD + 1))

    def test_rejects_invalid_codeword(self):
        packet = bytearray(pack(bytes(range(50))))
        for offset in (6, 9, 12, 15, 18, 21, 24, 27):
            packet[offset] ^= 0xFF
        with self.assertRaises(ValueError):
            unpack(bytes(packet))


if __name__ == "__main__":
    unittest.main()
