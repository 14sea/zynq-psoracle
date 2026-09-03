"""S #2 host batch, part 4 — reusing a v0.6 calibration under v0.7 is an EXPLICIT IMPORT.

D-r5 binds every calibration to the image, preregistration and protocol it ran under, and
the S runner refuses a report whose binding is not the current pin. Freezing v0.7 changes
the preregistration hash, so C1 #6 (`08222f85…`) and C2 #2 (`959790d0…`) — both bound to
v0.6 `bfd69d10…` — would be refused and v0.7 would have to re-calibrate.

The owner's rule (2026-09-03): they may be reused only "按 report 與三份 input hash 明文
匯入" — never by pretending they are bound to the new hash. `calibration.<k>.imported`
is that declaration: the prereg hash and version the report IS bound to, its own sha256,
its three input hashes, and why the v0.7 changes cannot move the measured period. The
import relaxes the prereg hash and NOTHING else; if the owner does not accept the
justification, v0.7 re-calibrates.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l6_runner as l6  # noqa: E402
import l6_soak_plan as lsp  # noqa: E402

L6M = json.loads((R / "manifests/l6_manifest.json").read_text())
V07_SHA = "07" * 32          # a stand-in for the v0.7 text's hash: v0.7 is NOT frozen here


V06_SHA = L6M["prereg"]["sha256"]           # the frozen v0.6 the reports are bound to


def manifest_v07(with_import: bool = True, n_rule: str = "policy_matched_wall", version: str = "v0.7",
                 supersedes_v06: bool = True, **over) -> dict:
    m = copy.deepcopy(L6M)
    m["prereg"]["version"] = version
    m["prereg"]["sha256"] = V07_SHA
    if supersedes_v06:                      # what the freeze writes: v0.6 heads the chain
        m["prereg"]["supersedes"] = [{"version": "v0.6", "sha256": V06_SHA, "protocol": "rel-v4",
                                      "note": "frozen 2026-09-03; ran C1 #6, C2 #2, S #2"}] + m["prereg"]["supersedes"]
    m["sessions"]["S"]["n_rule"] = n_rule
    if with_import:
        for k in ("C1", "C2"):
            c = m["calibration"][k]
            c["imported"] = {"from_prereg_sha256": c["binding"]["prereg_sha256"], "from_prereg_version": "v0.6",
                             "report_sha256": c["rate_report_sha256"], "inputs": dict(c["inputs"]),
                             "why": "v0.7 changes only host-side adjudication (the malformed-line policy, the "
                                    "heartbeat rule, the closing-baseline gate, the N rule); the image, the wire "
                                    "protocol, the operator contract, the seeds and the audit policy of C1/C2 are "
                                    "the ones these reports were measured under, so no change can move the period"}
            c.update(over.get(k, {}))
    return m


class ExplicitImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports, cls.logs = lsp.load_pinned(L6M)

    def plan(self, m):
        return l6.plan_session(m, "S", None, 7200.0, self.reports, None, calibration_logs=self.logs)

    def test_without_the_declaration_a_v06_calibration_is_refused_under_v07(self):
        with self.assertRaises(ValueError) as cm:
            self.plan(manifest_v07(with_import=False))
        self.assertIn("is bound to prereg_sha256", str(cm.exception))
        self.assertIn("needs new C1/C2", str(cm.exception))

    def test_with_the_declaration_the_soak_plans_and_records_the_import(self):
        p = self.plan(manifest_v07())
        self.assertEqual(p["n"], 12568, "D-n1 as ruled 2026-09-03: the faster arm sizes N")
        self.assertEqual(sorted(p["inputs"]["calibrations_imported"]), ["C1", "C2"])
        for k in ("C1", "C2"):
            decl = p["inputs"]["calibrations_imported"][k]
            self.assertEqual(decl["from_prereg_version"], "v0.6")
            self.assertEqual(decl["from_prereg_sha256"], V06_SHA)
            self.assertEqual(decl["report_sha256"], L6M["calibration"][k]["rate_report_sha256"])
            # the plan's evidence keeps the three input hashes VERBATIM — no placeholder
            self.assertEqual(decl["inputs"], self.reports[k]["inputs"])
            self.assertEqual(sorted(decl["inputs"]), ["audits", "run_log", "timeline"])
            for v in decl["inputs"].values():
                self.assertRegex(v, r"^[0-9a-f]{64}$")
            self.assertNotIn("(the report's)", json.dumps(decl))

    def test_the_import_is_honoured_only_under_v07(self):
        for version in ("v0.8", "v0.6", "v1.0"):
            with self.subTest(version=version), self.assertRaises(ValueError) as cm:
                self.plan(manifest_v07(version=version))
            self.assertIn("honoured only under", str(cm.exception))
            self.assertIn("rule the import in its own text", str(cm.exception))

    def test_the_version_is_mandatory_and_paired_with_the_hash_through_the_supersedes_chain(self):
        base = manifest_v07()["calibration"]["C1"]["imported"]
        m = manifest_v07(C1={"imported": {k: v for k, v in base.items() if k != "from_prereg_version"}})
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("must name from_prereg_version", str(cm.exception))
        # the right hash under the wrong version is refused: the pair must be in the chain
        m = manifest_v07(C1={"imported": dict(base, from_prereg_version="v0.4")})
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("not a (version, sha256) pair in prereg.supersedes", str(cm.exception))
        # and so is a v0.6 the chain does not record at all
        m = manifest_v07(supersedes_v06=False)
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("not a (version, sha256) pair", str(cm.exception))

    def test_the_import_relaxes_the_prereg_hash_and_nothing_else(self):
        # a different image is still refused, import or no import
        m = manifest_v07()
        m["pinned_at_build"]["app_image_sha256"] = "ab" * 32
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("is bound to image_sha256", str(cm.exception))
        # so is a different protocol
        m = manifest_v07(); m["pinned_at_build"]["protocol"] = "rec-v3"
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("is bound to protocol", str(cm.exception))

    def test_an_import_naming_the_wrong_prereg_hash_is_refused(self):
        m = manifest_v07(C1={"imported": dict(manifest_v07()["calibration"]["C1"]["imported"],
                                              from_prereg_sha256="cd" * 32)})
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("not a (version, sha256) pair", str(cm.exception),
                      "the pair check catches it first, and says which chain it looked in")

    def test_an_import_naming_another_report_or_other_inputs_is_refused(self):
        base = manifest_v07()["calibration"]["C1"]["imported"]
        m = manifest_v07(C1={"imported": dict(base, report_sha256="ef" * 32)})
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("report_sha256 is not the pinned one", str(cm.exception))
        m = manifest_v07(C1={"imported": dict(base, inputs=dict(base["inputs"], run_log="00" * 32))})
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("input hashes are not the report's", str(cm.exception))

    def test_an_import_without_a_justification_is_refused(self):
        base = manifest_v07()["calibration"]["C1"]["imported"]
        m = manifest_v07(C1={"imported": dict(base, why="   ")})
        with self.assertRaises(ValueError) as cm:
            self.plan(m)
        self.assertIn("must say why", str(cm.exception))

    def test_under_v06_nothing_of_this_runs_and_the_committed_manifest_declares_no_import(self):
        for k in ("C1", "C2"):
            self.assertNotIn("imported", L6M["calibration"][k], "the frozen v0.6 needs no import: it IS the pin")
        p = l6.plan_session(L6M, "S", None, 7200.0, self.reports, None)
        self.assertNotIn("calibrations_imported", p["inputs"])
        self.assertEqual(p["n"], 6061)


if __name__ == "__main__":
    unittest.main()
