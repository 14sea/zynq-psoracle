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


class PullIntegration(unittest.TestCase):
    """The whole-package review's three integration blockers, on the real session object."""

    def setUp(self):
        import l6_audit_pull as apm
        self.apm = apm
        self.now = {"t": 0.0}
        self.collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: self.now["t"])
        self.sent = []
        self.relay = n.NotaryRelay(TOKEN, lambda req: {"refused": {"finding_kinds": ["x"]}},
                                   drop_budget=4, clock=lambda: 0.0)
        self.tl = lt.Timeline()
        self.cs = lcs.ConsoleSession(TOKEN, self.collector, self.relay, self.tl, audit_seqs=set(),
                                     crc_budget=4, send=lambda line, mtype, seq: self.sent.append(line))

    def _signreq(self, seq):
        line = n.build_line(n.T_SIGNREQ, seq, TOKEN, n.encode_payload(
            {"seq": seq, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0,
             "schema": "sign_request", "schema_version": "1.0.0"}))
        self.cs.on_line(line, self.now["t"], self.now["t"])

    def _ready(self, seq, span="streams+readback", total=2814, chunks=8):
        return n.build_line(self.apm.T_READY, seq, TOKEN, n.encode_payload(
            {"seq": seq, "span": span, "total_words": total, "chunks": chunks, "nonzero": 1}))

    def test_1_a_ready_cannot_authorise_itself(self):
        """seq 999 with our token, no sign exchange behind it: PROTOCOL, not a pull."""
        self.cs.on_line(self._ready(999), 0.0, 0.0)
        self.assertIsNone(self.cs.puller)
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("AUDIT_READY for seq 999", self.collector.epoch_end["reason"])
        self.assertEqual(self.sent, [], "no AUDITGET was ever sent")

    def test_1_only_the_current_candidates_ready_is_accepted(self):
        self._signreq(1)                                  # the relay answered seq 1 (a refusal, but answered)
        self.cs.on_line(self._ready(1), 1.0, 1.0)
        self.assertIsNotNone(self.cs.puller)
        self.assertEqual(self.cs.puller.seq, 1)
        self.assertEqual(n.parse_line(self.sent[-1])["type"], self.apm.T_GET)

    def test_1_a_foreign_token_ready_goes_to_the_collectors_refusal(self):
        line = n.build_line(self.apm.T_READY, 1, "cd" * 16, n.encode_payload({"seq": 1}))
        self.cs.on_line(line, 0.0, 0.0)
        self.assertIsNone(self.cs.puller)
        self.assertEqual(self.collector.epoch_end["kind"], "CRASHED")
        self.assertEqual(self.collector.epoch_end["reason"], "foreign token")

    def test_2_valid_pull_traffic_refreshes_liveness(self):
        """Eight chunks plus retries can outlast 30 s; a pull in progress is not silence."""
        self._signreq(1)
        self.cs.on_line(self._ready(1), 0.0, 0.0)
        board = self.apm.PullBoard(TOKEN, 1, "streams+readback", [0] * 2814)
        for k in range(6):
            self.now["t"] += 9.0                         # 54 s of pull traffic, no other frame
            self.cs.on_line(board.serve(k), self.now["t"], self.now["t"])
            self.assertIsNone(self.collector.poll(), f"chunk {k}: valid audit traffic read as silence")
        self.now["t"] += 31.0                            # NOW it is real silence
        self.assertEqual(self.collector.poll()["kind"], "CRASHED")

    def test_3_the_over_budget_line_is_a_recorded_attempt_of_the_pull(self):
        self._signreq(1)
        hb = n.build_line(n.T_HB, 1, TOKEN)
        for i in range(4):                                # spend the budget outside the pull
            self.cs.on_line(broken(hb), float(i), float(i))
        self.assertFalse(self.cs.ended)
        self.cs.on_line(self._ready(1), 5.0, 5.0)
        board = self.apm.PullBoard(TOKEN, 1, "streams+readback", [0] * 2814)
        bad = broken(board.serve(0))
        self.cs.on_line(bad, 6.0, 6.0)                    # the fifth drop: over budget, inside the pull
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("PROTOCOL_CRC_BUDGET: 5 > 4", self.collector.epoch_end["reason"])
        self.assertEqual(len(self.cs.pull_ledgers), 1, "the pull's ledger was settled")
        pl = self.cs.pull_ledgers[0]
        self.assertTrue(pl["failed"]); self.assertIn("PROTOCOL_CRC_BUDGET", pl["why"])
        self.assertEqual([a["outcome"] for a in pl["attempts"] if a["chunk"] == 0][0], "crc")
        self.assertEqual(pl["lines_kept"], [bad.rstrip("\n")] if bad.endswith("\n") else [bad],
                         "the final failing line is kept verbatim in the pull's own ledger")


    def test_budget_and_exhaustion_together_one_reason_one_abort(self):
        """Three CRC failures on one chunk with a global budget of 2: the puller exhausts
        its retries on the same line that crosses the budget. The GLOBAL authority wins —
        epoch reason and pulls[].why are the same PROTOCOL_CRC_BUDGET fact — all three
        attempts and raw lines are kept, and exactly ONE AUDITABORT went to the board."""
        import l6_audit_pull as apm
        self.relay.drop_budget = 2
        self.cs.crc_budget = 2
        self._signreq(1)
        self.cs.on_line(self._ready(1), 0.0, 0.0)
        board = self.apm.PullBoard(TOKEN, 1, "streams+readback", [0] * 2814)
        for i in range(3):
            self.cs.on_line(broken(board.serve(0)), 1.0 + i, 1.0 + i)
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertEqual(self.collector.epoch_end["reason"], "PROTOCOL_CRC_BUDGET: 3 > 2")
        self.assertEqual(len(self.cs.pull_ledgers), 1)
        pl = self.cs.pull_ledgers[0]
        self.assertTrue(pl["failed"])
        self.assertEqual(pl["why"], "PROTOCOL_CRC_BUDGET: 3 > 2",
                         "the pull's reason is the epoch's reason, not the exhaustion text")
        self.assertEqual([a["outcome"] for a in pl["attempts"]], ["crc", "crc", "crc"])
        self.assertEqual(len(pl["lines_kept"]), 3)
        aborts = [l for l in self.sent if n.parse_line(l)["type"] == apm.T_ABORT]
        self.assertEqual(len(aborts), 1, "never a second ABORT")


class RecTransaction(unittest.TestCase):
    """rec-v3 on the real session object: RECACK on an accepted record; RECGET on a broken
    REC-shaped line for the pending candidate; duplicates re-acknowledged, never appended;
    a conflicting duplicate, a REC for another seq, or a SIGNREQ over an outstanding record
    → PROTOCOL; a malformed REC-shaped line in the window is a retry, not CRASHED."""

    def setUp(self):
        import l6_rec as rx
        self.rx = rx
        self.sent = []
        self.collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
        self.relay = n.NotaryRelay(TOKEN, lambda req: {"refused": {"finding_kinds": ["x"]}}, drop_budget=8, clock=lambda: 0.0)
        self.tl = lt.Timeline()
        self.cs = lcs.ConsoleSession(TOKEN, self.collector, self.relay, self.tl, audit_seqs=set(), crc_budget=8,
                                     send=lambda line, mtype, seq: self.sent.append((mtype, seq, line)))

    def _signreq(self, seq, t=0.0):
        line = n.build_line(n.T_SIGNREQ, seq, TOKEN, n.encode_payload(
            {"seq": seq, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0,
             "schema": "sign_request", "schema_version": "1.0.0"}))
        self.cs.on_line(line, t, t)

    def _rec(self, seq, extra=None):
        rec = {"schema": "loop_record", "schema_version": "1.1.0", "seq": seq, "genome": "0" * 80,
               "outcome": "REFUSED_BY_GATE", "verified": "replayed-only",
               "evidence": {"sign_refusal": {"schema": "sign_refusal", "schema_version": "1.0.0", "seq": seq, "finding_kinds": ["x"]}}}
        rec.update(extra or {})
        return n.build_line(n.T_REC, seq, TOKEN, n.encode_payload(rec))

    def _types(self):
        return [(m, s) for m, s, _ in self.sent]

    def test_an_accepted_record_is_acknowledged_once(self):
        self._signreq(1)
        self.assertEqual(self.cs.pending_rec_seq, 1)
        self.cs.on_line(self._rec(1), 1.0, 1.0)
        self.assertEqual(self.collector.last_rec_seq, 1); self.assertIsNone(self.cs.pending_rec_seq)
        self.assertEqual(self._types()[-1], (self.rx.T_RECACK, 1))
        led = self.cs.rec_ledgers_json()[0]
        self.assertEqual((led["seq"], led["accepted"], [a["outcome"] for a in led["attempts"]]), (1, True, ["ok"]))
        self.assertEqual(self.sent[-1][2], n.build_line(self.rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1})))

    def test_a_broken_rec_for_the_pending_candidate_is_asked_for_again_and_the_resend_accepted(self):
        self._signreq(1)
        self.cs.on_line(broken(self._rec(1)), 1.0, 1.0)
        self.assertEqual(self.cs.crc_dropped, 1, "the one ledger counts it")
        self.assertEqual(self._types()[-1], (self.rx.T_RECGET, 1))
        self.assertEqual(self.collector.loop_records, [])
        self.cs.on_line(self._rec(1), 2.0, 2.0)
        self.assertEqual(len(self.collector.loop_records), 1)
        led = self.cs.rec_ledgers_json()[0]
        self.assertEqual([a["outcome"] for a in led["attempts"]], ["crc", "ok"])
        self.assertEqual(len(led["lines_kept"]), 1); self.assertEqual(led["gets_sent"], 1)
        self.assertFalse(self.cs.ended)

    def test_the_hosts_asks_are_bounded_and_the_budget_still_ends_the_epoch(self):
        self._signreq(1)
        for i in range(4):
            self.cs.on_line(broken(self._rec(1)), float(i), float(i))
        self.assertEqual(self.cs.rec_ledgers_json()[0]["gets_sent"], self.rx.REC_HOST_MAX_GETS)
        self.assertFalse(self.cs.ended)
        self.cs.crc_budget = 5
        self.cs.on_line(broken(self._rec(1)), 9.0, 9.0); self.cs.on_line(broken(self._rec(1)), 10.0, 10.0)
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("PROTOCOL_CRC_BUDGET: 6 > 5", self.collector.epoch_end["reason"])

    def test_a_duplicate_is_re_acknowledged_and_never_appended(self):
        self._signreq(1)
        self.cs.on_line(self._rec(1), 1.0, 1.0)
        self.cs.on_line(self._rec(1), 2.0, 2.0)                  # our RECACK was lost: the board resent
        self.assertEqual(len(self.collector.loop_records), 1)
        self.assertEqual(self._types()[-2:], [(self.rx.T_RECACK, 1), (self.rx.T_RECACK, 1)])
        self.assertEqual([a["outcome"] for a in self.cs.rec_ledgers_json()[0]["attempts"]], ["ok", "duplicate"])
        self.assertFalse(self.cs.ended)
        # a corrupted resend of the accepted record cannot be known byte-identical: RECGET,
        # and only a CRC-valid resend equal to the accepted payload earns the RECACK
        # (review 2026-09-02, blocker 2)
        self.cs.on_line(broken(self._rec(1)), 3.0, 3.0)
        self.assertEqual(self._types()[-1], (self.rx.T_RECGET, 1))
        self.cs.on_line(self._rec(1), 4.0, 4.0)
        self.assertEqual(self._types()[-1], (self.rx.T_RECACK, 1)); self.assertFalse(self.cs.ended)
        self.assertEqual(len(self.collector.loop_records), 1)
        self.cs.on_line(broken(self._rec(1)), 5.0, 5.0)
        self.assertEqual(self._types()[-1], (self.rx.T_RECGET, 1))
        self.cs.on_line(self._rec(1, {"genome": "1" * 80}), 6.0, 6.0)     # a valid resend with OTHER content
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("different content", self.collector.epoch_end["reason"])
        self.assertEqual(len(self.collector.loop_records), 1)
        led = self.cs.rec_ledgers_json()[0]
        self.assertEqual([a["outcome"] for a in led["attempts"]], ["ok", "duplicate", "crc", "duplicate", "crc", "conflict"])

    def test_a_conflicting_duplicate_is_a_protocol_end_and_the_first_record_stands(self):
        self._signreq(1)
        self.cs.on_line(self._rec(1), 1.0, 1.0)
        self.cs.on_line(self._rec(1, {"genome": "1" * 80}), 2.0, 2.0)
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("different content", self.collector.epoch_end["reason"])
        self.assertEqual(len(self.collector.loop_records), 1)
        self.assertEqual(self.collector.loop_records[0]["genome"], "0" * 80)
        self.assertTrue(self.cs.rec_ledgers_json()[0]["conflict"])

    def test_a_record_for_another_seq_or_a_signreq_over_an_outstanding_record_is_protocol(self):
        self._signreq(1)
        self.cs.on_line(self._rec(2), 1.0, 1.0)
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("advanced without an acknowledgement", self.collector.epoch_end["reason"])
        self.assertEqual(self.collector.loop_records, [])
        self.setUp()
        self._signreq(1)
        self._signreq(2)                                          # REC 1 still outstanding
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("SIGNREQ seq 2 while the record of seq 1 is unacknowledged", self.collector.epoch_end["reason"])
        self.assertEqual(self.relay.last_seq, 1, "the relay never answered seq 2")
        self.assertEqual([m for m, _, _ in self.sent].count(n.T_SIGNREF), 1)

    def test_a_malformed_rec_shaped_line_in_the_window_is_a_retry_not_crashed(self):
        self._signreq(1)
        self.cs.on_line(self._rec(1).rstrip("\n") + " extra", 1.0, 1.0)     # seven fields
        self.assertFalse(self.cs.ended); self.assertEqual(self.tl.bad_frames, 1)
        self.assertEqual(self._types()[-1], (self.rx.T_RECGET, 1))
        self.assertEqual([a["outcome"] for a in self.cs.rec_ledgers_json()[0]["attempts"]], ["malformed"])
        # outside the window the collector's rule stands
        self.cs.on_line(self._rec(1), 2.0, 2.0)
        self.cs.on_line("P3L5 AUDIT 24 " + TOKEN + " abc def 00000000", 3.0, 3.0)
        self.assertEqual(self.collector.epoch_end["kind"], "CRASHED")

    def test_a_broken_line_of_another_type_does_not_trigger_a_recget(self):
        self._signreq(1)
        self.cs.on_line(broken(n.build_line(n.T_HB, 1, TOKEN)), 1.0, 1.0)
        self.assertEqual(self.cs.crc_dropped, 1)
        self.assertEqual([m for m, _, _ in self.sent if m == self.rx.T_RECGET], [])
        self.assertEqual(self.cs.rec_ledgers_json(), [])


class S1Replay(unittest.TestCase):
    """S #1's recorded console bytes through the rec-v3 session with the recorded notary
    answers: the broken REC 465 now draws a RECGET; the old image (which never listened for
    it) sent SIGNREQ 466 with the record outstanding, which the closure names as the
    PROTOCOL end. Nothing after the loss is accepted; 464 records stand."""

    @classmethod
    def setUpClass(cls):
        import l6_rec as rx
        S1 = R / "evidence/l6_17A6_2026-09-01-11-S"
        log = json.loads((S1 / "run_log.json").read_text())
        answers = {e["seq"]: e["answer"] for e in log["notary_log"]["entries"]}
        token = log["app_identity"]["token"]

        def signer(req):
            a = answers[req["seq"]]
            return {"commit": a["commit"], "expected_tables": a["expected_tables"], "tag": a["tag"]}
        cls.rx = rx
        cls.collector = n.Collector(token, heartbeat_s=10, clock=lambda: 0.0)
        cls.relay = n.NotaryRelay(token, signer, drop_budget=486, clock=lambda: 0.0)
        cls.tl = lt.Timeline()
        cls.sent = []
        cls.cs = lcs.ConsoleSession(token, cls.collector, cls.relay, cls.tl, audit_seqs=set(log["l6"]["audit_seqs"]),
                                    crc_budget=486, send=lambda line, mtype, seq: cls.sent.append((mtype, seq)))
        t = 0.0
        for raw in (S1 / "console.log").read_bytes().split(b"\n"):
            t += 0.001
            cls.cs.on_line(raw.decode("ascii", "replace").rstrip("\r"), t, t)

    def test_the_broken_rec_465_draws_a_recget_and_the_advance_is_the_protocol_end(self):
        self.assertIn((self.rx.T_RECGET, 465), self.sent)
        self.assertEqual([s for m, s in self.sent if m == self.rx.T_RECACK][-1], 464)
        self.assertEqual(self.collector.epoch_end["kind"], "PROTOCOL")
        self.assertIn("SIGNREQ seq 466 while the record of seq 465 is unacknowledged", self.collector.epoch_end["reason"])
        self.assertEqual(len(self.collector.loop_records), 464)
        self.assertEqual(self.tl.crc_dropped_by_type, {"REC": 1})
        led = {l["seq"]: l for l in self.cs.rec_ledgers_json()}
        self.assertEqual([a["outcome"] for a in led[465]["attempts"]], ["crc"])
        self.assertEqual(len(led[465]["lines_kept"][0]), 1775)
        self.assertTrue(all(led[s]["accepted"] for s in range(1, 465)))


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
