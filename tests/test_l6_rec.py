"""host/l6_rec.py — the REC transaction (rec-v3) as a WIRE state machine, both ends
building and parsing real P3L5 lines over a faulty channel.

Real records: S #1's console (evidence/l6_17A6_2026-09-01-11-S, read-only) — REC 464 as
the record, and REC 465 exactly as it arrived (1775 bytes, ~536 missing) as the shape of
the loss. Every requirement of the owner's batch is a test: closure of token/seq/current
candidate; idempotent duplicates and never two accepted records; bounded retry for a
lost/broken REC, a lost RECACK and a lost RECGET; exhaustion stops the next candidate and
never counts a missing REC as success; every attempt in the ledger with the raw line;
content is the validator's and a retry cannot wash it out; the forced control corrupts
exactly attempt 1 of seq 1 and is recovered by one RECGET."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_rec as rx  # noqa: E402

S1 = R / "evidence/l6_17A6_2026-09-01-11-S"
LOG = json.loads((S1 / "run_log.json").read_text())
TOKEN = LOG["app_identity"]["token"]
CONSOLE = (S1 / "console.log").read_bytes().split(b"\n")
REC464 = next(l for l in CONSOLE if l.startswith(b"P3L5 REC 464 ")).decode() + "\n"
REC465_BROKEN = next(l for l in CONSOLE if l.startswith(b"P3L5 REC 465 ")).decode() + "\n"
REC466 = next(l for l in CONSOLE if l.startswith(b"P3L5 REC 466 ")).decode() + "\n"


def rec_line(seq: int, payload: dict) -> str:
    return n.build_line(n.T_REC, seq, TOKEN, n.encode_payload(payload))


def run(faults=(), seq=464, line=REC464, corrupt_first=False):
    board = rx.RecBoard(TOKEN, seq, line, corrupt_first=corrupt_first)
    sim = rx.Simulation(board, faults=list(faults))
    return sim, sim.run()


class Clean(unittest.TestCase):
    def test_a_clean_record_is_accepted_once_and_acknowledged(self):
        sim, res = run()
        self.assertTrue(res["host_accepted"]); self.assertIsNone(res["protocol_end"])
        self.assertEqual(res["board"], {"acked": True, "attempts": 1, "next_candidate": True, "epoch": "RUNNING", "why": ""})
        self.assertEqual([n.parse_line(l)["type"] for l in sim.host_sent], [rx.T_RECACK])
        self.assertEqual(len(res["records"]), 1); self.assertEqual(res["records"][0]["seq"], 464)
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["ok"])

    def test_the_s1_loss_shape_is_recovered_by_one_recget(self):
        """REC 465 as it arrived on 2026-09-01 (1775 of ~2311 bytes) fails CRC; the host asks
        for it again; the board's second transmission is byte-identical to its first."""
        self.assertNotEqual(len(REC465_BROKEN), len(REC466))
        with self.assertRaises(n.CrcError):
            n.parse_line(REC465_BROKEN)
        L = len(REC464)
        sim, res = run([rx.Fault("b2h", n.T_REC, 0, "delete", L // 3, 536)])
        self.assertTrue(res["host_accepted"])
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["crc", "ok"])
        self.assertEqual(res["ledger"].gets_sent, 1); self.assertEqual(res["board"]["attempts"], 2)
        self.assertEqual(sim.delivered_b2h[1], REC464, "the resend is the same bytes")
        self.assertEqual(len(res["ledger"].lines_kept), 1, "the broken line is kept verbatim")
        self.assertEqual(len(res["records"]), 1)


class Closure(unittest.TestCase):
    def test_a_rec_for_another_seq_is_a_protocol_end_not_a_record(self):
        """The board may not advance without an acknowledgement: REC 466 while 465 is the
        current candidate is channel misbehaviour, and nothing is accepted."""
        delivered, sent = [], []
        host = rx.RecHost(TOKEN, 465, send=sent.append, deliver=delivered.append)
        host.on_line(REC466)
        self.assertIn("advanced without an acknowledgement", host.protocol_end)
        self.assertEqual(delivered, []); self.assertEqual(sent, [])

    def test_the_board_answers_only_its_own_seq_and_token(self):
        board = rx.RecBoard(TOKEN, 464, REC464)
        board.start()
        for stale in (n.build_line(rx.T_RECACK, 463, TOKEN, n.encode_payload({"seq": 463})),
                      n.build_line(rx.T_RECACK, 464, "cd" * 16, n.encode_payload({"seq": 464})),
                      n.build_line(rx.T_RECACK, 464, TOKEN, n.encode_payload({"seq": 463})),
                      n.build_line(n.T_HB, 464, TOKEN),
                      "P3L5 RECACK 464 " + TOKEN + " abc def 00000000"):
            self.assertEqual(board.on_host_line(stale), [])
            self.assertEqual(board.state, "WAIT_ACK", stale[:30])
        board.on_host_line(n.build_line(rx.T_RECACK, 464, TOKEN, n.encode_payload({"seq": 464})))
        self.assertEqual(board.state, "DONE")

    def test_a_broken_line_of_another_type_or_seq_does_not_trigger_a_recget(self):
        sent = []
        host = rx.RecHost(TOKEN, 464, send=sent.append, deliver=lambda r: None)
        hb = n.build_line(n.T_HB, 464, TOKEN)
        host.on_line(hb[:-3] + "0\n")                       # a broken HB
        host.on_line(REC466[:-3] + "0\n")                   # a broken REC for another seq
        self.assertEqual(sent, [])
        self.assertEqual(host.ledger.attempts, [])


class Idempotence(unittest.TestCase):
    def test_a_lost_ack_is_recovered_and_the_record_is_accepted_exactly_once(self):
        sim, res = run([rx.Fault("h2b", rx.T_RECACK, 0, "drop")])
        self.assertTrue(res["host_accepted"]); self.assertEqual(res["board"]["attempts"], 2)
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["ok", "duplicate"])
        self.assertEqual(res["ledger"].acks_sent, 2)
        self.assertEqual(len(res["records"]), 1, "never two accepted records")

    def test_a_duplicate_ack_is_harmless(self):
        sim, res = run([rx.Fault("h2b", rx.T_RECACK, 0, "dup")])
        self.assertTrue(res["board"]["acked"]); self.assertEqual(len(res["records"]), 1)

    def test_a_duplicated_rec_is_re_acknowledged_not_re_accepted(self):
        sim, res = run([rx.Fault("b2h", n.T_REC, 0, "dup")])
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["ok", "duplicate"])
        self.assertEqual(len(res["records"]), 1); self.assertTrue(res["board"]["acked"])

    def test_a_second_record_for_the_accepted_seq_with_other_content_is_a_protocol_end(self):
        """Never a second accepted record and never a 'newer' one: same seq, different
        bytes → the epoch ends PROTOCOL and the first record stands as accepted."""
        delivered, sent = [], []
        host = rx.RecHost(TOKEN, 464, send=sent.append, deliver=delivered.append)
        host.on_line(REC464)
        other = REC466.replace(" 466 ", " 464 ")           # a valid frame for seq 464 …
        body, _ = other.rstrip("\n").rsplit(" ", 1)
        import zlib
        other = f"{body} {zlib.crc32(body.encode()) & 0xFFFFFFFF:08x}\n"   # … with a correct CRC
        host.on_line(other)
        self.assertIn("different content", host.protocol_end)
        self.assertTrue(host.ledger.conflict)
        self.assertEqual(len(delivered), 1, "the first record stands; the second is not accepted")
        self.assertEqual([n.parse_line(l)["type"] for l in sent], [rx.T_RECACK])


class BoundedRetry(unittest.TestCase):
    def test_a_rec_lost_entirely_is_resent_after_the_boards_bound(self):
        sim, res = run([rx.Fault("b2h", n.T_REC, 0, "drop")])
        self.assertTrue(res["host_accepted"]); self.assertEqual(res["board"]["attempts"], 2)
        self.assertEqual(res["ledger"].gets_sent, 0, "nothing arrived, so nothing was asked for")
        self.assertGreater(res["seconds"], rx.BOARD_ACK_LIMIT_S)

    def test_a_lost_recget_is_covered_by_the_boards_bound(self):
        L = len(REC464)
        sim, res = run([rx.Fault("b2h", n.T_REC, 0, "delete", 100, 300), rx.Fault("h2b", rx.T_RECGET, 0, "drop")])
        self.assertTrue(res["host_accepted"]); self.assertEqual(res["board"]["attempts"], 2)
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["crc", "ok"])

    def test_exhaustion_stops_the_board_and_leaves_no_record(self):
        """Three broken transmissions: the board ends STOP_REC (no next candidate), the host
        accepted nothing, and the missing record is the structural HOLD it always was —
        never a success."""
        faults = [rx.Fault("b2h", n.T_REC, k, "delete", 100, 300) for k in range(rx.REC_MAX_ATTEMPTS)]
        sim, res = run(faults)
        self.assertFalse(res["host_accepted"])
        self.assertEqual(res["board"]["attempts"], rx.REC_MAX_ATTEMPTS)
        self.assertEqual(res["board"]["next_candidate"], False); self.assertEqual(res["board"]["epoch"], "STOPPED")
        self.assertIn("STOP_REC", res["board"]["why"])
        self.assertEqual(res["records"], [])
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["crc"] * 3)
        self.assertEqual(res["ledger"].gets_sent, rx.REC_HOST_MAX_GETS, "the host's asks are bounded too")
        self.assertEqual(len(res["ledger"].lines_kept), 3)

    def test_the_board_never_waits_unboundedly(self):
        board = rx.RecBoard(TOKEN, 464, REC464)
        board.start()
        total = 0
        while board.state == "WAIT_ACK":
            board.tick(rx.BOARD_ACK_LIMIT_S + 0.1); total += 1
        self.assertEqual(board.state, "EXHAUSTED"); self.assertEqual(board.attempts, rx.REC_MAX_ATTEMPTS)
        self.assertEqual(total, rx.REC_MAX_ATTEMPTS)

    def test_a_malformed_rec_shaped_line_is_a_retry(self):
        """C1 #1's shape: a loss across the line boundary merges two lines — seven fields,
        FrameError. Its head still reads REC <seq>; the host asks again."""
        sent = []
        host = rx.RecHost(TOKEN, 464, send=sent.append, deliver=lambda r: None)
        host.on_line(REC464.rstrip("\n") + " extra-field\n")
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["malformed"])
        self.assertEqual([n.parse_line(l)["type"] for l in sent], [rx.T_RECGET])


class Content(unittest.TestCase):
    def test_a_valid_but_wrong_record_is_accepted_once_for_the_validator_and_never_retried(self):
        """Content is not the transport's business: a CRC-valid record whose nonce did not
        step is accepted (ACK), never asked for again, and it is the validator that
        refuses the log later — a retry cannot wash out a falsifier."""
        rec = n.decode_payload(n.parse_line(REC464)["payload"])
        rec["evidence"]["arm"]["nonce_after"] = rec["evidence"]["arm"]["nonce_before"]     # a broken chain
        sim, res = run(line=rec_line(464, rec))
        self.assertTrue(res["host_accepted"]); self.assertEqual(res["ledger"].gets_sent, 0)
        self.assertEqual(res["records"][0]["evidence"]["arm"]["nonce_after"], rec["evidence"]["arm"]["nonce_before"])
        from validators import records
        with self.assertRaises(records.RecordError):
            records.validate(res["records"][0])


def seq1_line() -> str:
    """REC 464's record re-framed as seq 1 (frame and payload), the opening baseline's slot."""
    rec = n.decode_payload(n.parse_line(REC464)["payload"])
    rec["seq"] = 1
    for part in rec["evidence"].values():
        if isinstance(part, dict) and "seq" in part:
            part["seq"] = 1
    return rec_line(1, rec)


class ForcedControl(unittest.TestCase):
    def test_the_control_corrupts_exactly_the_first_transmission_and_is_recovered_by_one_recget(self):
        sim, res = run(seq=1, line=seq1_line(), corrupt_first=True)
        first, second = sim.delivered_b2h[0], sim.delivered_b2h[1]
        with self.assertRaises(n.CrcError):
            n.parse_line(first)
        self.assertEqual(rx.head_fields(first), (n.T_REC, 1))
        self.assertEqual(second, sim.board.line, "the resend is the real line, byte for byte")
        self.assertEqual(first[:-2], second[:-2], "only the last CRC digit differs")
        self.assertTrue(res["host_accepted"])
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts], ["crc", "ok"])
        self.assertEqual(res["ledger"].gets_sent, 1); self.assertEqual(res["board"]["attempts"], 2)

    def test_the_control_touches_no_other_transmission(self):
        board = rx.RecBoard(TOKEN, 1, seq1_line(), corrupt_first=True)
        first, = board.start()
        second, = board.on_host_line(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1})))
        third, = board.on_host_line(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1})))
        self.assertNotEqual(first, board.line); self.assertEqual(second, board.line); self.assertEqual(third, board.line)

    def test_corrupt_crc_flips_one_hex_digit_and_keeps_the_shape(self):
        line = REC464
        bad = rx.corrupt_crc(line)
        self.assertEqual(len(bad), len(line)); self.assertEqual(bad.count(" "), line.count(" "))
        self.assertEqual(sum(1 for a, b in zip(bad, line) if a != b), 1)
        self.assertEqual(rx.corrupt_crc(rx.corrupt_crc("P3L5 HB 1 x - 00000000\n")), "P3L5 HB 1 x - 00000000\n")


if __name__ == "__main__":
    unittest.main()
