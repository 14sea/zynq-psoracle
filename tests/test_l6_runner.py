"""host/l6_runner.py and host/l6_checks.py — the host-side behaviour of the L6 runner.

The runner cannot run today (the manifest is a draft with null pins) and these tests pin
that it refuses, in the documented order, for the documented reason each time: each
refusal is REACHED (the earlier checks are satisfied by fixtures) and is ABOUT its check.
The session plan and the PASS/HOLD conditions are pure and are tested as numbers."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "tests"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l6_checks as lc  # noqa: E402
import l6_runner as l6  # noqa: E402
import l6_schedule as ls  # noqa: E402
import l6_timing as lt  # noqa: E402
import test_d1_records as d1  # noqa: E402
from test_l6_timing import frames_for  # noqa: E402

L6M = json.loads((R / "manifests/l6_manifest.json").read_text())
LOAD = 1250000035


CONTRACT = L6M["operator"]["operator_data_sha256"]


def report(session: str, rate: float, median_polls: float = 16.0, contract: str = CONTRACT) -> dict:
    return {"schema": "l6_rate_report", "session": session, "schedule_mode": L6M["sessions"][session]["mode"],
            "evals_per_hour": rate, "settle_polls": {"median": median_polls}, "operator_data_sha256": contract}


class Plan(unittest.TestCase):
    def test_c1_is_64_random_safe_all_self_reporting_watchdog_on(self):
        p = l6.plan_session(L6M, "C1", 0x1234, 7200.0, None, None)
        self.assertEqual((p["n"], p["mode"], p["audit_policy"]), (64, ls.MODE_A_FORCED, "all-self-reporting"))
        self.assertEqual(p["audit_seqs"], ls.all_seqs(64))
        self.assertEqual(p["flags"], ls.FLAG_WATCHDOG | 1 << ls.MODE_FLAG_SHIFT)
        self.assertTrue(all(r["arm"] == ls.ARM_A for r in p["schedule"]))
        self.assertEqual(p["expected_frames"]["total"], 1 + 66 + 66 * 16 + 66 * 8 + 66 + 1 + 1)
        self.assertEqual(p["crc_budget"], 7)                            # ceil(4 × 1719 / 1000)

    def test_c2_forces_map_guided(self):
        p = l6.plan_session(L6M, "C2", 1, 7200.0, None, None)
        self.assertTrue(all(r["arm"] == ls.ARM_B for r in p["schedule"]))
        self.assertEqual(p["flags"], ls.FLAG_WATCHDOG | 2 << ls.MODE_FLAG_SHIFT)

    def test_soak_derives_n_budget_and_timeout_from_the_calibration_rates(self):
        p = l6.plan_session(L6M, "S", 5, 7200.0, {"C1": report("C1", 120.0), "C2": report("C2", 100.0)}, None)
        self.assertEqual(p["n"], 180); self.assertEqual(p["audit_policy"], "sampled")
        self.assertEqual(p["audit_seqs"], ls.sampled_audit_seqs(180))
        self.assertEqual(p["session_timeout_s"], ls.session_timeout_s(180, 120.0, 100.0))
        self.assertEqual(p["crc_budget"], ls.crc_budget(p["expected_frames"]["total"]))
        self.assertEqual(p["inputs"]["rate_C2_per_h"], 100.0)
        self.assertEqual(p["flags"], ls.FLAG_WATCHDOG)                 # abba = mode 0
        self.assertEqual([r["arm"] for r in p["schedule"][:4]], [ls.ARM_A, ls.ARM_B, ls.ARM_B, ls.ARM_A])

    def test_soak_refuses_a_report_of_the_wrong_session_or_without_a_rate(self):
        with self.assertRaises(ValueError):
            l6.plan_session(L6M, "S", 5, 7200.0, {"C1": report("C2", 120.0), "C2": report("C2", 100.0)}, None)
        bad = report("C1", 120.0); del bad["evals_per_hour"]
        with self.assertRaises(ValueError):
            l6.plan_session(L6M, "S", 5, 7200.0, {"C1": bad, "C2": report("C2", 100.0)}, None)
        with self.assertRaises(ValueError):
            l6.plan_session(L6M, "S", 5, 7200.0, None, None)

    def test_soak_refuses_a_calibration_under_another_operator_contract(self):
        """mutation_bits (and the map data) are the operator contract: a calibration run
        under a different operator_data_sha256 cannot budget this soak (owner 2026-09-01)."""
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(L6M, "S", 5, 7200.0, {"C1": report("C1", 120.0, contract="00" * 32),
                                                   "C2": report("C2", 100.0)}, None)
        self.assertIn("operator contract", str(cm.exception)); self.assertIn("re-run", str(cm.exception))

    def test_master_seed_is_32_bit_and_n_is_never_typed(self):
        with self.assertRaises(ValueError):
            l6.plan_session(L6M, "C1", 1 << 32, 7200.0, None, None)
        import inspect
        src = inspect.getsource(l6.main)
        self.assertNotIn('"--budget"', src); self.assertNotIn('"--n"', src)


class Refusals(unittest.TestCase):
    """Each refusal is reached and is about its own check."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "img.bin").write_bytes(b"the two-operator image stand-in")
        self.image_sha = hashlib.sha256((self.tmp / "img.bin").read_bytes()).hexdigest()
        (self.tmp / "ruling.json").write_text(json.dumps(
            {"ruling": l6.RULING_TEXT, "boardid": "17A6", "granted_by": "14sea", "date": "2026-09-99-01"}))
        (self.tmp / "l5ruling.json").write_text(json.dumps(
            {"ruling": "whole-of-probe P3-L5", "boardid": "17A6", "granted_by": "14sea", "date": "2026-09-99-02"}))
        self.boundary(True)

    def boundary(self, ok: bool):
        (self.tmp / "boundary.json").write_text(json.dumps(
            {"schema": "principal_boundary", "schema_version": "1.0.0", "runner_user": "test",
             "signer_user": "p3signer", "pod_group": "p3jtag", "key_store": "/var/lib/p3signer/keys",
             "all_passed": ok, "checks": [{"check": c, "passed": ok, "detail": "fixture"} for c in
                                          ("R1_runner_is_not_signer", "R2_runner_cannot_read_key",
                                           "R3_runner_cannot_open_pod", "R4_signer_reachable_and_holds_key",
                                           "R5_signer_in_pod_group")], "at": time.time()}))

    def manifest(self, *, frozen=True, image=True, watchdog=True, calib=None) -> Path:
        m = copy.deepcopy(L6M)
        if frozen:
            m["prereg"]["sha256"] = hashlib.sha256((R / "docs/l6_soak_prereg.md").read_bytes()).hexdigest()
        # the committed manifest now pins the real image; the fixture pins the stand-in or nulls it
        m["pinned_at_build"]["app_image_sha256"] = self.image_sha if image else None
        if not watchdog:
            m["pinned_at_build"]["watchdog_enabled"] = False
        if calib:
            for k, sha in calib.items():
                m["calibration"][k]["rate_report_sha256"] = sha
        p = self.tmp / "l6_manifest.json"
        p.write_text(json.dumps(m))
        return p

    def args(self, session="C1", ruling="ruling.json", manifest: Path | None = None, extra=()) -> list[str]:
        return ["--ruling", str(self.tmp / ruling), "--session", session, "--master-seed", "0x1234",
                "--boundary", str(self.tmp / "boundary.json"), "--out", str(self.tmp / "out"),
                "--manifest", str(R / "builds/p3/carrier_manifest.json"),
                "--bitstream", str(R / "builds/p3/p3.bit"), "--image", str(self.tmp / "img.bin"),
                "--l6-manifest", str(manifest or self.manifest()), *extra]

    def run_main(self, argv) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = l6.main(argv)
        self.assertFalse((self.tmp / "out").exists(), "no evidence dir before the checks pass")
        self.assertFalse((self.tmp / "ruling.json.consumed").exists(), "a refusal never consumes the ruling")
        return rc, err.getvalue()

    def test_an_l5_ruling_is_refused_by_text(self):
        rc, err = self.run_main(self.args(ruling="l5ruling.json"))
        self.assertEqual(rc, 2); self.assertIn("ruling text", err); self.assertIn("P3-L6", err)

    def test_the_real_draft_manifest_cannot_run_anything(self):
        rc, err = self.run_main(self.args(manifest=R / "manifests/l6_manifest.json"))
        self.assertEqual(rc, 2); self.assertIn("not frozen", err)

    def test_a_frozen_prereg_without_a_pinned_image_is_refused(self):
        rc, err = self.run_main(self.args(manifest=self.manifest(image=False)))
        self.assertEqual(rc, 2); self.assertIn("no pinned two-operator image", err)

    def test_an_image_that_is_not_the_pinned_one_is_refused(self):
        (self.tmp / "img.bin").write_bytes(b"something else")
        rc, err = self.run_main(self.args())
        self.assertEqual(rc, 2); self.assertIn("not the pinned one", err)

    def test_the_watchdog_must_be_pinned_on_with_the_d_s1_load(self):
        rc, err = self.run_main(self.args(manifest=self.manifest(watchdog=False)))
        self.assertEqual(rc, 2); self.assertIn("D-s1", err); self.assertIn(str(LOAD), err)

    def test_the_soak_needs_both_pinned_calibration_records(self):
        rc, err = self.run_main(self.args(session="S"))
        self.assertEqual(rc, 2); self.assertIn("D-s3", err); self.assertIn("C1", err)

    def test_a_calibration_record_that_does_not_hash_to_its_pin_is_refused(self):
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(report("C1", 120.0))); c2.write_text(json.dumps(report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        m = self.manifest(calib={"C1": sha(c1), "C2": "00" * 32})
        rc, err = self.run_main(self.args(session="S", manifest=m,
                                          extra=("--calibration-c1", str(c1), "--calibration-c2", str(c2))))
        self.assertEqual(rc, 2); self.assertIn("does not hash to the pinned C2", err)

    def test_every_pin_satisfied_still_stops_at_the_boundary_before_board_contact(self):
        """Proves the earlier checks all passed: the last refusal is the principal boundary."""
        self.boundary(False)
        rc, err = self.run_main(self.args())
        self.assertEqual(rc, 2); self.assertIn("principal boundary NOT established", err)

    def test_soak_with_hashing_calibration_reaches_the_boundary_too(self):
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(report("C1", 120.0))); c2.write_text(json.dumps(report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        self.boundary(False)
        rc, err = self.run_main(self.args(session="S", manifest=self.manifest(calib={"C1": sha(c1), "C2": sha(c2)}),
                                          extra=("--calibration-c1", str(c1), "--calibration-c2", str(c2))))
        self.assertEqual(rc, 2); self.assertIn("principal boundary NOT established", err)


class Checks(unittest.TestCase):
    def setUp(self):
        self.log = d1.make_log()       # seq 1 baseline, 2 scored, 3 refused, 4 baseline; written_by app
        for r in self.log["loop_records"]:
            if r["outcome"] == "SCORED":
                r["evidence"]["score"]["scores"] = list(lc.BASELINE_SCORES)
        self.frames = []
        for seq in (1, 2, 3, 4):
            self.frames += frames_for(seq, 30.0 * seq)

    def test_structural_missing_rec_audit_term(self):
        from test_audit_gate import CHUNKS      # session 3's real chunks are seq 1, complete
        ok = lc.structural_findings(self.log, CHUNKS, {1}, self.frames)
        self.assertEqual(ok, [])
        no_rec = copy.deepcopy(self.log); no_rec["loop_records"] = no_rec["loop_records"][:3]
        self.assertIn("missing REC for seq [4]", lc.structural_findings(no_rec, CHUNKS, {1}, self.frames))
        self.assertTrue(any(f.startswith("missing AUDIT for seq 2") for f in
                            lc.structural_findings(self.log, CHUNKS, {1, 2}, self.frames)))
        auto = copy.deepcopy(self.log); auto["loop_records"][1]["outcome"] = "STOP_ARM"
        self.assertTrue(any("§3a auto" in f for f in lc.structural_findings(auto, CHUNKS, {1}, self.frames)))
        crashed = copy.deepcopy(self.log); crashed["session_summary"]["written_by"] = "collector"
        self.assertTrue(any(f.startswith("missing TERM") for f in lc.structural_findings(crashed, CHUNKS, {1}, self.frames)))

    def test_heartbeat_completeness_per_scored_record(self):
        """Review 2026-09-01: a COMPLETED fixture with every SIGNREQ/AUDIT/REC kept and all
        HB but the first two removed passed every gate. Now the structural gate counts."""
        from test_audit_gate import CHUNKS
        ok = lc.structural_findings(self.log, CHUNKS, {1}, self.frames)
        self.assertEqual(ok, [])                                        # 16 HB each: PASS
        two = [f for f in self.frames if f["type"] != "HB"] + [f for f in self.frames if f["type"] == "HB"][:2]
        found = lc.structural_findings(self.log, CHUNKS, {1}, two)
        self.assertTrue(found, "a log whose heartbeats stopped after the second must HOLD")
        for seq in (1, 2, 4):                                            # the SCORED records, baselines included
            self.assertTrue(any(f.startswith(f"seq {seq} (SCORED)") for f in found), (seq, found))
        self.assertFalse(any(f.startswith("seq 3 ") for f in found))     # the gate refusal carries no HB
        one_short = copy.deepcopy(self.frames)
        one_short.remove(next(f for f in one_short if f["type"] == "HB" and f["seq"] == 4))
        found = lc.structural_findings(self.log, CHUNKS, {1}, one_short)
        self.assertEqual(found, ["seq 4 (SCORED): 15 HB frames, the protocol fixes 16"])
        one_extra = self.frames + [{"dir": "rx", "type": "HB", "seq": 2, "t_mono": 999.0, "t_wall": 999.0}]
        found = lc.structural_findings(self.log, CHUNKS, {1}, one_extra)
        self.assertEqual(found, ["seq 2 (SCORED): 17 HB frames, the protocol fixes 16"])
        # every other soak/baseline gate would still have passed the two-HB log: this gate is the one that holds
        base = dict(log=self.log, frames=two, crc_dropped=0, crc_budget=6, span_s=7000.0, duration_s=7200.0,
                    hb_gap_max_s=20.0, settle_median_calib=16.0, settle_bound_factor=10, wall_fraction_min=0.9)
        self.assertEqual(lc.baseline_findings(self.log), [])
        self.assertEqual([f for f in lc.soak_findings(**base) if "heartbeat" in f], [])

    def test_baselines_must_be_the_pinned_scores(self):
        self.assertEqual(lc.baseline_findings(self.log), [])
        bad = copy.deepcopy(self.log); bad["loop_records"][3]["evidence"]["score"]["scores"][0] = 17
        self.assertTrue(any(f.startswith("closing baseline") for f in lc.baseline_findings(bad)))

    def test_calibration_cov_bound(self):
        self.assertEqual(lc.calibration_findings({"cov": 0.05}, 0.10), [])
        self.assertTrue(lc.calibration_findings({"cov": 0.11}, 0.10)[0].startswith("coefficient of variation"))
        self.assertTrue(lc.calibration_findings({"cov": None}, 0.10))

    def test_soak_conditions_each_fire_alone(self):
        base = dict(log=self.log, frames=self.frames, crc_dropped=0, crc_budget=6, span_s=7000.0, duration_s=7200.0,
                    hb_gap_max_s=20.0, settle_median_calib=16.0, settle_bound_factor=10, wall_fraction_min=0.9)
        self.assertEqual(lc.soak_findings(**base), [])
        self.assertIn("CRC drops 7 exceed", lc.soak_findings(**{**base, "crc_dropped": 7})[0])
        self.assertIn("wall time", lc.soak_findings(**{**base, "span_s": 6000.0})[0])
        slow = copy.deepcopy(self.log); slow["loop_records"][1]["evidence"]["arm"]["settle"]["polls"] = 161
        self.assertIn("settle.polls 161", lc.soak_findings(**{**base, "log": slow})[0])

    def test_heartbeat_gap_is_over_hb_frames_only(self):
        base = dict(log=self.log, crc_dropped=0, crc_budget=6, span_s=7000.0, duration_s=7200.0,
                    hb_gap_max_s=20.0, settle_median_calib=16.0, settle_bound_factor=10, wall_fraction_min=0.9)
        # the review counter-example: HB at 0 and 40 s, AUDIT/REC/SIGNREQ every 10 s between
        mk = lambda t, ty, seq: {"dir": "rx", "type": ty, "seq": seq, "t_mono": t, "t_wall": t}  # noqa: E731
        fr = [mk(0.0, "HB", 1), mk(10.0, "AUDIT", 1), mk(20.0, "REC", 1), mk(30.0, "SIGNREQ", 2), mk(40.0, "HB", 2)]
        found = lc.soak_findings(**{**base, "frames": fr})
        self.assertEqual(len(found), 1); self.assertIn("heartbeat gap", found[0]); self.assertIn("40.0 s", found[0])
        # a late HB inside otherwise dense traffic is caught; the same shift on a REC is not a heartbeat matter
        late_hb = copy.deepcopy(self.frames)
        hb = [f for f in late_hb if f["type"] == "HB"][-1]; hb["t_mono"] += 25.0
        self.assertTrue(any("heartbeat gap" in f for f in lc.soak_findings(**{**base, "frames": late_hb})))
        late_rec = copy.deepcopy(self.frames)
        rec = [f for f in late_rec if f["type"] == "REC"][-1]; rec["t_mono"] += 25.0
        self.assertEqual(lc.soak_findings(**{**base, "frames": late_rec}), [])

    def test_too_few_heartbeats_is_a_hold_not_a_pass(self):
        base = dict(log=self.log, crc_dropped=0, crc_budget=6, span_s=7000.0, duration_s=7200.0,
                    hb_gap_max_s=20.0, settle_median_calib=16.0, settle_bound_factor=10, wall_fraction_min=0.9)
        for fr in ([], [{"dir": "rx", "type": "HB", "seq": 1, "t_mono": 0.0, "t_wall": 0.0}]):
            found = lc.soak_findings(**{**base, "frames": fr})
            self.assertTrue(any("not checkable" in f for f in found), found)

    def test_median_from_a_calibration_report(self):
        self.assertEqual(lc.median_settle_polls_from_report({"settle_polls": {"median": 16.0}}), 16.0)
        self.assertIsNone(lc.median_settle_polls_from_report({}))


if __name__ == "__main__":
    unittest.main()
