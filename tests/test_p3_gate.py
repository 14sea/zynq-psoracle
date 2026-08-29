"""Link 1 (host/p3_gate.py): the known answer passes; every mutation is refused by kind.

Findings are asserted by their `kind` bucket, never by message text (fabricmap's rule).
"""

import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "host"))
sys.path.insert(0, str(REPO))
import p3_gate as g  # noqa: E402
import pcap_write_plan as wp  # noqa: E402
from validators.records import validate  # noqa: E402

FAR_WORD = 20          # stream index of the FAR value (after t1 FAR at 19)
DATA0 = 23             # first FDRI data word
FLUSH0 = DATA0 + 4 * 101


class KnownAnswer(unittest.TestCase):
    def setUp(self):
        self.m = g.load_manifest()
        self.c = g.known_answer_candidate(self.m)

    def test_known_answer_is_writable_and_hashes_are_pinned(self):
        v = g.gate(g.build_streams(self.c, self.m), self.m)
        validate(v)
        self.assertTrue(v["writable"]); self.assertEqual(v["findings"], [])
        self.assertEqual(v["candidate_sha256"], "4f14db962e990c40" + v["candidate_sha256"][16:])
        self.assertEqual(len(v["candidate_sha256"]), 64)
        self.assertEqual(v["manifest_sha256"], hashlib.sha256(g.MANIFEST.read_bytes()).hexdigest())

    def test_streams_are_the_pinned_shape(self):
        s = g.build_streams(self.c, self.m)
        self.assertEqual([x["far_set"] for x in s], [0x00400A20, 0x00400C1A, 0x00400C20])
        for x in s:
            self.assertEqual(len(x["words"]), 534)
            self.assertEqual(x["words"][FAR_WORD], x["far_set"])
            self.assertEqual(x["words"][22], wp.t2_write(505))
            self.assertNotIn(wp.t1(True, wp.REG_CRC, 1), x["words"])   # never a CRC write
        base, _ = g.gc.pinned_frames(self.m)
        self.assertEqual(s[0]["words"][FLUSH0:FLUSH0 + 101], base[0x00400A80])

    def test_candidate_sha_is_order_independent_and_covers_all_twelve(self):
        rev = dict(reversed(list(self.c.items())))
        a = g.gate(g.build_streams(self.c, self.m), self.m)["candidate_sha256"]
        b = g.gate(g.build_streams(rev, self.m), self.m)["candidate_sha256"]
        self.assertEqual(a, b)
        other = dict(self.c); other[0x00400C23] = list(other[0x00400C23]); other[0x00400C23][51] ^= 1
        self.assertNotEqual(a, g.gate(g.build_streams(other, self.m), self.m)["candidate_sha256"])


class Refusals(unittest.TestCase):
    def setUp(self):
        self.m = g.load_manifest()
        self.c = g.known_answer_candidate(self.m)

    def kinds(self, streams):
        v = g.gate(streams, self.m); self.assertFalse(v["writable"])
        return [f["kind"] for f in v["findings"]]

    def test_bit_outside_whitelist(self):
        b = dict(self.c); b[0x00400A20] = list(b[0x00400A20]); b[0x00400A20][3] ^= 1
        self.assertIn("target_frame", self.kinds(g.build_streams(b, self.m)))

    def test_stale_ecc(self):
        b = dict(self.c); b[0x00400A20] = list(b[0x00400A20]); b[0x00400A20][51] ^= 0x0001  # whitelisted bit, ECC not recomputed
        self.assertIn("ecc", self.kinds(g.build_streams(b, self.m)))

    def test_flush_frame_altered(self):
        s = g.build_streams(self.c, self.m); s[0]["words"][FLUSH0 + 7] ^= 1
        self.assertEqual(self.kinds(s), ["flush_frame"])

    def test_crc_register_write(self):
        s = g.build_streams(self.c, self.m); s[0]["words"][10] = wp.t1(True, wp.REG_CRC, 1); s[0]["words"][11] = 0
        k = self.kinds(s); self.assertIn("structure", k)

    def test_forbidden_command(self):
        s = g.build_streams(self.c, self.m); s[2]["words"][17] = 0x0000000B   # GRESTORE? any non-allowed command
        self.assertIn("structure", self.kinds(s))

    def test_far_outside_envelope_sets(self):
        s = g.build_streams(self.c, self.m); s[0]["words"][FAR_WORD] = 0x00400A24
        self.assertIn("structure", self.kinds(s))

    def test_duplicate_envelope_missing_another(self):
        s = g.build_streams(self.c, self.m); s[1]["words"][FAR_WORD] = 0x00400A20
        self.assertIn("addressing", self.kinds(s))

    def test_missing_envelope(self):
        self.assertIn("addressing", self.kinds(g.build_streams(self.c, self.m)[:2]))

    def test_wrong_fdri_length(self):
        s = g.build_streams(self.c, self.m); s[0]["words"][22] = wp.t2_write(101)
        self.assertIn("structure", self.kinds(s))

    def test_extra_word(self):
        s = g.build_streams(self.c, self.m); s[0]["words"].append(wp.NOOP)
        self.assertIn("structure", self.kinds(s))

    def test_candidate_sha_absent_when_a_stream_is_refused(self):
        s = g.build_streams(self.c, self.m); s[0]["words"].append(wp.NOOP)
        self.assertIsNone(g.gate(s, self.m)["candidate_sha256"])


if __name__ == "__main__":
    unittest.main()
