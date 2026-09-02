"""host/l6_runner.py and host/l6_checks.py — the host-side behaviour of the L6 runner.

The runner cannot run today (the manifest is a draft with null pins) and these tests pin
that it refuses, in the documented order, for the documented reason each time: each
refusal is REACHED (the earlier checks are satisfied by fixtures) and is ABOUT its check.
The session plan and the PASS/HOLD conditions are pure and are tested as numbers."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import os
import pwd
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


def binding(session: str, m: dict = L6M, **over) -> dict:
    """The binding a v0.4 rate report carries (host/l6_rate.binding_of): the pins the
    session ran under. Tests that bind to a fixture manifest pass it in."""
    b = {"image_sha256": m["pinned_at_build"]["app_image_sha256"], "prereg_sha256": m["prereg"]["sha256"],
         "protocol": m["pinned_at_build"]["protocol"], "session": session,
         "schedule_mode": m["sessions"][session]["mode"], "master_seed": m["sessions"][session]["master_seed"]}
    b.update(over)
    return b


def report(session: str, rate: float, median_polls: float = 16.0, contract: str = CONTRACT,
           bound: dict | None = None, m: dict = L6M) -> dict:
    return {"schema": "l6_rate_report", "session": session, "schedule_mode": m["sessions"][session]["mode"],
            "evals_per_hour": rate, "settle_polls": {"median": median_polls}, "operator_data_sha256": contract,
            "binding": binding(session, m) if bound is None else bound}


# the committed manifest still pins the pull-v2 image and the v0.3 (pull-v2) prereg; the
# plan tests need a rec-v3 manifest, which is what the fixture manifest below is
L6M_V4 = copy.deepcopy(L6M)
L6M_V4["pinned_at_build"]["protocol"] = "rec-v3"
L6M_V4["prereg"]["protocol"] = "rec-v3"


class Plan(unittest.TestCase):
    def test_c1_is_64_random_safe_all_self_reporting_watchdog_on(self):
        p = l6.plan_session(L6M_V4, "C1", None, 7200.0, None, None)
        self.assertEqual(p["master_seed"], 0x4c364341)
        self.assertEqual((p["n"], p["mode"], p["audit_policy"]), (64, ls.MODE_A_FORCED, "all-self-reporting"))
        self.assertEqual(p["audit_seqs"], ls.all_seqs(64))
        # rec-v3 (v0.4): the forced REC-retry control is armed in every session (bit4)
        self.assertEqual(p["flags"], ls.FLAG_WATCHDOG | ls.FLAG_REC_CONTROL | 1 << ls.MODE_FLAG_SHIFT)
        self.assertTrue(p["rec_retry_control"]); self.assertEqual(p["protocol"], "rec-v3")
        self.assertTrue(all(r["arm"] == ls.ARM_A for r in p["schedule"]))
        # rec-v3 keeps pull-v2's inbound brackets: AUDIT_READY×1 + AUDIT×8 per audited record
        self.assertEqual(p["expected_frames"]["protocol"], "rec-v3")
        self.assertEqual(p["expected_frames"]["total"], 1 + 66 + 66 * 16 + 66 * 9 + 66 + 1 + 1)
        self.assertEqual(p["crc_budget"], 8)                            # ceil(4 × 1785 / 1000)

    def test_c2_forces_map_guided(self):
        p = l6.plan_session(L6M_V4, "C2", 0x4c364341, 7200.0, None, None)
        self.assertTrue(all(r["arm"] == ls.ARM_B for r in p["schedule"]))
        self.assertEqual(p["flags"], ls.FLAG_WATCHDOG | ls.FLAG_REC_CONTROL | 2 << ls.MODE_FLAG_SHIFT)

    def test_soak_derives_n_budget_and_timeout_from_the_calibration_rates(self):
        p = l6.plan_session(L6M_V4, "S", None, 7200.0, {"C1": report("C1", 120.0, m=L6M_V4), "C2": report("C2", 100.0, m=L6M_V4)}, None)
        self.assertEqual(p["master_seed"], 0x4c36534f)
        self.assertEqual(p["n"], 180); self.assertEqual(p["audit_policy"], "sampled")
        self.assertEqual(p["audit_seqs"], ls.sampled_audit_seqs(180))
        self.assertEqual(p["session_timeout_s"], ls.session_timeout_s(180, 120.0, 100.0))
        self.assertEqual(p["crc_budget"], ls.crc_budget(p["expected_frames"]["total"]))
        self.assertEqual(p["inputs"]["rate_C2_per_h"], 100.0)
        self.assertEqual(p["flags"], ls.FLAG_WATCHDOG | ls.FLAG_REC_CONTROL)   # abba = mode 0
        self.assertEqual([r["arm"] for r in p["schedule"][:4]], [ls.ARM_A, ls.ARM_B, ls.ARM_B, ls.ARM_A])

    def test_soak_refuses_a_report_of_the_wrong_session_or_without_a_rate(self):
        M = L6M_V4
        with self.assertRaises(ValueError):
            l6.plan_session(M, "S", None, 7200.0, {"C1": report("C2", 120.0, m=M), "C2": report("C2", 100.0, m=M)}, None)
        bad = report("C1", 120.0, m=M); del bad["evals_per_hour"]
        with self.assertRaises(ValueError):
            l6.plan_session(M, "S", None, 7200.0, {"C1": bad, "C2": report("C2", 100.0, m=M)}, None)
        with self.assertRaises(ValueError):
            l6.plan_session(M, "S", None, 7200.0, None, None)

    def test_soak_refuses_a_calibration_under_another_operator_contract(self):
        """mutation_bits (and the map data) are the operator contract: a calibration run
        under a different operator_data_sha256 cannot budget this soak (owner 2026-09-01)."""
        M = L6M_V4
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(M, "S", None, 7200.0, {"C1": report("C1", 120.0, contract="00" * 32, m=M),
                                                 "C2": report("C2", 100.0, m=M)}, None)
        self.assertIn("operator contract", str(cm.exception)); self.assertIn("re-run", str(cm.exception))

    def test_soak_refuses_a_calibration_not_bound_to_the_current_image_prereg_and_protocol(self):
        """prereg v0.4: the REC protocol changes the nominal candidate period, so the v0.3
        calibrations (no binding) may not be reused; a report bound to another image,
        preregistration, protocol, session, mode or seed is refused by name."""
        M = L6M_V4
        good = {"C1": report("C1", 120.0, m=M), "C2": report("C2", 100.0, m=M)}
        self.assertEqual(l6.plan_session(M, "S", None, 7200.0, good, None)["n"], 180)
        # the pinned v0.3 reports on disk carry no binding: refused, C1/C2 to be re-run
        for k, path in (("C1", "evidence/l6_17A6_2026-09-01-09-C1/rate_report.json"),
                        ("C2", "evidence/l6_17A6_2026-09-01-10-C2/rate_report.json")):
            old = json.loads((R / path).read_text())
            self.assertNotIn("binding", old)
            cal = dict(good); cal[k] = old
            with self.assertRaises(ValueError) as cm:
                l6.plan_session(M, "S", None, 7200.0, cal, None)
            self.assertIn("carries no binding", str(cm.exception)); self.assertIn(f"re-run {k}", str(cm.exception))
        for field, wrong in (("image_sha256", "11" * 32), ("prereg_sha256", "22" * 32), ("protocol", "pull-v2"),
                             ("session", "C2"), ("schedule_mode", "abba"), ("master_seed", 1)):
            b = binding("C1", M); b[field] = wrong
            cal = dict(good); cal["C1"] = report("C1", 120.0, m=M, bound=b)
            with self.assertRaises(ValueError) as cm:
                l6.plan_session(M, "S", None, 7200.0, cal, None)
            self.assertIn("C1", str(cm.exception), field)

    def test_the_seeds_are_the_owners_pins_and_c1_c2_share_one(self):
        """Owner 2026-09-01: C1 = C2 = 0x4c364341 (same seed pairs, only the operator
        differs), S = 0x4c36534f; a CLI seed must equal the pin; S's T is exactly 7200."""
        self.assertEqual(L6M["sessions"]["C1"]["master_seed"], L6M["sessions"]["C2"]["master_seed"])
        self.assertEqual(L6M["sessions"]["C1"]["master_seed"], 1278624577)
        self.assertEqual(L6M["sessions"]["S"]["master_seed"], 1278628687)
        M = L6M_V4
        self.assertEqual([r["seed"] for r in l6.plan_session(M, "C1", None, 7200.0, None, None)["schedule"]],
                         [r["seed"] for r in l6.plan_session(M, "C2", None, 7200.0, None, None)["schedule"]])
        with self.assertRaises(ValueError) as cm:
            l6.plan_session(M, "C1", 0x1234, 7200.0, None, None)
        self.assertIn("not the pinned", str(cm.exception))
        cal = {"C1": report("C1", 120.0, m=M), "C2": report("C2", 100.0, m=M)}
        for t in (3600.0, 7199.0, 7201.0):
            with self.assertRaises(ValueError) as cm:
                l6.plan_session(M, "S", None, t, cal, None)
            self.assertIn("exactly the pinned 7200", str(cm.exception))
        self.assertEqual(l6.plan_session(M, "S", None, 7200.0, cal, None)["inputs"]["duration_s"], 7200.0)

    def test_master_seed_is_32_bit_and_n_is_never_typed(self):
        bad = copy.deepcopy(L6M_V4); bad["sessions"]["C1"]["master_seed"] = 1 << 32
        with self.assertRaises(ValueError):
            l6.plan_session(bad, "C1", None, 7200.0, None, None)
        import inspect
        src = inspect.getsource(l6.main)
        self.assertNotIn('"--budget"', src); self.assertNotIn('"--n"', src)


class Refusals(unittest.TestCase):
    """Each refusal is reached and is about its own check."""

    IMAGE_STANDIN = b"the two-operator image stand-in"
    PREREG_SHA = hashlib.sha256((R / "docs/l6_soak_prereg.md").read_bytes()).hexdigest()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "img.bin").write_bytes(self.IMAGE_STANDIN)
        self.image_sha = hashlib.sha256(self.IMAGE_STANDIN).hexdigest()
        self.manifest()                      # the default manifest, which the rulings bind
        self.write_ruling("ruling.json", l6.RULING_TEXT, "C1", master_seed=L6M["sessions"]["C1"]["master_seed"])
        self.write_ruling("l5ruling.json", "whole-of-probe P3-L5", "C1")
        self.write_ruling("pk.json", l6.PROVISION_RULING_TEXT, "C1")
        self.boundary(True)

    def report(self, session: str, rate: float) -> dict:
        """A calibration report bound to THIS fixture's pins (image stand-in, prereg, rec-v3)."""
        m = copy.deepcopy(L6M)
        m["pinned_at_build"]["app_image_sha256"] = self.image_sha
        m["pinned_at_build"]["protocol"] = "rec-v3"
        m["prereg"]["sha256"] = self.PREREG_SHA
        return report(session, rate, m=m)

    def manifest_sha(self, path: Path | None = None) -> str:
        return hashlib.sha256((path or self.tmp / "l6_manifest.json").read_bytes()).hexdigest()

    def write_ruling(self, name, text, session, master_seed=None, prereg=None, image=None, l6m=None, **extra):
        r = {"ruling": text, "boardid": "17A6", "granted_by": "14sea", "date": "2026-09-99-01",
             "session": session, "prereg_sha256": self.PREREG_SHA if prereg is None else prereg,
             "image_sha256": self.image_sha if image is None else image,
             "l6_manifest_sha256": self.manifest_sha() if l6m is None else l6m}
        if master_seed is not None:
            r["master_seed"] = master_seed
        r.update(extra)
        (self.tmp / name).write_text(json.dumps(r))

    def boundary(self, ok: bool, runner_user=None, signer_user="p3signer", key_store="/var/lib/p3signer/keys"):
        (self.tmp / "boundary.json").write_text(json.dumps(
            {"schema": "principal_boundary", "schema_version": "1.0.0",
             "runner_user": pwd.getpwuid(os.getuid()).pw_name if runner_user is None else runner_user,
             "signer_user": signer_user, "pod_group": "p3jtag", "key_store": key_store,
             "all_passed": ok, "checks": [{"check": c, "passed": ok, "detail": "fixture"} for c in
                                          ("R1_runner_is_not_signer", "R2_runner_cannot_read_key",
                                           "R3_runner_cannot_open_pod", "R4_signer_reachable_and_holds_key",
                                           "R5_signer_in_pod_group")], "at": time.time()}))

    def manifest(self, *, frozen=True, image=True, watchdog=True, calib=None, carrier=None,
                 duration=None, rebind=True, board_ready=True, protocol="rec-v3", prereg_protocol="rec-v3") -> Path:
        """Writes the fixture manifest and, by default, re-binds both rulings to its hash
        (as the owner would issue them against the committed manifest of the time); a
        tamper test passes rebind=False to keep the rulings bound to the earlier file."""
        m = copy.deepcopy(L6M)
        m["prereg"]["sha256"] = self.PREREG_SHA if frozen else None
        # the committed manifest pins the real image; the fixture pins the stand-in or nulls it
        m["pinned_at_build"]["app_image_sha256"] = self.image_sha if image else None
        if not watchdog:
            m["pinned_at_build"]["watchdog_enabled"] = False
        m["pinned_at_build"]["board_ready"] = board_ready
        m["pinned_at_build"]["protocol"] = protocol
        m["prereg"]["protocol"] = prereg_protocol
        self.fixture_manifest = m
        if calib:
            for k, sha in calib.items():
                m["calibration"][k]["rate_report_sha256"] = sha
        if carrier:
            m["instrument"]["carrier"].update(carrier)
        if duration is not None:
            m["sessions"]["S"]["duration_s"] = duration
        p = self.tmp / "l6_manifest.json"
        p.write_text(json.dumps(m))
        if rebind:
            for name in ("ruling.json", "pk.json"):
                rp = self.tmp / name
                if rp.exists():
                    r = json.loads(rp.read_text()); r["l6_manifest_sha256"] = self.manifest_sha(p)
                    rp.write_text(json.dumps(r))
        return p

    def args(self, session="C1", ruling="ruling.json", manifest: Path | None = None, extra=(),
             pk="pk.json", bitstream=None, carrier_manifest=None) -> list[str]:
        # SAFETY: the manifest is the one on disk (never rewritten here — a rewrite re-binds
        # the rulings and can make a tamper test pass preflight), and the port is a path
        # that cannot exist, so a fixture defect can never reach a board. Found live
        # 2026-09-01: a rebinding args() let the P3-K tamper loop pass every check and
        # the runner claimed the fixture ruling and tried to open /dev/ebaz-uart (absent).
        argv = ["--ruling", str(self.tmp / ruling), "--session", session,
                "--boundary", str(self.tmp / "boundary.json"), "--out", str(self.tmp / "out"),
                "--manifest", str(carrier_manifest or R / "builds/p3/carrier_manifest.json"),
                "--bitstream", str(bitstream or R / "builds/p3/p3.bit"), "--image", str(self.tmp / "img.bin"),
                "--l6-manifest", str(manifest or self.tmp / "l6_manifest.json"),
                "--port", str(self.tmp / "no-such-port"), *extra]
        if pk:
            argv += ["--provision-ruling", str(self.tmp / pk)]
        return argv

    def run_main(self, argv) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = l6.main(argv)
        self.assertFalse((self.tmp / "out").exists(), "no evidence dir before the checks pass")
        self.assertFalse((self.tmp / "ruling.json.consumed").exists(), "a refusal never consumes the ruling")
        self.assertFalse((self.tmp / "pk.json.consumed").exists(), "a refusal never consumes the P3-K ruling")
        return rc, err.getvalue()

    def test_an_l5_ruling_is_refused_by_text(self):
        rc, err = self.run_main(self.args(ruling="l5ruling.json"))
        self.assertEqual(rc, 2); self.assertIn("ruling text", err); self.assertIn("P3-L6", err)

    def test_the_real_manifest_accepts_the_frozen_prereg_and_stops_at_the_image(self):
        """The committed manifest is frozen (prereg.sha256 set): the prereg check passes on
        the real document, and the next check — the image — refuses this test's stand-in.
        So the board path is closed by the pinned-image and ruling gates, not by a draft."""
        rc, err = self.run_main(self.args(manifest=R / "manifests/l6_manifest.json"))
        self.assertEqual(rc, 2); self.assertIn("not the pinned one", err); self.assertNotIn("not frozen", err)

    def test_an_unfrozen_manifest_is_refused_before_the_image(self):
        rc, err = self.run_main(self.args(manifest=self.manifest(frozen=False)))
        self.assertEqual(rc, 2); self.assertIn("not frozen", err)

    def test_a_prereg_that_does_not_hash_to_the_pin_is_refused(self):
        m = json.loads(self.manifest().read_text()); m["prereg"]["sha256"] = "00" * 32
        (self.tmp / "l6_bad.json").write_text(json.dumps(m))
        rc, err = self.run_main(self.args(manifest=self.tmp / "l6_bad.json"))
        self.assertEqual(rc, 2); self.assertIn("does not hash to the frozen preregistration", err)

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

    def _s_rulings(self):
        """S rulings bound to the manifest currently on disk (tmp/l6_manifest.json)."""
        self.write_ruling("ruling.json", l6.RULING_TEXT, "S", master_seed=L6M["sessions"]["S"]["master_seed"])
        self.write_ruling("pk.json", l6.PROVISION_RULING_TEXT, "S")

    def test_an_image_not_marked_board_ready_or_not_rec_v3_is_refused(self):
        rc, err = self.run_main(self.args(manifest=self.manifest(board_ready=False)))
        self.assertEqual(rc, 2); self.assertIn("not marked board-ready", err)
        for proto in ("push-v1", "pull-v2"):
            rc, err = self.run_main(self.args(manifest=self.manifest(protocol=proto)))
            self.assertEqual(rc, 2, proto); self.assertIn("is not this runner's rec-v3", err)
        # the frozen v0.3 is a pull-v2 preregistration: this runner refuses it until v0.4 is frozen
        rc, err = self.run_main(self.args(manifest=self.manifest(prereg_protocol="pull-v2")))
        self.assertEqual(rc, 2); self.assertIn("freeze prereg v0.4 first", err)
        rc, err = self.run_main(self.args(manifest=R / "manifests/l6_manifest.json"))
        self.assertEqual(rc, 2, "the committed manifest cannot run a session under this runner")

    def test_the_soak_needs_both_pinned_calibration_records(self):
        self._s_rulings()
        rc, err = self.run_main(self.args(session="S"))
        self.assertEqual(rc, 2); self.assertIn("D-s3", err); self.assertIn("C1", err)

    def test_a_calibration_record_that_does_not_hash_to_its_pin_is_refused(self):
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(self.report("C1", 120.0))); c2.write_text(json.dumps(self.report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        m = self.manifest(calib={"C1": sha(c1), "C2": "00" * 32})
        self._s_rulings()
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
        c1.write_text(json.dumps(self.report("C1", 120.0))); c2.write_text(json.dumps(self.report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        self.boundary(False); self._s_rulings()
        rc, err = self.run_main(self.args(session="S", manifest=self.manifest(calib={"C1": sha(c1), "C2": sha(c2)}),
                                          extra=("--calibration-c1", str(c1), "--calibration-c2", str(c2))))
        self.assertEqual(rc, 2); self.assertIn("principal boundary NOT established", err)


class BoardPhasePreflight(Refusals):
    """The five preflight blockers of the owner's board-phase ruling (2026-09-01), each a
    named refusal reached with every earlier check satisfied."""

    def test_1_no_provision_ruling_means_no_claim_and_no_port(self):
        rc, err = self.run_main(self.args(pk=None))
        self.assertEqual(rc, 2); self.assertIn("--provision-ruling is mandatory", err)

    def test_1_a_used_provision_ruling_is_refused(self):
        (self.tmp / "pk.json.consumed").write_text("used")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = l6.main(self.args())
        self.assertEqual(rc, 2); self.assertIn("already used", err.getvalue())
        self.assertFalse((self.tmp / "ruling.json.consumed").exists())

    def test_1_a_provision_ruling_with_the_wrong_text_is_refused(self):
        self.write_ruling("pk.json", "whole-of-probe P3-L5", "C1")
        rc, err = self.run_main(self.args())
        self.assertEqual(rc, 2); self.assertIn("ruling text", err)

    def test_2_the_l6_ruling_is_bound_to_session_seed_prereg_and_image(self):
        seed = L6M["sessions"]["C1"]["master_seed"]
        cases = {"session": dict(session="C2"), "master_seed": dict(master_seed=seed + 1),
                 "prereg_sha256": dict(prereg="00" * 32), "image_sha256": dict(image="11" * 32),
                 "l6_manifest_sha256": dict(l6m="22" * 32)}
        for field, kw in cases.items():
            kw = {"session": "C1", "master_seed": seed, **kw}
            self.write_ruling("ruling.json", l6.RULING_TEXT, **kw)
            rc, err = self.run_main(self.args())
            self.assertEqual(rc, 2, field); self.assertIn("is bound to " + field, err, field)
        for missing in ("session", "master_seed", "prereg_sha256", "image_sha256", "l6_manifest_sha256"):
            r = json.loads((self.tmp / "ruling.json").read_text()); r["session"] = "C1"; r["master_seed"] = seed
            r["prereg_sha256"] = self.PREREG_SHA; r["image_sha256"] = self.image_sha
            r["l6_manifest_sha256"] = self.manifest_sha()
            del r[missing]
            (self.tmp / "ruling.json").write_text(json.dumps(r))
            rc, err = self.run_main(self.args())
            self.assertEqual(rc, 2); self.assertIn(f"lacks '{missing}'", err)
        # a hex-string seed is accepted when it equals the pin
        self.write_ruling("ruling.json", l6.RULING_TEXT, "C1", master_seed=f"{seed:#x}")
        self.boundary(False)
        rc, err = self.run_main(self.args())
        self.assertIn("principal boundary NOT established", err)

    def test_2_the_p3k_ruling_is_bound_to_session_prereg_and_image(self):
        for field, kw in {"session": dict(session="S"), "prereg_sha256": dict(prereg="00" * 32),
                          "image_sha256": dict(image="11" * 32), "l6_manifest_sha256": dict(l6m="22" * 32)}.items():
            self.write_ruling("pk.json", l6.PROVISION_RULING_TEXT, **{"session": "C1", **kw})
            rc, err = self.run_main(self.args())
            self.assertEqual(rc, 2, field); self.assertIn("'provisioning P3-K' is bound to " + field, err, field)

    def test_3_the_boundary_is_bound_to_this_invocation(self):
        self.boundary(True, runner_user="someone-else")
        rc, err = self.run_main(self.args())
        self.assertEqual(rc, 2); self.assertIn("is not this OS user", err)
        # closing review blocker 2: forging LOGNAME/USER must not satisfy it — the identity
        # is the effective UID's name, as the boundary verifier resolves it
        saved = {k: os.environ.get(k) for k in ("LOGNAME", "USER")}
        try:
            os.environ["LOGNAME"] = os.environ["USER"] = "someone-else"
            rc, err = self.run_main(self.args())
            self.assertEqual(rc, 2); self.assertIn("is not this OS user", err)
            self.assertIn(repr(pwd.getpwuid(os.getuid()).pw_name), err)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.boundary(True)
        rc, err = self.run_main(self.args(extra=("--signer-user", "other")))
        self.assertEqual(rc, 2); self.assertIn("--signer-user 'other' is not the record's", err)
        rc, err = self.run_main(self.args(extra=("--key", str(self.tmp / "K.bin"))))
        self.assertEqual(rc, 2); self.assertIn("is not the record's key store's", err)

    def test_4_the_carrier_is_the_frozen_one_by_file_hash(self):
        other = self.tmp / "carrier_manifest.json"
        m = json.loads((R / "builds/p3/carrier_manifest.json").read_text()); m["note_x"] = "edited"
        other.write_text(json.dumps(m))
        rc, err = self.run_main(self.args(carrier_manifest=other))
        self.assertEqual(rc, 2); self.assertIn("carrier manifest", err); self.assertIn("does not hash to the frozen", err)
        bit = self.tmp / "p3.bit"; bit.write_bytes(b"not the carrier")
        rc, err = self.run_main(self.args(bitstream=bit))
        self.assertEqual(rc, 2); self.assertIn("bitstream", err); self.assertIn("does not hash to the frozen carrier", err)
        self.assertEqual(L6M["instrument"]["carrier"]["manifest_sha256"],
                         "2a7abc2b4054fee1ed02edc38dcae23a5a64b2174ef571401b32b309a4123dfa")
        self.assertEqual(L6M["instrument"]["carrier"]["bitstream_sha256"],
                         "956379fa8d23f8a6f1e0c80fe18b8c4aee68e76cc650499911a4bdb7807e610a")

    def test_5_the_seed_is_the_pin_and_the_soak_duration_is_exactly_7200(self):
        rc, err = self.run_main(self.args(extra=("--master-seed", "0x1234")))
        self.assertEqual(rc, 2); self.assertIn("not the pinned", err)
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(self.report("C1", 120.0))); c2.write_text(json.dumps(self.report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        self._s_rulings()
        m = self.manifest(calib={"C1": sha(c1), "C2": sha(c2)})
        rc, err = self.run_main(self.args(session="S", manifest=m, extra=(
            "--calibration-c1", str(c1), "--calibration-c2", str(c2), "--duration-s", "600")))
        self.assertEqual(rc, 2); self.assertIn("exactly the pinned 7200", err)


class ManifestBinding(Refusals):
    """Closing review blocker 1: the manifest carries the carrier pins, the soak duration and
    the calibration pins, so a ruling that does not name the manifest's hash lets a swapped
    manifest re-specify all of them with prereg/image/seed intact. Each tamper below keeps
    those three intact and must be refused on l6_manifest_sha256."""

    def _refused_on_manifest_hash(self, argv):
        rc, err = self.run_main(argv)
        self.assertEqual(rc, 2)
        self.assertIn("is bound to l6_manifest_sha256", err, err)
        return err

    def test_a_swapped_carrier_pin_is_refused_by_the_manifest_binding(self):
        other = self.tmp / "p3.bit"; other.write_bytes(b"another carrier")
        m = self.manifest(carrier={"bitstream_sha256": hashlib.sha256(b"another carrier").hexdigest()}, rebind=False)
        self._refused_on_manifest_hash(self.args(manifest=m, bitstream=other))

    def test_a_shortened_soak_duration_is_refused_by_the_manifest_binding(self):
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(self.report("C1", 120.0))); c2.write_text(json.dumps(self.report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        self.manifest(calib={"C1": sha(c1), "C2": sha(c2)})         # the manifest the S rulings were issued against
        self._s_rulings()
        m = self.manifest(calib={"C1": sha(c1), "C2": sha(c2)}, duration=600, rebind=False)
        self._refused_on_manifest_hash(self.args(session="S", manifest=m, extra=(
            "--calibration-c1", str(c1), "--calibration-c2", str(c2), "--duration-s", "600")))

    def test_swapped_calibration_pins_are_refused_by_the_manifest_binding(self):
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(self.report("C1", 120.0))); c2.write_text(json.dumps(self.report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        self.manifest(calib={"C1": sha(c1), "C2": sha(c2)})
        self._s_rulings()
        fast = self.tmp / "c1_fast.json"; fast.write_text(json.dumps(self.report("C1", 9000.0)))
        m = self.manifest(calib={"C1": sha(fast), "C2": sha(c2)}, rebind=False)
        self._refused_on_manifest_hash(self.args(session="S", manifest=m, extra=(
            "--calibration-c1", str(fast), "--calibration-c2", str(c2))))

    def test_the_bound_manifest_passes_to_the_boundary(self):
        """The same S run with rulings bound to the manifest in force reaches the last gate."""
        c1, c2 = self.tmp / "c1.json", self.tmp / "c2.json"
        c1.write_text(json.dumps(self.report("C1", 120.0))); c2.write_text(json.dumps(self.report("C2", 100.0)))
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        m = self.manifest(calib={"C1": sha(c1), "C2": sha(c2)})
        self._s_rulings(); self.boundary(False)
        rc, err = self.run_main(self.args(session="S", manifest=m, extra=(
            "--calibration-c1", str(c1), "--calibration-c2", str(c2))))
        self.assertIn("principal boundary NOT established", err)

    def test_the_nonce_seed_is_the_manifests_own_pin_and_there_is_no_l5_manifest_input(self):
        import inspect
        src = inspect.getsource(l6.main) + inspect.getsource(l6.preflight)
        self.assertNotIn('"--l5-manifest"', src); self.assertNotIn("l5_manifest", src)
        self.assertNotIn("l5_manifest.json", inspect.getsource(l6))
        self.assertEqual(L6M["instrument"]["carrier"]["nonce_seed"],
                         json.loads((R / "manifests/l5_manifest.json").read_text())["carrier"]["nonce_seed"])
        self.assertEqual(L6M["instrument"]["carrier"]["nonce_seed"], "9e3779b97f4a7c15")


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

    @staticmethod
    def _ledger(seq, attempts=("ok",), accepted=True, gets=0, acks=1, conflict=False):
        return {"seq": seq, "attempts": [{"attempt": i + 1, "outcome": o, "t_mono": None} for i, o in enumerate(attempts)],
                "lines_kept": [], "gets_sent": gets, "acks_sent": acks, "accepted": accepted, "conflict": conflict}

    def test_rec_closure_gate_accepts_a_closed_session_and_names_every_defect(self):
        """v0.4 PASS condition 7 (review 2026-09-02, blocker 3): record seqs == accepted
        ledger seqs, every ledger accepted/no conflict/acknowledged; each defect by seq."""
        seqs = [r["seq"] for r in self.log["loop_records"]]
        good = [self._ledger(s) for s in seqs]
        self.assertEqual(lc.rec_closure_findings(self.log, good), [])
        # discrimination: an arbitrary MIDDLE ledger removed
        gone = [l for l in good if l["seq"] != 3]
        f = lc.rec_closure_findings(self.log, gone)
        self.assertEqual(len(f), 1); self.assertIn("records without a transaction ledger: [3]", f[0])
        # only seq 1's ledger (what the control check alone would have accepted)
        f = lc.rec_closure_findings(self.log, [self._ledger(1, ("crc", "ok"), gets=1)])
        self.assertTrue(any("records without a transaction ledger: [2, 3, 4]" in x for x in f), f)
        # a ledger without a record (an exhausted or advanced-without-ACK transaction)
        f = lc.rec_closure_findings(self.log, good + [self._ledger(9, ("crc", "crc", "crc"), accepted=False, gets=2, acks=0)])
        self.assertTrue(any("ledgers without a record: [9]" in x for x in f), f)
        # unaccepted, conflicting, unacknowledged, no accepted attempt — each named
        for bad, needle in ((self._ledger(2, ("crc",), accepted=False, acks=0), "never accepted"),
                            (self._ledger(2, ("ok", "conflict"), conflict=True), "conflicting duplicate"),
                            (self._ledger(2, ("ok",), acks=0), "never acknowledged"),
                            (self._ledger(2, ("crc",), accepted=True), "no accepted attempt")):
            leds = [bad if l["seq"] == 2 else l for l in good]
            f = lc.rec_closure_findings(self.log, leds)
            self.assertTrue(any(needle in x and "seq 2" in x for x in f), (needle, f))
        # duplicated ledger for one seq
        f = lc.rec_closure_findings(self.log, good + [self._ledger(2)])
        self.assertTrue(any("two ledgers for seq 2" in x for x in f), f)
        # the runner calls it
        import inspect
        self.assertIn("lc.rec_closure_findings(log, console.rec_ledgers_json())", inspect.getsource(l6.run_l6))

    def test_rec_control_check_requires_exactly_the_preregistered_shape(self):
        """Review 2026-09-02, blocker 4: exactly ['crc', 'ok'], accepted, one RECGET, an ACK."""
        ok = [self._ledger(1, ("crc", "ok"), gets=1)]
        self.assertEqual(lc.rec_control_findings(ok, armed=True), [])
        self.assertEqual(lc.rec_control_findings([], armed=False), [])
        for leds, needle in (([self._ledger(1, ("ok",))], "not exercised exactly"),
                             ([self._ledger(1, ("crc", "ok", "duplicate"), gets=1, acks=2)], "not exercised exactly"),
                             ([self._ledger(1, ("crc", "crc", "ok"), gets=2)], "not exercised exactly"),
                             ([self._ledger(1, ("crc", "ok"), gets=2)], "2 RECGETs sent"),
                             ([self._ledger(1, ("crc", "ok"), gets=0)], "0 RECGETs sent"),
                             ([self._ledger(1, ("crc", "ok"), gets=1, acks=0)], "never acknowledged"),
                             ([self._ledger(1, ("crc", "ok"), gets=1, conflict=True)], "not exercised exactly"),
                             ([], "no REC transaction ledger for seq 1"),
                             ([self._ledger(2, ("crc", "ok"), gets=1)], "no REC transaction ledger for seq 1")):
            f = lc.rec_control_findings(leds, armed=True)
            self.assertEqual(len(f), 1, (needle, f)); self.assertIn(needle, f[0])

    def test_median_from_a_calibration_report(self):
        self.assertEqual(lc.median_settle_polls_from_report({"settle_polls": {"median": 16.0}}), 16.0)
        self.assertIsNone(lc.median_settle_polls_from_report({}))


if __name__ == "__main__":
    unittest.main()
