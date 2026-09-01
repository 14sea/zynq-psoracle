"""host/l6_schedule.py — the L6 preregistration's arithmetic, pinned.

Every number the runner must derive before a session (arm schedule, sampled audit
schedule, expected frames, CRC budget, N, timeout) is checked against the prereg's own
wording, and the pairing rule is checked against Claim B's sentence ("A,B,B,A ordering
across successive pairs"), not against this module's opinion of it."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l6_schedule as ls  # noqa: E402


class ArmSchedule(unittest.TestCase):
    def test_the_pairing_rule_is_a_b_b_a_across_successive_pairs(self):
        arms = [ls.arm_abba(i) for i in range(8)]
        A, B = ls.ARM_A, ls.ARM_B
        self.assertEqual(arms, [A, B, B, A, A, B, B, A])

    def test_each_pair_shares_one_seed_and_runs_both_arms(self):
        sched = ls.schedule(0x1234, 8, ls.MODE_ABBA)
        for k in range(4):
            a, b = sched[2 * k], sched[2 * k + 1]
            self.assertEqual(a["pair"], k); self.assertEqual(a["seed"], b["seed"])
            self.assertEqual({a["arm"], b["arm"]}, set(ls.ARMS))

    def test_neither_arm_systematically_runs_second(self):
        sched = ls.schedule(7, 64, ls.MODE_ABBA)
        second = [row["arm"] for row in sched if row["index"] % 2 == 1]
        self.assertEqual(second.count(ls.ARM_A), second.count(ls.ARM_B))

    def test_successive_pairs_get_different_seeds(self):
        """Caught live: one xorshift step leaves the high half independent of the low bits,
        so pair 0 and pair 1 (differing only there) yielded the same seed — and the same
        genome in the same arm. The warm-up fixes it; this pins the property."""
        seeds = [ls.pair_seed(0x1234, k) for k in range(64)]
        self.assertEqual(len(set(seeds)), 64)
        self.assertNotEqual(ls.pair_seed(1, 0), ls.pair_seed(2, 0))

    def test_seq_index_mapping_and_brackets(self):
        sched = ls.schedule(1, 5, ls.MODE_ABBA)
        self.assertEqual([r["seq"] for r in sched], [2, 3, 4, 5, 6])
        self.assertEqual(ls.baseline_seqs(5), (1, 7))
        self.assertIsNone(ls.arm_for_seq(sched, 1)); self.assertIsNone(ls.arm_for_seq(sched, 7))
        self.assertEqual(ls.arm_for_seq(sched, 2), ls.ARM_A)

    def test_forced_modes_force_one_arm(self):
        self.assertTrue(all(r["arm"] == ls.ARM_A for r in ls.schedule(1, 16, ls.MODE_A_FORCED)))
        self.assertTrue(all(r["arm"] == ls.ARM_B for r in ls.schedule(1, 16, ls.MODE_B_FORCED)))

    def test_pure_function_of_master_seed_and_index(self):
        self.assertEqual(ls.schedule(99, 32, ls.MODE_ABBA), ls.schedule(99, 32, ls.MODE_ABBA))
        self.assertNotEqual([r["seed"] for r in ls.schedule(99, 4, ls.MODE_ABBA)],
                            [r["seed"] for r in ls.schedule(100, 4, ls.MODE_ABBA)])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            ls.schedule(1, 0, ls.MODE_ABBA)
        with self.assertRaises(ValueError):
            ls.schedule(1, 4, "abab")
        with self.assertRaises(ValueError):
            ls.pair_seed(1 << 32, 0)

    def test_flags_round_trip_and_keep_the_l5_bits(self):
        f = ls.flags_for(ls.MODE_B_FORCED, watchdog=True)
        self.assertEqual(f & 0b11, ls.FLAG_WATCHDOG)              # bit1 = watchdog, bit0 = holdout off
        self.assertEqual(ls.mode_from_flags(f), ls.MODE_B_FORCED)
        self.assertEqual(ls.flags_for(ls.MODE_ABBA, watchdog=False), 0)   # exactly L5's session-4 word
        with self.assertRaises(ValueError):
            ls.mode_from_flags(0b11 << 2)


class SampledAudit(unittest.TestCase):
    def test_every_16th_plus_first_last_candidate_and_both_baselines(self):
        self.assertEqual(ls.sampled_audit_seqs(64), {1, 2, 16, 32, 48, 64, 65, 66})

    def test_small_n_still_has_the_four_fixed_points(self):
        self.assertEqual(ls.sampled_audit_seqs(3), {1, 2, 4, 5})

    def test_all_seqs_is_the_completed_record_set(self):
        self.assertEqual(ls.all_seqs(3), {1, 2, 3, 4, 5})


class ExpectedFramesAndBudget(unittest.TestCase):
    def test_session_4s_shape_is_reproduced_exactly(self):
        """Session 4: N = 8, all-self-reporting → 1 IDENT, 10 SIGNREQ, 160 HB, 80 AUDIT,
        10 REC, 1 CLOSE, 1 TERM (evidence/l5_17A6_2026-09-01-04/console.log)."""
        e = ls.expected_frames(8, ls.all_seqs(8))
        self.assertEqual(e["by_type"], {"IDENT": 1, "CLOSE": 1, "TERM": 1, "SIGNREQ": 10, "HB": 160,
                                        "REC": 10, "AUDIT": 80})
        self.assertEqual(e["total"], 263)

    def test_sampled_soak_counts_only_scheduled_audits(self):
        e = ls.expected_frames(64, ls.sampled_audit_seqs(64))
        self.assertEqual(e["audited_records"], 8); self.assertEqual(e["by_type"]["AUDIT"], 64)
        self.assertEqual(e["total"], 1 + 66 + 66 * 16 + 64 + 66 + 1 + 1)

    def test_budget_is_the_closed_formula_and_rounds_up(self):
        self.assertEqual(ls.crc_budget(263), 2)       # ceil(1.052)
        self.assertEqual(ls.crc_budget(1255), 6)      # ceil(5.02)
        self.assertEqual(ls.crc_budget(250), 1)       # exactly 1.0
        with self.assertRaises(ValueError):
            ls.crc_budget(0)

    def test_the_formula_never_reads_a_received_count(self):
        import inspect
        src = inspect.getsource(ls.expected_frames) + inspect.getsource(ls.crc_budget)
        for word in ("collector", "received", "console", "frames_seen"):
            self.assertNotIn(word, src)


class SoakArithmetic(unittest.TestCase):
    def test_n_is_floor_of_0_9_min_rate_times_hours(self):
        self.assertEqual(ls.soak_n(120.0, 100.0, 7200.0), 180)
        self.assertEqual(ls.soak_n(100.0, 120.0, 7200.0), 180)
        self.assertEqual(ls.soak_n(33.3, 50.0, 3600.0), 29)       # floor(29.97)

    def test_timeout_is_recorded_arithmetic_with_margin(self):
        t = ls.session_timeout_s(180, 120.0, 100.0)
        self.assertEqual(t, 1.25 * 182 * 36 + 600)                 # 3600/100 = 36 s each

    def test_refusals(self):
        with self.assertRaises(ValueError):
            ls.soak_n(0.0, 10.0, 7200.0)
        with self.assertRaises(ValueError):
            ls.session_timeout_s(10, 0.0, 10.0)


if __name__ == "__main__":
    unittest.main()
