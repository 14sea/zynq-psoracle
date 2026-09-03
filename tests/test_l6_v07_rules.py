"""S #2 host batch, part 2 — the v0.7 CANDIDATE rules and their selection:

  * `l6_checks.baseline_findings`: the opening baseline always, the closing one only on a
    COMPLETED epoch (S #2's crash-path artefact reproduced and removed);
  * `l6_rel.heartbeat_findings_v07`: RECORDS budgeted (floor(R/1000)), the per-record cap
    of v0.6 gone — both rules run on the same fixtures so the difference is explicit;
  * `l6_checks.soak_findings`: the soak's bad frames bounded (the D-s4 formula), never
    unbounded tolerance;
  * `l6_runner.rules_for` / `plan_session`: nothing of v0.7 runs under v0.6; under v0.7
    the console policy is "ledger" with the CRC budget as its bound, the heartbeat rule
    v07, and S's N follows the manifest's named `n_rule` — refused when unnamed;
  * `host/l6_soak_plan.py`: the N/T comparison recomputed from the two PINNED calibrations
    (report bytes + the run logs their `inputs` hash) and locked to the values in
    `evidence/l6_soak_plan/n_vs_t_2026-09-03.json`; the post-hoc gate: only
    `policy_matched_wall` passes at S #2's pace; S #1's pace is informational (another
    protocol); the rounded-label counterexample; and D-n1 as RULED 2026-09-03 — the faster
    arm sizes N, the slower one the timeout, and the post-hoc pace excludes seq 1's forced
    controls and is normalised to the candidate's own sampled-audit fraction.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_checks as lc  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_rel as rel  # noqa: E402
import l6_runner as l6  # noqa: E402
import l6_schedule as ls  # noqa: E402
import l6_soak_plan as lsp  # noqa: E402

L6M = json.loads((R / "manifests/l6_manifest.json").read_text())
S2 = R / "evidence/l6_17A6_2026-09-03-03-S"
S1 = R / "evidence/l6_17A6_2026-09-01-11-S"
S2_LOG = json.loads((S2 / "run_log.json").read_text())
TABLE = json.loads((R / "evidence/l6_soak_plan/n_vs_t_2026-09-03.json").read_text())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ baseline gate


class BaselineGate(unittest.TestCase):
    def test_s2s_crash_path_artefact_is_gone_and_the_opening_is_still_checked(self):
        self.assertEqual(lc.baseline_findings(S2_LOG), [], "candidate 144 is not a closing baseline on a CRASHED epoch")
        bad = copy.deepcopy(S2_LOG)
        bad["loop_records"][0]["evidence"]["score"]["scores"] = [18, 22, 20, 20, 20, 19]
        self.assertEqual(lc.baseline_findings(bad), ["opening baseline scores [18, 22, 20, 20, 20, 19] != pinned [18, 22, 20, 20, 20, 18]"])

    def test_a_completed_epoch_checks_both(self):
        log = copy.deepcopy(S2_LOG)
        log["session_summary"]["epoch_end"] = {"kind": "COMPLETED", "last_seq": 144, "reason": "budget"}
        out = lc.baseline_findings(log)
        self.assertEqual(out, ["closing baseline scores [18, 22, 20, 20, 20, 21] != pinned [18, 22, 20, 20, 20, 18]"])
        log["loop_records"][-1]["evidence"]["score"]["scores"] = [18, 22, 20, 20, 20, 18]
        self.assertEqual(lc.baseline_findings(log), [])

    def test_the_c1_6_evidence_is_unchanged_by_the_gate(self):
        log = json.loads((R / "evidence/l6_17A6_2026-09-03-01-C1/run_log.json").read_text())
        self.assertEqual(lc.baseline_findings(log), [])


# ------------------------------------------------------------------ heartbeat rule


def hb_fixture(n_records: int, missing: dict[int, list[int]], token: str = "5c" * 16) -> tuple[dict, list[dict]]:
    log = {"loop_records": [{"seq": s, "outcome": "SCORED", "evidence": {}} for s in range(1, n_records + 1)]}
    frames = []
    for s in range(1, n_records + 1):
        for i in range(16):
            if i in missing.get(s, []):
                continue
            frames.append({"dir": "rx", "type": n.T_HB, "seq": s, "t_mono": float(s * 16 + i), "hb_i": i})
    return log, frames


class HeartbeatRuleV07(unittest.TestCase):
    def test_s2s_shape_one_record_missing_four_in_a_soak_holds_under_v06_and_passes_under_v07(self):
        log, frames = hb_fixture(6063, {145: [12, 13, 14, 15]})
        v06 = rel.heartbeat_findings_rel(log, frames)
        self.assertEqual(len(v06), 1); self.assertIn("seq 145 (SCORED): 4 heartbeats missing", v06[0])
        self.assertEqual(rel.heartbeat_findings_v07(log, frames), [], "one record of a budget of 6")

    def test_seven_records_with_a_missing_heartbeat_in_a_soak_cross_the_record_budget(self):
        log, frames = hb_fixture(6063, {s: [3] for s in range(100, 107)})
        self.assertEqual(rel.heartbeat_findings_rel(log, frames), [f"7 heartbeats missing over 6063 SCORED records > the budget floor(R/1000) = 6"])
        out = rel.heartbeat_findings_v07(log, frames)
        self.assertEqual(len(out), 1); self.assertIn("7 SCORED records miss heartbeats (7 in all", out[0]); self.assertIn("= 6", out[0])

    def test_a_calibration_tolerates_no_missing_heartbeat_under_either_rule(self):
        log, frames = hb_fixture(66, {30: [7]})
        self.assertTrue(rel.heartbeat_findings_rel(log, frames))
        self.assertEqual(rel.heartbeat_findings_v07(log, frames), ["1 SCORED records miss heartbeats (1 in all: [(30, 1)]) > the record budget floor(R/1000) = 0"])

    def test_index_out_of_range_and_unindexed_are_findings_under_v07_too(self):
        log, frames = hb_fixture(3, {})
        frames.append({"dir": "rx", "type": n.T_HB, "seq": 2, "t_mono": 99.0, "hb_i": 16})
        frames.append({"dir": "rx", "type": n.T_HB, "seq": 2, "t_mono": 99.5})
        out = rel.heartbeat_findings_v07(log, frames)
        self.assertTrue(any("index out of range [16]" in f for f in out)); self.assertTrue(any("carry no index" in f for f in out))

    def test_a_duplicate_index_is_harmless(self):
        log, frames = hb_fixture(3, {})
        frames.append({"dir": "rx", "type": n.T_HB, "seq": 2, "t_mono": 99.0, "hb_i": 5})
        self.assertEqual(rel.heartbeat_findings_v07(log, frames), [])

    def test_structural_findings_select_the_rule_and_refuse_an_unknown_one(self):
        log, frames = hb_fixture(6063, {145: [12, 13, 14, 15]})
        log["session_summary"] = {"written_by": "app"}
        self.assertTrue(any("seq 145" in f for f in lc.structural_findings(log, [], set(), frames, protocol="rel-v4")))
        self.assertEqual([f for f in lc.structural_findings(log, [], set(), frames, protocol="rel-v4", hb_rule="v07") if "seq 145" in f], [])
        with self.assertRaises(ValueError):
            lc.structural_findings(log, [], set(), frames, protocol="rel-v4", hb_rule="lenient")


# ------------------------------------------------------------------ the soak's bad-frame bound


class SoakBadFrameBound(unittest.TestCase):
    def soak(self, **kw):
        log, frames = hb_fixture(4, {})
        return lc.soak_findings(log, frames, crc_dropped=0, crc_budget=451, span_s=7000.0, duration_s=7200.0,
                                hb_gap_max_s=20.0, settle_median_calib=16.0, settle_bound_factor=10, wall_fraction_min=0.9, **kw)

    def test_within_the_budget_no_finding_past_it_named(self):
        self.assertEqual(self.soak(bad_frames=451, bad_frame_budget=451), [])
        self.assertEqual(self.soak(bad_frames=452, bad_frame_budget=451), ["bad frames 452 exceed the budget 451 (v0.7: the D-s4 formula applied to malformed lines)"])

    def test_the_v07_rule_never_runs_uncounted_and_v06_is_untouched(self):
        self.assertEqual(self.soak(bad_frames=None, bad_frame_budget=451), ["bad frames not counted: the ledger's bad_frames must be supplied under the v0.7 rule"])
        self.assertEqual(self.soak(), [], "v0.6: no bad-frame bound (the collector's CRASHED rule ended the epoch instead)")


# ------------------------------------------------------------------ rule selection


def manifest_v07(n_rule: str | None = "policy_matched_wall") -> dict:
    m = copy.deepcopy(L6M)
    m["prereg"]["version"] = "v0.7"
    if n_rule is None:
        m["sessions"]["S"].pop("n_rule", None)
    else:
        m["sessions"]["S"]["n_rule"] = n_rule
    return m


class RuleSelection(unittest.TestCase):
    def test_under_v06_nothing_of_v07_runs(self):
        self.assertEqual(L6M["prereg"]["version"], "v0.6")
        r = l6.rules_for(L6M)
        self.assertEqual((r["v07"], r["hb_rule"], r["bad_frame_policy"], r["three_rate"]), (False, "v06", lcs.BAD_FRAME_CRASH, True))
        p = l6.plan_session(L6M, "C1", None, 7200.0, None, None)
        self.assertEqual((p["bad_frame_policy"], p["bad_frame_budget"], p["hb_rule"], p["rules_version"]), (lcs.BAD_FRAME_CRASH, None, "v06", "v0.6"))

    def test_under_v07_the_ledger_policy_the_crc_budget_as_its_bound_and_the_v07_heartbeat_rule(self):
        m = manifest_v07()
        r = l6.rules_for(m)
        self.assertEqual((r["v07"], r["hb_rule"], r["bad_frame_policy"], r["three_rate"]), (True, "v07", lcs.BAD_FRAME_LEDGER, True))
        p = l6.plan_session(m, "C1", None, 7200.0, None, None)
        self.assertEqual((p["bad_frame_policy"], p["bad_frame_budget"], p["hb_rule"]), (lcs.BAD_FRAME_LEDGER, p["crc_budget"], "v07"))
        self.assertEqual(p["crc_budget"], 8)

    def test_the_runner_wires_the_plan_into_the_console_the_gates_and_the_soak_check(self):
        src = inspect.getsource(l6.run_l6)
        self.assertIn('bad_frame_policy=plan.get("bad_frame_policy", lcs.BAD_FRAME_CRASH)', src)
        self.assertIn('bad_frame_budget=plan.get("bad_frame_budget")', src)
        self.assertIn('hb_rule=plan.get("hb_rule", "v06")', src)
        self.assertIn('bad_frames=timeline.bad_frames if plan.get("bad_frame_budget") is not None else None', src)
        pre = inspect.getsource(l6.preflight)
        self.assertIn('rules_for(l6m)["v07"]', pre); self.assertIn("inputs.run_log", pre)
        self.assertIn("calibration_logs=calibration_logs", pre)

    def reports_and_logs(self):
        return lsp.load_pinned(L6M)

    def test_under_v07_s_needs_a_named_n_rule_and_the_calibration_run_logs(self):
        reports, logs = self.reports_and_logs()
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(manifest_v07(n_rule=None), "S", None, 7200.0, reports, None, calibration_logs=logs)
        self.assertIn("sessions.S.n_rule must name one of", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(manifest_v07("policy_matched_wall"), "S", None, 7200.0, reports, None)
        self.assertIn("needs both calibration run logs", str(cm.exception))
        with self.assertRaises(ValueError):
            l6.plan_session(manifest_v07("median_of_something"), "S", None, 7200.0, reports, None, calibration_logs=logs)

    def test_under_v07_the_named_rule_gives_the_soak_plans_n(self):
        reports, logs = self.reports_and_logs()
        for rule in lsp.RULES:
            p = l6.plan_session(manifest_v07(rule), "S", None, 7200.0, reports, None, calibration_logs=logs)
            want = TABLE["rules"][rule]
            self.assertEqual(p["n"], want["n"], rule)
            if rule != "planning":
                self.assertEqual(p["inputs"]["n_rule_trace"]["sizing_arm"], "max", rule)
            self.assertEqual(p["inputs"]["n_rule"], rule)
            self.assertEqual(len(p["audit_seqs"]), want["sampled_audits"])
            self.assertEqual(p["session_timeout_s"], ls.session_timeout_s(want["n"], want["rate_C1"], want["rate_C2"]))
        p6 = l6.plan_session(L6M, "S", None, 7200.0, reports, None)
        self.assertEqual((p6["n"], p6["inputs"]["n_rule"]), (6061, "planning"), "v0.6 is what S #2 ran with")


# ------------------------------------------------------------------ the N/T table, locked to the pinned files


class SoakPlanLocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports, cls.logs = lsp.load_pinned(L6M)

    def test_the_inputs_are_the_pinned_bytes_and_their_hashed_run_logs(self):
        for k in ("C1", "C2"):
            pin = L6M["calibration"][k]
            self.assertEqual(TABLE["calibration_pins"][k]["rate_report_sha256"], pin["rate_report_sha256"])
            self.assertEqual(TABLE["calibration_pins"][k]["inputs"], self.reports[k]["inputs"])
            self.assertEqual(_sha(R / pin["evidence"]), pin["rate_report_sha256"])
            self.assertEqual(_sha((R / pin["evidence"]).parent / "run_log.json"), self.reports[k]["inputs"]["run_log"])
        tampered = copy.deepcopy(L6M); tampered["calibration"]["C1"]["rate_report_sha256"] = "00" * 32
        with self.assertRaises(ValueError):
            lsp.load_pinned(tampered)

    def test_every_rule_recomputes_to_the_table_unrounded(self):
        for rule in lsp.RULES:
            got = lsp.soak_n_for_rule(rule, self.logs, 7200.0)
            want = TABLE["rules"][rule]
            for key in ("n", "unrounded", "rate_C1", "rate_C2", "audit_fraction", "sampled_audits"):
                self.assertAlmostEqual(got[key], want[key], places=9, msg=f"{rule}.{key}")
            self.assertEqual(got["n"], math.floor(got["unrounded"]))
            self.assertLess(abs(got["audit_fraction"] - lsp.audit_fraction(got["n"])), 1e-12, "the fixed point closed")

    def test_the_faster_arm_sizes_n_and_the_slower_one_the_timeout(self):
        """D-n1 as ruled 2026-09-03: min() is right for a timeout and wrong for a wall-time
        floor — a soak running near the faster arm finishes a min-sized N too early."""
        self.assertEqual(lsp.ARM_FOR_RULE["planning"], "min", "the v0.6 control reproduces what S #2 ran")
        for rule in ("policy_matched_period", "policy_matched_wall", "policy_matched_span"):
            plan = TABLE["rules"][rule]
            self.assertEqual(plan["sizing_arm"], "max", rule)
            self.assertEqual(plan["sizing_rate"], max(plan["rate_C1"], plan["rate_C2"]), rule)
            self.assertAlmostEqual(plan["unrounded"], 0.9 * plan["sizing_rate"] * 7200 / 3600, places=9)
            g = plan["gates"]["l6_17A6_2026-09-03-03-S"]
            self.assertEqual(g["timeout_s"], ls.session_timeout_s(plan["n"], plan["rate_C1"], plan["rate_C2"]), rule)
        wall = TABLE["rules"]["policy_matched_wall"]
        self.assertEqual((wall["n"], wall["sampled_audits"]), (12568, 789), "the owner's regression target")
        self.assertEqual(wall["gates"]["l6_17A6_2026-09-03-03-S"]["timeout_s"], 8739)

    def test_the_two_estimators_the_owner_named_are_both_here_and_differ_by_the_stated_amount(self):
        t = TABLE["rules"]
        self.assertAlmostEqual(t["policy_matched_period"]["rate_C2"], 6199.917170, places=5)   # ≈ "6197" (the period estimator)
        self.assertAlmostEqual(t["policy_matched_wall"]["rate_C2"], 6950.492576, places=5)     # ≈ "6952" (the wall estimator)
        self.assertEqual((t["policy_matched_period"]["n"], t["policy_matched_wall"]["n"], t["planning"]["n"]), (11201, 12568, 6061))
        # the difference is the inter-record gap: period − wall (≈ 0.06 s per record in the calibrations)
        c1 = t["policy_matched_wall"]["per_calibration"]["C1"]
        self.assertAlmostEqual(c1["mean_period_s"] - c1["mean_wall_s"], 0.0627, places=3)

    def test_the_rounded_label_counterexample(self):
        self.assertEqual(math.floor(0.9 * 6952 * 2), 12513)
        self.assertEqual(math.floor(0.9 * 6952.2375 * 2), 12514)
        wall = TABLE["rules"]["policy_matched_wall"]
        self.assertEqual(wall["n"], math.floor(wall["unrounded"]), "N is the floor of the unrounded product, once")
        self.assertNotEqual(wall["n"], math.floor(0.9 * round(wall["sizing_rate"]) * 2),
                            "…and never the floor of a displayed, rounded rate")

    def test_the_post_hoc_pace_excludes_the_seq_1_controls_and_is_normalised(self):
        """The gate's input is the loop's pace, not seq 1's: §2.6c and §2.6k corrupt the
        first transmission of seq 1's REC and SIGNREQ on purpose. And it is normalised to
        the candidate's own sampled-audit fraction before it is compared."""
        obs = lsp.observed_interval_s(S2_LOG)
        self.assertEqual(obs["excluded_seqs"], [1]); self.assertEqual(obs["records_used"], 143)
        self.assertEqual(obs["planned_n"], 6061)
        self.assertAlmostEqual(obs["planned_audit_fraction"], 382 / 6063, places=12)
        raw_all = lsp.observed_interval_s(S2_LOG, exclude_seqs=())["interval_s"]
        self.assertNotAlmostEqual(obs["interval_s"], raw_all, places=6, msg="seq 1 really did cost time")
        g = TABLE["rules"]["policy_matched_wall"]["gates"]["l6_17A6_2026-09-03-03-S"]
        self.assertAlmostEqual(g["observed_interval_s"], obs["interval_s"], places=12)
        self.assertAlmostEqual(g["normalised_interval_s"],
                               obs["interval_s"] - (obs["planned_audit_fraction"] - g["target_audit_fraction"]) * obs["mean_audit_s"],
                               places=12)
        self.assertAlmostEqual(g["predicted_wall_s"], 12568 * g["normalised_interval_s"], places=9)
        self.assertGreater(g["margin_over_floor_s"], 250)     # the owner's estimate was ≈ 304 s

    def test_the_post_hoc_gate_only_the_wall_rule_passes_at_s2s_pace_and_s1_is_informational(self):
        self.assertEqual(TABLE["protocol"], "rel-v4")
        for rule, want in (("planning", False), ("policy_matched_period", False), ("policy_matched_wall", True), ("policy_matched_span", False)):
            g = TABLE["rules"][rule]["gates"]
            self.assertEqual(TABLE["rules"][rule]["gate_pass_all"], want, rule)
            self.assertEqual(TABLE["rules"][rule]["gating_soaks"], ["l6_17A6_2026-09-03-03-S"])
            self.assertFalse(g["l6_17A6_2026-09-01-11-S"]["gates"], "S #1 ran another protocol: informational only")
        w = TABLE["rules"]["policy_matched_wall"]["gates"]["l6_17A6_2026-09-03-03-S"]
        self.assertTrue(w["wall_ok"] and w["timeout_ok"])
        self.assertEqual(w["wall_floor_s"], 6480.0); self.assertEqual(w["timeout_s"], 8739)
        # the observed pace is recomputed from the evidence, not typed
        obs = lsp.observed_interval_s(S2_LOG)
        self.assertAlmostEqual(obs["interval_s"], w["observed_interval_s"], places=12)
        # 144 timed records (seq 145 has no record); seq 1 is excluded (its forced controls),
        # so 143 records and 142 SIGNREQ→SIGNREQ intervals
        self.assertEqual((obs["records"], obs["records_used"], obs["protocol"]), (144, 143, "rel-v4"))
        self.assertAlmostEqual(obs["interval_s"], 0.5402, places=3)
        self.assertEqual(_sha(S2 / "run_log.json"), TABLE["observed"]["l6_17A6_2026-09-03-03-S"]["run_log_sha256"])

    def test_the_observed_pace_never_enters_the_formula(self):
        src = inspect.getsource(lsp.soak_n_for_rule) + inspect.getsource(lsp.policy_matched_rates)
        self.assertNotIn("observed", src); self.assertNotIn("soak", src.replace("soak_n_for_rule", "").replace("SOAK_FRACTION", ""))
        self.assertIn("observed", inspect.getsource(lsp.validation_gate))


if __name__ == "__main__":
    unittest.main()


class V07DraftDrift(unittest.TestCase):
    """The v0.7 freeze candidate must speak in its own present tense (owner's review
    2026-09-03, blocker 4: the first draft inherited v0.6's "calibration.C1/C2 are null",
    "it has not run on hardware", D-p1's per-record heartbeat cap that D-h1 replaces, a
    three-rate rule that did not list v0.7, an order of work that re-ran C1 → C2 → S under
    v0.6, and §6 item 14 printed before item 13)."""

    DRAFT = (R / "docs/l6_soak_prereg_v0.7_draft.md").read_text()

    STALE = ("`calibration.C1`/`C2` are null", "No PASS calibration", "it has not run on hardware",
             "It has not run on hardware.", "`calibration.C1` stays null",
             "never two missing in one record.", "`prereg.version` is v0.5 or v0.6**",
             "ONE C1 → C2 → S under v0.6", "v0.6, FROZEN 2026-09-03")

    PRESENT = ("preregistration v0.7, DRAFT", "Both v0.6 calibrations are pinned and ACTIVE",
               "`08222f85…`", "`959790d0…`", "6q.", "6r.", "D-b1", "D-h1", "D-n1", "D-i1",
               "PROTOCOL_BAD_FRAME_BUDGET", "⌊R/1000⌋ SCORED records", "only when the epoch COMPLETED",
               "the same way twice", "v0.5, v0.6 or v0.7", "ONE soak under v0.7",
               "C1 #6 (PASS), C2 #2 (PASS) and S #2 (HOLD")

    def test_the_draft_carries_none_of_v06s_stale_present_tense(self):
        for stale in self.STALE:
            self.assertNotIn(stale, self.DRAFT, f"the v0.7 draft still says {stale!r}")

    def test_the_draft_says_what_is_true_now(self):
        for present in self.PRESENT:
            self.assertIn(present, self.DRAFT, present)

    def test_the_pass_conditions_are_in_order(self):
        for a, b in zip(range(1, 14), range(2, 15)):
            if f"\n{a}. " in self.DRAFT and f"\n{b}. " in self.DRAFT:
                self.assertLess(self.DRAFT.index(f"\n{a}. **") if f"\n{a}. **" in self.DRAFT else self.DRAFT.index(f"\n{a}. "),
                                self.DRAFT.index(f"\n{b}. **") if f"\n{b}. **" in self.DRAFT else self.DRAFT.index(f"\n{b}. "),
                                f"§6 item {b} is printed before item {a}")
        self.assertLess(self.DRAFT.index("13. the recovery indicators of 3b"),
                        self.DRAFT.index("14. **bad frames bounded"), "item 14 follows item 13")

    def test_the_draft_is_not_marked_frozen_and_the_manifest_still_pins_v06(self):
        self.assertIn("DRAFT, NOT FROZEN", self.DRAFT)
        self.assertIn("That is not yet the case for v0.7", self.DRAFT)
        self.assertEqual(L6M["prereg"]["version"], "v0.6", "the manifest is the owner's to change at the freeze")
        self.assertEqual(hashlib.sha256((R / "docs/l6_soak_prereg.md").read_bytes()).hexdigest(),
                         L6M["prereg"]["sha256"], "…and the frozen text on disk is still the one it pins")

    def test_the_draft_states_the_ruled_n_rule_and_arm(self):
        self.assertIn("policy_matched_wall", self.DRAFT)
        self.assertIn("faster arm", self.DRAFT.replace("FASTER arm", "faster arm"))
        self.assertIn("0.9 T", self.DRAFT)
