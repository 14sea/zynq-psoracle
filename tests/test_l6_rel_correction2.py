"""The owner's second review of the rel-v4 batch (2026-09-02): two host acceptance
blockers, two items to pin before the firmware batch, two minor items.

  1. sign ledgers can never last-wins: exactly one per seq, the seq set equal to the
     record set; duplicates / missing / extra named by seq; the closure check, the
     control check and the rate's recovery all refuse a duplicated ledger — with the bad
     ledger BEFORE and AFTER the good one;
  2. an application-written TERM must carry the complete, typed closing_control: a
     missing block, a missing field, a wrong type are findings; a lost CLOSE is rebuilt
     only from a complete TERM; both present must agree;
  3. the IDENT echoes flags.bit5 (`sign_retry_control`) and the runner verifies it under
     rel-v4 (before the acknowledgement and at adjudication), never under rec-v3;
  4. the TERM linger is derived from a pinned wall-time bound on the board's poll count —
     a contract the firmware batch must prove;
  5. after a refusal only a byte-identical IDENT is a `refused-repeat`; other bytes are a
     conflict;
  6. the heartbeat budget is documented as "≥ 99.9 % of SCORED records complete".
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
import l6_checks as lc  # noqa: E402
import l6_rate as lr  # noqa: E402
import l6_rel as rel  # noqa: E402
import l6_runner as l6  # noqa: E402
import l6_schedule as ls  # noqa: E402
import test_l6_rel as base  # noqa: E402
import test_l6_rel_correction as c1  # noqa: E402
from validators import records  # noqa: E402

TOKEN = base.TOKEN
GOOD_LOG = {"app_identity": {"protocol": "rel-v4"},
            "loop_records": [{"seq": 1, "outcome": "SCORED", "verified": "audited"}],
            "session_summary": {"written_by": "app", "epoch_end": {"kind": "COMPLETED", "reason": "budget"},
                                "closing": {"restore": "done", "baseline": "done", "unsigned_control": "done"},
                                "closing_control": {"fault": 13, "kind": "unsigned", "status": "0x00000982",
                                                    "nonce_before": "3" * 16, "nonce_after": "4" * 16}}}
GOOD_LEDGERS = {"ident": {"accepted": True, "acks_sent": 1, "conflict": False, "refused": False},
                "signs": [{"seq": 1, "attempts": [{"outcome": "crc"}, {"outcome": "ok"}], "gets_sent": 1, "replays": 0,
                           "accepted": True, "conflict": False}],
                "term": {"accepted": True, "acks_sent": 1, "conflict": False}, "closing_conflict": None}
GOOD_PULLS = [{"seq": 1, "done": True, "waits_seen": 0, "done_replays": 0}]


class SignLedgersNeverLastWins(unittest.TestCase):
    def setUp(self):
        self.assertEqual(lc.rel_closure_findings(GOOD_LOG, GOOD_LEDGERS, GOOD_PULLS), [])
        self.assertEqual(lc.rel_control_findings(GOOD_LEDGERS["signs"], armed=True), [])

    def _with(self, signs):
        led = copy.deepcopy(GOOD_LEDGERS); led["signs"] = signs
        return led

    def test_1_a_duplicated_identical_seq_1_ledger_is_refused_before_and_after(self):
        good = GOOD_LEDGERS["signs"][0]
        for order in ("after", "before"):
            signs = [good, copy.deepcopy(good)] if order == "after" else [copy.deepcopy(good), good]
            out = lc.rel_closure_findings(GOOD_LOG, self._with(signs), GOOD_PULLS)
            self.assertEqual(out, ["seq 1: more than one sign ledger (refused, never last-wins)"], order)
            ctl = lc.rel_control_findings(signs, armed=True)
            self.assertEqual(ctl, ["SIGNREQ-retry control: seq 1: more than one sign ledger (refused, never last-wins)"], order)

    def test_1_a_bad_ledger_beside_a_good_one_is_refused_in_both_orders(self):
        good = GOOD_LEDGERS["signs"][0]
        bad = dict(good, attempts=[{"outcome": "ok"}], gets_sent=0)      # would pass the control if last-wins picked it
        for signs in ([bad, good], [good, bad]):
            self.assertIn("seq 1: more than one sign ledger", lc.rel_closure_findings(GOOD_LOG, self._with(signs), GOOD_PULLS)[0])
            self.assertIn("more than one sign ledger", lc.rel_control_findings(signs, armed=True)[0])
            with self.assertRaises(lr.RateError) as cm:
                lr.recovery_by_seq({1: {"t_signreq": 0.0}}, [1], {"pulls": [], "recs": [], "signs": signs}, [])
            self.assertIn("more than one sign ledger for seq 1", str(cm.exception))

    def test_1_missing_and_extra_seqs_are_named_and_the_sets_must_be_equal(self):
        out = lc.rel_closure_findings(GOOD_LOG, self._with([]), GOOD_PULLS)
        self.assertIn("seq 1: record without a sign ledger", out)
        extra = GOOD_LEDGERS["signs"] + [dict(GOOD_LEDGERS["signs"][0], seq=2)]
        self.assertIn("seq 2: sign ledger without a record", lc.rel_closure_findings(GOOD_LOG, self._with(extra), GOOD_PULLS))
        self.assertIn("a sign ledger without a seq", lc.rel_closure_findings(GOOD_LOG, self._with([{"accepted": True}]), GOOD_PULLS)[0])

    def test_1_the_rate_report_refuses_duplicate_missing_or_extra_sign_ledgers(self):
        c15 = R / "evidence/l6_17A6_2026-09-02-01-C1"
        log = json.loads((c15 / "run_log.json").read_text()); audits = json.loads((c15 / "audits.json").read_text())
        frames = json.loads((c15 / "timeline.json").read_text())["frames"]
        inputs = {k: "0" * 64 for k in ("run_log", "audits", "timeline")}
        signs = [{"seq": s, "attempts": [{"outcome": "ok"}], "gets_sent": 0, "replays": 0} for s in range(1, 67)]
        lr.rate_report(log, "C1", None, audits=dict(audits, signs=signs), frames=frames, inputs_sha256=inputs)
        for bad, msg in ((signs + [copy.deepcopy(signs[0])], "more than one sign ledger for seq [1]"),
                         ([copy.deepcopy(signs[3])] + signs, "more than one sign ledger for seq [4]"),
                         (signs[1:], "do not match the records"),
                         (signs + [dict(signs[0], seq=99)], "do not match the records"),
                         (signs[:-1] + [{"attempts": []}], "a sign ledger without an integer seq")):
            with self.assertRaises(lr.RateError) as cm:
                lr.rate_report(log, "C1", None, audits=dict(audits, signs=bad), frames=frames, inputs_sha256=inputs)
            self.assertIn(msg, str(cm.exception), msg)


class RelReportNeedsTheSignLedgers(unittest.TestCase):
    """The last blocker (owner's third review): with `signs` missing or null a rel-v4
    calibration was accepted with sign_retries 0. Through the REAL entry point on a copy of
    C1 #5's evidence with the identity set to rel-v4."""

    def _dir(self, td, protocol="rel-v4", signs="keep", ident=True, term=True):
        import shutil
        d = Path(td) / "ev"; shutil.copytree(R / "evidence/l6_17A6_2026-09-02-01-C1", d, ignore=shutil.ignore_patterns("rate_report.json"))
        log = json.loads((d / "run_log.json").read_text()); log["app_identity"]["protocol"] = protocol
        (d / "run_log.json").write_text(json.dumps(log))
        a = json.loads((d / "audits.json").read_text())
        good = [{"seq": s, "attempts": [{"outcome": "ok"}], "gets_sent": 0, "replays": 0, "accepted": True} for s in range(1, 67)]
        if signs == "keep":
            a["signs"] = good
        elif signs == "null":
            a["signs"] = None
        elif signs == "missing_one":
            a["signs"] = good[1:]
        elif signs == "duplicate":
            a["signs"] = good + [copy.deepcopy(good[4])]
        elif signs == "bad_seq":
            a["signs"] = good[:-1] + [dict(good[-1], seq="sixty-six")]
        elif signs == "absent":
            a.pop("signs", None)
        if ident:
            a["ident"] = {"seq": 0, "attempts": [{"outcome": "ok"}], "acks_sent": 1, "accepted": True}
        if term:
            a["term"] = {"seq": 67, "attempts": [{"outcome": "ok"}], "acks_sent": 1, "accepted": True}
        (d / "audits.json").write_text(json.dumps(a))
        return d

    def test_1_rel_v4_without_sign_ledgers_is_refused_through_the_real_entry_point(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            rep = lr.rate_report_from_evidence_dir(self._dir(td), "C1")
            self.assertEqual(rep["recovery"]["sign_retries"], 0); self.assertIsNotNone(rep["nominal"])
        for signs, msg in (("absent", "must carry signs, ident and term"), ("null", "signs is not a list (null is refused)"),
                           ("missing_one", "do not match the records"), ("duplicate", "more than one sign ledger for seq [5]"),
                           ("bad_seq", "sign ledger without an integer seq")):
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(lr.RateError) as cm:
                    lr.rate_report_from_evidence_dir(self._dir(td, signs=signs), "C1")
                self.assertIn(msg, str(cm.exception), signs)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(lr.RateError) as cm:
                lr.rate_report_from_evidence_dir(self._dir(td, ident=False), "C1")
            self.assertIn("must carry signs, ident and term", str(cm.exception))

    def test_1_rec_v3_without_the_sign_key_still_passes_as_c1_5_did(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            rep = lr.rate_report_from_evidence_dir(self._dir(td, protocol="rec-v3", signs="absent", ident=False, term=False), "C1")
            self.assertEqual(rep["nominal"]["excluded_seqs"], [39]); self.assertEqual(rep["recovery"]["sign_retries"], 0)
        rep = lr.rate_report_from_evidence_dir(R / "evidence/l6_17A6_2026-09-02-01-C1", "C1")
        self.assertEqual(rep["inclusive"]["n"], 63)

    def test_1_a_non_integer_seq_anywhere_is_a_rate_error_not_a_bare_value_error(self):
        c15 = R / "evidence/l6_17A6_2026-09-02-01-C1"
        log = json.loads((c15 / "run_log.json").read_text()); audits = json.loads((c15 / "audits.json").read_text())
        frames = json.loads((c15 / "timeline.json").read_text())["frames"]
        inputs = {k: "0" * 64 for k in ("run_log", "audits", "timeline")}
        for key in ("recs", "pulls"):
            a = copy.deepcopy(audits); a[key][0]["seq"] = "one"
            with self.assertRaises(lr.RateError) as cm:
                lr.rate_report(log, "C1", None, audits=a, frames=frames, inputs_sha256=inputs)
            self.assertIn("without an integer seq", str(cm.exception))
        with self.assertRaises(lr.RateError):
            lr.recovery_by_seq({1: {"t_signreq": 0.0}}, [1], {"pulls": [], "recs": [], "signs": [{"seq": "x"}]}, [])


class ClosingControlIsMandatory(unittest.TestCase):
    def _summary(self, **over):
        s = copy.deepcopy(GOOD_LOG["session_summary"]); s.update(over); return s

    def test_2_a_missing_block_a_missing_field_and_a_wrong_type_are_each_named(self):
        s = self._summary(); del s["closing_control"]
        self.assertEqual(rel.closing_control_findings(s), ["TERM carries no closing_control block (v0.6 §2.6o requires the complete closing control)"])
        s = self._summary(); del s["closing_control"]["nonce_after"]
        self.assertEqual(rel.closing_control_findings(s), ["TERM closing_control lacks 'nonce_after'"])
        s = self._summary(); s["closing_control"]["fault"] = "13"
        self.assertEqual(rel.closing_control_findings(s), ["TERM closing_control.fault is not an integer"])
        s = self._summary(); s["closing_control"]["nonce_before"] = "ZZ"
        self.assertIn("nonce_before is not 16 lowercase hex", rel.closing_control_findings(s)[0])
        self.assertEqual(rel.closing_control_findings(self._summary()), [])
        # an epoch stopped before the closing control carries no block — and must not
        s = self._summary(); s["closing"] = {"restore": "done", "baseline": "not_reached", "unsigned_control": "not_reached"}
        del s["closing_control"]
        self.assertEqual(rel.closing_control_findings(s), [])
        s["closing_control"] = self._summary()["closing_control"]
        self.assertIn("was not reached", rel.closing_control_findings(s)[0])

    def test_2_the_closure_check_holds_an_app_written_term_without_the_complete_control_even_when_close_arrived(self):
        log = copy.deepcopy(GOOD_LOG); del log["session_summary"]["closing_control"]
        out = lc.rel_closure_findings(log, GOOD_LEDGERS, GOOD_PULLS)
        self.assertEqual(out, ["TERM carries no closing_control block (v0.6 §2.6o requires the complete closing control)"])
        log = copy.deepcopy(GOOD_LOG); log["session_summary"]["closing_control"]["status"] = 0x982
        self.assertEqual(lc.rel_closure_findings(log, GOOD_LEDGERS, GOOD_PULLS), ["TERM closing_control.status is not a string"])
        crashed = copy.deepcopy(GOOD_LOG); crashed["session_summary"] = {"written_by": "collector", "epoch_end": {"kind": "CRASHED"}}
        self.assertNotIn("closing_control", " ".join(lc.rel_closure_findings(crashed, dict(GOOD_LEDGERS, term=None), GOOD_PULLS)),
                         "a collector-written summary has no TERM to carry it")

    def test_2_on_the_real_session_close_lost_is_rebuilt_only_from_a_complete_term_and_both_present_must_agree(self):
        S = c1.Session("make"); S.setUp = lambda: None
        # (a) CLOSE lost, complete TERM → rebuilt
        cs, sent, col, rl, tl = S.make(); S.feed(cs, base.IDENT_LINE); S.feed(cs, base.signreq_line(1)); S.pull(cs)
        S.feed(cs, base.term_line(seq=2))
        self.assertEqual(col.closing_negative["source"], "TERM"); self.assertIsNone(cs.closing_conflict)
        # (b) CLOSE lost, TERM without the block → nothing rebuilt, the closure check names it
        cs, sent, col, rl, tl = S.make(); S.feed(cs, base.IDENT_LINE); S.feed(cs, base.signreq_line(1)); S.pull(cs)
        S.feed(cs, base.term_line(seq=2, with_closing=False))
        self.assertIsNone(col.closing_negative)
        out = lc.rel_closure_findings({"app_identity": col.app_identity, "loop_records": [], "session_summary": col.session_summary},
                                      cs.rel_ledgers_json(), [])
        self.assertTrue(any("carries no closing_control" in f for f in out))
        # (c) CLOSE present, TERM without the block → the CLOSE stands AND the missing block is still a finding
        cs, sent, col, rl, tl = S.make(); S.feed(cs, base.IDENT_LINE); S.feed(cs, base.signreq_line(1)); S.pull(cs)
        close = {"fault": 13, "kind": "unsigned", "status": "0x00000982", "nonce_before": "3" * 16, "nonce_after": "4" * 16}
        S.feed(cs, n.build_line(n.T_CLOSE, 1, TOKEN, n.encode_payload(close))); S.feed(cs, base.term_line(seq=2, with_closing=False))
        self.assertEqual(col.closing_negative["fault"], 13); self.assertNotIn("source", col.closing_negative)
        out = lc.rel_closure_findings({"app_identity": col.app_identity, "loop_records": [], "session_summary": col.session_summary},
                                      cs.rel_ledgers_json(), [])
        self.assertTrue(any("carries no closing_control" in f for f in out), "item 2: a valid CLOSE does not excuse the TERM")
        # (d) both present and equal → no finding; different → the conflict (test_l6_rel_correction::test_7)
        cs, sent, col, rl, tl = S.make(); S.feed(cs, base.IDENT_LINE); S.feed(cs, base.signreq_line(1)); S.pull(cs)
        S.feed(cs, n.build_line(n.T_CLOSE, 1, TOKEN, n.encode_payload(close))); S.feed(cs, base.term_line(seq=2))
        out = lc.rel_closure_findings({"app_identity": col.app_identity, "loop_records": [], "session_summary": col.session_summary},
                                      dict(cs.rel_ledgers_json(), signs=[dict(GOOD_LEDGERS["signs"][0])]), [])
        self.assertEqual([f for f in out if "closing" in f.lower()], [])


class Bit5Echo(unittest.TestCase):
    IDENT = dict(base.IDENT_PAYLOAD)

    def test_3_check_l6_identity_verifies_the_sign_retry_control_echo_when_asked(self):
        ok = records.check_l6_identity(self.IDENT, 7, "random_safe_forced", "0" * 64, protocol="rel-v4",
                                       rec_retry_control=True, sign_retry_control=True)
        self.assertTrue(ok["sign_retry_control"])
        for bad in (dict(self.IDENT, sign_retry_control=False), {k: v for k, v in self.IDENT.items() if k != "sign_retry_control"},
                    dict(self.IDENT, sign_retry_control="yes")):
            with self.assertRaises(records.RecordError) as cm:
                records.check_l6_identity(bad, 7, "random_safe_forced", "0" * 64, protocol="rel-v4",
                                          rec_retry_control=True, sign_retry_control=True)
            self.assertIn("sign_retry_control", str(cm.exception))
        # not asked (rec-v3): an IDENT without the field passes, as C1 #5's did
        old = {k: v for k, v in self.IDENT.items() if k != "sign_retry_control"}
        records.check_l6_identity(old, 7, "random_safe_forced", "0" * 64, protocol="rel-v4", rec_retry_control=True)

    def test_3_the_runner_expects_the_echo_under_rel_v4_only_at_both_checks(self):
        self.assertTrue(l6._sign_control_expectation({"protocol": "rel-v4", "flags": ls.FLAG_SIGN_CONTROL}))
        self.assertFalse(l6._sign_control_expectation({"protocol": "rel-v4", "flags": 0}))
        self.assertIsNone(l6._sign_control_expectation({"protocol": "rec-v3", "flags": ls.FLAG_SIGN_CONTROL}))
        src = inspect.getsource(l6.run_l6)
        self.assertEqual(src.count("sign_retry_control=_sign_control_expectation(plan)"), 2,
                         "the identity_check before the IDENTACK and the adjudication after the session")


class BoundContract(unittest.TestCase):
    def test_4_the_linger_is_derived_from_the_pinned_wall_bound_and_the_contract_names_the_poll_counts(self):
        self.assertEqual(rel.TERM_LINGER_S, (rel.MAX_ATTEMPTS - 1) * rel.BOARD_BOUND_WALL_MAX_S + rel.LINGER_MARGIN_S)
        self.assertEqual(rel.BOARD_BOUND_S, rel.BOARD_BOUND_WALL_MAX_S, "the twins model the bound at its upper bound")
        c = rel.FIRMWARE_BOUND_CONTRACT
        self.assertEqual(c["poll_bound_wall_max_s"], 10.0)
        for name in ("P3_IDENT_IDLE_POLLS", "P3_SIGN_IDLE_POLLS", "P3_PULL_IDLE_POLLS", "P3_REC_IDLE_POLLS", "P3_TERM_IDLE_POLLS"):
            self.assertIn(name, c["applies_to"])
        self.assertIn("source-audit test", c["proof"])
        draft = (R / "docs/l6_soak_prereg_v0.6_draft.md").read_text()
        self.assertIn("BOARD_BOUND_WALL_MAX_S", draft); self.assertIn("poll count", draft)


class MinorItems(unittest.TestCase):
    def test_5_after_a_refusal_only_a_byte_identical_ident_is_a_repeat(self):
        host = rel.IdentHost(TOKEN, lambda ident: ["refused"], send=lambda l: None)
        host.on_line(base.IDENT_LINE.rstrip("\n")); host.on_line(base.IDENT_LINE.rstrip("\n"))
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["refused", "refused-repeat"]); self.assertIsNone(host.protocol_end)
        other = n.build_line(n.T_IDENT, 0, TOKEN, n.encode_payload({**base.IDENT_PAYLOAD, "master_seed": 8}))
        host.on_line(other.rstrip("\n"))
        self.assertEqual(host.ledger.attempts[-1]["outcome"], "conflict"); self.assertTrue(host.ledger.conflict)
        self.assertIn("different IDENT after a refusal", host.protocol_end)

    def test_6_the_heartbeat_budget_is_documented_as_records_complete_not_frames(self):
        doc = rel.hb_missing_budget.__doc__
        self.assertIn("99.9 % of the SCORED records carry all 16 heartbeats", doc)
        self.assertIn('NOT "99.9 % of the 16 R frames"', doc)


if __name__ == "__main__":
    unittest.main()
