"""host/l6_audit_pull.py — the host-paced sparse audit pull, modelled (design review 2026-09-01).

Real words: C1 #3's seq 1 audit (evidence/l6_17A6_2026-09-01-08-C1, read-only) reassembled
from the recorded dense chunks. The sparse encoding must be lossless on them and recompute
the record's three hashes; the deletion fixtures reproduce C1 #1's boundary loss (39 bytes
across chunk 4/5) and C1 #3's in-line losses (309 and 229 bytes inside chunk 3) and must
be RECOVERED by one retry; retries exhausted must be a HOLD; a CRC-valid chunk with wrong
content must be Falsified; every failed attempt must be in the ledger and the budget."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import p3_gate as g  # noqa: E402
from validators import audit as au  # noqa: E402
from validators.records import Falsified, RecordError  # noqa: E402

C13 = R / "evidence/l6_17A6_2026-09-01-08-C1"
LOG = json.loads((C13 / "run_log.json").read_text())
TOKEN = LOG["app_identity"]["token"]
CHUNKS = [c for c in json.loads((C13 / "audits.json").read_text())["chunks"] if c["seq"] == 1]
WORDS = au.assemble(CHUNKS)[1]["words"]
ORACLE = LOG["loop_records"][0]["evidence"]["app_oracle_record"]
MANIFEST = g.load_manifest()
SPAN = "streams+readback"


def pull(board_kw=None, host_kw=None):
    board = ap.ModelBoard(TOKEN, 1, SPAN, WORDS, **(board_kw or {}))
    host = ap.ModelHost(TOKEN, **(host_kw or {}))
    return host, host.pull(board)


class Encoding(unittest.TestCase):
    def test_round_trip_on_real_words_is_lossless_and_recomputes_the_record(self):
        chunks = [ap.build_chunk_payload(1, c, SPAN, WORDS) for c in range(ap.chunk_count(len(WORDS)))]
        got = ap.assemble_sparse(chunks)[1]
        self.assertEqual(got["words"], WORDS)
        h = ap.recompute_from_sparse(chunks, MANIFEST, ORACLE)[1]
        self.assertEqual(h["staged_sha256"], ORACLE["staged_sha256"])
        self.assertEqual(h["readback_sha256"], ORACLE["readback_sha256"])

    def test_the_sparse_wire_is_a_fraction_of_the_dense_one(self):
        c = ap.compare_encodings(WORDS, TOKEN, 1, SPAN)
        self.assertLess(c["ratio"], 0.25)
        self.assertEqual(c["nonzero_words"], sum(1 for w in WORDS if w))
        self.assertGreater(c["dense"]["seconds"], 1.5); self.assertLess(c["sparse"]["seconds"], 0.5)

    def test_strictness_refuses_every_ambiguous_shape(self):
        lo, hi = 0, ap.WINDOW
        import base64, struct
        def entries(pairs):
            return base64.urlsafe_b64encode(b"".join(struct.pack(">HI", p, w) for p, w in pairs)).decode()
        for bad, why in ((entries([(5, 1), (5, 2)]), "duplicate"), (entries([(7, 1), (3, 1)]), "disorder"),
                         (entries([(ap.WINDOW, 1)]), "outside the chunk window"), (entries([(2, 0)]), "zero word"),
                         (entries([(1, 1)])[:-3] + "!!!", "outside base64url"), (base64.urlsafe_b64encode(b"\x00\x01\x00\x00\x00").decode(), "whole")):
            with self.assertRaises(RecordError, msg=why) as cm:
                ap.decode_entries(bad, lo, hi)
            self.assertIn(why.split()[0], str(cm.exception))

    def test_a_missing_chunk_and_a_chunk_served_twice_differently_are_refused(self):
        chunks = [ap.build_chunk_payload(1, c, SPAN, WORDS) for c in range(8)]
        with self.assertRaises(RecordError) as cm:
            ap.assemble_sparse(chunks[:7])
        self.assertIn("missing [7]", str(cm.exception))
        other = dict(chunks[3]); other["entries"] = ap.encode_entries([0] * ap.WINDOW * 3 + [9] + [0] * 5000, 3 * ap.WINDOW, 4 * ap.WINDOW)
        with self.assertRaises(RecordError) as cm:
            ap.assemble_sparse(chunks + [other])
        self.assertIn("served twice with different content", str(cm.exception))
        ap.assemble_sparse(chunks + [dict(chunks[3])])           # an identical echo is fine


class DeletionFixtures(unittest.TestCase):
    def _line_len(self, chunk):
        return len(ap.ModelBoard(TOKEN, 1, SPAN, WORDS).serve(chunk))

    def test_c1_3s_in_line_losses_are_recovered_by_one_retry(self):
        for chunk, lost in ((3, 309), (3, 229)):
            n_len = self._line_len(chunk)
            host, chunks = pull(host_kw={"deletions": [ap.Deletion(chunk, 0, min(1500, n_len // 3), min(lost, n_len // 2))]})
            self.assertEqual(len(chunks), 8)
            ap.recompute_from_sparse(chunks, MANIFEST, ORACLE)
            att = [a for a in host.ledger.attempts if a["chunk"] == chunk]
            self.assertEqual([a["outcome"] for a in att][:1], ["crc"])
            self.assertEqual(att[-1]["outcome"], "ok"); self.assertEqual(len(att), 2)
            self.assertEqual(host.ledger.crc_dropped, 1)
            self.assertEqual(len(host.ledger.lines_kept), 1, "the failed attempt is kept verbatim")

    def test_c1_1s_boundary_loss_is_recovered_by_one_retry(self):
        n4 = self._line_len(4)
        host, chunks = pull(host_kw={"deletions": [ap.Deletion(4, 0, n4 - 20, 39)]})   # 20 bytes of chunk 4's tail + \n + chunk 5's head
        self.assertEqual(len(chunks), 8)
        ap.recompute_from_sparse(chunks, MANIFEST, ORACLE)
        att = [a for a in host.ledger.attempts if a["chunk"] == 4]
        self.assertEqual(len(att), 2); self.assertNotEqual(att[0]["outcome"], "ok"); self.assertEqual(att[1]["outcome"], "ok")

    def test_retries_exhausted_is_a_hold_not_a_pass(self):
        dels = [ap.Deletion(3, a, 100, 50) for a in range(ap.MAX_RETRIES + 1)]
        with self.assertRaises(RecordError) as cm:
            pull(host_kw={"deletions": dels})
        self.assertNotIsInstance(cm.exception, Falsified)
        self.assertIn("attempts failed", str(cm.exception)); self.assertIn("HOLD", str(cm.exception))

    def test_every_failed_attempt_counts_against_the_budget_and_can_end_the_epoch(self):
        dels = [ap.Deletion(c, 0, 100, 50) for c in range(3)]
        host, chunks = pull(host_kw={"deletions": dels})
        self.assertEqual(host.ledger.crc_dropped, 3); self.assertEqual(len(chunks), 8)
        with self.assertRaises(RecordError) as cm:
            pull(host_kw={"deletions": dels, "crc_budget": 2})
        self.assertIn("PROTOCOL_CRC_BUDGET: 3 > 2", str(cm.exception))

    def test_a_timeout_is_an_attempt_not_a_crc_drop(self):
        host, chunks = pull(host_kw={"timeouts": {(2, 0)}})
        self.assertEqual(len(chunks), 8)
        self.assertEqual(host.ledger.timeouts, 1); self.assertEqual(host.ledger.crc_dropped, 0)

    def test_valid_crc_with_wrong_content_is_falsified(self):
        host, chunks = pull(board_kw={"corrupt": {5: (5 * ap.WINDOW + 7, 0xDEADBEEF)}})
        self.assertEqual(len(chunks), 8, "the chunk verifies on the wire …")
        with self.assertRaises(Falsified):
            ap.recompute_from_sparse(chunks, MANIFEST, ORACLE)   # … and is a KILL on content

    def test_the_cost_of_retransmission_is_in_the_ledger(self):
        clean, _ = pull()
        lossy, _ = pull(host_kw={"deletions": [ap.Deletion(3, 0, 100, 50)]})
        self.assertGreater(lossy.ledger.bytes_sent, clean.ledger.bytes_sent)
        self.assertAlmostEqual(lossy.ledger.bytes_sent - clean.ledger.bytes_sent, self._line_len(3) + 1 - 50, delta=2)


if __name__ == "__main__":
    unittest.main()
