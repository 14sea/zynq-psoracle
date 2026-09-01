"""host/l6_console.py — the one inbound ledger and the CRC authority (design review 2026-09-01).

Driven with the REAL Timeline, Collector and NotaryRelay and a scripted sender. The
C1 #3 counterfactual replays that session's recorded console bytes through this session
object with the recorded notary answers: the ledger counts exactly the two audit drops,
they are inside the D-s4 budget, and the log is still refused for the two missing chunks —
a budget within bounds never turns an incomplete audit into a PASS."""
from __future__ import annotations

import inspect
import json
import sys
import unittest
import zlib
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l5_notary as n  # noqa: E402
import l6_checks as lc  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_timing as lt  # noqa: E402
from validators import records  # noqa: E402

TOKEN = "ab" * 16
C13 = R / "evidence/l6_17A6_2026-09-01-08-C1"


def broken(line: str) -> str:
    """The same line with its CRC field wrong (a corrupted body would do the same)."""
    body, crc = line.rstrip("\n").rsplit(" ", 1)
    bad = f"{(int(crc, 16) ^ 1):08x}"
    return f"{body} {bad}"


def session(budget=4, signer=None):
    collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
    relay = n.NotaryRelay(TOKEN, signer or (lambda req: {"refused": {"finding_kinds": ["x"]}}), drop_budget=budget, clock=lambda: 0.0)
    tl = lt.Timeline()
    sent = []
    cs = lcs.ConsoleSession(TOKEN, collector, relay, tl, audit_seqs=set(), crc_budget=budget,
                            send=lambda line, mtype, seq: sent.append((mtype, seq)))
    return cs, sent


class Ledger(unittest.TestCase):
    def test_every_frame_type_that_fails_crc_is_counted_exactly_once_and_by_type(self):
        cs, sent = session(budget=10)
        lines = {n.T_SIGNREQ: n.build_line(n.T_SIGNREQ, 1, TOKEN, n.encode_payload({"seq": 1, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0})),
                 n.T_HB: n.build_line(n.T_HB, 1, TOKEN), n.T_AUDIT: n.build_line(n.T_AUDIT, 1, TOKEN, "eyJ9"),
                 n.T_REC: n.build_line(n.T_REC, 1, TOKEN, "eyJ9"), n.T_TERM: n.build_line(n.T_TERM, 2, TOKEN, "eyJ9"),
                 n.T_CLOSE: n.build_line(n.T_CLOSE, 1, TOKEN, "eyJ9")}
        t = 0.0
        for ty, ln in lines.items():
            t += 1; cs.on_line(broken(ln), t, t)
        self.assertEqual(cs.crc_dropped, 6)
        self.assertEqual(cs.timeline.crc_dropped_by_type, {ty: 1 for ty in lines})
        self.assertEqual(cs.relay.crc_dropped, 0, "the relay never sees a CRC-failed line")
        self.assertEqual(sent, [], "no reply to a broken SIGNREQ")
        self.assertFalse(cs.ended, "within budget: the epoch goes on")
        self.assertEqual(cs.collector.loop_records, [], "a broken REC is not a record")

    def test_a_broken_signreq_is_a_drop_not_a_signed_exchange(self):
        cs, sent = session()
        ln = n.build_line(n.T_SIGNREQ, 1, TOKEN, n.encode_payload({"seq": 1, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0}))
        cs.on_line(broken(ln), 1.0, 1.0)
        self.assertEqual(cs.crc_dropped, 1); self.assertEqual(sent, [])
        cs.on_line(ln, 2.0, 2.0)                                   # the intact resend is answered
        self.assertEqual([m for m, _ in sent], [n.T_SIGNREF])

    def test_the_first_drop_past_the_budget_ends_the_epoch_protocol_and_nothing_after_counts(self):
        cs, sent = session(budget=2)
        hb = n.build_line(n.T_HB, 1, TOKEN)
        for i in range(3):
            cs.on_line(broken(hb), float(i), float(i))
        self.assertTrue(cs.ended)
        self.assertEqual(cs.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("PROTOCOL_CRC_BUDGET: 3 > 2", cs.collector.epoch_end["reason"])
        cs.on_line(broken(hb), 9.0, 9.0); cs.on_line(hb, 10.0, 10.0)
        self.assertEqual(cs.crc_dropped, 3, "after the end nothing is evidence")
        self.assertEqual(len([f for f in cs.timeline.frames if f["type"] == n.T_HB]), 0)

    def test_a_malformed_frame_is_not_a_crc_drop_and_still_crashes(self):
        cs, sent = session()
        cs.on_line("P3L5 AUDIT 24 " + TOKEN + " abc def 00000000", 1.0, 1.0)   # seven fields: FrameError
        self.assertEqual(cs.crc_dropped, 0); self.assertEqual(cs.timeline.bad_frames, 1)
        self.assertEqual(cs.collector.epoch_end["kind"], "CRASHED")
        self.assertEqual(cs.collector.epoch_end["reason"], "unparseable frame")

    def test_the_runner_reads_every_crc_number_from_the_ledger(self):
        import l6_runner as l6
        src = inspect.getsource(l6.run_l6)
        self.assertNotIn("relay.crc_dropped", src)
        self.assertIn("console.on_line(line, t_mono, t_wall)", src)
        self.assertIn('summary["crc_dropped"] = timeline.crc_dropped', src)
        self.assertIn("crc_dropped=console.crc_dropped", src)          # the crashed summary
        self.assertIn("console.crc_dropped, plan[\"crc_budget\"]", src)  # the soak check


class C13Counterfactual(unittest.TestCase):
    """C1 #3's recorded console bytes through the real session object, with the recorded
    notary answers: the ledger says 2 drops (both AUDIT), inside the budget of 7; the log
    is still refused — missing audit chunks are a HOLD whatever the CRC total."""

    @classmethod
    def setUpClass(cls):
        log = json.loads((C13 / "run_log.json").read_text())
        answers = {e["seq"]: e["answer"] for e in log["notary_log"]["entries"]}
        token = log["app_identity"]["token"]

        def signer(req):
            a = answers[req["seq"]]
            return {"commit": a["commit"], "expected_tables": a["expected_tables"], "tag": a["tag"]}
        cls.collector = n.Collector(token, heartbeat_s=10, clock=lambda: 0.0)
        cls.relay = n.NotaryRelay(token, signer, drop_budget=7, clock=lambda: 0.0)
        cls.tl = lt.Timeline()
        cls.cs = lcs.ConsoleSession(token, cls.collector, cls.relay, cls.tl, audit_seqs=set(range(1, 67)),
                                    crc_budget=7, send=lambda *a: None)
        t = 0.0
        for raw in (C13 / "console.log").read_bytes().split(b"\n"):
            t += 0.001
            cls.cs.on_line(raw.decode("ascii", "replace").rstrip("\r"), t, t)
        cls.log = {"control_plane": "standalone", "app_identity": cls.collector.app_identity,
                   "loop_records": cls.collector.loop_records, "session_summary": cls.collector.session_summary,
                   "notary_log": cls.relay.notary_log(), "closing_negative": cls.collector.closing_negative}

    def test_the_ledger_counts_exactly_the_two_audit_drops_within_budget(self):
        self.assertEqual(self.cs.crc_dropped, 2)
        self.assertEqual(self.tl.crc_dropped_by_type, {"AUDIT": 2})
        self.assertEqual(self.tl.bad_frames, 0)
        self.assertLessEqual(self.cs.crc_dropped, 7)
        self.assertEqual(self.collector.epoch_end["kind"], "COMPLETED")
        self.assertEqual(len(self.collector.loop_records), 66); self.assertEqual(len(self.collector.audits), 526)

    def test_within_budget_the_incomplete_audit_is_still_refused(self):
        import p3_gate as g
        import p3_genome as gn
        phen = g.load_manifest()
        blank = g.gate(g.build_streams(gn.frames_from_genome(gn.blank_genome(phen), phen), phen), phen)["candidate_sha256"]
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(self.log, blank, 0x9E3779B97F4A7C15, self.collector.audits, phen)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("audit seq 20", str(cm.exception)); self.assertIn("missing [3]", str(cm.exception))
        found = lc.structural_findings(self.log, self.collector.audits, set(range(1, 67)), self.tl.frames)
        self.assertTrue(any("missing AUDIT for seq 20" in f for f in found))
        self.assertTrue(any("missing AUDIT for seq 62" in f for f in found))


if __name__ == "__main__":
    unittest.main()
