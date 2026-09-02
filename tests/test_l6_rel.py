"""rel-v4 — the reliability revision, host side and board twins (`host/l6_rel.py`), behind
the protocol switch (owner's ruling 2026-09-02):

  * every frame that was not re-requestable has a loss / duplication / truncation /
    exhaustion test: IDENT (handshake before the first SIGNREQ), SIGNREQ (transaction,
    cached reply, one signature per seq), AUDIT_READY (resent on the bound), AUDITDONE
    (AUDITWAIT → the same DONE replayed; exhaustion visible on both sides), TERM
    (transaction; a lost CLOSE reconstructed from it), HB (indexed, budgeted);
  * the ConsoleSession under rel-v4 wires all of it; under rec-v3 NOTHING changes — the
    same script yields the same frames as before and none of the new types;
  * the validator's STOP_SIGN contract and the orphan-notary-entry rule (vii-b);
  * the schedule and runner select rel-v4 by the pinned image's protocol.
Board→host bytes go through the real reader in every simulation (torn lines, resync)."""
from __future__ import annotations

import copy
import inspect
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "tests"))
import bitstream_frames  # noqa: E402,F401
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_checks as lc  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_rel as rel  # noqa: E402
import l6_schedule as ls  # noqa: E402
import l6_timing as lt  # noqa: E402
from validators import records  # noqa: E402

TOKEN = "5c" * 16
IDENT_PAYLOAD = {"schema": "app_identity", "schema_version": "1.2.0", "control_plane": "standalone", "token": TOKEN,
                 "protocol": "rel-v4", "master_seed": 7, "schedule_mode": "random_safe_forced",
                 "operator_data_sha256": "0" * 64, "rec_retry_control": True, "pss_idcode": "0x13722093",
                 "uboot_epoch": 0, "carrier_sha256": "1" * 64, "nonce_at_start": "2" * 16, "findings": [],
                 "app_epoch": 0, "status_at_start": "0x0"}
IDENT_LINE = n.build_line(n.T_IDENT, 0, TOKEN, n.encode_payload(IDENT_PAYLOAD))
COMMIT, TAG = "a" * 64, "b" * 32
TABLES = ["0" * 16] * 6


def signreq_line(seq: int, genome: str = "0" * 80) -> str:
    return n.build_line(n.T_SIGNREQ, seq, TOKEN, n.encode_payload(
        {"seq": seq, "token": TOKEN, "genome": genome, "nonce": "0" * 16, "app_epoch": 0,
         "schema": "sign_request", "schema_version": "1.0.0"}))


def term_line(seq: int = 3, with_closing: bool = True) -> str:
    p = {"schema": "session_summary", "schema_version": "1.0.0", "token": TOKEN,
         "epoch_end": {"kind": "COMPLETED", "last_seq": seq - 1, "reason": "budget"},
         "counts": {"scored": 2, "refused_by_gate": 0},
         "closing": {"restore": "done", "baseline": "done", "unsigned_control": "done"},
         "audit": {"audited": 2, "total": 2}, "crc_dropped": 0, "drop_budget": 8, "written_by": "app"}
    if with_closing:
        p["closing_control"] = {"fault": 13, "kind": "unsigned", "status": "0x00000982",
                                "nonce_before": "3" * 16, "nonce_after": "4" * 16}
    return n.build_line(n.T_TERM, seq, TOKEN, n.encode_payload(p))


def relay(signer=None):
    return n.NotaryRelay(TOKEN, signer or (lambda req: {"commit": COMMIT, "expected_tables": TABLES, "tag": TAG}),
                         drop_budget=8, clock=lambda: 0.0)


def verify_ok(ident):
    return [] if ident.get("token") == TOKEN and ident.get("protocol") == "rel-v4" else ["not this session's identity"]


def types(lines):
    return [n.parse_line(l)["type"] for l in lines]


# ------------------------------------------------------------------ IDENT


class IdentHandshake(unittest.TestCase):
    def run_ident(self, faults=(), verify=verify_ok):
        board = rel.IdentBoard(TOKEN, IDENT_LINE)
        sim = rel.Simulation(board, host_on_line=lambda ln: None, faults=faults)
        host = rel.IdentHost(TOKEN, verify, send=sim.send)
        sim.host_on_line = host.on_line
        res = sim.run()
        return board, host, sim, res

    def test_clean_handshake_one_ack_established(self):
        board, host, sim, res = self.run_ident()
        self.assertTrue(host.established); self.assertEqual(types(res["host_sent"]), [rel.T_IDENTACK])
        self.assertEqual(board.finish(), {"acked": True, "attempts": 1, "why": ""})
        self.assertEqual(host.identity["master_seed"], 7)

    def test_ident_lost_is_resent_on_the_bound(self):
        board, host, sim, res = self.run_ident([rel.Fault("b2h", n.T_IDENT, 0, "drop")])
        self.assertTrue(host.established); self.assertEqual(board.attempts, 2)

    def test_ack_lost_the_identical_repeat_is_re_acknowledged_once_more(self):
        board, host, sim, res = self.run_ident([rel.Fault("h2b", rel.T_IDENTACK, 0, "drop")])
        self.assertTrue(host.established); self.assertTrue(board.acked)
        self.assertEqual(host.ledger.acks_sent, 2); self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["ok", "duplicate"])

    def test_ident_torn_then_resent_the_reader_resyncs(self):
        board, host, sim, res = self.run_ident([rel.Fault("b2h", n.T_IDENT, 0, "truncate", offset=300)])
        self.assertTrue(host.established); self.assertEqual(board.attempts, 2)
        self.assertEqual(len(res["fragments"]), 1); self.assertTrue(res["fragments"][0]["reason"].startswith("resync"))

    def test_three_losses_exhaust_to_stop_ident_and_nothing_is_established(self):
        board, host, sim, res = self.run_ident([rel.Fault("b2h", n.T_IDENT, k, "drop") for k in range(3)])
        self.assertEqual(board.state, "EXHAUSTED"); self.assertIn(rel.STOP_IDENT, board.why)
        self.assertFalse(host.established); self.assertEqual(res["host_sent"], [])

    def test_an_identity_the_host_refuses_is_never_acknowledged_and_the_board_exhausts(self):
        board, host, sim, res = self.run_ident(verify=lambda ident: ["master_seed is not the page's"])
        self.assertFalse(host.established); self.assertEqual(res["host_sent"], [])
        self.assertTrue(host.refused); self.assertIsNone(host.protocol_end, "a refusal is not a channel fault: no host-side end")
        self.assertEqual(board.state, "EXHAUSTED"); self.assertIn(rel.STOP_IDENT, board.why)
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["refused", "refused-repeat", "refused-repeat"])

    def test_a_second_different_ident_is_a_conflict(self):
        host = rel.IdentHost(TOKEN, verify_ok, send=lambda l: None)
        host.on_line(IDENT_LINE.rstrip("\n"))
        other = n.build_line(n.T_IDENT, 0, TOKEN, n.encode_payload({**IDENT_PAYLOAD, "master_seed": 8}))
        host.on_line(other.rstrip("\n"))
        self.assertIn("PROTOCOL_IDENT", host.protocol_end); self.assertTrue(host.ledger.conflict)


# ------------------------------------------------------------------ SIGNREQ


class SignTransaction(unittest.TestCase):
    def run_sign(self, faults=(), audit_seqs={1}, seq=1, rl=None):
        rl = rl or relay()
        board = rel.SignBoard(TOKEN, seq, signreq_line(seq))
        sim = rel.Simulation(board, host_on_line=lambda ln: None, faults=faults)
        host = rel.SignHost(TOKEN, rl, send=sim.send, audit_seqs=audit_seqs)

        def on_line(ln):
            try:
                f = n.parse_line(ln)
            except n.CrcError:
                host.on_broken_line(ln, "crc"); return
            except n.FrameError:
                host.on_broken_line(ln, "malformed"); return
            if f["type"] == n.T_SIGNREQ:
                host.on_signreq(f, ln)
        sim.host_on_line = on_line
        res = sim.run()
        return board, host, sim, res, rl

    def test_clean_exchange_folds_audit_requested_into_signok_no_auditreq_frame(self):
        board, host, sim, res, rl = self.run_sign()
        self.assertTrue(board.acked); self.assertEqual(board.reply_type, n.T_SIGNOK); self.assertTrue(board.audit_requested)
        self.assertEqual(types(res["host_sent"]), [n.T_SIGNOK]); self.assertEqual(len(rl.entries), 1)
        board2, host2, sim2, res2, rl2 = self.run_sign(audit_seqs=set())
        self.assertFalse(board2.audit_requested)
        self.assertEqual(n.decode_payload(n.parse_line(res["host_sent"][0])["payload"])["commit"], COMMIT)

    def test_signreq_lost_is_resent_on_the_bound_and_signed_once(self):
        board, host, sim, res, rl = self.run_sign([rel.Fault("b2h", n.T_SIGNREQ, 0, "drop")])
        self.assertTrue(board.acked); self.assertEqual(board.attempts, 2); self.assertEqual(len(rl.entries), 1)

    def test_signreq_corrupted_draws_signget_and_the_resend_is_signed_once(self):
        board, host, sim, res, rl = self.run_sign([rel.Fault("b2h", n.T_SIGNREQ, 0, "delete", offset=60, length=7)])
        self.assertTrue(board.acked); self.assertEqual(types(res["host_sent"]), [rel.T_SIGNGET, n.T_SIGNOK])
        led = host.ledgers[1]
        self.assertEqual([a["outcome"] for a in led.attempts], ["crc", "ok"]); self.assertEqual(led.gets_sent, 1)
        self.assertEqual(len(rl.entries), 1)

    def test_signok_lost_the_identical_resend_gets_the_cached_reply_not_a_second_signature(self):
        calls = []

        def signer(req):
            calls.append(req["seq"]); return {"commit": COMMIT, "expected_tables": TABLES, "tag": TAG}
        board, host, sim, res, rl = self.run_sign([rel.Fault("h2b", n.T_SIGNOK, 0, "drop")], rl=relay(signer))
        self.assertTrue(board.acked); self.assertEqual(calls, [1], "one signature")
        self.assertEqual(types(res["host_sent"]), [n.T_SIGNOK, n.T_SIGNOK]); self.assertEqual(res["host_sent"][0], res["host_sent"][1])
        self.assertEqual(rl.entries[0]["replays"], 1); self.assertEqual(rl.last_seq, 1)
        self.assertEqual([a["outcome"] for a in host.ledgers[1].attempts], ["ok", "duplicate"])

    def test_three_lost_replies_exhaust_to_stop_sign_with_one_signature_and_bounded_replays(self):
        board, host, sim, res, rl = self.run_sign([rel.Fault("h2b", n.T_SIGNOK, k, "drop") for k in range(3)])
        self.assertEqual(board.state, "EXHAUSTED"); self.assertIn(rel.STOP_SIGN, board.why)
        self.assertEqual(len(rl.entries), 1); self.assertEqual(rl.entries[0]["replays"], 2)
        self.assertEqual(host.ledgers[1].replays, 2)

    def test_a_same_seq_request_with_other_content_is_protocol_sign(self):
        rl = relay(); sent = []
        host = rel.SignHost(TOKEN, rl, send=sent.append, audit_seqs=set())
        ln = signreq_line(1); host.on_signreq(n.parse_line(ln), ln)
        other = signreq_line(1, genome="1" * 80); host.on_signreq(n.parse_line(other), other)
        self.assertIn("PROTOCOL_SIGN", host.protocol_end); self.assertTrue(host.ledgers[1].conflict)
        self.assertEqual(len(rl.entries), 1)

    def test_signreq_torn_then_resent_resyncs_and_signs_once(self):
        board, host, sim, res, rl = self.run_sign([rel.Fault("b2h", n.T_SIGNREQ, 0, "truncate", offset=120)])
        self.assertTrue(board.acked); self.assertEqual(len(rl.entries), 1); self.assertEqual(len(res["fragments"]), 1)

    def test_a_refusal_is_cached_and_replayed_the_same_way(self):
        rl = relay(lambda req: {"refused": {"finding_kinds": ["x"]}})
        board, host, sim, res, _ = self.run_sign([rel.Fault("h2b", n.T_SIGNREF, 0, "drop")], rl=rl)
        self.assertTrue(board.acked); self.assertEqual(board.reply_type, n.T_SIGNREF)
        self.assertEqual(types(res["host_sent"]), [n.T_SIGNREF, n.T_SIGNREF]); self.assertEqual(len(rl.entries), 1)


# ------------------------------------------------------------------ AUDIT_READY / AUDITDONE


class ReadyAndDone(unittest.TestCase):
    WORDS = [0] * 2814

    def run_pull(self, faults=()):
        board = rel.ReadyBoard(TOKEN, 1, "streams+readback", self.WORDS, requested=True)
        sim = rel.Simulation(board, host_on_line=lambda ln: None, faults=faults,
                             board_done=lambda b: b.state != "PULL")
        host = ap.PullHost(TOKEN, 1, send=sim.send, clock=lambda: sim.t)

        def on_line(ln):
            try:
                f = n.parse_line(ln)
            except (n.CrcError, n.FrameError):
                host.on_line(ln); return
            if f["type"] == rel.T_AUDITWAIT:
                host.on_wait()
            else:
                host.on_line(ln)
        sim.host_on_line = on_line
        sim.host_tick = host.tick
        res = sim.run()
        return board, host, sim, res

    def test_clean_pull_is_audited_with_no_wait(self):
        board, host, sim, res = self.run_pull()
        self.assertTrue(host.done); self.assertEqual(board.finish()["verified"], "audited"); self.assertEqual(board.waits_sent, 0)

    def test_ready_lost_is_resent_on_the_bound(self):
        board, host, sim, res = self.run_pull([rel.Fault("b2h", ap.T_READY, 0, "drop")])
        self.assertTrue(host.done); self.assertEqual(board.ready_sent, 2); self.assertEqual(board.finish()["verified"], "audited")

    def test_ready_lost_three_times_aborts_as_before(self):
        board, host, sim, res = self.run_pull([rel.Fault("b2h", ap.T_READY, k, "drop") for k in range(3)])
        self.assertFalse(host.done); self.assertEqual(board.finish()["outcome"], "STOP_AUDIT"); self.assertEqual(board.ready_sent, 3)

    def test_done_lost_the_board_asks_and_the_same_done_is_replayed(self):
        board, host, sim, res = self.run_pull([rel.Fault("h2b", ap.T_DONE, 0, "drop")])
        self.assertTrue(host.done); self.assertEqual(board.finish()["verified"], "audited")
        self.assertEqual(board.waits_sent, 1); self.assertEqual(host.ledger.waits_seen, 1); self.assertEqual(host.ledger.done_replays, 1)
        dones = [l for l in res["host_sent"] if n.parse_line(l)["type"] == ap.T_DONE]
        self.assertEqual(len(dones), 2); self.assertEqual(dones[0], dones[1])

    def test_done_lost_four_times_is_visible_on_both_sides(self):
        board, host, sim, res = self.run_pull([rel.Fault("h2b", ap.T_DONE, k, "drop") for k in range(4)])
        self.assertTrue(host.done, "the host verified every chunk")
        self.assertEqual(host.ledger.waits_seen, rel.WAIT_MAX, "…and counted every announcement; the verdict is the board's record")
        self.assertEqual(board.finish()["outcome"], "STOP_AUDIT"); self.assertEqual(board.waits_sent, rel.WAIT_MAX)


# ------------------------------------------------------------------ TERM / CLOSE


class TermTransaction(unittest.TestCase):
    def run_term(self, faults=(), line=None):
        line = line or term_line()
        board = rel.TermBoard(TOKEN, 3, line)
        sim = rel.Simulation(board, host_on_line=lambda ln: None, faults=faults)
        delivered = []
        host = rel.TermHost(TOKEN, deliver=delivered.append, send=sim.send)

        def on_line(ln):
            try:
                f = n.parse_line(ln)
            except n.CrcError:
                host.on_broken_line(ln, "crc"); return
            except n.FrameError:
                host.on_broken_line(ln, "malformed"); return
            if f["type"] == n.T_TERM:
                host.on_term(f, ln)
        sim.host_on_line = on_line
        res = sim.run()
        return board, host, delivered, res

    def test_clean_term_delivered_once_and_acknowledged(self):
        board, host, delivered, res = self.run_term()
        self.assertTrue(board.acked); self.assertEqual(len(delivered), 1); self.assertEqual(types(res["host_sent"]), [rel.T_TERMACK])

    def test_term_corrupted_draws_termget_then_delivered_once(self):
        board, host, delivered, res = self.run_term([rel.Fault("b2h", n.T_TERM, 0, "delete", offset=80, length=9)])
        self.assertEqual(len(delivered), 1); self.assertEqual(types(res["host_sent"]), [rel.T_TERMGET, rel.T_TERMACK])
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["crc", "ok"])

    def test_termack_lost_the_repeat_is_re_acknowledged_and_not_delivered_twice(self):
        board, host, delivered, res = self.run_term([rel.Fault("h2b", rel.T_TERMACK, 0, "drop")])
        self.assertTrue(board.acked); self.assertEqual(len(delivered), 1); self.assertEqual(host.ledger.acks_sent, 2)

    def test_term_lost_three_times_exhausts_and_the_host_saw_nothing(self):
        board, host, delivered, res = self.run_term([rel.Fault("b2h", n.T_TERM, k, "drop") for k in range(3)])
        self.assertEqual(board.state, "EXHAUSTED"); self.assertEqual(delivered, []); self.assertEqual(res["host_sent"], [])

    def test_term_torn_then_resent_resyncs(self):
        board, host, delivered, res = self.run_term([rel.Fault("b2h", n.T_TERM, 0, "truncate", offset=150)])
        self.assertEqual(len(delivered), 1); self.assertEqual(len(res["fragments"]), 1)

    def test_closing_control_is_reconstructed_from_term_only_when_complete(self):
        summary = n.decode_payload(n.parse_line(term_line())["payload"])
        cn = rel.closing_from_term(summary)
        self.assertEqual(cn["fault"], 13); self.assertEqual(cn["source"], "TERM")
        self.assertIsNone(rel.closing_from_term(n.decode_payload(n.parse_line(term_line(with_closing=False))["payload"])))
        partial = dict(summary); partial["closing_control"] = {"fault": 13}
        self.assertIsNone(rel.closing_from_term(partial))


# ------------------------------------------------------------------ HB


class Heartbeats(unittest.TestCase):
    def frames(self, per_seq: dict[int, list[int]], unindexed=0):
        out = []
        for seq, idx in per_seq.items():
            for i in idx:
                out.append({"dir": "rx", "type": n.T_HB, "seq": seq, "t_mono": 0.0, "hb_i": i})
        for _ in range(unindexed):
            out.append({"dir": "rx", "type": n.T_HB, "seq": 1, "t_mono": 0.0})
        return out

    def log(self, n_scored: int):
        return {"loop_records": [{"seq": s, "outcome": "SCORED"} for s in range(1, n_scored + 1)]}

    def test_the_budget_is_floor_of_scored_records_over_1000(self):
        self.assertEqual([rel.hb_missing_budget(r) for r in (0, 66, 999, 1000, 1999, 6541)], [0, 0, 0, 1, 1, 6])

    def test_all_present_no_finding_duplicates_harmless(self):
        fr = self.frames({1: list(range(16)), 2: list(range(16)) + [3, 3]})
        self.assertEqual(rel.heartbeat_findings_rel(self.log(2), fr), [])

    def test_one_missing_in_a_calibration_crosses_the_zero_budget(self):
        fr = self.frames({1: list(range(16)), 2: list(range(15))})
        out = rel.heartbeat_findings_rel(self.log(2), fr)
        self.assertEqual(len(out), 1); self.assertIn("1 heartbeats missing over 2 SCORED records > the budget floor(R/1000) = 0", out[0])

    def test_one_missing_in_a_soak_sized_session_is_within_budget_two_in_one_record_never(self):
        big = {s: list(range(16)) for s in range(1, 2001)}; big[7] = list(range(15))
        self.assertEqual(rel.heartbeat_findings_rel(self.log(2000), self.frames(big)), [])
        big[9] = list(range(14))
        out = rel.heartbeat_findings_rel(self.log(2000), self.frames(big))
        self.assertTrue(any("seq 9 (SCORED): 2 heartbeats missing" in o for o in out))

    def test_unindexed_and_out_of_range_are_named(self):
        fr = self.frames({1: list(range(16)) + [16]}, unindexed=2)
        out = rel.heartbeat_findings_rel(self.log(1), fr)
        self.assertTrue(any("carry no index" in o for o in out)); self.assertTrue(any("out of range [16]" in o for o in out))

    def test_the_timeline_records_the_index_and_the_structural_check_selects_the_rule(self):
        tl = lt.Timeline()
        tl.observe(rel.hb_line(TOKEN, 1, 5).rstrip("\n"), 1.0, 1.0); tl.observe(n.build_line(n.T_HB, 1, TOKEN).rstrip("\n"), 2.0, 2.0)
        self.assertEqual([f.get("hb_i") for f in tl.frames], [5, None])
        src = inspect.getsource(lc.structural_findings)
        self.assertIn('if protocol == "rel-v4":', src); self.assertIn("heartbeat_findings_rel", src)


# ------------------------------------------------------------------ the session under rel-v4, and rec-v3 unchanged


class Session(unittest.TestCase):
    def make(self, protocol: str):
        self.now = {"t": 0.0}
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: self.now["t"])
        rl = n.NotaryRelay(TOKEN, lambda req: {"commit": COMMIT, "expected_tables": TABLES, "tag": TAG}, drop_budget=8,
                           clock=lambda: 0.0)
        tl = lt.Timeline(); sent = []
        cs = lcs.ConsoleSession(TOKEN, collector, rl, tl, audit_seqs={1}, crc_budget=8,
                                send=lambda line, mtype, seq: sent.append(line), protocol=protocol, identity_check=verify_ok)
        return cs, sent, collector, rl, tl

    def feed(self, cs, line):
        self.now["t"] += 0.01
        cs.on_line(line.rstrip("\n"), self.now["t"], self.now["t"])

    def test_rel_v4_ident_before_signreq_cached_reply_wait_replay_term_and_close_from_term(self):
        cs, sent, collector, rl, tl = self.make("rel-v4")
        self.feed(cs, IDENT_LINE)
        self.assertEqual(types(sent), [rel.T_IDENTACK]); self.assertTrue(cs.ident.established); self.assertIsNotNone(collector.app_identity)
        self.feed(cs, signreq_line(1))
        self.assertEqual(types(sent), [rel.T_IDENTACK, n.T_SIGNOK], "no AUDITREQ frame: audit_requested rides in SIGNOK")
        self.assertTrue(n.decode_payload(n.parse_line(sent[-1])["payload"])["audit_requested"])
        self.feed(cs, signreq_line(1))                                # the reply was lost: the same request again
        self.assertEqual(sent[-1], sent[-2]); self.assertEqual(len(rl.entries), 1); self.assertEqual(rl.entries[0]["replays"], 1)
        self.assertFalse(cs.ended, "a same-seq resend is the transaction, not the board advancing")
        board = rel.ReadyBoard(TOKEN, 1, "streams+readback", [0] * 2814, requested=True)
        self.feed(cs, board.start()[0])
        for c in range(8):
            self.feed(cs, board.serve(c))
        self.assertIsNone(cs.puller); self.assertTrue(cs.pull_ledgers[-1]["done"])
        n_done = sum(1 for l in sent if n.parse_line(l)["type"] == ap.T_DONE)
        self.feed(cs, n.build_line(rel.T_AUDITWAIT, 1, TOKEN, n.encode_payload({"seq": 1, "served": 8})))
        self.assertEqual(sum(1 for l in sent if n.parse_line(l)["type"] == ap.T_DONE), n_done + 1, "the same DONE replayed")
        self.assertEqual(cs.last_pull.ledger.waits_seen, 1)
        self.feed(cs, term_line(seq=2))
        self.assertEqual(n.parse_line(sent[-1])["type"], rel.T_TERMACK); self.assertTrue(cs.ended)
        self.assertEqual(collector.closing_negative["source"], "TERM"); self.assertEqual(collector.closing_negative["fault"], 13)
        self.feed(cs, term_line(seq=2))                                # the ACK was lost: re-acknowledged after the end
        self.assertEqual(types(sent[-2:]), [rel.T_TERMACK, rel.T_TERMACK])
        led = cs.rel_ledgers_json()
        self.assertEqual(led["ident"]["acks_sent"], 1); self.assertEqual(led["signs"][0]["replays"], 1); self.assertEqual(led["term"]["acks_sent"], 2)

    def test_rel_v4_a_signreq_before_the_handshake_ends_the_epoch_and_a_broken_signreq_draws_signget(self):
        cs, sent, collector, rl, tl = self.make("rel-v4")
        self.feed(cs, signreq_line(1))
        self.assertTrue(cs.ended); self.assertIn("PROTOCOL_IDENT", collector.epoch_end["reason"]); self.assertEqual(sent, [])
        cs, sent, collector, rl, tl = self.make("rel-v4")
        self.feed(cs, IDENT_LINE)
        body = signreq_line(1).rstrip("\n"); broken = body[:-1] + ("0" if body[-1] != "0" else "1")
        self.feed(cs, broken)
        self.assertEqual(types(sent), [rel.T_IDENTACK, rel.T_SIGNGET]); self.assertFalse(cs.ended)
        self.feed(cs, signreq_line(1))
        self.assertEqual(types(sent), [rel.T_IDENTACK, rel.T_SIGNGET, n.T_SIGNOK]); self.assertEqual(len(rl.entries), 1)
        broken_term = term_line(seq=2).rstrip("\n"); broken_term = broken_term[:-1] + ("0" if broken_term[-1] != "0" else "1")
        self.feed(cs, broken_term)
        self.assertEqual(n.parse_line(sent[-1])["type"], rel.T_TERMGET); self.assertFalse(cs.ended)

    def test_rec_v3_is_unchanged_none_of_the_new_frames_and_the_old_rules(self):
        cs, sent, collector, rl, tl = self.make("rec-v3")
        self.assertFalse(cs.rel); self.assertEqual(cs.rel_ledgers_json(), {})
        self.feed(cs, IDENT_LINE)
        self.assertEqual(sent, [], "rec-v3 acknowledges no IDENT")
        self.feed(cs, signreq_line(1))
        self.assertEqual(types(sent), [n.T_AUDITREQ, n.T_SIGNOK], "the separate AUDITREQ frame, as C1 #5 ran")
        self.assertNotIn("audit_requested", n.decode_payload(n.parse_line(sent[-1])["payload"]))
        self.feed(cs, signreq_line(1))                                # a same-seq SIGNREQ under rec-v3: the old rule
        self.assertTrue(cs.ended); self.assertIn("PROTOCOL_REC", collector.epoch_end["reason"])
        for l in sent:
            self.assertNotIn(n.parse_line(l)["type"], rel.HOST_TYPES)

    def test_the_schedule_and_the_runner_select_rel_v4_by_the_pinned_protocol(self):
        e3 = ls.expected_frames(64, ls.all_seqs(64), "rec-v3"); e4 = ls.expected_frames(64, ls.all_seqs(64), "rel-v4")
        self.assertEqual(e3["by_type"], e4["by_type"]); self.assertEqual(e4["protocol"], "rel-v4")
        import l6_runner as l6
        self.assertEqual(l6.HOST_PROTOCOLS, ("rec-v3", "rel-v4"))
        src = inspect.getsource(l6.run_l6)
        self.assertIn('protocol=plan["protocol"]', src); self.assertIn("identity_check=identity_check", src)
        self.assertIn("**console.rel_ledgers_json()", src)
        plan_src = inspect.getsource(l6.plan_session)
        self.assertIn('"protocol": l6m["pinned_at_build"].get("protocol", HOST_PROTOCOL)', plan_src)
        pre = inspect.getsource(l6.preflight)
        self.assertIn('wd.get("protocol") not in HOST_PROTOCOLS', pre)
        self.assertIn('l6m["prereg"].get("protocol") != wd.get("protocol")', pre)


# ------------------------------------------------------------------ the validator


class ValidatorContract(unittest.TestCase):
    def test_stop_sign_record_shape(self):
        base = {"schema": "loop_record", "schema_version": "1.1.0", "seq": 5, "genome": "0" * 80, "outcome": "STOP_SIGN",
                "verified": "replayed-only", "evidence": {"sign_stop": {"attempts": 3, "why": "STOP_SIGN: no acknowledgement after 3 attempts"}}}
        records.validate(base)
        bad = copy.deepcopy(base); bad["evidence"]["sign_reply"] = {"schema": "sign_reply"}
        with self.assertRaises(records.RecordError):
            records.validate(bad)
        bad = copy.deepcopy(base); bad["evidence"]["sign_stop"] = {"attempts": 0, "why": "x"}
        with self.assertRaises(records.RecordError):
            records.validate(bad)
        bad = copy.deepcopy(base); bad["verified"] = "audited"
        with self.assertRaises(records.RecordError):
            records.validate(bad)
        self.assertEqual(records.self_report_class(base), "none")

    def test_orphan_notary_entries_are_refused_for_an_app_written_epoch_and_allowed_for_a_crash(self):
        import test_d1_records as d1
        import p3_gate as g
        log = copy.deepcopy(d1.make_log())
        blank = log["loop_records"][0]["evidence"]["sign_reply"]["commit"]
        seed = int(log["loop_records"][0]["evidence"]["arm"]["nonce_before"], 16)
        records.validate_standalone_run_log(log, blank, seed, [], None)
        extra = copy.deepcopy(log["notary_log"]["entries"][1]); extra["seq"] = 9
        for k in ("request", "answer"):
            extra[k] = dict(extra[k], seq=9)
        bad = copy.deepcopy(log); bad["notary_log"]["entries"].append(extra)
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(bad, blank, seed, [], None)
        self.assertIn("(vii) notary entries without a record: [9]", str(cm.exception))
        crashed = copy.deepcopy(bad)
        crashed["session_summary"] = {"schema": "session_summary", "schema_version": "1.0.0", "token": log["session_summary"]["token"],
                                      "epoch_end": {"kind": "CRASHED", "reason": "x", "last_seq": 4},
                                      "counts": {"scored": 2, "refused_by_gate": 1},
                                      "closing": {"restore": "not_reached", "baseline": "not_reached", "unsigned_control": "not_reached"},
                                      "audit": {"audited": 0, "total": 4}, "crc_dropped": 0, "drop_budget": 8, "written_by": "collector"}
        crashed.pop("closing_negative", None)
        try:
            records.validate_standalone_run_log(crashed, blank, seed, [], None)
        except records.RecordError as exc:
            self.assertNotIn("notary entries without a record", str(exc), "a crash may leave the in-flight entry")


if __name__ == "__main__":
    unittest.main()
