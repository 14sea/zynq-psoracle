"""validators: the sparse-v1 (2.0.0) audit chunks and the STOP_AUDIT outcome (L6 pull design).

The assembler must bind one transaction to one span/total/chunks, refuse dense/sparse
mixing within a seq, refuse windows and counts that disagree, accept a byte-identical
echo and refuse a differing duplicate; and the dense path must be unchanged (session 4's
recorded chunks still assemble). STOP_AUDIT: staged (oracle present), no ARM, never
audited, always a HOLD under either policy."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "tests"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l6_schedule as ls  # noqa: E402
import p3_gate as g  # noqa: E402
import test_d1_records as d1  # noqa: E402
from validators import audit as au  # noqa: E402
from validators import records  # noqa: E402

C13 = R / "evidence/l6_17A6_2026-09-01-08-C1"
S4 = R / "evidence/l5_17A6_2026-09-01-04"
DENSE = [c for c in json.loads((C13 / "audits.json").read_text())["chunks"] if c["seq"] == 1]
WORDS = au.assemble(DENSE)[1]["words"]
FULL, STREAMS = "streams+readback", "streams"


def sparse(seq=1, span=FULL, words=None):
    words = WORDS if words is None else words
    return [au.build_sparse_chunk(seq, c, span, words) for c in range(au.sparse_chunk_count(len(words)))]


class SparseAssembly(unittest.TestCase):
    def test_lossless_on_real_words_and_recomputes_the_record(self):
        got = au.assemble(sparse())[1]
        self.assertEqual(got["words"], WORDS); self.assertEqual(got["encoding"], au.SPARSE_ENCODING)
        oracle = json.loads((C13 / "run_log.json").read_text())["loop_records"][0]["evidence"]["app_oracle_record"]
        h = au.recompute(got["words"], FULL, g.load_manifest())
        self.assertEqual(h["staged_sha256"], oracle["staged_sha256"]); self.assertEqual(h["readback_sha256"], oracle["readback_sha256"])

    def test_the_dense_path_is_unchanged(self):
        s4 = json.loads((S4 / "audits.json").read_text())["chunks"]
        self.assertEqual(sorted(au.assemble(s4)), list(range(1, 11)))

    def test_one_transaction_one_binding(self):
        chunks = sparse()
        alien = au.build_sparse_chunk(1, 2, STREAMS, WORDS[:au.STREAM_SPAN])
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(chunks[:2] + [alien] + chunks[3:])
        self.assertIn("one transaction, one binding", str(cm.exception))

    def test_dense_and_sparse_may_not_mix_within_a_seq(self):
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(DENSE + sparse())
        self.assertIn("dense and sparse chunks mixed", str(cm.exception))
        both = au.assemble(DENSE + sparse(seq=2))            # different seqs: each by its own rules
        self.assertEqual(sorted(both), [1, 2]); self.assertEqual(both[1]["words"], both[2]["words"])

    def test_windows_counts_and_ranges_must_agree(self):
        c = sparse()
        bad = copy.deepcopy(c); bad[3]["window"] = [0, 384]
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(bad)
        self.assertIn("window", str(cm.exception))
        bad = copy.deepcopy(c); bad[0]["chunks"] = 7
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(bad)
        self.assertIn("chunks 7", str(cm.exception))
        bad = copy.deepcopy(c); bad[0]["chunk"] = 8
        with self.assertRaises(records.RecordError):
            au.assemble(bad)
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(c[:7])
        self.assertIn("missing [7]", str(cm.exception))

    def test_an_identical_echo_is_fine_and_a_differing_duplicate_is_not(self):
        c = sparse()
        au.assemble(c + [copy.deepcopy(c[4])])
        other = copy.deepcopy(c[4]); w = list(WORDS); w[4 * 384 + 1] ^= 1
        other["entries"] = au.encode_entries(w, *au.sparse_window(4, len(w)))
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(c + [other])
        self.assertIn("served twice with different content", str(cm.exception))

    def test_entry_strictness(self):
        import base64, struct
        lo, hi = au.sparse_window(1, 2814)
        def e(pairs): return base64.urlsafe_b64encode(b"".join(struct.pack(">HI", p, w) for p, w in pairs)).decode()
        for bad, why in ((e([(lo + 5, 1), (lo + 5, 2)]), "duplicate"), (e([(lo + 7, 1), (lo + 3, 1)]), "disorder"),
                         (e([(hi, 1)]), "outside the chunk window"), (e([(lo + 2, 0)]), "zero word"),
                         (e([(lo + 1, 1)])[:-3] + "!!!", "outside base64url"),
                         (base64.urlsafe_b64encode(b"\x00\x01\x00\x00\x00").decode(), "whole")):
            with self.assertRaises(records.RecordError, msg=why) as cm:
                au.decode_entries(bad, lo, hi)
            self.assertIn(why.split()[0], str(cm.exception))

    def test_verify_marks_a_sparse_audit_audited_like_a_dense_one(self):
        log = json.loads((C13 / "run_log.json").read_text())
        log = {"loop_records": [log["loop_records"][0]]}
        marks, detail = au.verify(log, sparse(), g.load_manifest())
        self.assertEqual(marks[1], "audited")
        self.assertTrue(all(detail[1]["compared"].values()))


class StopAudit(unittest.TestCase):
    def rec(self, seq=3):
        r = d1.scored(seq, d1.G_CAND, d1.CAND, d1.SEED)
        r["outcome"] = "STOP_AUDIT"
        for k in ("arm", "score"):
            del r["evidence"][k]
        r["evidence"]["audit_stop"] = {"why": "chunk 3: 3 attempts failed", "attempts": 3}
        r["verified"] = "replayed-only"
        return r

    def test_a_well_formed_stop_audit_validates(self):
        records.validate(self.rec())

    def test_it_needs_the_oracle_and_the_stop_detail_and_forbids_arm_and_score(self):
        r = self.rec(); del r["evidence"]["audit_stop"]
        with self.assertRaises(records.RecordError):
            records.validate(r)
        r = self.rec(); del r["evidence"]["app_oracle_record"]
        with self.assertRaises(records.RecordError):
            records.validate(r)
        r = self.rec(); r["evidence"]["arm"] = d1.scored(3, d1.G_CAND, d1.CAND, d1.SEED)["evidence"]["arm"]
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("must not contain", str(cm.exception))

    def test_it_can_never_be_marked_audited(self):
        r = self.rec(); r["verified"] = "audited"
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("cannot be marked audited", str(cm.exception))

    def test_staged_not_the_commit_is_still_a_falsifier(self):
        r = self.rec(); r["evidence"]["app_oracle_record"]["staged_sha256"] = "ee" * 32
        with self.assertRaises(records.Falsified):
            records.validate(r)

    def test_it_is_a_hold_under_both_policies(self):
        log = {"loop_records": [self.rec()]}
        for policy, sched in (("all-self-reporting", None), ("sampled", ls.sampled_audit_seqs(8))):
            with self.assertRaises(records.RecordError) as cm:
                records.check_audit_policy(log, {3: "replayed-only"}, policy, sched)
            self.assertNotIsInstance(cm.exception, records.Falsified)
            self.assertIn("[3]", str(cm.exception))
        self.assertEqual(records.self_report_class(self.rec()), "auto")


if __name__ == "__main__":
    unittest.main()
