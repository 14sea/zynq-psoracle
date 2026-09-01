"""host/l6_rate.py — the rate report: refuses session 4's untimed log, and reproduces
known numbers from a synthetic timed log built with test_d1_records' happy session."""
from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "tests"))
import l6_rate as lr  # noqa: E402
import l6_timing as lt  # noqa: E402
import test_d1_records as d1  # noqa: E402
from test_l6_timing import frames_for  # noqa: E402

S4 = R / "evidence/l5_17A6_2026-09-01-04"


def timed_log(period=(30.0, 40.0, 35.0)) -> dict:
    """d1's happy log (seq 1 baseline, 2 scored, 3 refused, 4 baseline) with stamps: each
    record at 1 s per event, successive SIGNREQs `period` apart."""
    log = copy.deepcopy(d1.make_log())
    frames, t = [], 0.0
    for i, seq in enumerate((1, 2, 3, 4)):
        rec = next(r for r in log["loop_records"] if r["seq"] == seq)
        if rec["outcome"] == "REFUSED_BY_GATE":
            frames += [{"dir": "rx", "type": "SIGNREQ", "seq": seq, "t_mono": t, "t_wall": t},
                       {"dir": "tx", "type": "SIGNREF", "seq": seq, "t_mono": t + 1, "t_wall": t + 1},
                       {"dir": "rx", "type": "REC", "seq": seq, "t_mono": t + 2, "t_wall": t + 2}]
        else:
            frames += frames_for(seq, t)
        if i < 3:
            t += period[i]
    tim = lt.record_timing(frames, [1, 2, 3, 4])
    log["timing"] = {"clocks": lt.CLOCKS, "records": {str(k): v for k, v in tim.items()}}
    return log


class Refusals(unittest.TestCase):
    def test_session_4s_log_is_refused_for_want_of_timestamps(self):
        log = json.loads((S4 / "run_log.json").read_text())
        with self.assertRaises(lr.RateError) as cm:
            lr.rate_report(log, "C1")
        self.assertIn("no per-frame timing", str(cm.exception))

    def test_cli_refuses_the_same_way_and_writes_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with redirect_stderr(err):
                rc = lr.main([str(S4), "--out", str(Path(tmp) / "r.json")])
            self.assertEqual(rc, 2); self.assertIn("no per-frame timing", err.getvalue())
            self.assertFalse((Path(tmp) / "r.json").exists())

    def test_a_record_without_timing_is_refused_by_seq(self):
        log = timed_log()
        del log["timing"]["records"]["3"]
        with self.assertRaises(lr.RateError) as cm:
            lr.rate_report(log)
        self.assertIn("[3]", str(cm.exception))

    def test_unknown_session_label_is_refused(self):
        with self.assertRaises(lr.RateError):
            lr.rate_report(timed_log(), "C9")


class Numbers(unittest.TestCase):
    def test_the_four_numbers_from_a_synthetic_timed_log(self):
        rep = lr.rate_report(timed_log(), "C1", "ab" * 32)
        self.assertEqual(rep["brackets"], [1, 4]); self.assertEqual(rep["candidates"], 2)
        # candidate 2: wall 26 (16 HB + 8 AUDIT + reply + REC), period 40; candidate 3 (refused):
        # wall 2, period 35 → mean period 37.5 → 96 evals/h
        rows = {r["seq"]: r for r in rep["per_candidate"]}
        self.assertEqual(rows[2]["wall_s"], 26.0); self.assertEqual(rows[2]["period_s"], 40.0)
        self.assertEqual(rows[3]["wall_s"], 2.0); self.assertEqual(rows[3]["period_s"], 35.0)
        self.assertAlmostEqual(rep["evals_per_hour"], 3600 / 37.5)
        self.assertAlmostEqual(rep["cov"], (2.5 * (2 ** 0.5)) / 37.5)    # sample stdev of {40, 35}
        self.assertEqual(rep["failure_rate"], 0.0)                       # a gate refusal is not a failure
        self.assertEqual(rep["outcome_counts"], {"SCORED": 1, "REFUSED_BY_GATE": 1})
        self.assertEqual(rep["stages_s"]["link3"]["mean"], 12.0)
        self.assertEqual(rep["run_log_sha256"], "ab" * 32)
        self.assertIn("period", rep["definitions"])

    def test_a_stop_is_a_failure_and_a_stopped_epoch_keeps_its_last_candidate(self):
        log = timed_log()
        log["session_summary"]["epoch_end"] = {"kind": "STOPPED", "reason": "x", "last_seq": 4}
        log["loop_records"][3]["outcome"] = "STOP_LINK3"
        rep = lr.rate_report(log)
        self.assertEqual(rep["brackets"], [1]); self.assertEqual(rep["candidates"], 3)
        self.assertEqual(rep["failures"], [4]); self.assertAlmostEqual(rep["failure_rate"], 1 / 3)

    def test_cli_writes_the_report_once(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "run_log.json").write_text(json.dumps(timed_log()))
            self.assertEqual(lr.main([str(d), "--session", "C2"]), 0)
            rep = json.loads((d / "rate_report.json").read_text())
            self.assertEqual(rep["session"], "C2")
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(lr.main([str(d)]), 2)          # never replaced
            self.assertIn("exists", err.getvalue())


if __name__ == "__main__":
    unittest.main()
