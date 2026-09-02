"""The crash-path summary (owner's batch item 4/5, after S #1): a collector-written
CRASHED summary carries the audit count the HOST AUDIT GATE derived — and, with that
count corrected on S #1's real evidence, the session is still a HOLD: the validator
accepts the 464 records and the structural gate names the missing REC/TERM. The wrong
reason was a defect; the outcome it hid was never a PASS."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l5_notary as n  # noqa: E402
import l5_runner as l5  # noqa: E402
import l6_checks as lc  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
from validators import records  # noqa: E402

S1 = R / "evidence/l6_17A6_2026-09-01-11-S"
LOG = json.loads((S1 / "run_log.json").read_text())
AUDITS = json.loads((S1 / "audits.json").read_text())["chunks"]
TIMELINE = json.loads((S1 / "timeline.json").read_text())
PHEN = g.load_manifest()
BLANK = g.gate(g.build_streams(gn.frames_from_genome(gn.blank_genome(PHEN), PHEN), PHEN), PHEN)["candidate_sha256"]
SEED = 0x9E3779B97F4A7C15


class S1Counterfactual(unittest.TestCase):
    def test_the_recorded_summary_says_0_and_the_validator_named_rule_ix(self):
        """What S #1 shipped: audited 0 from the crash path, 31 verified by the gate."""
        self.assertEqual(LOG["session_summary"]["written_by"], "collector")
        self.assertEqual(LOG["session_summary"]["audit"], {"audited": 0, "total": 464})
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(LOG, BLANK, SEED, AUDITS, PHEN)
        self.assertIn("(ix) summary says 0 audited, the host verified 31", str(cm.exception))

    def test_the_gate_count_is_31_from_the_host_audit_gate_marks(self):
        n_aud, src = lc.crash_audit_count({"loop_records": LOG["loop_records"]}, AUDITS, PHEN)
        self.assertEqual(n_aud, 31); self.assertIn("host audit gate", src)
        # not the pull count (31 pulls reached DONE here too, but that is not the source)
        pulls = json.loads((S1 / "audits.json").read_text())["pulls"]
        self.assertEqual(sum(1 for p in pulls if p["done"]), 31)
        # and not the firmware's marks: the count is what recomputes, seq by seq
        from validators import audit as au
        marks, _ = au.verify({"loop_records": LOG["loop_records"]}, AUDITS, PHEN)
        self.assertEqual(sorted(s for s, m in marks.items() if m == "audited"), [1, 2] + list(range(16, 465, 16)))

    def test_with_the_count_corrected_the_session_is_still_a_hold_on_the_missing_rec_and_term(self):
        """Item 5: the corrected summary makes the validator accept the 464 records; the
        structural gate then names REC 465/466 (SIGNREQs answered, no record) and the
        missing TERM; the epoch is CRASHED — HOLD, never PASS."""
        import copy
        log = copy.deepcopy(LOG)
        n_aud, _ = lc.crash_audit_count({"loop_records": log["loop_records"]}, AUDITS, PHEN)
        log["session_summary"]["audit"] = {"audited": n_aud, "total": len(log["loop_records"])}
        v = records.validate_standalone_run_log(log, BLANK, SEED, AUDITS, PHEN)
        self.assertEqual((v["scored"], v["audited"], v["chain_length"]), (464, 31, 464))
        found = lc.structural_findings(log, AUDITS, set(LOG["l6"]["audit_seqs"]), TIMELINE["frames"])
        self.assertTrue(any("missing REC for seq [465, 466]" in f for f in found), found)
        self.assertTrue(any("missing TERM" in f for f in found), found)
        self.assertNotEqual(l5.outcome_for(log["session_summary"]["epoch_end"]), "PASS")
        self.assertTrue(l5.outcome_for(log["session_summary"]["epoch_end"]).startswith("HOLD CRASHED"))

    def test_a_gate_refusal_yields_zero_with_the_refusal_named(self):
        """If the served words do not reassemble, the count is 0 and the note says why: the
        validator's own refusal will then be the true first reason."""
        broken = [c for c in AUDITS if not (c["seq"] == 16 and c["chunk"] == 3)]
        n_aud, src = lc.crash_audit_count({"loop_records": LOG["loop_records"]}, broken, PHEN)
        self.assertEqual(n_aud, 0); self.assertIn("refused", src); self.assertIn("audit seq 16", src)

    def test_the_runner_builds_the_crashed_summary_from_the_gate(self):
        import inspect
        import l6_runner as l6
        src = inspect.getsource(l6.run_l6)
        self.assertIn("lc.crash_audit_count(gate_log, collector.audits, phen)", src)
        self.assertIn('audit={"audited": audited_n, "total": len(collector.loop_records)}', src)
        # the collector's default (audited 0) is never what the runner writes
        self.assertNotIn("collector.crashed_summary(\n                crc_dropped", src)


class CollectorDefaultIsNotTheRunnersSource(unittest.TestCase):
    def test_the_collectors_own_default_stays_zero_for_a_bare_crash(self):
        """l5_notary is not edited (the L5 instrument that PASSED): its default is still 0
        audited; the L6 runner supplies the gate's count explicitly."""
        c = n.Collector("ab" * 16, heartbeat_s=10, clock=lambda: 0.0)
        c._crash("x")
        self.assertEqual(c.crashed_summary()["audit"], {"audited": 0, "total": 0})
        self.assertEqual(c.crashed_summary(audit={"audited": 3, "total": 5})["audit"], {"audited": 3, "total": 5})


if __name__ == "__main__":
    unittest.main()
