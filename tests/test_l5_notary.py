"""The T1 notary channel protocol layer (D1 spec §5b): framing, relay, collector.

No transport: lines go straight between builder and handler. The signer is a stub — the
real signer's genome path has its own tests (test_sign_genome)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import records  # noqa: E402
import l5_notary as n  # noqa: E402

TOKEN = "ab" * 16
OTHER = "cd" * 16


def stub_signer(req):
    if req["genome"].startswith("ff"):
        return {"refused": {"finding_kinds": ["whitelist"]}}
    return {"commit": "0c" * 32, "expected_tables": [f"{i:016x}" for i in range(6)], "tag": "0d" * 16}


def signreq(seq, genome="11" * 40, nonce="9e3779b97f4a7c15", token=TOKEN):
    payload = n.encode_payload({"token": token, "app_epoch": 0, "seq": seq,
                                "genome": genome, "nonce": nonce})
    return n.build_line(n.T_SIGNREQ, seq, token, payload)


class Framing(unittest.TestCase):
    def test_round_trip(self):
        line = n.build_line("HB", 7, TOKEN, n.encode_payload({"x": 1}))
        f = n.parse_line(line)
        self.assertEqual((f["type"], f["seq"], f["token"]), ("HB", 7, TOKEN))
        self.assertEqual(n.decode_payload(f["payload"]), {"x": 1})

    def test_crc_corruption_is_a_crc_error(self):
        line = n.build_line("HB", 7, TOKEN)
        with self.assertRaises(n.CrcError):
            n.parse_line(line.replace("HB", "hb", 1))

    def test_truncated_token_is_a_frame_error(self):
        body = f"{n.MAGIC} HB 1 {'ab' * 4} -"
        import zlib
        line = f"{body} {zlib.crc32(body.encode()) & 0xFFFFFFFF:08x}\n"
        with self.assertRaises(n.FrameError) as cm:
            n.parse_line(line)
        self.assertIn("128-bit", str(cm.exception))


class Relay(unittest.TestCase):
    def setUp(self):
        self.relay = n.NotaryRelay(TOKEN, stub_signer, drop_budget=2, clock=lambda: 0.0)

    def test_sign_and_log(self):
        reply = self.relay.handle_line(signreq(1))
        f = n.parse_line(reply)
        self.assertEqual(f["type"], n.T_SIGNOK)
        ans = n.decode_payload(f["payload"])
        self.assertEqual(ans["schema"], "sign_reply")
        log = self.relay.notary_log()
        records.validate(log)
        self.assertEqual(len(log["entries"]), 1)

    def test_gate_refusal_continues_the_session(self):
        reply = self.relay.handle_line(signreq(1, genome="ff" * 40))
        self.assertEqual(n.parse_line(reply)["type"], n.T_SIGNREF)
        reply2 = self.relay.handle_line(signreq(2))          # still alive
        self.assertEqual(n.parse_line(reply2)["type"], n.T_SIGNOK)
        records.validate(self.relay.notary_log())

    def test_seq_gap_is_a_protocol_end(self):
        self.relay.handle_line(signreq(1))
        with self.assertRaises(n.ProtocolEnd) as cm:
            self.relay.handle_line(signreq(3))
        self.assertIn("PROTOCOL_SEQ", str(cm.exception))
        with self.assertRaises(n.ProtocolEnd):
            self.relay.handle_line(signreq(2))               # ended stays ended

    def test_foreign_token_is_a_protocol_end(self):
        with self.assertRaises(n.ProtocolEnd) as cm:
            self.relay.handle_line(signreq(1, token=OTHER))
        self.assertIn("PROTOCOL_TOKEN", str(cm.exception))

    def test_crc_drops_count_and_budget_ends_the_epoch(self):
        bad = signreq(1).replace("SIGNREQ", "SIGNREZ", 1)
        self.assertIsNone(self.relay.handle_line(bad))
        self.assertIsNone(self.relay.handle_line(bad))
        self.assertEqual(self.relay.crc_dropped, 2)
        with self.assertRaises(n.ProtocolEnd) as cm:
            self.relay.handle_line(bad)
        self.assertIn("PROTOCOL_CRC_BUDGET", str(cm.exception))

    def test_non_signreq_lines_are_not_the_relays_business(self):
        self.assertIsNone(self.relay.handle_line(n.build_line(n.T_HB, 1, TOKEN)))
        self.assertEqual(self.relay.last_seq, 0)


class CollectorRules(unittest.TestCase):
    def setUp(self):
        self.t = 0.0
        self.col = n.Collector(TOKEN, heartbeat_s=10.0, clock=lambda: self.t)

    def rec(self, seq):
        return n.build_line(n.T_REC, seq, TOKEN, n.encode_payload({"seq": seq, "outcome": "SCORED"}))

    def test_records_collect_in_order(self):
        self.col.on_line(self.rec(1)); self.col.on_line(self.rec(2))
        self.assertEqual([r["seq"] for r in self.col.loop_records], [1, 2])
        self.assertIsNone(self.col.epoch_end)

    def test_silence_past_three_heartbeats_is_crashed(self):
        self.col.on_line(self.rec(1))
        self.assertIsNone(self.col.poll(now=29.0))
        end = self.col.poll(now=31.0)
        self.assertEqual(end["kind"], "CRASHED")
        summary = self.col.crashed_summary(drop_budget=8)
        records.validate(summary)
        self.assertEqual(summary["written_by"], "collector")

    def test_banner_is_crashed_unless_terminal_arrived(self):
        self.col.on_line(self.rec(1))
        self.col.on_banner()
        self.assertEqual(self.col.epoch_end["kind"], "CRASHED")

    def test_terminal_line_wins_over_a_later_banner(self):
        term = {"epoch_end": {"kind": "COMPLETED", "reason": "budget", "last_seq": 1}}
        self.col.on_line(n.build_line(n.T_TERM, 2, TOKEN, n.encode_payload(term)))
        self.col.on_banner()
        self.assertEqual(self.col.epoch_end["kind"], "COMPLETED")

    def test_seq_gap_is_crashed(self):
        self.col.on_line(self.rec(1)); self.col.on_line(self.rec(3))
        self.assertEqual(self.col.epoch_end["kind"], "CRASHED")
        self.assertIn("seq gap", self.col.epoch_end["reason"])

    def test_foreign_token_is_crashed_and_nothing_after_counts(self):
        line = n.build_line(n.T_REC, 1, OTHER, n.encode_payload({"seq": 1}))
        self.col.on_line(line)
        self.assertEqual(self.col.epoch_end["kind"], "CRASHED")
        self.col.on_line(self.rec(1))
        self.assertEqual(self.col.loop_records, [])


if __name__ == "__main__":
    unittest.main()
