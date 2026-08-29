"""The principal boundary: the verifier's record shape, the validator's refusals, and the
L3 runner's refusal to start without an established boundary. The real checks need the
owner's host setup (host/principal/setup_signer_principal.sh); here the record is a fixture
and one live negative is run: on THIS host, before setup, the verifier must report the
boundary as NOT established (it cannot pass by accident)."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "host"))
from validators import records  # noqa: E402
import verify_principal_boundary as vb  # noqa: E402


def record(all_ok=True, runner="test", signer="p3signer", age=0):
    checks = [{"check": n, "passed": all_ok, "detail": "fixture"} for n in records.BOUNDARY_CHECKS]
    return {"schema": "principal_boundary", "schema_version": "1.0.0", "runner_user": runner, "signer_user": signer,
            "pod_group": "p3jtag", "key_store": "/var/lib/p3signer/keys", "checks": checks,
            "all_passed": all(c["passed"] for c in checks), "at": time.time() - age}


class Boundary(unittest.TestCase):
    def test_established_record_passes(self):
        records.boundary_established(record(), time.time())

    def test_failed_check_is_refused_naming_it(self):
        r = record(); r["checks"][2]["passed"] = False; r["checks"][2]["detail"] = "no pod attached"; r["all_passed"] = False
        with self.assertRaises(records.RecordError) as cm: records.boundary_established(r, time.time())
        self.assertIn("R3_runner_cannot_open_pod", str(cm.exception))

    def test_same_user_is_no_boundary(self):
        with self.assertRaises(records.RecordError): records.validate(record(runner="test", signer="test"))

    def test_stale_record_is_refused(self):
        with self.assertRaises(records.RecordError): records.boundary_established(record(age=7 * 3600), time.time())

    def test_missing_or_reordered_checks_are_refused(self):
        r = record(); r["checks"] = r["checks"][::-1]
        with self.assertRaises(records.RecordError): records.validate(r)

    def test_all_passed_must_agree_with_checks(self):
        r = record(); r["checks"][0]["passed"] = False
        with self.assertRaises(records.RecordError): records.validate(r)

    def test_live_verifier_on_this_host_reports_the_current_state_honestly(self):
        """Before the owner's setup this must NOT pass; after it, it must. Either way the
        record validates and says which."""
        rec = vb.run_checks()
        records.validate(rec)
        self.assertEqual([c["check"] for c in rec["checks"]], list(records.BOUNDARY_CHECKS))
        if not Path("/var/lib/p3signer/keys").exists():
            self.assertFalse(rec["all_passed"], "no signer principal exists on this host, yet the verifier passed")

    def test_l3_runner_refuses_to_start_without_an_established_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "b.json"; r = record(); r["checks"][1]["passed"] = False; r["all_passed"] = False
            b.write_text(json.dumps(r))
            ruling = Path(d) / "r.json"; ruling.write_text(json.dumps({"ruling": "whole-of-probe P3-L3", "boardid": "17A6", "granted_by": "x", "date": "x"}))
            p = subprocess.run([sys.executable, str(REPO / "host/l3_runner.py"), "--ruling", str(ruling), "--out", str(Path(d) / "out"),
                                "--manifest", str(REPO / "builds/p3/carrier_manifest.json"), "--bitstream", str(REPO / "builds/p3/p3.bit"),
                                "--boundary", str(b)], capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("NOT established", p.stderr)
            self.assertFalse((Path(d) / "out").exists())


if __name__ == "__main__":
    unittest.main()
