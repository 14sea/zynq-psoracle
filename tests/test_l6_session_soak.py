"""S #2 host batch, part 3 — the modelled-channel SESSION soak (`host/l6_session_soak.py`):
whole rel-v4 sessions of the board twins driven against the real host stack over a channel
that injects the S #2 fault class (a contiguous deletion run that crosses frame
boundaries), plus truncation, CRC corruption, duplication, whole-line loss and lost
host→board acknowledgements.

What the tests lock:
  * a clean session COMPLETES with every record accepted once and no gate finding;
  * the S #2 shape scripted into a session (a run starting in `HB #12` and carrying into
    the REC's head) — under the v0.7 ledger policy the epoch COMPLETES and that record is
    accepted on the board's resend; under v0.6 the same bytes end it `CRASHED`;
  * the deletion run is a BURST: its remainder expires when the wire goes idle, so it can
    never eat a line the board sends seconds later on a transaction's bound (the model
    artefact that made three AUDIT_READY resends vanish 50 s apart);
  * the committed evidence: 12 seeds × 300 candidates (ledger COMPLETED 302/302 with zero
    unrecovered faults every time; crash CRASHED at the first malformed line every time)
    and 3 soak-sized sessions (N = 12568, the `policy_matched_wall` candidate under D-n1
    as ruled) at a ~6× stress line rate, where the v0.7 heartbeat rule is clean and the
    v0.6 rule is not.

Only the PROTOCOL gates run over the model's artefacts, and the report names exactly which
(`structural_v06`/`structural_v07`, REC closure and control, rel-v4 closure and control,
baseline). `soak_findings` — the heartbeat GAP, the CRC and bad-frame budgets, the wall
fraction and the settle bound — needs a rate report and a real duration and is NOT run
here; the bad-frame bound is exercised directly in `tests/test_l6_s2_host_batch.py`.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_session_soak as ss  # noqa: E402

MATRIX = json.loads((R / "evidence/l6_session_soak/rel_v4_session_soak_2026-09-03.json").read_text())
SIZED = json.loads((R / "evidence/l6_session_soak/rel_v4_soak_sized_2026-09-03.json").read_text())
# S #2's exact shape: the run starts 58 bytes into HB #12, eats its tail (8) + HB #13–#15
# whole (3 × 66) + the REC's head and 300 bytes of its body, so the REC's TAIL survives and
# glues to the HB remnant into one malformed line — 850 would eat the REC whole and leave
# no merged line at all (the recording's REC 145 kept 1663 of its 2248 body characters)
S2_SHAPE = [{"type": "HB", "seq": 10, "hb_i": 12, "kind": "delete_run", "offset": 58, "length": 506}]


class CleanSession(unittest.TestCase):
    def test_the_report_names_exactly_which_gates_it_ran(self):
        """Owner's review 2026-09-03: "every gate empty" overstated it — the model runs the
        PROTOCOL gates, not soak_findings (which needs a rate report and a real duration)."""
        r = ss.SessionSoak(11, 64, 0.0, 0.0, lcs.BAD_FRAME_LEDGER).run()
        self.assertEqual(sorted(r["gates"]), ["baseline", "rec_closure", "rec_control", "rel_closure",
                                              "rel_control", "structural_v06", "structural_v07"])
        src = __import__("inspect").getsource(ss.SessionSoak.report)
        self.assertNotIn("soak_findings", src, "the soak check is not run here and is not claimed")

    def test_a_session_without_faults_completes_and_every_protocol_gate_is_empty(self):
        r = ss.SessionSoak(11, 64, 0.0, 0.0, lcs.BAD_FRAME_LEDGER).run()
        self.assertEqual(r["epoch_end"], {"kind": "COMPLETED", "last_seq": 66, "reason": "budget"})
        self.assertEqual((r["records_accepted"], r["records"]), (66, 66))
        self.assertEqual((r["bad_frames"], r["fragments"]), (0, 0))
        self.assertEqual(r["crc_dropped"], 2, "the two forced controls are the only CRC drops")
        self.assertEqual(r["crc_dropped_by_type"], {"SIGNREQ": 1, "REC": 1})
        self.assertEqual({k: v for k, v in r["gates"].items() if v}, {}, "no protocol-gate finding on a clean session")
        self.assertEqual(r["board_stats"]["waits_sent"], 0)

    def test_the_controls_are_what_the_gates_expect(self):
        r = ss.SessionSoak(11, 64, 0.0, 0.0, lcs.BAD_FRAME_LEDGER).run()
        self.assertEqual(r["gates"]["rec_control"], []); self.assertEqual(r["gates"]["rel_control"], [])
        self.assertEqual(r["gates"]["rec_closure"], []); self.assertEqual(r["gates"]["rel_closure"], [])
        self.assertEqual(r["gates"]["baseline"], [])


class S2ShapeInASession(unittest.TestCase):
    def run_shape(self, policy: str):
        return ss.SessionSoak(5, 20, 0.0, 0.0, policy, scripted=list(S2_SHAPE)).run()

    def test_under_the_ledger_policy_the_session_completes_and_the_record_is_accepted(self):
        r = self.run_shape(lcs.BAD_FRAME_LEDGER)
        self.assertEqual(r["epoch_end"], {"kind": "COMPLETED", "last_seq": 22, "reason": "budget"})
        self.assertEqual(r["records_accepted"], 22, "seq 10 among them: the board resent the same bytes")
        self.assertEqual(r["bad_frames"], 1, "the merged line, once")
        hit = r["fault_log"][0]["hit"]
        self.assertEqual(hit[0]["type"], n.T_HB); self.assertEqual(hit[0]["seq"], 10)
        self.assertEqual([h["type"] for h in hit[-1:]], [n.T_REC], "the run carried into the REC")
        self.assertFalse(hit[-1]["whole"], "it ended INSIDE the REC: its tail survived and merged")
        self.assertEqual(sum(1 for h in hit if h["type"] == n.T_HB and h.get("whole")), 3, "HB #13-#15 whole")
        self.assertEqual(r["records_missing_heartbeats"], [10])

    def test_under_v06_the_same_bytes_end_the_epoch(self):
        r = self.run_shape(lcs.BAD_FRAME_CRASH)
        self.assertEqual(r["epoch_end"]["kind"], "CRASHED"); self.assertEqual(r["epoch_end"]["reason"], "unparseable frame")
        self.assertEqual(r["records_accepted"], 9, "the epoch ended before seq 10's record")

    def test_the_two_heartbeat_rules_differ_on_exactly_this_record(self):
        r = self.run_shape(lcs.BAD_FRAME_LEDGER)
        self.assertTrue(any("seq 10 (SCORED): 4 heartbeats missing" in f for f in r["gates"]["structural_v06"]))
        v07 = r["gates"]["structural_v07"]
        self.assertEqual(len(v07), 1)
        self.assertIn("1 SCORED records miss heartbeats", v07[0])
        self.assertIn("floor(R/1000) = 0", v07[0], "a 20-candidate session budgets no record; a soak budgets 12")


class TheDeletionRunIsABurst(unittest.TestCase):
    def test_the_carry_expires_when_the_wire_goes_idle(self):
        faults: list[dict] = []
        w = ss.FaultyWire(__import__("random").Random(0), 0.0, faults,
                          scripted=[{"type": n.T_HB, "seq": 1, "kind": "delete_run", "offset": 10, "length": 5000}])
        hb = ss.rel.hb_line(ss.TOKEN, 1, 0)
        self.assertEqual(w.apply(hb, 100.0), hb.encode()[:10], "the rest of the line is eaten")
        self.assertGreater(w.carry, 0)
        nxt = ss.rel.hb_line(ss.TOKEN, 1, 1)
        self.assertEqual(w.apply(nxt, 100.0 + ss.CARRY_MAX_GAP_S / 2), b"", "still in the burst: eaten whole")
        later = ss.rel.hb_line(ss.TOKEN, 1, 2)
        self.assertEqual(w.apply(later, 110.0), later.encode(), "10 s later the burst is long over")
        self.assertEqual(w.carry, 0)

    def test_without_the_bound_one_run_would_swallow_a_transactions_resends(self):
        """The model artefact this bound removes: a 900-byte run 'ate' three AUDIT_READY
        resends that the board sent 10 s apart, and the session died of silence."""
        src = __import__("inspect").getsource(ss.FaultyWire.apply)
        self.assertIn("self.carry and t > self.carry_until", src)
        self.assertIn("the burst ended: the wire went idle", src)


class CommittedEvidence(unittest.TestCase):
    def test_the_matrix_is_twelve_seeds_of_both_policies(self):
        led = [r for r in MATRIX["runs"] if r["policy"] == "ledger"]
        crash = [r for r in MATRIX["runs"] if r["policy"] == "crash"]
        self.assertEqual((len(led), len(crash)), (12, 12))
        self.assertEqual({r["candidates"] for r in MATRIX["runs"]}, {300})
        self.assertEqual({r["p_fault"] for r in MATRIX["runs"]}, {0.004})

    def test_under_the_ledger_policy_every_seed_completed_with_no_unrecovered_fault(self):
        led = [r for r in MATRIX["runs"] if r["policy"] == "ledger"]
        for r in led:
            self.assertEqual(r["epoch_end"], {"kind": "COMPLETED", "last_seq": 302, "reason": "budget"}, r["seed"])
            self.assertEqual(r["records_accepted"], 302, r["seed"])
            self.assertEqual(r["faults_unrecovered"], [], r["seed"])
            self.assertLessEqual(r["crc_dropped"], r["crc_budget"], r["seed"])
        self.assertGreaterEqual(sum(r["faults"] for r in led), 200, "the soak really was faulty")
        self.assertGreaterEqual(sum(r["faults_into_rec"] for r in led), 30, "runs that reached a REC line")
        self.assertGreaterEqual(sum(r["faults_crossing_lines"] for r in led), 50, "runs that crossed frame boundaries")
        self.assertGreaterEqual(sum(r["bad_frames"] for r in led), 40, "malformed lines the ledger policy absorbed")

    def test_under_v06_every_seed_crashed_on_a_malformed_line(self):
        for r in [x for x in MATRIX["runs"] if x["policy"] == "crash"]:
            self.assertEqual(r["epoch_end"]["kind"], "CRASHED", r["seed"])
            self.assertEqual(r["epoch_end"]["reason"], "unparseable frame", r["seed"])
            self.assertEqual(r["bad_frames"], 1, "it ends at the FIRST one")
            self.assertLess(r["records_accepted"], 302, r["seed"])

    def test_the_rec_transaction_did_the_recovering(self):
        led = [r for r in MATRIX["runs"] if r["policy"] == "ledger"]
        two = sum(int(r["rec_attempt_histogram"].get("2", 0)) for r in led)
        one = sum(int(r["rec_attempt_histogram"].get("1", 0)) for r in led)
        self.assertGreaterEqual(two, 20, "records that needed a second REC transmission")
        self.assertEqual(one + two, 12 * 302, "every record's ledger, no third attempt anywhere")
        self.assertGreater(sum(r["board_stats"]["ready_sent"] for r in led), 12 * 20, "AUDIT_READY resends too")

    def test_the_soak_sized_runs_separate_the_two_heartbeat_rules(self):
        self.assertEqual(len(SIZED["runs"]), 3)
        for r in SIZED["runs"]:
            self.assertEqual(r["candidates"], 12568, "the policy_matched_wall candidate N (D-n1, max arm)")
            self.assertEqual(r["epoch_end"], {"kind": "COMPLETED", "last_seq": 12570, "reason": "budget"}, r["seed"])
            self.assertEqual(r["records_accepted"], 12570, r["seed"])
            self.assertEqual(r["faults_unrecovered"], [], r["seed"])
            self.assertEqual(r["gates"]["structural_v07"], [], f"seed {r['seed']}: the v0.7 rule is clean")
            self.assertTrue(r["gates"]["structural_v06"], f"seed {r['seed']}: v0.6 HOLDs the whole soak")
            self.assertLessEqual(len(r["records_missing_heartbeats"]), 12, "within floor(R/1000)")
            self.assertEqual({k: v for k, v in r["gates"].items() if v and not k.startswith("structural")}, {}, r["seed"])

    def test_v06_holds_a_soak_that_recovered_everything(self):
        """The argument for the v0.7 rule, from the evidence rather than asserted: one
        contiguous loss takes several heartbeats of ONE record, so v0.6's per-record cap
        fails a soak in which every record was recovered and accepted."""
        for r in SIZED["runs"]:
            per_record = [f for f in r["gates"]["structural_v06"] if "the bound is one per record" in f]
            self.assertTrue(per_record, r["seed"])
            self.assertEqual(r["records_accepted"], r["records"], "…while every record was accepted")


if __name__ == "__main__":
    unittest.main()
