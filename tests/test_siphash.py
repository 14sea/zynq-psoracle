"""`arm_mac` 1.0.0 — SipHash-2-4 against the published reference vectors.

Vectors from `veorq/SipHash` `vectors.h` (fetched 2026-08-29): key = bytes 0x00..0x0f,
message i = bytes 0x00..(i-1). First three entries of `vectors_sip64` and `vectors_sip128`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validators.siphash import siphash, siphash128  # noqa: E402

KEY = bytes(range(16))
SIP64 = [bytes([0x31, 0x0e, 0x0e, 0xdd, 0x47, 0xdb, 0x6f, 0x72]),
         bytes([0xfd, 0x67, 0xdc, 0x93, 0xc5, 0x39, 0xf8, 0x74]),
         bytes([0x5a, 0x4f, 0xa9, 0xd9, 0x09, 0x80, 0x6c, 0x0d])]
SIP128 = [bytes([0xa3, 0x81, 0x7f, 0x04, 0xba, 0x25, 0xa8, 0xe6, 0x6d, 0xf6, 0x72, 0x14, 0xc7, 0x55, 0x02, 0x93]),
          bytes([0xda, 0x87, 0xc1, 0xd8, 0x6b, 0x99, 0xaf, 0x44, 0x34, 0x76, 0x59, 0x11, 0x9b, 0x22, 0xfc, 0x45]),
          bytes([0x81, 0x77, 0x22, 0x8d, 0xa4, 0xa4, 0x5d, 0xc7, 0xfc, 0xa3, 0x8b, 0xde, 0xf6, 0x0a, 0xff, 0xe4])]


class SipHashVectors(unittest.TestCase):
    def test_sip64_first_three(self):
        for i, want in enumerate(SIP64):
            with self.subTest(i=i):
                self.assertEqual(siphash(KEY, bytes(range(i)), 8), want)

    def test_sip128_first_three(self):
        for i, want in enumerate(SIP128):
            with self.subTest(i=i):
                self.assertEqual(siphash128(KEY, bytes(range(i))), want)

    def test_key_and_outlen_are_checked(self):
        with self.assertRaises(ValueError):
            siphash(b"short", b"")
        with self.assertRaises(ValueError):
            siphash(KEY, b"", outlen=12)

    def test_a_different_key_gives_a_different_tag(self):
        self.assertNotEqual(siphash128(KEY, b"x"), siphash128(bytes(16), b"x"))


if __name__ == "__main__":
    unittest.main()
