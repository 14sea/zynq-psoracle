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
        import pwd
        try:
            pwd.getpwnam("p3signer"); have_principal = True
        except KeyError:
            have_principal = False
        if not have_principal:
            self.assertFalse(rec["all_passed"], "no signer principal exists on this host, yet the verifier passed")
        else:
            # with the principal present the runner must still be unable to read the store (R2)
            self.assertTrue(rec["checks"][1]["passed"], rec["checks"][1]["detail"])

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


class SignerProvisionOp(unittest.TestCase):
    """The signer's provision op with a fixture key: prepare writes nothing; execute without a
    ruling is a clean refusal; a ruling of another text is refused."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        self.key = d / "K.bin"; self.key.write_bytes(bytes(range(16))); os.chmod(self.key, 0o400); self.d = d

    def tearDown(self): self.tmp.cleanup()

    def dummy_cfg(self):
        """the provisioning cfg with the dummy adapter: openocd runs, no pod is ever opened"""
        src = (REPO / "scripts/jtag_provision.cfg").read_text().replace("adapter driver ftdi", "adapter driver dummy")
        src = "\n".join(l for l in src.splitlines() if not l.startswith("ftdi "))
        p = self.d / "dummy.cfg"; p.write_text(src + "\n"); return p

    def ask(self, req):
        return subprocess.run([sys.executable, str(REPO / "host/sign_arm.py"), str(self.key)], input=json.dumps(req),
                              capture_output=True, text=True, timeout=60)

    def test_prepare_writes_no_file_and_reveals_no_words(self):
        before = set(Path(tempfile.gettempdir()).glob("*.tcl"))
        p = self.ask({"op": "provision", "execute": False})
        self.assertEqual(p.returncode, 0, p.stderr)
        ans = json.loads(p.stdout)
        self.assertEqual(ans["provision"]["executed"], False); self.assertNotIn("words_hex", json.dumps(ans))
        self.assertNotIn("0f0e0d0c", p.stdout); self.assertNotIn("03020100", p.stdout)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("*.tcl")) - before, set())

    def test_execute_without_ruling_is_a_clean_refusal(self):
        p = self.ask({"op": "provision", "execute": True})
        self.assertEqual(p.returncode, 1); self.assertIn("no ruling", p.stderr); self.assertNotIn("Traceback", p.stderr)

    def test_signer_consumes_a_provisioning_ruling_itself_once(self):
        """Not executed for real (no pod as this user): the marker logic is exercised by asking
        twice with a valid P3-K ruling and a state dir under our control; the first attempt
        proceeds past the ruling check (fails later at openocd/pod), the second is refused as used."""
        r = self.d / "k.json"; r.write_text(json.dumps({"ruling": "provisioning P3-K", "boardid": "17A6", "granted_by": "x", "date": "x"}))
        env = dict(os.environ, P3_SIGNER_STATE_DIR=str(self.d / "state"), P3_PROVISION_CFG=str(self.dummy_cfg()))
        run = lambda: subprocess.run([sys.executable, str(REPO / "host/sign_arm.py"), str(self.key)], input=json.dumps({"op": "provision", "execute": True, "ruling": str(r)}),
                                     capture_output=True, text=True, timeout=120, env=env)
        p1 = run(); self.assertNotIn("already used", p1.stderr); self.assertEqual(len(list((self.d / "state").glob("*.consumed"))), 1)
        p2 = run(); self.assertEqual(p2.returncode, 1); self.assertIn("already used", p2.stderr)

    def test_a_preclaimed_ruling_in_rulings_dir_does_not_block_the_signer(self):
        r = self.d / "k.json"; r.write_text(json.dumps({"ruling": "provisioning P3-K", "boardid": "17A6", "granted_by": "x", "date": "x"}))
        (self.d / "k.json.consumed").write_text("claimed by the runner side\n")
        env = dict(os.environ, P3_SIGNER_STATE_DIR=str(self.d / "state"), P3_PROVISION_CFG=str(self.dummy_cfg()))
        p = subprocess.run([sys.executable, str(REPO / "host/sign_arm.py"), str(self.key)], input=json.dumps({"op": "provision", "execute": True, "ruling": str(r)}),
                           capture_output=True, text=True, timeout=120, env=env)
        self.assertNotIn("was consumed", p.stderr)

    def test_execute_with_a_ruling_of_another_text_is_refused(self):
        r = self.d / "r.json"; r.write_text(json.dumps({"ruling": "whole-of-probe P3-L3", "boardid": "17A6", "granted_by": "x", "date": "x"}))
        p = self.ask({"op": "provision", "execute": True, "ruling": str(r)})
        self.assertEqual(p.returncode, 1); self.assertIn("ruling refused", p.stderr); self.assertNotIn("Traceback", p.stderr)

    def test_openocd_script_shape(self):
        sys.path.insert(0, str(REPO / "host")); import provision_key_jtag as pk
        t = pk.openocd_tcl(bytes(range(16)))
        self.assertIn("zynq.ahb mww 0x43c02160 0x0f0e0d0c", t); self.assertIn("mww 0x43c0216c 0x03020100", t)
        self.assertIn("mww 0x43c02000 0x00000100", t); self.assertTrue(t.strip().endswith("shutdown"))
        self.assertIn("mem_ap", (REPO / "scripts/jtag_provision.cfg").read_text())
        code = "\n".join(l for l in (REPO / "scripts/jtag_provision.cfg").read_text().splitlines() if not l.startswith("#"))
        self.assertNotIn("cortex_a", code)


if __name__ == "__main__":
    unittest.main()
