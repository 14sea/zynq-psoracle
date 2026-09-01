"""The audit gate (validators/audit.py): raw words reassembled and recomputed on the host.

Design review 2026-09-01 (HOLD): the runner wrote served chunks to audits.json and then
trusted the record's own "verified": "audited". Nothing recomputed a hash. These tests pin
the gate that now exists, against REAL board data where possible: session 3's served
chunks (evidence/l5_17A6_2026-09-01-03/, read-only) must reassemble and recompute to the
record's three hashes; every structural defect in the chunk stream and every altered word
must be refused, in the class the preregistration assigns it.
"""
from __future__ import annotations

import base64
import copy
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
# This module sorts FIRST in discovery. `p3_gate` puts imported/fabricmap's copy of
# `bitstream_frames` at the front of the path, and only zynq-psmap's copy (scripts/) has its
# tile data beneath it — so pin the psmap copy before anything can pull the other one, as
# tests/test_firmware_twin.py explains.
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy: pinned first, deliberately)
from validators import audit as au  # noqa: E402
from validators import records  # noqa: E402
import p3_gate as g  # noqa: E402

S3 = R / "evidence/l5_17A6_2026-09-01-03"
CHUNKS = json.loads((S3 / "audits.json").read_text())["chunks"]
LOG = json.loads((S3 / "run_log.json").read_text())
MANIFEST = g.load_manifest()


def _reencode(words: list[int]) -> str:
    return base64.urlsafe_b64encode(b"".join(w.to_bytes(4, "big") for w in words)).decode()


def _chunks_with_word_flipped(index: int, bit: int = 0) -> list[dict]:
    chunks = copy.deepcopy(CHUNKS)
    c = next(c for c in chunks if c["word_offset"] <= index < c["word_offset"] + c["word_count"])
    words = au._decode_words(c["words"], "fixture")
    words[index - c["word_offset"]] ^= 1 << bit
    c["words"] = _reencode(words)
    return chunks


class Session3RealData(unittest.TestCase):
    """The board's own words, through the gate."""

    def test_the_served_chunks_reassemble_closed(self):
        out = au.assemble(CHUNKS)
        self.assertEqual(list(out), [1])
        self.assertEqual(out[1]["span"], "streams+readback")
        self.assertEqual(len(out[1]["words"]), 2814)
        self.assertEqual(out[1]["chunks"], 8)

    def test_the_three_hashes_recompute_to_the_record(self):
        words = au.assemble(CHUNKS)[1]["words"]
        got = au.recompute(words, "streams+readback", MANIFEST)
        oracle = LOG["loop_records"][0]["evidence"]["app_oracle_record"]
        for k in ("staged_stream_sha256", "staged_sha256", "readback_sha256"):
            self.assertEqual(got[k], oracle[k], k)
        self.assertEqual(got["staged_sha256"], LOG["loop_records"][0]["evidence"]["sign_reply"]["commit"])

    def test_verify_derives_audited_for_session_3(self):
        marks, detail = au.verify(LOG, CHUNKS, MANIFEST)
        self.assertEqual(marks, {1: "audited"})
        self.assertTrue(all(detail[1]["compared"].values()))

    def test_arrival_order_does_not_matter_chunk_numbers_do(self):
        shuffled = list(reversed(CHUNKS))
        self.assertEqual(au.assemble(shuffled)[1]["words"], au.assemble(CHUNKS)[1]["words"])


class AlteredWords(unittest.TestCase):
    """Any single bit of any served word changes a hash the record claimed: Falsified."""

    def _falsified(self, chunks):
        with self.assertRaises(records.Falsified) as cm:
            au.verify(LOG, chunks, MANIFEST)
        return str(cm.exception)

    def test_a_flipped_stream_word_is_a_falsifier(self):
        msg = self._falsified(_chunks_with_word_flipped(700, 5))       # inside stream 1's FDRI data
        self.assertIn("staged_stream_sha256", msg)

    def test_a_flipped_readback_word_is_a_falsifier(self):
        msg = self._falsified(_chunks_with_word_flipped(1602 + 250, 3))  # inside readback frame 2
        self.assertIn("readback_sha256", msg)

    def test_a_flipped_last_word_is_a_falsifier(self):
        self._falsified(_chunks_with_word_flipped(2813, 31))


class StructuralDefects(unittest.TestCase):
    """Missing, duplicated, gapped, overlapping, over-long, mis-spanned, mixed: RecordError,
    never a silent partial audit — and never Falsified, because nothing was recomputed."""

    def _rejected(self, chunks, fragment):
        with self.assertRaises(records.RecordError) as cm:
            au.assemble(chunks)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn(fragment, str(cm.exception))

    def test_a_missing_chunk(self):
        self._rejected([c for c in CHUNKS if c["chunk"] != 3], "missing [3]")

    def test_a_duplicated_chunk(self):
        self._rejected(CHUNKS + [copy.deepcopy(CHUNKS[2])], "duplicate chunk numbers [2]")

    def test_swapped_chunk_numbers_are_an_offset_defect(self):
        chunks = copy.deepcopy(CHUNKS)
        a = next(c for c in chunks if c["chunk"] == 1); b = next(c for c in chunks if c["chunk"] == 2)
        a["chunk"], b["chunk"] = 2, 1
        self._rejected(chunks, "word_offset")

    def test_a_gap_in_offsets(self):
        chunks = copy.deepcopy(CHUNKS)
        next(c for c in chunks if c["chunk"] == 4)["word_offset"] += 4
        self._rejected(chunks, "gap")

    def test_an_overlap_in_offsets(self):
        chunks = copy.deepcopy(CHUNKS)
        next(c for c in chunks if c["chunk"] == 4)["word_offset"] -= 4
        self._rejected(chunks, "overlap")

    def test_a_word_count_that_lies(self):
        chunks = copy.deepcopy(CHUNKS)
        next(c for c in chunks if c["chunk"] == 0)["word_count"] -= 1
        self._rejected(chunks, "word_count")

    def test_an_over_long_last_chunk(self):
        chunks = copy.deepcopy(CHUNKS)
        last = next(c for c in chunks if c["chunk"] == 7)
        words = au._decode_words(last["words"], "fixture") + [0]
        last["words"], last["word_count"] = _reencode(words), len(words)
        self._rejected(chunks, "exceed")

    def test_a_wrong_total_for_the_span(self):
        chunks = copy.deepcopy(CHUNKS)
        for c in chunks:
            c["total_words"] = 2810
        self._rejected(chunks, "not the pinned")

    def test_a_short_audit_cannot_claim_the_full_span(self):
        """streams-only words labelled streams+readback: the total does not match the span."""
        chunks = [copy.deepcopy(c) for c in CHUNKS if c["word_offset"] + c["word_count"] <= 1602]
        for c in chunks:
            c["chunks"] = len(chunks)
        self._rejected(chunks, "total_words")

    def test_chunks_disagreeing_on_span(self):
        chunks = copy.deepcopy(CHUNKS)
        chunks[3]["span"] = "streams"
        self._rejected(chunks, "disagree")

    def test_an_unknown_span(self):
        chunks = copy.deepcopy(CHUNKS)
        for c in chunks:
            c["span"] = "everything"
        self._rejected(chunks, "span")

    def test_words_outside_the_alphabet(self):
        chunks = copy.deepcopy(CHUNKS)
        chunks[0]["words"] = chunks[0]["words"][:-4] + "+/=="
        self._rejected(chunks, "base64url")

    def test_a_chunk_from_another_seq_is_not_mixed_in(self):
        chunks = copy.deepcopy(CHUNKS)
        chunks[5]["seq"] = 2
        with self.assertRaises(records.RecordError):
            au.assemble(chunks)          # seq 1 now misses chunk 5; seq 2 has 1 of 8

    def test_words_for_a_seq_with_no_record_are_refused(self):
        chunks = copy.deepcopy(CHUNKS)
        for c in chunks:
            c["seq"] = 9
        with self.assertRaises(records.RecordError) as cm:
            au.verify(LOG, chunks, MANIFEST)
        self.assertIn("no loop record", str(cm.exception))


class ContentThatCannotSupportTheClaim(unittest.TestCase):
    """Design review round 2: once assemble() has accepted the chunk stream, words that do
    not parse as a staging, that repeat an envelope, or that do not stage all twelve
    target frames are CONTENT the record's hashes cannot be recomputed from — prereg §3,
    Falsified — not an instrument HOLD. The boundary is assemble()."""

    WORDS = None

    @classmethod
    def setUpClass(cls):
        cls.WORDS = au.assemble(CHUNKS)[1]["words"]

    def _rechunk(self, words: list[int]) -> list[dict]:
        n = (len(words) + 383) // 384
        return [{"schema": "app_audit_chunk", "schema_version": "1.0.0", "seq": 1,
                 "span": "streams+readback", "chunk": c, "chunks": n, "word_offset": c * 384,
                 "word_count": len(words[c * 384:(c + 1) * 384]), "total_words": len(words),
                 "words": _reencode(words[c * 384:(c + 1) * 384])} for c in range(n)]

    def _falsified(self, words, fragment):
        chunks = self._rechunk(words)
        au.assemble(chunks)                                    # the structural layer passes
        with self.assertRaises(records.Falsified) as cm:
            au.verify(LOG, chunks, MANIFEST)
        self.assertIn(fragment, str(cm.exception))
        with self.assertRaises(records.Falsified):             # …and so through the whole log
            log = copy.deepcopy(LOG)
            log["session_summary"]["audit"]["total"] = 1
            arm = log["loop_records"][0]["evidence"]["arm"]
            arm["settle"] = {"polls": 1, "polls_max": 1000000, "settled": True,
                             "status_first": arm["status_after"], "status_last": arm["status_after"]}
            records.validate_standalone_run_log(log, "00" * 32, 0x9E3779B97F4A7C15, chunks, MANIFEST)

    def test_a_broken_stream_header_with_the_full_word_count_is_a_falsifier(self):
        words = list(self.WORDS)
        words[8] ^= 0xFFFFFFFF                                 # stream 0's sync word
        self._falsified(words, "does not parse as a staging")

    def test_a_repeated_envelope_with_the_full_word_count_is_a_falsifier(self):
        words = list(self.WORDS)
        words[534:1068] = words[0:534]                         # stream 1 := stream 0
        self._falsified(words, "repeats envelope")

    def test_a_narrowed_envelope_table_is_a_host_defect_not_a_falsifier(self):
        """Round 3 correction: under a valid manifest, three parseable distinct envelopes ×
        four targets = twelve frames, always — so 'fewer than twelve' cannot be served by
        the board. Narrowing the envelope table breaks the HOST's interpretation, and the
        envelope contract catches it first: RecordError, and the runner says HOLD."""
        import unittest.mock as um
        import p3_gate as pg
        import l5_runner as lr
        real = pg.envelopes(MANIFEST)
        narrowed = [dict(e, targets=e["targets"][:3]) for e in real]     # 9 frames, not 12
        with um.patch.object(pg, "envelopes", lambda m: narrowed):
            chunks = self._rechunk(list(self.WORDS))
            with self.assertRaises(records.RecordError) as cm:
                au.verify(LOG, chunks, MANIFEST)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("invalid manifest", str(cm.exception))
        self.assertTrue(lr.classify_rejection(cm.exception).startswith("HOLD instrument:"))

    def test_every_envelope_contract_clause_is_a_host_defect(self):
        """Each clause of the manifest contract, broken one at a time: RecordError, never
        Falsified — the board served the same valid words throughout."""
        import unittest.mock as um
        import p3_gate as pg
        real = pg.envelopes(MANIFEST)
        variants = {
            "two envelopes": real[:2],
            "duplicate far_set": [real[0], dict(real[1], far_set=real[0]["far_set"]), real[2]],
            "five targets": [dict(real[0], targets=real[0]["targets"] + [0x7FFFFFF])] + real[1:],
            # twelve unique targets in all, but 5/3/4 across the envelopes: only the
            # "exactly four each" clause can see this one (its mutant survived otherwise)
            "5/3/4 redistribution": [dict(real[0], targets=real[0]["targets"] + [real[1]["targets"][0]]),
                                     dict(real[1], targets=real[1]["targets"][1:]), real[2]],
            "repeated target FAR": [dict(real[0], targets=real[0]["targets"][:3] + [real[1]["targets"][0]])] + real[1:],
            "not the pinned roles": [dict(real[0], targets=real[0]["targets"][:3] + [0x7FFFFFF])] + real[1:],
        }
        chunks = self._rechunk(list(self.WORDS))
        for name, envs in variants.items():
            with um.patch.object(pg, "envelopes", lambda m, envs=envs: envs):
                with self.assertRaises(records.RecordError, msg=name) as cm:
                    au.verify(LOG, chunks, MANIFEST)
            self.assertNotIsInstance(cm.exception, records.Falsified, name)
            self.assertIn("invalid manifest", str(cm.exception), name)
        with um.patch.object(pg, "envelopes", lambda m: (_ for _ in ()).throw(KeyError("write_envelope"))):
            with self.assertRaises(records.RecordError) as cm:
                au.verify(LOG, chunks, MANIFEST)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("cannot be read", str(cm.exception))

    def test_the_contract_is_checked_before_any_served_word_is_interpreted(self):
        """A broken manifest AND unparseable words: the host-side finding wins, so a host
        defect can never be reported as a board falsifier."""
        import unittest.mock as um
        import p3_gate as pg
        words = list(self.WORDS); words[8] ^= 0xFFFFFFFF
        with um.patch.object(pg, "envelopes", lambda m: pg.envelopes(MANIFEST)[:2]):
            with self.assertRaises(records.RecordError) as cm:
                au.verify(LOG, self._rechunk(words), MANIFEST)
        self.assertNotIsInstance(cm.exception, records.Falsified)

    def test_the_structural_layer_is_still_a_plain_record_error(self):
        """Discrimination for the boundary: the same defects BEFORE assemble() accepts the
        stream stay RecordError and are never promoted to KILL."""
        for chunks, fragment in (
                ([c for c in CHUNKS if c["chunk"] != 5], "missing"),
                (self._with(lambda cs: cs[2].__setitem__("word_offset", cs[2]["word_offset"] + 4)), "gap"),
                (self._with(lambda cs: cs[0].__setitem__("words", cs[0]["words"][:-4] + "+/==")), "base64url")):
            with self.assertRaises(records.RecordError) as cm:
                au.verify(LOG, chunks, MANIFEST)
            self.assertNotIsInstance(cm.exception, records.Falsified, fragment)
            self.assertIn(fragment, str(cm.exception))

    def test_a_missing_manifest_is_a_plain_record_error(self):
        with self.assertRaises(records.RecordError) as cm:
            au.verify(LOG, CHUNKS, None)
        self.assertNotIsInstance(cm.exception, records.Falsified)

    @staticmethod
    def _with(mutate):
        chunks = copy.deepcopy(CHUNKS)
        mutate(chunks)
        return chunks


class ShortAuditBehindAReadbackClaim(unittest.TestCase):
    """A link-2-shaped audit (streams only) served for a record that claims a readback backs
    link 2 and nothing about link 3. The host derives replayed-only; the application's
    'audited' then disagrees and the log is refused — it cannot pass as a full audit."""

    def _streams_only(self):
        words = au.assemble(CHUNKS)[1]["words"][:1602]
        n = (1602 + 383) // 384
        out = []
        for c in range(n):
            part = words[c * 384:(c + 1) * 384]
            out.append({"schema": "app_audit_chunk", "schema_version": "1.0.0", "seq": 1,
                        "span": "streams", "chunk": c, "chunks": n, "word_offset": c * 384,
                        "word_count": len(part), "total_words": 1602, "words": _reencode(part)})
        return out

    def test_the_host_derives_replayed_only(self):
        marks, detail = au.verify(LOG, self._streams_only(), MANIFEST)
        self.assertEqual(marks[1], "replayed-only")
        self.assertIn("short", detail[1])
        self.assertTrue(detail[1]["compared"]["staged_sha256"])   # what it CAN back, it backs

    def test_the_log_is_refused_because_the_record_claims_audited(self):
        seed = int(json.loads((R / "manifests/l5_manifest.json").read_text())["carrier"]["nonce_seed"], 16)
        log = copy.deepcopy(LOG)
        log["session_summary"]["audit"]["total"] = 1     # past session 3's own counter defect
        arm = log["loop_records"][0]["evidence"]["arm"]  # …and past the settle block it predates
        arm["settle"] = {"polls": 1, "polls_max": 1000000, "settled": True,
                         "status_first": arm["status_after"], "status_last": arm["status_after"]}
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(log, "00" * 32, seed, self._streams_only(), MANIFEST)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("host-derived mark is 'replayed-only'", str(cm.exception))


class Link2RefusalClaim(unittest.TestCase):
    """A STOP_LINK2 record's whole claim is staged != commit. Served words that recompute
    TO the commit make that claim false: Falsified."""

    def test_a_false_link2_refusal_is_a_falsifier(self):
        log = copy.deepcopy(LOG)
        r = log["loop_records"][0]
        r["outcome"] = "STOP_LINK2"
        del r["evidence"]["arm"]; del r["evidence"]["app_oracle_record"]
        with self.assertRaises(records.Falsified) as cm:
            au.verify(log, CHUNKS, MANIFEST)
        self.assertIn("STOP_LINK2", str(cm.exception))

    def test_a_true_link2_refusal_is_audited(self):
        log = copy.deepcopy(LOG)
        r = log["loop_records"][0]
        r["outcome"] = "STOP_LINK2"
        r["evidence"]["sign_reply"]["commit"] = "ab" * 32       # a commit the staging is NOT
        del r["evidence"]["arm"]; del r["evidence"]["app_oracle_record"]
        marks, detail = au.verify(log, CHUNKS, MANIFEST)
        self.assertEqual(marks[1], "audited")
        self.assertTrue(detail[1]["compared"]["staged_sha256 != commit"])


class TheGateIsNotOptional(unittest.TestCase):
    def test_validate_requires_the_audits_argument(self):
        import inspect
        params = inspect.signature(records.validate_standalone_run_log).parameters
        self.assertIs(params["audits"].default, inspect.Parameter.empty,
                      "audits must be a required argument so no caller can skip the gate")

    def test_served_words_without_a_manifest_are_refused(self):
        with self.assertRaises(records.RecordError):
            au.verify(LOG, CHUNKS, None)

    def test_the_runner_passes_the_collected_chunks_and_the_manifest(self):
        src = (R / "host/l5_runner.py").read_text()
        self.assertIn("collector.audits, phen)", src)
        self.assertIn('check_audit_policy(log, v["marks"])', src)


if __name__ == "__main__":
    unittest.main()
