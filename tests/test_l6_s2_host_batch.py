"""S #2 (2026-09-03-03) host batch, part 1 — the malformed non-transaction line no longer
ends the epoch (v0.7 candidate `bad_frame_policy="ledger"`), proven two ways:

  1. the RECORDED bytes of S #2's console (evidence, read-only) replayed through the real
     reader, the real ConsoleSession, Collector and NotaryRelay: under the v0.6 policy the
     epoch ends `CRASHED: unparseable frame` exactly as on the day (the discrimination
     control); under the ledger policy the host survives the merged line with ONE bad frame
     in the ledger, seq 145 still pending, nothing acknowledged or signed for it;
  2. what the recording cannot show (it stops at the port close 0.2 s later): a MODELLED
     byte-identical resend of REC 145 by the firmware's REC twin (`l6_rec.RecBoard`) after
     its bound — accepted once with a RECACK, the record appended once, then the negatives:
     no resend (silence), a wrong resend (another seq), a conflicting resend (same seq, other
     bytes), the malformed line again and again (the terminal bound), and the budget.

Nothing here measures the board; the twin's clock is virtual.
"""
from __future__ import annotations

import copy
import json
import random
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_reader as lrd  # noqa: E402
import l6_rec as rx  # noqa: E402
import l6_timing as lt  # noqa: E402

S2 = R / "evidence/l6_17A6_2026-09-03-03-S"
SUMMARY = json.loads((S2 / "summary.json").read_text())
RUN_LOG = json.loads((S2 / "run_log.json").read_text())
TOKEN = SUMMARY["token"]
AUDIT_SEQS = set(SUMMARY["l6"]["audit_seqs"])
CRC_BUDGET = SUMMARY["l6"]["crc_budget"]
RAW = (S2 / "console.log").read_bytes()
MERGED = next(l for l in RAW.split(b"\n") if l.startswith(b"P3L5 HB 145") and len(l) > 100).decode() + "\n"
SIGN_ANSWER = {"commit": "a" * 64, "expected_tables": ["0" * 16] * 6, "tag": "b" * 32}


class FakeSerial:
    """The recorded bytes, delivered in random poll-sized pieces (seeded)."""

    def __init__(self, data: bytes, seed: int = 1, max_piece: int = 4096):
        rng = random.Random(seed)
        self.pieces = []
        i = 0
        while i < len(data):
            k = rng.randint(1, max_piece)
            self.pieces.append(data[i:i + k]); i += k

    @property
    def in_waiting(self) -> int:
        return len(self.pieces[0]) if self.pieces else 0

    def read(self, k: int) -> bytes:
        return self.pieces.pop(0)


def rec_line(seq: int, template: dict | None = None) -> str:
    """A CRC-valid REC line for `seq` shaped like S #2's REC 144 (the recording holds no
    complete REC 145: its head and ~590 body characters were lost)."""
    rec = copy.deepcopy(template or RUN_LOG["loop_records"][143])
    assert rec["seq"] == 144
    rec["seq"] = seq
    return n.build_line(n.T_REC, seq, TOKEN, n.encode_payload(rec))


class Replay:
    def __init__(self, policy: str, bad_frame_budget: int | None = CRC_BUDGET, seed: int = 1):
        self.now = {"t": 1000.0}
        clock = lambda: self.now["t"]  # noqa: E731
        self.collector = n.Collector(TOKEN, heartbeat_s=10, clock=clock)
        self.relay = n.NotaryRelay(TOKEN, lambda req: dict(SIGN_ANSWER), drop_budget=CRC_BUDGET, clock=clock)
        self.timeline = lt.Timeline()
        self.sent: list[str] = []
        self.serial = FakeSerial(RAW, seed=seed)
        self.reader = lrd.L6LineReader(self.serial, clock_mono=clock, clock_wall=clock)
        self.cs = lcs.ConsoleSession(TOKEN, self.collector, self.relay, self.timeline, AUDIT_SEQS, CRC_BUDGET,
                                     send=lambda line, mtype, seq: self.sent.append(line), reader=self.reader,
                                     clock=clock, protocol="rel-v4", identity_check=lambda ident: [],
                                     bad_frame_policy=policy, bad_frame_budget=bad_frame_budget)

    def run(self) -> None:
        while self.serial.pieces:
            self.now["t"] += 0.001
            for line, tm, tw in self.reader.poll():
                self.cs.on_line(line, tm, tw)
            self.cs.tick()
            self.collector.poll()

    def feed(self, line: str, dt: float = 0.01) -> None:
        self.now["t"] += dt
        self.cs.on_line(line.rstrip("\n"), self.now["t"], self.now["t"])
        self.collector.poll()

    def sent_types(self) -> list[str]:
        return [n.parse_line(l)["type"] for l in self.sent]


class S2RecordedBytes(unittest.TestCase):
    def test_the_recording_is_the_one_the_findings_describe(self):
        self.assertEqual(len(MERGED), 1731)                      # 1730 bytes + the newline
        self.assertTrue(MERGED.startswith("P3L5 HB 145 " + TOKEN + " eyJpIjoxMn0= "))
        import base64
        b64 = MERGED.rstrip("\n").rsplit(" ", 1)[0][len("P3L5 HB 145 " + TOKEN + " eyJpIjoxMn0= "):]
        seg = b64[3:]; seg = seg[:len(seg) // 4 * 4]                 # the REC 145 tail decodes at offset 3
        decoded = base64.urlsafe_b64decode(seg).decode("utf-8", "replace")
        self.assertTrue(decoded.endswith('"schema_version":"1.1.0","seq":145,"verified":"replayed-only"}'), decoded[-80:])
        with self.assertRaises(n.FrameError):
            n.parse_line(MERGED)                                 # malformed, not a CRC failure

    def test_under_v06_the_replay_reproduces_the_days_crash(self):
        rp = Replay(lcs.BAD_FRAME_CRASH)
        rp.run()
        self.assertEqual(rp.collector.epoch_end, {"kind": "CRASHED", "reason": "unparseable frame", "last_seq": 144})
        self.assertEqual((rp.timeline.bad_frames, rp.timeline.crc_dropped, rp.collector.last_rec_seq), (1, 2, 144))
        self.assertEqual(rp.timeline.crc_dropped_by_type, {"SIGNREQ": 1, "REC": 1})

    def test_under_the_ledger_policy_the_host_survives_the_merged_line(self):
        rp = Replay(lcs.BAD_FRAME_LEDGER)
        rp.run()
        self.assertIsNone(rp.collector.epoch_end, "the epoch is open: the merged line ended nothing")
        self.assertEqual(rp.timeline.bad_frames, 1, "the ledger holds the line exactly once")
        self.assertEqual(sum(1 for f in rp.timeline.frames if f["type"] == "BAD_FRAME"), 1)
        self.assertEqual(rp.timeline.crc_dropped, 2, "the two controls; the merged line is not a CRC drop")
        self.assertEqual(rp.collector.last_rec_seq, 144); self.assertEqual(len(rp.collector.loop_records), 144)
        self.assertEqual(rp.relay.last_seq, 145); self.assertEqual(rp.cs.pending_rec_seq, 145, "seq 145 is the pending candidate")
        self.assertNotIn(145, rp.cs.rec_ledgers, "nothing was asked for or acknowledged for 145 on the merged line")
        types = rp.sent_types()
        self.assertEqual(types.count(rx.T_RECACK), 144); self.assertEqual(types.count(rx.T_RECGET), 1)   # the control only
        self.assertEqual(types.count(n.T_SIGNOK), 145); self.assertEqual(types.count("SIGNGET"), 1)     # the control only
        self.assertEqual(types.count("AUDITDONE"), 11); self.assertEqual(types.count("AUDITGET"), 88)
        self.assertEqual(rp.reader.fragments, [], "no resync fragment: the REC head was lost, so nothing to resync on")
        self.assertEqual(rp.collector.last_heard < rp.now["t"], True)


class ModelledRecResend(unittest.TestCase):
    """After the replay: the REC transaction twin resends the SAME bytes on its bound.

    `l6_rec.RecBoard` is the PYTHON twin of the board's transaction, cross-verified against
    the image's C unit (`firmware/p3_rectx.c`) by the wire-contract tests; it is a model of
    the board, never the firmware itself and never a measurement of it.

    The replay has already consumed S #2's merged line from `console.log`, so the merged
    line is NOT delivered again here: `board.start()` establishes the state the recording
    ends in — attempt 1 sent, and mangled on the way — and only the bound's resend is
    delivered (owner's review 2026-09-03)."""

    MERGED_ALREADY_DELIVERED = "the replay consumed it; feeding it again would double-count the ledger"

    def survived(self) -> Replay:
        rp = Replay(lcs.BAD_FRAME_LEDGER)
        rp.run()
        self.assertIsNone(rp.collector.epoch_end)
        return rp

    def test_a_byte_identical_resend_after_the_bound_is_accepted_once_and_acknowledged(self):
        rp = self.survived()
        line = rec_line(145)
        board = rx.RecBoard(TOKEN, 145, line)
        first = board.start()                    # attempt 1: the transmission the console mangled
        self.assertEqual(first, [line])
        self.assertEqual(rp.timeline.bad_frames, 1, self.MERGED_ALREADY_DELIVERED)
        self.assertIsNone(rp.collector.epoch_end)
        self.assertEqual(board.state, "WAIT_ACK")
        resend = board.tick(rx.BOARD_ACK_LIMIT_S + 0.5)            # the bound: the same bytes again
        self.assertEqual(resend, [line]); self.assertEqual(board.attempts, 2)
        rp.feed(line, dt=rx.BOARD_ACK_LIMIT_S + 0.5)
        self.assertEqual(rp.collector.last_rec_seq, 145); self.assertEqual(len(rp.collector.loop_records), 145)
        self.assertEqual(rp.collector.loop_records[-1]["seq"], 145)
        ack = [l for l in rp.sent if n.parse_line(l)["type"] == rx.T_RECACK and n.parse_line(l)["seq"] == 145]
        self.assertEqual(len(ack), 1)
        led = rp.cs.rec_ledgers[145].to_json()
        self.assertEqual([a["outcome"] for a in led["attempts"]], ["ok"]); self.assertEqual((led["gets_sent"], led["acks_sent"]), (0, 1))
        self.assertTrue(led["accepted"]); self.assertFalse(led["conflict"])
        for reply in ack:
            board.on_host_line(reply)
        self.assertEqual(board.finish(), {"acked": True, "attempts": 2, "next_candidate": True, "epoch": "RUNNING", "why": ""})
        self.assertIsNone(rp.collector.epoch_end); self.assertIsNone(rp.cs.pending_rec_seq)
        # the next candidate proceeds normally
        rp.feed(n.build_line(n.T_SIGNREQ, 146, TOKEN, n.encode_payload(
            {"seq": 146, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0,
             "schema": "sign_request", "schema_version": "1.0.0"})))
        self.assertIsNone(rp.collector.epoch_end); self.assertEqual(rp.relay.last_seq, 146)

    def test_a_second_identical_resend_is_re_acknowledged_never_appended(self):
        rp = self.survived()
        line = rec_line(145)
        rp.feed(line, dt=rx.BOARD_ACK_LIMIT_S + 0.5)               # the bound's resend
        rp.feed(line, dt=rx.BOARD_ACK_LIMIT_S + 0.5)               # our RECACK was lost: the same bytes again
        self.assertEqual(len(rp.collector.loop_records), 145)
        led = rp.cs.rec_ledgers[145].to_json()
        self.assertEqual([a["outcome"] for a in led["attempts"]], ["ok", "duplicate"]); self.assertEqual(led["acks_sent"], 2)
        self.assertIsNone(rp.collector.epoch_end)

    def test_no_resend_is_the_collectors_silence_end_not_a_silent_continuation(self):
        rp = self.survived()
        rp.now["t"] += 3 * 10 + 1                                  # 3 heartbeat intervals with nothing from the board
        rp.collector.poll()
        self.assertEqual(rp.collector.epoch_end["kind"], "CRASHED"); self.assertIn("silence", rp.collector.epoch_end["reason"])
        self.assertEqual(rp.collector.last_rec_seq, 144)

    def test_a_wrong_resend_another_seq_is_protocol_rec(self):
        rp = self.survived()
        rp.feed(rec_line(146), dt=rx.BOARD_ACK_LIMIT_S + 0.5)     # the board advanced without an acknowledgement
        self.assertEqual(rp.collector.epoch_end["kind"], "PROTOCOL"); self.assertIn("PROTOCOL_REC", rp.collector.epoch_end["reason"])
        self.assertEqual(len(rp.collector.loop_records), 144)

    def test_a_conflicting_resend_same_seq_other_bytes_is_protocol_rec(self):
        rp = self.survived()
        line = rec_line(145)
        rp.feed(line, dt=rx.BOARD_ACK_LIMIT_S + 0.5)
        other = copy.deepcopy(RUN_LOG["loop_records"][143]); other["seq"] = 145; other["arm"] = "random_safe"
        rp.feed(n.build_line(n.T_REC, 145, TOKEN, n.encode_payload(other)), dt=0.5)
        self.assertEqual(rp.collector.epoch_end["kind"], "PROTOCOL"); self.assertIn("different content", rp.collector.epoch_end["reason"])
        self.assertTrue(rp.cs.rec_ledgers[145].to_json()["conflict"]); self.assertEqual(len(rp.collector.loop_records), 145)

    def test_the_malformed_line_again_and_again_is_bounded_by_the_budget(self):
        """Here the line IS delivered again, deliberately: the question is what a repeated
        malformed line costs, not what S #2's single one did."""
        rp = Replay(lcs.BAD_FRAME_LEDGER, bad_frame_budget=3)
        rp.run()                                                   # bad_frames 1 (the recorded one)
        rp.feed(MERGED); rp.feed(MERGED)                           # 3 = the budget: still open
        self.assertEqual(rp.timeline.bad_frames, 3); self.assertIsNone(rp.collector.epoch_end)
        rp.feed(MERGED)                                            # the first past the budget ends the epoch
        self.assertEqual(rp.timeline.bad_frames, 4)
        self.assertEqual(rp.collector.epoch_end, {"kind": "PROTOCOL", "last_seq": 144, "reason": "PROTOCOL_BAD_FRAME_BUDGET: 4 > 3"})
        self.assertEqual(sum(1 for f in rp.timeline.frames if f["type"] == "BAD_FRAME"), 4, "every one in the ledger, once")

    def test_the_ledger_policy_refuses_to_run_unbounded(self):
        with self.assertRaises(ValueError):
            lcs.ConsoleSession(TOKEN, n.Collector(TOKEN, 10), n.NotaryRelay(TOKEN, lambda r: SIGN_ANSWER, 8), lt.Timeline(),
                               set(), 8, send=lambda *a: None, protocol="rel-v4", bad_frame_policy=lcs.BAD_FRAME_LEDGER)
        with self.assertRaises(ValueError):
            lcs.ConsoleSession(TOKEN, n.Collector(TOKEN, 10), n.NotaryRelay(TOKEN, lambda r: SIGN_ANSWER, 8), lt.Timeline(),
                               set(), 8, send=lambda *a: None, protocol="rel-v4", bad_frame_policy="lenient")

    def test_a_malformed_line_does_not_refresh_liveness_or_sign_or_advance(self):
        """A unit check of the policy itself: the line is delivered again on purpose."""
        rp = self.survived()
        heard, seq, signed = rp.collector.last_heard, rp.relay.last_seq, len(rp.relay.entries)
        rp.feed(MERGED)
        self.assertEqual((rp.collector.last_heard, rp.relay.last_seq, len(rp.relay.entries)), (heard, seq, signed))
        self.assertEqual([t for t in rp.sent_types()[-1:]], rp.sent_types()[-1:])   # nothing new was sent
        self.assertEqual(len(rp.sent), 144 + 1 + 145 + 1 + 88 + 11 + 1, "IDENTACK, SIGNOK×145, SIGNGET, AUDITGET×88, AUDITDONE×11, RECACK×144, RECGET")


if __name__ == "__main__":
    unittest.main()


class BadFrameBudgetIsGlobal(unittest.TestCase):
    """Owner's review 2026-09-03, blocker 1: the bound sat AFTER the transaction routing, so
    a malformed line whose head still read `REC`/`IDENT`/`SIGNREQ`/`TERM`, or that arrived
    inside an open pull, returned before it — with `bad_frame_budget=0` the epoch stayed
    open and a `RECGET` still went out. The bound is now global and immediate: past it the
    epoch ends `PROTOCOL_BAD_FRAME_BUDGET`, no transaction advances and nothing is sent."""

    def session(self, budget: int, pending: bool = True, pull: bool = False):
        import l6_rel as rel
        import l6_timing as lt2
        now = {"t": 500.0}
        clock = lambda: now["t"]  # noqa: E731
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=clock)
        relay = n.NotaryRelay(TOKEN, lambda req: dict(SIGN_ANSWER), drop_budget=99, clock=clock)
        tl = lt2.Timeline(); sent: list[str] = []
        cs = lcs.ConsoleSession(TOKEN, collector, relay, tl, {1}, 99,
                                send=lambda line, mtype, seq: sent.append(line), clock=clock,
                                protocol="rel-v4", identity_check=lambda ident: [],
                                bad_frame_policy=lcs.BAD_FRAME_LEDGER, bad_frame_budget=budget)

        def feed(line: str) -> None:
            now["t"] += 0.01
            cs.on_line(line.rstrip("\n"), now["t"], now["t"])

        ident = n.build_line(n.T_IDENT, 0, TOKEN, n.encode_payload(
            {"schema": "app_identity", "schema_version": "1.3.0", "control_plane": "standalone", "token": TOKEN,
             "protocol": "rel-v4", "master_seed": 7, "schedule_mode": "abba", "operator_data_sha256": "0" * 64,
             "rec_retry_control": True, "sign_retry_control": True, "pss_idcode": "0x13722093", "uboot_epoch": 0,
             "carrier_sha256": "1" * 64, "nonce_at_start": "2" * 16, "findings": [], "app_epoch": 0,
             "status_at_start": "0x0"}))
        feed(ident)
        if pending:
            feed(n.build_line(n.T_SIGNREQ, 1, TOKEN, n.encode_payload(
                {"seq": 1, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0,
                 "schema": "sign_request", "schema_version": "1.0.0"})))
        if pull:
            board = __import__("l6_rel").ReadyBoard(TOKEN, 1, "streams+readback", [0] * 2814, requested=True)
            feed(board.start()[0])
        del rel
        return cs, collector, sent, feed

    @staticmethod
    def malformed(mtype: str, seq: int) -> str:
        """A line whose head still reads <mtype> <seq> but that is not a frame (5 fields)."""
        return f"{n.MAGIC} {mtype} {seq} {TOKEN} eyJhIjoxfQ=="

    def test_every_shape_is_bounded_by_the_same_global_budget(self):
        shapes = {"REC": self.malformed(n.T_REC, 1),
                  "IDENT": self.malformed(n.T_IDENT, 0),
                  "SIGNREQ": self.malformed(n.T_SIGNREQ, 1),
                  "TERM": self.malformed(n.T_TERM, 2),
                  "non-transaction": MERGED.rstrip("\n")}
        for name, line in shapes.items():
            with self.subTest(shape=name):
                cs, collector, sent, feed = self.session(budget=0)
                before = len(sent)
                feed(line)
                self.assertEqual(cs.timeline.bad_frames, 1, name)
                self.assertEqual(collector.epoch_end,
                                 {"kind": "PROTOCOL", "last_seq": 0, "reason": "PROTOCOL_BAD_FRAME_BUDGET: 1 > 0"}, name)
                self.assertEqual(len(sent), before, f"{name}: nothing may be sent past the bound")

    def test_a_malformed_line_inside_an_open_pull_is_bounded_too(self):
        cs, collector, sent, feed = self.session(budget=0, pull=True)
        gets_before = sum(1 for l in sent if n.parse_line(l)["type"] == "AUDITGET")
        feed(self.malformed(n.T_AUDIT, 1))
        self.assertEqual(cs.timeline.bad_frames, 1)
        self.assertEqual(collector.epoch_end["reason"], "PROTOCOL_BAD_FRAME_BUDGET: 1 > 0")
        after = [n.parse_line(l)["type"] for l in sent]
        self.assertEqual(sum(1 for tp in after if tp == "AUDITGET"), gets_before, "no AUDITGET retry past the bound")
        self.assertEqual(after[-1], "AUDITABORT", "the board is told the pull is over, exactly once")
        self.assertEqual(sum(1 for tp in after if tp == "AUDITABORT"), 1)
        led = cs.pull_ledgers[-1]
        self.assertTrue(led["failed"]); self.assertEqual(led["why"], "PROTOCOL_BAD_FRAME_BUDGET: 1 > 0",
                                                         "the pull's reason is the global one, not its own retry exhaustion")
        self.assertTrue(any(a["outcome"] != "ok" for a in led["attempts"]), "the attempt is kept in the pull ledger")

    def test_within_the_budget_each_shape_still_recovers_as_before(self):
        cs, collector, sent, feed = self.session(budget=8)
        feed(self.malformed(n.T_REC, 1))
        self.assertIsNone(collector.epoch_end)
        self.assertEqual([n.parse_line(l)["type"] for l in sent][-1:], [rx.T_RECGET], "the REC transaction still asks again")
        self.assertEqual(cs.timeline.bad_frames, 1)

    def test_the_ledger_keeps_the_line_that_crossed_the_bound(self):
        cs, collector, sent, feed = self.session(budget=1)
        feed(self.malformed(n.T_REC, 1))           # 1 = the budget: still open, still a retry
        self.assertIsNone(collector.epoch_end)
        feed(MERGED.rstrip("\n"))                  # 2 > 1: over
        self.assertEqual(collector.epoch_end["reason"], "PROTOCOL_BAD_FRAME_BUDGET: 2 > 1")
        self.assertEqual(cs.timeline.bad_frames, 2)
        self.assertEqual(sum(1 for f in cs.timeline.frames if f["type"] == "BAD_FRAME"), 2,
                         "both lines are in the one inbound ledger, once each")

    def test_a_budget_that_is_not_a_whole_non_negative_number_is_refused(self):
        for bad in (None, "8", 3.0, True, False, -1):
            with self.subTest(budget=bad), self.assertRaises(ValueError):
                lcs.ConsoleSession(TOKEN, n.Collector(TOKEN, 10), n.NotaryRelay(TOKEN, lambda r: SIGN_ANSWER, 8),
                                   __import__("l6_timing").Timeline(), set(), 8, send=lambda *a: None,
                                   protocol="rel-v4", bad_frame_policy=lcs.BAD_FRAME_LEDGER, bad_frame_budget=bad)
        lcs.ConsoleSession(TOKEN, n.Collector(TOKEN, 10), n.NotaryRelay(TOKEN, lambda r: SIGN_ANSWER, 8),
                           __import__("l6_timing").Timeline(), set(), 8, send=lambda *a: None,
                           protocol="rel-v4", bad_frame_policy=lcs.BAD_FRAME_LEDGER, bad_frame_budget=0)

    def test_under_v06_the_crash_rule_is_untouched_by_all_of_this(self):
        cs, collector, sent, feed = self.session(budget=0)
        self.assertEqual(cs.bad_frame_policy, lcs.BAD_FRAME_LEDGER)
        cs.bad_frame_policy, cs.bad_frame_budget = lcs.BAD_FRAME_CRASH, None
        feed(self.malformed(n.T_REC, 1))
        self.assertIsNone(collector.epoch_end, "v0.6: a REC-shaped malformed line is the transaction's, unbounded")
        feed(MERGED.rstrip("\n"))
        self.assertEqual(collector.epoch_end["kind"], "CRASHED")


class BadFrameBoundAndPullExhaustionCollide(unittest.TestCase):
    """The line that is BOTH the pull's last allowed attempt and the one past the global
    bad-frame bound (owner's review 2026-09-03): the terminal reason must be the global one,
    all three attempts stay in the ledger, no fourth AUDITGET goes out, and exactly one
    AUDITABORT does — carrying that global reason. The first attempt at this silenced the
    puller's sender, so when the pull failed itself inside the silence its ABORT never went
    out at all (`AUDITABORT: 0`)."""

    def setUp(self):
        import l6_audit_pull as ap
        import l6_rel as rel
        import l6_timing as lt2
        self.ap = ap
        self.now = {"t": 700.0}
        clock = lambda: self.now["t"]  # noqa: E731
        self.collector = n.Collector(TOKEN, heartbeat_s=10, clock=clock)
        relay = n.NotaryRelay(TOKEN, lambda req: dict(SIGN_ANSWER), drop_budget=99, clock=clock)
        self.tl = lt2.Timeline(); self.sent: list[str] = []
        self.cs = lcs.ConsoleSession(TOKEN, self.collector, relay, self.tl, {1}, 99,
                                     send=lambda line, mtype, seq: self.sent.append(line), clock=clock,
                                     protocol="rel-v4", identity_check=lambda ident: [],
                                     bad_frame_policy=lcs.BAD_FRAME_LEDGER, bad_frame_budget=2)
        self.feed(n.build_line(n.T_IDENT, 0, TOKEN, n.encode_payload(
            {"schema": "app_identity", "schema_version": "1.3.0", "control_plane": "standalone", "token": TOKEN,
             "protocol": "rel-v4", "master_seed": 7, "schedule_mode": "abba", "operator_data_sha256": "0" * 64,
             "rec_retry_control": True, "sign_retry_control": True, "pss_idcode": "0x13722093", "uboot_epoch": 0,
             "carrier_sha256": "1" * 64, "nonce_at_start": "2" * 16, "findings": [], "app_epoch": 0,
             "status_at_start": "0x0"})))
        self.feed(n.build_line(n.T_SIGNREQ, 1, TOKEN, n.encode_payload(
            {"seq": 1, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0,
             "schema": "sign_request", "schema_version": "1.0.0"})))
        board = rel.ReadyBoard(TOKEN, 1, "streams+readback", [0] * 2814, requested=True)
        self.feed(board.start()[0])                       # the pull is open, chunk 0 requested

    def feed(self, line: str) -> None:
        self.now["t"] += 0.01
        self.cs.on_line(line.rstrip("\n"), self.now["t"], self.now["t"])

    def types(self) -> list[str]:
        return [n.parse_line(l)["type"] for l in self.sent]

    def test_the_global_reason_wins_and_exactly_one_abort_goes_out(self):
        bad = f"{n.MAGIC} {n.T_AUDIT} 1 {TOKEN} eyJjaHVuayI6MH0="        # AUDIT-shaped, 5 fields: malformed
        gets_at_start = self.types().count(self.ap.T_GET)
        self.feed(bad)                                    # attempt 0 fails, the pull asks again
        self.assertIsNone(self.collector.epoch_end); self.assertEqual(self.tl.bad_frames, 1)
        self.feed(bad)                                    # attempt 1 fails, the pull asks again
        self.assertIsNone(self.collector.epoch_end); self.assertEqual(self.tl.bad_frames, 2)
        gets_before_last = self.types().count(self.ap.T_GET)
        self.assertEqual(gets_before_last, gets_at_start + 2, "two retries so far")

        self.feed(bad)                                    # 3 > 2 AND the pull's third failure
        self.assertEqual(self.tl.bad_frames, 3)
        self.assertEqual(self.collector.epoch_end,
                         {"kind": "PROTOCOL", "last_seq": 0, "reason": "PROTOCOL_BAD_FRAME_BUDGET: 3 > 2"},
                         "the GLOBAL reason wins over the pull's own retry exhaustion")
        self.assertEqual(self.types().count(self.ap.T_GET), gets_before_last, "no fourth AUDITGET")
        aborts = [l for l in self.sent if n.parse_line(l)["type"] == self.ap.T_ABORT]
        self.assertEqual(len(aborts), 1, "exactly one AUDITABORT — not zero, not two")
        self.assertEqual(n.decode_payload(n.parse_line(aborts[0])["payload"]),
                         {"seq": 1, "why": "PROTOCOL_BAD_FRAME_BUDGET: 3 > 2"},
                         "and it carries the global reason, not the pull's retry exhaustion")

        led = self.cs.pull_ledgers[-1]
        self.assertEqual([(a["chunk"], a["attempt"], a["outcome"]) for a in led["attempts"]],
                         [(0, 0, "malformed"), (0, 1, "malformed"), (0, 2, "malformed")],
                         "all three attempts stay in the ledger, numbered")
        self.assertEqual(len(led["lines_kept"]), 3, "each failing line kept verbatim")
        self.assertTrue(led["failed"]); self.assertEqual(led["why"], "PROTOCOL_BAD_FRAME_BUDGET: 3 > 2")
        self.assertEqual(sum(1 for f in self.tl.frames if f["type"] == "BAD_FRAME"), 3)

    def test_a_pull_that_is_only_over_the_bound_still_aborts_once(self):
        """The non-collision case: the bound is crossed on the pull's FIRST failure."""
        self.cs.bad_frame_budget = 0
        bad = f"{n.MAGIC} {n.T_AUDIT} 1 {TOKEN} eyJjaHVuayI6MH0="
        self.feed(bad)
        self.assertEqual(self.collector.epoch_end["reason"], "PROTOCOL_BAD_FRAME_BUDGET: 1 > 0")
        aborts = [l for l in self.sent if n.parse_line(l)["type"] == self.ap.T_ABORT]
        self.assertEqual(len(aborts), 1)
        led = self.cs.pull_ledgers[-1]
        self.assertEqual([(a["attempt"], a["outcome"]) for a in led["attempts"]], [(0, "malformed")])
