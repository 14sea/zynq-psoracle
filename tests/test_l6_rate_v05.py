"""The owner's three freeze blockers on the v0.5 draft (review 2026-09-02):

  1. BOTH ledgers or neither — `l6_rate.rate_report` refuses half a ledger set (audits
     without frames or frames without audits) and invalid ledgers (a REC ledger missing
     for a record, an audited record without a completed pull, frames that carry no
     SIGNREQ for a record); with neither it makes the v0.4 report (no nominal).
  2. Input binding — a report made with the ledgers must name the sha256 of the three
     files it is derived from (`inputs`: run_log / audits / timeline); the CLI hashes the
     files; `l6_checks.calibration_inputs_findings` verifies the files beside a pinned
     calibration; the runner's S import refuses a mismatch (and, under v0.5, a report
     without inputs).
  3. The planning rate — candidates over the whole bracketed span, so a recovery on the
     LAST candidate (which lands in the last→closing transition, outside every
     steady-state period) lowers it while the inclusive rate does not move: the
     counterexample the owner asked for. `plan_session` sizes S from it under v0.5 and
     from `evals_per_hour` under v0.4.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "tests"))
import l6_checks as lc  # noqa: E402
import l6_rate as lr  # noqa: E402
import test_l6_runner as tr  # noqa: E402
l6 = tr.l6

C15 = R / "evidence/l6_17A6_2026-09-02-01-C1"
LOG = json.loads((C15 / "run_log.json").read_text())
AUDITS = json.loads((C15 / "audits.json").read_text())
FRAMES = json.loads((C15 / "timeline.json").read_text())["frames"]
INPUTS = {k: hashlib.sha256((C15 / f).read_bytes()).hexdigest()
          for k, f in (("run_log", "run_log.json"), ("audits", "audits.json"), ("timeline", "timeline.json"))}


def full_report(log=LOG, audits=AUDITS, frames=FRAMES, inputs=INPUTS, session="C1"):
    return lr.rate_report(log, session, None, audits=audits, frames=frames, inputs_sha256=inputs)


class BothLedgersOrNeither(unittest.TestCase):
    def test_half_a_ledger_set_is_refused_never_zero_filled(self):
        with self.assertRaises(lr.RateError) as cm:
            lr.rate_report(LOG, "C1", None, audits=AUDITS, inputs_sha256=INPUTS)
        self.assertIn("half the ledgers", str(cm.exception))
        with self.assertRaises(lr.RateError) as cm:
            lr.rate_report(LOG, "C1", None, frames=FRAMES, inputs_sha256=INPUTS)
        self.assertIn("half the ledgers", str(cm.exception))

    def test_neither_ledger_is_the_v04_report_with_no_nominal(self):
        r = lr.rate_report(LOG, "C1", "ab" * 32)
        self.assertIsNone(r["nominal"]); self.assertIsNone(r["inputs"]); self.assertEqual(r["run_log_sha256"], "ab" * 32)
        self.assertIsNotNone(r["planning"]["evals_per_hour"], "the planning rate needs only the timing")

    def test_invalid_ledger_shapes_are_refused_by_name(self):
        for audits, frames, msg in (([], FRAMES, "audits ledger invalid"),
                                    ({"pulls": [], "recs": "x"}, FRAMES, "audits ledger invalid"),
                                    (AUDITS, [], "timeline frames invalid"),
                                    (AUDITS, [{"dir": "rx"}], "timeline frames invalid")):
            with self.assertRaises(lr.RateError) as cm:
                lr.rate_report(LOG, "C1", None, audits=audits, frames=frames, inputs_sha256=INPUTS)
            self.assertIn(msg, str(cm.exception), msg)

    def test_a_ledger_that_does_not_cover_the_records_is_refused(self):
        a = copy.deepcopy(AUDITS); a["recs"] = [r for r in a["recs"] if r["seq"] != 17]
        with self.assertRaises(lr.RateError) as cm:
            full_report(audits=a)
        self.assertIn("does not cover the records", str(cm.exception))
        a = copy.deepcopy(AUDITS)
        for p in a["pulls"]:
            if p["seq"] == 40:
                p["done"] = False
        with self.assertRaises(lr.RateError) as cm:
            full_report(audits=a)
        self.assertIn("no completed pull for audited records [40]", str(cm.exception))
        f = [x for x in FRAMES if not (x["type"] == "SIGNREQ" and x["seq"] == 5)]
        with self.assertRaises(lr.RateError) as cm:
            full_report(frames=f)
        self.assertIn("no SIGNREQ for records [5]", str(cm.exception))

    def test_the_real_c1_5_ledgers_are_valid(self):
        r = full_report()
        self.assertEqual(r["nominal"]["excluded_seqs"], [39]); self.assertEqual(r["recovery"]["candidates_with_recovery"], 1)


class InputBinding(unittest.TestCase):
    def test_ledgers_without_the_three_input_hashes_are_refused(self):
        for bad in (None, {"run_log": INPUTS["run_log"]}, {**INPUTS, "audits": "zz" * 32}, {**INPUTS, "extra": "00" * 32}):
            with self.assertRaises(lr.RateError):
                lr.rate_report(LOG, "C1", None, audits=AUDITS, frames=FRAMES, inputs_sha256=bad)

    def test_the_report_names_the_three_files_and_one_run_log(self):
        r = full_report()
        self.assertEqual(r["inputs"], INPUTS); self.assertEqual(r["run_log_sha256"], INPUTS["run_log"])
        with self.assertRaises(lr.RateError) as cm:
            lr.rate_report(LOG, "C1", "00" * 32, audits=AUDITS, frames=FRAMES, inputs_sha256=INPUTS)
        self.assertIn("ONE run log file", str(cm.exception))

    def test_the_cli_hashes_the_files_it_reads_and_refuses_half_a_set(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            self.assertEqual(lr.main([str(C15), "--session", "C1", "--out", str(out)]), 0)
            rep = json.loads(out.read_text())
            self.assertEqual(rep["inputs"], INPUTS)
            half = Path(td) / "half"; half.mkdir()
            shutil.copy(C15 / "run_log.json", half); shutil.copy(C15 / "audits.json", half)
            import io
            from contextlib import redirect_stderr
            err = io.StringIO()
            with redirect_stderr(err):
                rc = lr.main([str(half), "--out", str(Path(td) / "h.json")])
            self.assertEqual(rc, 2); self.assertIn("half the ledgers", err.getvalue())

    def test_calibration_inputs_are_verified_beside_the_report(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "cal"; shutil.copytree(C15, d, ignore=shutil.ignore_patterns("rate_report.json"))
            rep = full_report(); rp = d / "rate_report.json"; rp.write_text(json.dumps(rep))
            self.assertEqual(lc.calibration_inputs_findings(rp, rep, required=True), [])
            (d / "audits.json").write_bytes((d / "audits.json").read_bytes() + b"\n")
            bad = lc.calibration_inputs_findings(rp, rep, required=True)
            self.assertEqual(len(bad), 1); self.assertIn("audits.json hashes to", bad[0])
            (d / "timeline.json").unlink()
            self.assertIn("timeline.json is missing", lc.calibration_inputs_findings(rp, rep, required=True)[1])
            old = {k: v for k, v in rep.items() if k != "inputs"}
            self.assertEqual(lc.calibration_inputs_findings(rp, old, required=False), [])
            self.assertIn("carries no `inputs`", lc.calibration_inputs_findings(rp, old, required=True)[0])

    def test_the_runner_refuses_a_pinned_calibration_whose_inputs_moved(self):
        src = inspect.getsource(l6.preflight)
        self.assertIn("lc.calibration_inputs_findings(path, calibration[k], required=", src)
        self.assertIn('D-s3: {k} calibration inputs', src)
        run = inspect.getsource(l6.run_l6)
        self.assertIn('_sha(out_dir / "run_log.json")', run); self.assertIn('_sha(out_dir / "audits.json")', run)
        self.assertIn('_sha(out_dir / "timeline.json")', run); self.assertIn("inputs_sha256=inputs_sha", run)


class PlanningRate(unittest.TestCase):
    def test_planning_is_candidates_over_the_bracketed_span_and_below_the_inclusive_rate(self):
        r = full_report()
        tim = {int(k): v for k, v in LOG["timing"]["records"].items()}
        span = tim[66]["t_rec"] - tim[1]["t_signreq"]
        self.assertAlmostEqual(r["planning"]["span_s"], span); self.assertAlmostEqual(r["planning"]["evals_per_hour"], 64 * 3600 / span)
        self.assertLess(r["planning"]["evals_per_hour"], r["inclusive"]["evals_per_hour"])
        self.assertLess(r["planning"]["evals_per_hour"], r["nominal"]["evals_per_hour"])

    def test_a_recovery_on_the_last_candidate_moves_planning_but_not_the_inclusive_rate(self):
        """The owner's counterexample: the last candidate (seq 65) recovers for 2 s. Its
        period is the last→closing transition, outside every steady-state period, so the
        inclusive rate and CoV are unchanged, the nominal set excludes nothing new — only
        the planning rate and the recovery indicators see it."""
        base = full_report()
        log = copy.deepcopy(LOG)
        t66 = log["timing"]["records"]["66"]
        for k in ("t_signreq", "t_reply", "t_auditreq", "t_rec", "t_ready", "t_done"):
            if t66.get(k) is not None:
                t66[k] += 2.0
        t66["hb"] = [x + 2.0 for x in t66["hb"]]; t66["audit"] = [x + 2.0 for x in t66["audit"]]
        t65 = log["timing"]["records"]["65"]
        frames = FRAMES + [{"dir": "rx", "type": "FRAGMENT", "seq": None, "t_mono": t65["t_signreq"] + 0.5, "t_wall": 0.0,
                            "bytes": 300, "reason": "pull timeout: seq 65 chunk 3"}]
        moved = lr.rate_report(log, "C1", None, audits=AUDITS, frames=frames, inputs_sha256=INPUTS)
        self.assertEqual(moved["inclusive"], base["inclusive"], "the steady-state periods did not move")
        self.assertEqual(moved["cov"], base["cov"]); self.assertEqual(moved["evals_per_hour"], base["evals_per_hour"])
        self.assertAlmostEqual(moved["transitions_s"]["last_to_closing_s"], base["transitions_s"]["last_to_closing_s"] + 2.0)
        self.assertLess(moved["planning"]["evals_per_hour"], base["planning"]["evals_per_hour"])
        self.assertAlmostEqual(moved["planning"]["span_s"], base["planning"]["span_s"] + 2.0)
        self.assertEqual(moved["recovery"]["recovered_seqs"], [39, 65]); self.assertEqual(moved["recovery"]["fragments"], 1)
        self.assertEqual(moved["nominal"]["excluded_seqs"], [39], "65's period is a transition: not in the nominal set either")
        row = {r["seq"]: r for r in moved["per_candidate"]}[65]
        self.assertFalse(row["clean"]); self.assertIsNone(row["period_s"])


class SoakSizedByThePlanningRate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r1 = full_report()
        r2 = copy.deepcopy(cls.r1); r2["session"] = "C2"; r2["schedule_mode"] = "map_guided_forced"
        r2["binding"] = tr.binding("C2"); r2["planning"]["evals_per_hour"] = 3300.0; r2["evals_per_hour"] = 3400.0
        cls.r2 = r2
        cls.m5 = copy.deepcopy(tr.L6M); cls.m5["prereg"]["version"] = "v0.5"

    def test_under_v05_the_soak_uses_the_planning_rates_under_v04_the_inclusive_ones(self):
        p5 = l6.plan_session(self.m5, "S", None, 7200.0, {"C1": self.r1, "C2": self.r2}, None)
        self.assertEqual(p5["inputs"]["rate_C1_per_h"], self.r1["planning"]["evals_per_hour"])
        self.assertEqual(p5["inputs"]["rate_C2_per_h"], 3300.0); self.assertTrue(p5["inputs"]["rate_source"].startswith("planning"))
        p4 = l6.plan_session(tr.L6M, "S", None, 7200.0, {"C1": self.r1, "C2": self.r2}, None)
        self.assertEqual(p4["inputs"]["rate_C1_per_h"], self.r1["evals_per_hour"]); self.assertEqual(p4["inputs"]["rate_C2_per_h"], 3400.0)
        self.assertLess(p5["n"], p4["n"], "the planning rate is the smaller one: fewer candidates in the soak")

    def test_under_v05_a_report_without_planning_or_inputs_is_refused(self):
        r = copy.deepcopy(self.r1); del r["planning"]
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(self.m5, "S", None, 7200.0, {"C1": r, "C2": self.r2}, None)
        self.assertIn("no planning rate", str(cm.exception))
        r = copy.deepcopy(self.r1); r["inputs"] = None
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(self.m5, "S", None, 7200.0, {"C1": r, "C2": self.r2}, None)
        self.assertIn("binds no inputs", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
