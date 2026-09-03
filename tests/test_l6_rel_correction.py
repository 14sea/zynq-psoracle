"""The owner's seven HOLD items on the rel-v4 host batch (review 2026-09-02), each with a
negative test on the REAL `ConsoleSession` or the runner's loop condition:

  1. the pull ledger written to audits.json is rendered LIVE (AUDITWAIT replays after the
     settle are in it);
  2. no `unconfirmed` verdict on the wait count — the board's record decides, through
     `rel_closure_findings`; the third replay may still succeed;
  3. the runner keeps reading after the first TERM (`session_loop_continues` lingers under
     rel-v4, never under rec-v3) so a resent TERM is re-acknowledged;
  4. IDENT wiring: a CRC-broken IDENT is in the ledger, a malformed IDENT is not CRASHED, a
     refused identity draws no ack and NO host-side end — the board exhausts to STOP_IDENT
     and its TERM ends the epoch; a SIGNREQ after the refusal is PROTOCOL_IDENT;
  5. v0.6 §6.10–13 machine-enforced: rel closure, the SIGNREQ control's exact shape, the
     rel recovery indicators and their bounds, all called by the runner;
  6. STOP_SIGN accepted by the validator only under rel-v4;
  7. CLOSE and TERM.closing_control compared when both exist; a disagreement is a finding.
"""
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
import l6_rate as lr  # noqa: E402
import l6_rel as rel  # noqa: E402
import l6_runner as l6  # noqa: E402
import l6_schedule as ls  # noqa: E402
import l6_timing as lt  # noqa: E402
import test_l6_rel as base  # noqa: E402
from validators import records  # noqa: E402

TOKEN = base.TOKEN
MANIFEST = json.loads((R / "manifests/l6_manifest.json").read_text())
REL_PC = {k: MANIFEST["pass_conditions"][k] for k in lc.REL_RECOVERY_KEYS}     # merged at the v0.6 freeze (2026-09-03)


def broken(line: str) -> str:
    body = line.rstrip("\n")
    return body[:-1] + ("0" if body[-1] != "0" else "1")


class Session(unittest.TestCase):
    def make(self, protocol="rel-v4", verify=base.verify_ok):
        self.now = {"t": 100.0}
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: self.now["t"])
        rl = n.NotaryRelay(TOKEN, lambda req: {"commit": base.COMMIT, "expected_tables": base.TABLES, "tag": base.TAG},
                           drop_budget=8, clock=lambda: 0.0)
        tl = lt.Timeline(); sent = []
        cs = lcs.ConsoleSession(TOKEN, collector, rl, tl, audit_seqs={1}, crc_budget=8,
                                send=lambda line, mtype, seq: sent.append(line), protocol=protocol,
                                identity_check=verify, clock=lambda: self.now["t"])
        return cs, sent, collector, rl, tl

    def feed(self, cs, line):
        self.now["t"] += 0.01
        cs.on_line(line.rstrip("\n"), self.now["t"], self.now["t"])

    def pull(self, cs):
        board = rel.ReadyBoard(TOKEN, 1, "streams+readback", [0] * 2814, requested=True)
        self.feed(cs, board.start()[0])
        for c in range(8):
            self.feed(cs, board.serve(c))
        return board

    # ---- 1
    def test_1_the_pull_ledger_written_after_an_auditwait_carries_the_replay(self):
        cs, sent, collector, rl, tl = self.make()
        self.feed(cs, base.IDENT_LINE); self.feed(cs, base.signreq_line(1)); self.pull(cs)
        self.assertEqual(cs.pull_ledgers[-1]["waits_seen"], 0)
        self.feed(cs, n.build_line(rel.T_AUDITWAIT, 1, TOKEN, n.encode_payload({"seq": 1, "served": 8})))
        led = cs.pull_ledgers[-1]
        self.assertEqual((led["waits_seen"], led["done_replays"], led["waits_exhausted"]), (1, 1, False),
                         "the ledger that goes to audits.json is rendered live, not copied at settle time")
        self.assertNotIn("unconfirmed", led)
        for _ in range(2):
            self.feed(cs, n.build_line(rel.T_AUDITWAIT, 1, TOKEN, n.encode_payload({"seq": 1, "served": 8})))
        led = cs.pull_ledgers[-1]
        self.assertEqual((led["waits_seen"], led["done_replays"], led["waits_exhausted"]), (3, 3, True))
        run = inspect.getsource(l6.run_l6)
        self.assertIn('"pulls": console.pull_ledgers', run)

    # ---- 2
    def test_2_the_verdict_on_a_waited_pull_is_the_boards_record_not_the_wait_count(self):
        pulls = [{"seq": 5, "done": True, "waits_seen": 3, "done_replays": 3, "waits_exhausted": True}]
        ok_log = {"app_identity": {"protocol": "rel-v4"}, "loop_records": [{"seq": 5, "outcome": "SCORED", "verified": "audited"}],
                  "session_summary": {"written_by": "collector", "epoch_end": {"kind": "CRASHED"}}}
        ledgers = {"ident": {"accepted": True, "acks_sent": 1}, "signs": [{"seq": 5, "accepted": True}], "term": None}
        self.assertEqual([f for f in lc.rel_closure_findings(ok_log, ledgers, pulls) if "confirmed" in f], [],
                         "three waits, but the board's record says audited: the third replay reached it")
        bad_log = copy.deepcopy(ok_log); bad_log["loop_records"][0]["verified"] = "replayed-only"
        out = [f for f in lc.rel_closure_findings(bad_log, ledgers, pulls) if "not confirmed on the board" in f]
        self.assertEqual(len(out), 1); self.assertIn("waits_seen 3", out[0]); self.assertIn("done_replays 3", out[0])
        src = inspect.getsource(ap.PullHost.on_wait)
        self.assertNotIn("unconfirmed", src.replace("No verdict", ""))

    # ---- 3
    def test_3_the_runner_lingers_after_the_term_under_rel_v4_and_re_acknowledges_a_resend(self):
        cs, sent, collector, rl, tl = self.make()
        self.feed(cs, base.IDENT_LINE); self.feed(cs, base.signreq_line(1)); self.pull(cs)
        self.feed(cs, base.term_line(seq=2))
        self.assertIsNotNone(collector.epoch_end, "the collector ends the epoch on the first TERM, as before")
        now = self.now["t"]
        self.assertTrue(l6.session_loop_continues(collector, cs, now, now + 1e6), "…but the loop reads on")
        self.assertTrue(l6.session_loop_continues(collector, cs, now + rel.TERM_LINGER_S - 0.5, now + 1e6))
        self.assertFalse(l6.session_loop_continues(collector, cs, now + rel.TERM_LINGER_S + 0.1, now + 1e6))
        self.assertFalse(l6.session_loop_continues(collector, cs, now, now - 1.0), "the runner's own bound wins")
        n_ack = sum(1 for l in sent if n.parse_line(l)["type"] == rel.T_TERMACK)
        self.now["t"] += rel.BOARD_BOUND_S                     # the board resent: our first ACK was lost
        self.feed(cs, base.term_line(seq=2))
        self.assertEqual(sum(1 for l in sent if n.parse_line(l)["type"] == rel.T_TERMACK), n_ack + 1)
        self.assertEqual(cs.rel_ledgers_json()["term"]["acks_sent"], 2)
        # rec-v3: the loop ends with the epoch, exactly as before
        cs3, sent3, col3, rl3, tl3 = self.make("rec-v3")
        self.feed(cs3, base.signreq_line(1))
        col3.epoch_end = {"kind": "COMPLETED", "reason": "budget", "last_seq": 1}
        self.assertFalse(l6.session_loop_continues(col3, cs3, self.now["t"], self.now["t"] + 1e6))
        self.assertFalse(cs3.lingering())
        src = inspect.getsource(l6.run_l6)
        self.assertIn("while session_loop_continues(collector, console, time.monotonic(), deadline):", src)

    # ---- 4
    def test_4a_a_crc_broken_ident_is_ledgered_and_not_acknowledged(self):
        cs, sent, collector, rl, tl = self.make()
        self.feed(cs, broken(base.IDENT_LINE))
        self.assertEqual(sent, []); self.assertFalse(cs.ended)
        self.assertEqual([a["outcome"] for a in cs.ident.ledger.attempts], ["crc"])
        self.assertEqual(tl.crc_dropped, 1)
        self.feed(cs, base.IDENT_LINE)                          # the board's resend on its bound
        self.assertTrue(cs.ident.established); self.assertEqual([a["outcome"] for a in cs.ident.ledger.attempts], ["crc", "ok"])

    def test_4b_a_malformed_ident_is_not_the_collectors_crash(self):
        cs, sent, collector, rl, tl = self.make()
        self.feed(cs, "P3L5 IDENT 0 " + TOKEN + " abc def 00000000")     # seven fields
        self.assertFalse(cs.ended, "not CRASHED: unparseable frame"); self.assertEqual(sent, [])
        self.assertEqual([a["outcome"] for a in cs.ident.ledger.attempts], ["malformed"]); self.assertEqual(tl.bad_frames, 1)
        cs3, sent3, col3, rl3, tl3 = self.make("rec-v3")
        self.feed(cs3, "P3L5 IDENT 0 " + TOKEN + " abc def 00000000")
        self.assertTrue(cs3.ended, "rec-v3 unchanged: a malformed frame is the collector's CRASHED")

    def test_4c_a_refused_identity_draws_no_ack_and_no_host_end_the_board_exhausts_to_stop_ident(self):
        cs, sent, collector, rl, tl = self.make(verify=lambda ident: ["master_seed 7 != the page's 9"])
        self.feed(cs, base.IDENT_LINE)
        self.assertEqual(sent, [], "no IDENTACK"); self.assertFalse(cs.ended, "no host-side end")
        self.assertTrue(cs.ident.refused); self.assertIsNotNone(collector.app_identity, "the declared identity is evidence")
        for _ in range(2):
            self.now["t"] += rel.BOARD_BOUND_S; self.feed(cs, base.IDENT_LINE)   # the board's resends
        self.assertEqual(sent, []); self.assertFalse(cs.ended)
        self.assertEqual([a["outcome"] for a in cs.ident.ledger.attempts], ["refused", "refused-repeat", "refused-repeat"])
        # the board exhausts and stops itself: its TERM (STOP_IDENT) ends the epoch
        p = n.decode_payload(n.parse_line(base.term_line(seq=1))["payload"])
        p["epoch_end"] = {"kind": "STOPPED", "last_seq": 0, "reason": "STOP_IDENT: no acknowledgement after 3 attempts"}
        p["closing"] = {"restore": "done", "baseline": "not_reached", "unsigned_control": "not_reached"}
        p["counts"] = {"scored": 0, "refused_by_gate": 0}; p["audit"] = {"audited": 0, "total": 0}; p.pop("closing_control")
        self.feed(cs, n.build_line(n.T_TERM, 1, TOKEN, n.encode_payload(p)))
        self.assertTrue(cs.ended); self.assertEqual(collector.epoch_end["kind"], "STOPPED")
        led = cs.rel_ledgers_json()["ident"]
        self.assertTrue(led["refused"]); self.assertEqual(led["findings"], ["master_seed 7 != the page's 9"])
        self.assertTrue(any("identity refused by the host" in f for f in
                            lc.rel_closure_findings({"app_identity": collector.app_identity, "loop_records": [],
                                                     "session_summary": collector.session_summary}, cs.rel_ledgers_json(), [])))

    def test_4d_a_signreq_after_the_refusal_is_protocol_ident(self):
        cs, sent, collector, rl, tl = self.make(verify=lambda ident: ["not this session"])
        self.feed(cs, base.IDENT_LINE); self.feed(cs, base.signreq_line(1))
        self.assertTrue(cs.ended); self.assertIn("after the identity was refused", collector.epoch_end["reason"])
        self.assertEqual(sent, []); self.assertEqual(rl.entries, [], "the relay never signed")

    # ---- 5
    def test_5a_rel_closure_names_every_defect(self):
        log = {"app_identity": {"protocol": "rel-v4"},
               "loop_records": [{"seq": 1, "outcome": "SCORED", "verified": "audited"}, {"seq": 2, "outcome": "SCORED", "verified": "audited"}],
               "session_summary": {"written_by": "app", "epoch_end": {"kind": "COMPLETED", "reason": "budget"},
                                   "closing": {"restore": "done", "baseline": "done", "unsigned_control": "done"},
                                   "closing_control": {"fault": 13, "kind": "unsigned", "status": "0x00000982",
                                                       "nonce_before": "3" * 16, "nonce_after": "4" * 16}}}
        good = {"ident": {"accepted": True, "acks_sent": 1, "conflict": False, "refused": False},
                "signs": [{"seq": 1, "accepted": True, "conflict": False}, {"seq": 2, "accepted": True, "conflict": False}],
                "term": {"accepted": True, "acks_sent": 1, "conflict": False}, "closing_conflict": None}
        pulls = [{"seq": 1, "done": True, "waits_seen": 0, "done_replays": 0}, {"seq": 2, "done": True, "waits_seen": 0, "done_replays": 0}]
        self.assertEqual(lc.rel_closure_findings(log, good, pulls), [])

        def mut(**kw):
            g = copy.deepcopy(good); lg = copy.deepcopy(log); pl = copy.deepcopy(pulls)
            for k, v in kw.items():
                if k == "ident":
                    g["ident"].update(v)
                elif k == "signs":
                    g["signs"] = v
                elif k == "term":
                    g["term"] = v
                elif k == "closing_conflict":
                    g["closing_conflict"] = v
                elif k == "proto":
                    lg["app_identity"]["protocol"] = v
                elif k == "record":
                    lg["loop_records"][1].update(v)
                elif k == "end":
                    lg["session_summary"]["epoch_end"] = v
            return lc.rel_closure_findings(lg, g, pl)
        self.assertIn("identity not established", mut(ident={"accepted": False})[0])
        self.assertIn("identity conflict", mut(ident={"conflict": True})[0])
        self.assertIn("never acknowledged", mut(ident={"acks_sent": 0})[0])
        self.assertIn("not rel-v4", mut(proto="rec-v3")[0])
        self.assertIn("seq 2: record without a sign ledger", mut(signs=good["signs"][:1])[0])
        self.assertIn("seq 2: sign transaction not accepted or in conflict", mut(signs=[good["signs"][0], {"seq": 2, "accepted": True, "conflict": True}])[0])
        self.assertIn("seq 3: sign ledger without a record", mut(signs=good["signs"] + [{"seq": 3, "accepted": True}])[0])
        self.assertIn("seq 2: terminal STOP_SIGN", mut(record={"outcome": "STOP_SIGN"})[0])
        self.assertIn("epoch ended PROTOCOL", mut(end={"kind": "PROTOCOL", "reason": "x"})[0])
        self.assertIn("TERM transaction not accepted", mut(term=None)[0])
        self.assertIn("TERM accepted but never acknowledged", mut(term={"accepted": True, "acks_sent": 0})[0])
        self.assertIn("CLOSE and TERM.closing_control disagree", mut(closing_conflict={"close": {"fault": 13}, "term": {"fault": 12}})[0])

    def test_5b_the_signreq_control_shape_is_exact(self):
        ok = [{"seq": 1, "attempts": [{"outcome": "crc"}, {"outcome": "ok"}], "gets_sent": 1, "replays": 0, "accepted": True, "conflict": False}]
        self.assertEqual(lc.rel_control_findings(ok, armed=True), [])
        self.assertIn("not armed", lc.rel_control_findings(ok, armed=False)[0])
        self.assertIn("not exercised", lc.rel_control_findings([], armed=True)[0])
        for change, text in (({"attempts": [{"outcome": "ok"}]}, "attempts ['ok']"),
                             ({"attempts": [{"outcome": "crc"}, {"outcome": "crc"}, {"outcome": "ok"}], "gets_sent": 2}, "['crc', 'crc', 'ok']"),
                             ({"gets_sent": 0}, "0 SIGNGET sent"), ({"replays": 1}, "1 cached replays"),
                             ({"accepted": False}, "not accepted")):
            led = copy.deepcopy(ok); led[0].update(change)
            self.assertTrue(any(text in f for f in lc.rel_control_findings(led, armed=True)), text)

    def test_5c_the_rel_recovery_indicators_are_computed_and_bounded(self):
        c15 = R / "evidence/l6_17A6_2026-09-02-01-C1"
        log = json.loads((c15 / "run_log.json").read_text()); audits = json.loads((c15 / "audits.json").read_text())
        frames = json.loads((c15 / "timeline.json").read_text())["frames"]
        audits = dict(audits, signs=[{"seq": s, "attempts": [{"outcome": "ok"}], "gets_sent": 0, "replays": 0} for s in range(1, 67)],
                      ident={"attempts": [{"outcome": "ok"}, {"outcome": "duplicate"}], "acks_sent": 2},
                      term={"attempts": [{"outcome": "crc"}, {"outcome": "ok"}], "gets_sent": 1, "acks_sent": 1})
        audits["signs"][0]["attempts"] = [{"outcome": "crc"}, {"outcome": "ok"}]; audits["signs"][0]["gets_sent"] = 1   # the control
        audits["signs"][9]["attempts"] = [{"outcome": "ok"}, {"outcome": "duplicate"}]; audits["signs"][9]["replays"] = 1
        for p in audits["pulls"]:
            if p["seq"] == 20:
                p["ready_dups"] = 1; p["done_replays"] = 2
        inputs = {k: "0" * 64 for k in ("run_log", "audits", "timeline")}
        rep = lr.rate_report(log, "C1", None, audits=audits, frames=frames, inputs_sha256=inputs)
        rec = rep["recovery"]
        self.assertEqual((rec["sign_retries"], rec["ready_resends"], rec["done_replays"], rec["ident_repeats"], rec["term_retries"]), (1, 1, 2, 1, 1))
        self.assertEqual(rec["control_drops"], 2, "the REC control and the SIGNREQ control, both apart")
        self.assertIn(10, rec["recovered_seqs"]); self.assertIn(20, rec["recovered_seqs"]); self.assertNotIn(1, rec["recovered_seqs"])
        self.assertEqual(lc.rel_recovery_findings(rec, REL_PC), [])
        for k, bound in (("sign_retries", 4), ("ready_resends", 4), ("ident_repeats", 4), ("term_retries", 4), ("done_replays", 4)):
            r2 = dict(rec); r2[k] = bound
            self.assertTrue(any(f"{k} {bound} > 3" in f for f in lc.rel_recovery_findings(r2, REL_PC)), k)
        self.assertIn("not pinned", lc.rel_recovery_findings(rec, {})[0])

    def test_5d_hb_missing_is_attributed_per_scored_record(self):
        log = {"loop_records": [{"seq": 1, "outcome": "SCORED"}, {"seq": 2, "outcome": "SCORED"}], "timing": {"records": {}}}
        tim = {1: {"t_signreq": 0.0}, 2: {"t_signreq": 10.0}}
        frames = [{"dir": "rx", "type": "HB", "seq": 1, "t_mono": 1.0, "hb_i": i} for i in range(16)]
        frames += [{"dir": "rx", "type": "HB", "seq": 2, "t_mono": 11.0, "hb_i": i} for i in range(15)]
        rec = lr.recovery_by_seq(tim, [1, 2], {"pulls": [], "recs": []}, frames, records={r["seq"]: r for r in log["loop_records"]})
        self.assertEqual((rec[1]["hb_missing"], rec[2]["hb_missing"]), (0, 1)); self.assertTrue(rec[2]["recovered"])

    def test_5e_the_runner_calls_the_three_gates_under_rel_v4_and_arms_the_control(self):
        src = inspect.getsource(l6.run_l6)
        self.assertIn('if plan["protocol"] == "rel-v4":', src)
        self.assertIn("lc.rel_closure_findings(log, rel_ledgers, console.pull_ledgers)", src)
        self.assertIn('lc.rel_control_findings(rel_ledgers.get("signs") or [], bool(plan["flags"] & ls.FLAG_SIGN_CONTROL))', src)
        self.assertIn('lc.rel_recovery_findings(rep.get("recovery") or {}, pc)', src)
        plan_src = inspect.getsource(l6.plan_session)
        self.assertIn('sign_control=l6m["pinned_at_build"].get("protocol") == "rel-v4"', plan_src)
        self.assertEqual(ls.flags_for("random_safe_forced", watchdog=True, rec_control=True, sign_control=True) & ls.FLAG_SIGN_CONTROL, ls.FLAG_SIGN_CONTROL)
        self.assertEqual(ls.flags_for("random_safe_forced", watchdog=True, rec_control=True) & ls.FLAG_SIGN_CONTROL, 0)
        self.assertEqual(REL_PC, {"max_sign_retries": 3, "max_ready_resends": 3, "max_ident_repeats": 3, "max_term_retries": 3, "max_done_replays": 3})

    # ---- 6
    def test_6_stop_sign_is_refused_under_any_protocol_but_rel_v4(self):
        import test_d1_records as d1
        log = copy.deepcopy(d1.make_log())
        blank = log["loop_records"][0]["evidence"]["sign_reply"]["commit"]
        seed = int(log["loop_records"][0]["evidence"]["arm"]["nonce_before"], 16)
        last = log["loop_records"][-1]
        stop = {"schema": "loop_record", "schema_version": "1.1.0", "seq": last["seq"] + 1, "genome": "0" * 80, "outcome": "STOP_SIGN",
                "verified": "replayed-only", "evidence": {"sign_stop": {"attempts": 3, "why": "STOP_SIGN: no acknowledgement after 3 attempts"}}}
        log["loop_records"].append(stop)
        log["session_summary"]["epoch_end"] = {"kind": "STOPPED", "reason": "STOP_SIGN", "last_seq": stop["seq"]}
        log["session_summary"]["closing"] = {"restore": "done", "baseline": "not_reached", "unsigned_control": "not_reached"}
        log["session_summary"]["audit"]["total"] = len(log["loop_records"])
        log.pop("closing_negative", None)
        log["app_identity"]["protocol"] = "rec-v3"
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(log, blank, seed, [], None)
        self.assertIn("STOP_SIGN under wire protocol 'rec-v3'", str(cm.exception))
        log["app_identity"]["protocol"] = "rel-v4"
        try:
            records.validate_standalone_run_log(log, blank, seed, [], None)
        except records.RecordError as exc:
            self.assertNotIn("STOP_SIGN under wire protocol", str(exc))

    # ---- 7
    def test_7_a_close_that_disagrees_with_the_terms_closing_control_is_a_recorded_conflict(self):
        cs, sent, collector, rl, tl = self.make()
        self.feed(cs, base.IDENT_LINE); self.feed(cs, base.signreq_line(1)); self.pull(cs)
        close = {"fault": 13, "kind": "unsigned", "status": "0x00000982", "nonce_before": "3" * 16, "nonce_after": "4" * 16}
        self.feed(cs, n.build_line(n.T_CLOSE, 1, TOKEN, n.encode_payload(close)))
        self.assertEqual(collector.closing_negative["fault"], 13)
        self.feed(cs, base.term_line(seq=2))                                   # agrees
        self.assertIsNone(cs.closing_conflict); self.assertNotIn("source", collector.closing_negative)
        cs2, sent2, col2, rl2, tl2 = self.make()
        self.feed(cs2, base.IDENT_LINE); self.feed(cs2, base.signreq_line(1)); self.pull(cs2)
        self.feed(cs2, n.build_line(n.T_CLOSE, 1, TOKEN, n.encode_payload(dict(close, nonce_after="5" * 16))))
        self.feed(cs2, base.term_line(seq=2))                                  # disagrees on nonce_after
        self.assertIsNotNone(cs2.closing_conflict); self.assertEqual(cs2.closing_conflict["close"]["nonce_after"], "5" * 16)
        self.assertEqual(col2.closing_negative["nonce_after"], "5" * 16, "the CLOSE that arrived stands; the conflict is the finding")
        out = lc.rel_closure_findings({"app_identity": col2.app_identity, "loop_records": [], "session_summary": col2.session_summary},
                                      cs2.rel_ledgers_json(), [])
        self.assertTrue(any("CLOSE and TERM.closing_control disagree" in f for f in out))


if __name__ == "__main__":
    unittest.main()
