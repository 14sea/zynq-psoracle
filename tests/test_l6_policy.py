"""The L6 validator additions (prereg §3a, §2.4): the sampled audit policy with its two
required negatives, the arm-aware check, and the L6 identity fields.

The §3a fixture is REAL board data: session 3's STOP_ARM record and its eight served
chunks (evidence/l5_17A6_2026-09-01-03/, read-only), re-keyed to a seq the sampled
schedule does not select. Its words recompute on the host (the gate says `audited`), so
under §3a item 2 the record is accepted; with the words withheld it is the unaudited
self-report the policy must refuse; with a word flipped it is Falsified — the same gate,
for auto-served words exactly as for requested ones."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "tests"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
from validators import audit as au  # noqa: E402
from validators import records  # noqa: E402
import l6_schedule as ls  # noqa: E402
import p3_gate as g  # noqa: E402
import test_d1_records as d1  # noqa: E402
from test_audit_gate import _reencode  # noqa: E402

S3 = R / "evidence/l5_17A6_2026-09-01-03"
S3_LOG = json.loads((S3 / "run_log.json").read_text())
S3_CHUNKS = json.loads((S3 / "audits.json").read_text())["chunks"]
MANIFEST = g.load_manifest()
N = 8                                       # sampled schedule for N = 8: {1, 2, 9, 10}
UNSAMPLED = 3


def rekeyed_stop_arm(seq: int) -> tuple[dict, list[dict]]:
    rec = copy.deepcopy(S3_LOG["loop_records"][0])
    assert rec["outcome"] == "STOP_ARM" and rec["verified"] == "audited"
    rec["seq"] = seq
    rec["evidence"]["sign_reply"]["seq"] = seq
    rec["evidence"]["app_oracle_record"]["seq"] = seq
    chunks = copy.deepcopy(S3_CHUNKS)
    for c in chunks:
        c["seq"] = seq
    return rec, chunks


def log_with(records_: list[dict]) -> dict:
    return {"loop_records": records_}


class SampledPolicy(unittest.TestCase):
    def setUp(self):
        self.sched = ls.sampled_audit_seqs(N)
        self.assertNotIn(UNSAMPLED, self.sched)

    def test_a_scheduled_scored_candidate_must_be_audited(self):
        log = log_with([d1.scored(1, d1.G_BLANK, d1.BLANK, d1.SEED), d1.scored(2, d1.G_CAND, d1.CAND, d1.SEED)])
        with self.assertRaises(records.RecordError) as cm:
            records.check_audit_policy(log, {1: "audited", 2: "replayed-only"}, "sampled", self.sched)
        self.assertIn("[2]", str(cm.exception)); self.assertIn("scheduled", str(cm.exception))

    def test_an_unscheduled_scored_candidate_need_not_be_audited(self):
        log = log_with([d1.scored(1, d1.G_BLANK, d1.BLANK, d1.SEED), d1.scored(3, d1.G_CAND, d1.CAND, d1.SEED)])
        out = records.check_audit_policy(log, {1: "audited", 3: "replayed-only"}, "sampled", self.sched)
        self.assertEqual(out["audited"], [1]); self.assertEqual(out["unscheduled_audited"], [])
        out = records.check_audit_policy(log, {1: "audited", 3: "audited"}, "sampled", self.sched)
        self.assertEqual(out["unscheduled_audited"], [3])          # recorded, not refused

    def test_gate_refusals_stay_exempt(self):
        log = log_with([d1.refused(3, d1.G_CAND)])
        out = records.check_audit_policy(log, {3: "replayed-only"}, "sampled", self.sched)
        self.assertEqual(out["exempt_no_self_report"], [3])

    def test_the_policy_needs_its_schedule(self):
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log_with([]), {}, "sampled")
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log_with([]), {}, "every-other")

    def test_all_self_reporting_is_unchanged(self):
        log = log_with([d1.scored(2, d1.G_CAND, d1.CAND, d1.SEED)])
        self.assertEqual(records.check_audit_policy(log, {2: "audited"})["policy"], "all-self-reporting")
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log, {2: "replayed-only"})


class Section3aOnRealData(unittest.TestCase):
    """§3a item 5's two required negatives, and the positive they discriminate from."""

    def test_an_auto_audited_stop_arm_outside_the_schedule_is_accepted(self):
        rec, chunks = rekeyed_stop_arm(UNSAMPLED)
        log = log_with([rec])
        marks, _ = au.verify(log, chunks, MANIFEST)
        self.assertEqual(marks[UNSAMPLED], "audited")
        out = records.check_audit_policy(log, marks, "sampled", ls.sampled_audit_seqs(N))
        self.assertEqual(out["audited_auto"], [UNSAMPLED])

    def test_negative_1_unsampled_stop_arm_without_served_words_is_a_hold(self):
        rec, _ = rekeyed_stop_arm(UNSAMPLED)
        log = log_with([rec])
        marks, _ = au.verify(log, [], MANIFEST)              # nothing served
        self.assertEqual(marks[UNSAMPLED], "replayed-only")
        with self.assertRaises(records.RecordError) as cm:
            records.check_audit_policy(log, marks, "sampled", ls.sampled_audit_seqs(N))
        self.assertNotIsInstance(cm.exception, records.Falsified)     # a HOLD, not a KILL
        msg = str(cm.exception)
        self.assertIn(f"[{UNSAMPLED}]", msg); self.assertIn("§3a item 2", msg); self.assertIn("unaudited self-report", msg)

    def test_negative_1_fires_on_exactly_that_record(self):
        rec, chunks = rekeyed_stop_arm(UNSAMPLED)
        other = d1.scored(1, d1.G_BLANK, d1.BLANK, d1.SEED)
        log = log_with([other, rec])
        marks, _ = au.verify(log, [], MANIFEST)
        marks[1] = "audited"                                  # the baseline is fine; only seq 3 offends
        with self.assertRaises(records.RecordError) as cm:
            records.check_audit_policy(log, marks, "sampled", ls.sampled_audit_seqs(N))
        self.assertIn(f"[{UNSAMPLED}]", str(cm.exception)); self.assertNotIn("[1]", str(cm.exception))

    def test_negative_2_auto_served_words_that_do_not_recompute_are_falsified(self):
        rec, chunks = rekeyed_stop_arm(UNSAMPLED)
        c = next(c for c in chunks if c["chunk"] == 0)
        words = au._decode_words(c["words"], "fixture")
        words[10] ^= 1
        c["words"] = _reencode(words)
        with self.assertRaises(records.Falsified):
            au.verify(log_with([rec]), chunks, MANIFEST)


class ArmAware(unittest.TestCase):
    def setUp(self):
        self.n = 4
        self.sched = ls.schedule(0x77, self.n, ls.MODE_ABBA)     # seqs 2..5: A, B, B, A
        self.log = {"session_summary": {"epoch_end": {"kind": "COMPLETED"}}, "loop_records": [
            d1.scored(1, d1.G_BLANK, d1.BLANK, d1.SEED),
            {**d1.scored(2, d1.G_CAND, d1.CAND, d1.SEED), "arm": "random_safe"},
            {**d1.scored(3, d1.G_CAND, d1.CAND, d1.SEED), "arm": "map_guided"},
            {**d1.refused(4, d1.G_CAND), "arm": "map_guided"},
            {**d1.scored(5, d1.G_CAND, d1.CAND, d1.SEED), "arm": "random_safe"},
            d1.scored(6, d1.G_BLANK, d1.BLANK, d1.SEED)]}

    def test_a_conforming_log_passes_and_names_the_brackets(self):
        out = records.check_arm_schedule(self.log, self.sched, self.n)
        self.assertEqual(out["checked"], [2, 3, 4, 5]); self.assertEqual(out["brackets"], [1, 6])

    def test_a_swapped_arm_is_refused(self):
        log = copy.deepcopy(self.log)
        log["loop_records"][2]["arm"] = "random_safe"
        with self.assertRaises(records.RecordError) as cm:
            records.check_arm_schedule(log, self.sched, self.n)
        self.assertIn("seq 3", str(cm.exception)); self.assertIn("swapped", str(cm.exception))

    def test_a_missing_arm_on_a_candidate_is_refused(self):
        log = copy.deepcopy(self.log)
        del log["loop_records"][1]["arm"]
        with self.assertRaises(records.RecordError) as cm:
            records.check_arm_schedule(log, self.sched, self.n)
        self.assertIn("seq 2", str(cm.exception)); self.assertIn("required", str(cm.exception))

    def test_an_arm_on_a_baseline_is_refused(self):
        log = copy.deepcopy(self.log)
        log["loop_records"][0]["arm"] = "random_safe"
        with self.assertRaises(records.RecordError) as cm:
            records.check_arm_schedule(log, self.sched, self.n)
        self.assertIn("bracket", str(cm.exception))

    def test_an_unknown_arm_name_is_refused(self):
        log = copy.deepcopy(self.log)
        log["loop_records"][1]["arm"] = "baseline"
        with self.assertRaises(records.RecordError):
            records.check_arm_schedule(log, self.sched, self.n)

    def test_the_genome_must_be_the_scheduled_operators(self):
        want = {2: d1.G_CAND, 3: d1.G_CAND, 4: d1.G_CAND, 5: d1.G_CAND}
        records.check_arm_schedule(self.log, self.sched, self.n, want)
        want[5] = "22" * 40
        with self.assertRaises(records.RecordError) as cm:
            records.check_arm_schedule(self.log, self.sched, self.n, want)
        self.assertIn("twin mismatch", str(cm.exception))


class L6Identity(unittest.TestCase):
    IDENT = {"master_seed": 0x1234, "schedule_mode": "abba", "operator_data_sha256": "0c" * 32}

    def test_accepts_the_matching_fields(self):
        out = records.check_l6_identity(self.IDENT, 0x1234, "abba", "0c" * 32)
        self.assertEqual(set(out), set(records.L6_IDENTITY_FIELDS))

    def test_refuses_each_mismatch_and_a_missing_field(self):
        with self.assertRaises(records.RecordError):
            records.check_l6_identity(self.IDENT, 0x1235, "abba", "0c" * 32)
        with self.assertRaises(records.RecordError):
            records.check_l6_identity(self.IDENT, 0x1234, "random_safe_forced", "0c" * 32)
        with self.assertRaises(records.RecordError) as cm:
            records.check_l6_identity(self.IDENT, 0x1234, "abba", "0d" * 32)
        self.assertIn("compiled-in map data", str(cm.exception))
        with self.assertRaises(records.RecordError):
            records.check_l6_identity({k: v for k, v in self.IDENT.items() if k != "master_seed"}, 0x1234, "abba", "0c" * 32)


if __name__ == "__main__":
    unittest.main()
