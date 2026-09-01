"""The post-build package must not contradict itself.

Written because it kept happening. Twice in one batch a document went on naming an image
hash that had been withdrawn — `status.md`'s L5 row accumulated text from three rounds and
ended up self-contradictory, and the preregistration and review package each kept a
superseded hash after a rebuild. A package whose own documents disagree about which image
is pinned is not reviewable, and the canonical status table is exactly where that must
never happen.

These checks are cheap and structural: one pinned image, named consistently everywhere it
is named, never a withdrawn one presented as current, and the manifests agreeing with the
artefacts they describe.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

L5 = json.loads((R / "manifests/l5_manifest.json").read_text())
PINNED = L5["pinned_at_build"]
WITHDRAWN = [w["sha256"] for w in PINNED.get("withdrawn_images", [])]
BUILT = R / "firmware/bsp/out/p3_app.bin"          # gitignored: absent on a fresh clone
EVIDENCE = R / "evidence/l5_build/build_evidence.json"

# every tracked document that talks about which image is pinned
DOCS = ["docs/status.md", "docs/l5_prereg.md", "docs/l5_wire_findings.md",
        "docs/l5_review_package.md", "docs/l5_findings.md"]


class PinnedImage(unittest.TestCase):
    def test_the_pinned_hash_is_well_formed_and_not_withdrawn(self):
        sha = PINNED["app_image_sha256"]
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertNotIn(sha, WITHDRAWN,
                         "the pinned image is also listed as withdrawn")

    def test_withdrawn_images_are_recorded_with_a_reason(self):
        self.assertTrue(WITHDRAWN, "the withdrawal history is part of the package")
        for w in PINNED["withdrawn_images"]:
            self.assertRegex(w["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(w.get("why", "").strip(), f"{w['sha256'][:8]} withdrawn silently")
        self.assertEqual(len(set(WITHDRAWN)), len(WITHDRAWN), "a hash withdrawn twice")

    def test_the_built_binary_matches_the_manifest(self):
        if not BUILT.is_file():
            self.skipTest(f"{BUILT} absent (out/ is gitignored); run firmware/bsp/build.sh")
        self.assertEqual(hashlib.sha256(BUILT.read_bytes()).hexdigest(),
                         PINNED["app_image_sha256"])

    def test_the_build_evidence_agrees_with_the_manifest(self):
        ev = json.loads(EVIDENCE.read_text())
        self.assertEqual(ev["image"]["bin_sha256"], PINNED["app_image_sha256"])
        self.assertEqual(ev["image"]["expected_bin_sha256"], PINNED["app_image_sha256"])
        self.assertTrue(ev["image"]["reproduced_byte_identical"])
        self.assertEqual(ev["toolchain"]["tarball_sha256"],
                         PINNED["toolchain"]["tarball_sha256"])
        self.assertEqual(ev["bsp_inputs"]["count"], PINNED["bsp_inputs"]["count"])

    def test_the_bsp_input_manifest_agrees_with_its_summary(self):
        inputs = json.loads((R / "manifests/l5_bsp_inputs.json").read_text())
        self.assertEqual(inputs["count"], PINNED["bsp_inputs"]["count"])
        self.assertEqual(inputs["count"], len(inputs["files"]))


L6 = json.loads((R / "manifests/l6_manifest.json").read_text())
L6_PINNED = L6["pinned_at_build"]
L6_WITHDRAWN = [w["sha256"] for w in L6_PINNED.get("withdrawn_images", [])]
L6_BUILT = R / "firmware/bsp/out/p3_app_l6.bin"
L6_EVIDENCE = R / "evidence/l6_build/build_evidence.json"


class PinnedL6Image(unittest.TestCase):
    """The two-operator image (L6 §2): pinned, reproduced byte-identical, built from the
    same identified BSP input set, and never confusable with the L5 image."""

    def test_the_l6_pin_is_well_formed_and_is_not_the_l5_image(self):
        sha = L6_PINNED["app_image_sha256"]
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertNotEqual(sha, PINNED["app_image_sha256"])
        self.assertNotIn(sha, WITHDRAWN); self.assertNotIn(sha, L6_WITHDRAWN)
        for w in L6_PINNED["withdrawn_images"]:
            self.assertRegex(w["sha256"], r"^[0-9a-f]{64}$"); self.assertTrue(w["why"].strip())

    def test_the_built_l6_binary_matches_the_manifest(self):
        if not L6_BUILT.is_file():
            self.skipTest(f"{L6_BUILT} absent (out/ is gitignored); run IMAGE=p3_app_l6 firmware/bsp/build.sh")
        self.assertEqual(hashlib.sha256(L6_BUILT.read_bytes()).hexdigest(), L6_PINNED["app_image_sha256"])

    def test_the_l6_build_evidence_agrees_with_the_manifest(self):
        ev = json.loads(L6_EVIDENCE.read_text())
        self.assertEqual(ev["schema"], "l6_build_evidence")
        self.assertEqual(ev["image"]["bin_sha256"], L6_PINNED["app_image_sha256"])
        self.assertEqual(ev["image"]["expected_bin_sha256"], L6_PINNED["app_image_sha256"])
        self.assertTrue(ev["image"]["reproduced_byte_identical"])
        self.assertEqual(ev["image"]["elf_sha256"], L6_PINNED["elf_sha256"])
        self.assertEqual(ev["toolchain"]["tarball_sha256"], L6_PINNED["toolchain"]["tarball_sha256"])
        self.assertEqual(ev["bsp_inputs"]["manifest"], "manifests/l6_bsp_inputs.json")
        self.assertEqual(ev["bsp_inputs"]["count"], L6_PINNED["bsp_inputs"]["count"])

    def test_the_cited_test_report_exists_and_is_green(self):
        """Blocker 2 of the compatibility review: the evidence cited a stale report and the
        generator would have cited a red one. A cited report must exist, hash as recorded,
        and be green; a `pending` citation is allowed only as the pre-suite step and must
        say so."""
        ev = json.loads(L6_EVIDENCE.read_text())["tests"]
        if ev["report"] is None:
            self.assertIn("PENDING", ev["status"])
            return
        path = R / ev["report"]
        self.assertTrue(path.is_file(), ev["report"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ev["report_sha256"])
        rep = json.loads(path.read_text())
        self.assertEqual(rep["exit_status"], 0); self.assertNotIn("FAILED", rep["result_line"])
        self.assertEqual((ev["ran"], ev["head_at_run"]), (rep["ran"], rep["head_at_run"]))

    def test_the_watchdog_pins_are_the_d_s1_values(self):
        self.assertTrue(L6_PINNED["watchdog_enabled"])
        self.assertEqual((L6_PINNED["watchdog_prescaler"], L6_PINNED["watchdog_load_value"]), (7, 1250000035))
        # 30.0 s at PERIPHCLK/8, from the manifest's own clock — the derivation the pin was made from
        self.assertAlmostEqual((L6_PINNED["watchdog_load_value"] + 1) * 8 / L6_PINNED["peripheral_clock_hz"], 30.0, places=6)

    def test_the_frozen_prereg_hashes_to_its_pin(self):
        """Frozen 2026-09-01 after the compatibility review PASS: the document on disk must
        hash to the pin, or the runner (which checks the same thing) refuses every session."""
        pin = L6["prereg"]["sha256"]
        self.assertRegex(pin, r"^[0-9a-f]{64}$")
        self.assertEqual(hashlib.sha256((R / "docs/l6_soak_prereg.md").read_bytes()).hexdigest(), pin)
        self.assertIn("FROZEN", (R / "docs/l6_soak_prereg.md").read_text().splitlines()[0])

    def test_once_frozen_the_build_evidence_must_cite_a_green_report(self):
        """The freeze-time guard the owner asked for (2026-09-01): a `pending`/null report
        citation is allowed only while the prereg is a draft. Frozen ⇒ the evidence cites
        a report that exists, hashes as recorded and is green."""
        if L6["prereg"]["sha256"] is None:
            self.skipTest("draft: the pending citation is allowed until the freeze")
        ev = json.loads(L6_EVIDENCE.read_text())["tests"]
        self.assertIsNotNone(ev["report"], "frozen prereg with a pending build-evidence report")
        path = R / ev["report"]
        self.assertTrue(path.is_file(), ev["report"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ev["report_sha256"])
        rep = json.loads(path.read_text())
        self.assertEqual(rep["exit_status"], 0); self.assertNotIn("FAILED", rep["result_line"])


class WithdrawnHashesStayInHistory(unittest.TestCase):
    """A withdrawn image hash may appear ONLY where it is history.

    Scope lesson: the first version of this guard scanned `docs/*.md` only, and a review
    caught what it missed — `manifests/l5_bsp_inputs.json`'s `purpose` still described the
    input set as feeding image `7540239f…`, by then withdrawn twice over. The provenance
    manifest and the post-build package thus disagreed about the same input set, and the
    generator that wrote the string would have reintroduced it. So the scan is now
    repo-wide over tracked text, and every file allowed to mention a withdrawn hash must say
    why, here, deliberately.

    History is NOT scrubbed: findings, decisions and superseded packages keep their hashes,
    because rewriting them would be falsifying the record.
    """

    ALLOWED = {
        "manifests/l5_manifest.json": "withdrawn_images IS the history",
        "docs/l5_wire_findings.md": "§7 image history",
        "docs/l5_findings.md": "the round-2 record",
        "docs/decisions.md": "a decision log is historical by nature",
        "docs/status.md": "names them explicitly as withdrawn",
        "docs/l5_post_build_package.md": "the withdrawn-images table",
        "docs/l5_review_package.md": "superseded package, kept as record",
        "docs/l5_review_result.md": "the round-2 review, verbatim",
        "docs/l5_prereg.md": "the image-change-on-record paragraph",
        "docs/l5_session2_findings.md": "names session 1's image when comparing the two runs",
        "docs/l5_session1_findings.md": "names the image that RAN session 1 — that is the "
                                        "record, and it must stay identifiable",
        "docs/l5_session3_findings.md": "names the image that RAN session 3 — the record, and "
                                        "it must stay identifiable",
        "docs/l5_settle_correction.md": "the design-correction record: says which image it "
                                        "supersedes and why",
        "tests/test_package_consistency.py": "this guard names them to test itself",
        # the L6 line's withdrawn image (compatibility review 2026-09-01, blocker 1)
        "manifests/l6_manifest.json": "withdrawn_images IS the history",
        "docs/l6_compat_review_package.md": "names the withdrawn image and why (§1, §4.7)",
        "docs/l6_c1_session1_findings.md": "records that the session refutes the withdrawn image's defect on hardware",
    }
    # evidence/ is recorded observation: never edited, never scanned
    SKIP_PREFIXES = ("evidence/", "data/", "builds/", "imported/", "gate_runs/", "fixtures/")
    TEXT_SUFFIXES = (".py", ".md", ".json", ".c", ".h", ".sh", ".v", ".tcl", ".xdc")

    def test_no_current_context_still_names_a_withdrawn_image(self):
        import subprocess
        tracked = subprocess.check_output(["git", "-C", str(R), "ls-files"], text=True).split()
        short = {w[:8] for w in WITHDRAWN + L6_WITHDRAWN}
        offenders = []
        for rel in tracked:
            if rel.startswith(self.SKIP_PREFIXES) or not rel.endswith(self.TEXT_SUFFIXES):
                continue
            if rel in self.ALLOWED:
                continue
            try:
                text = (R / rel).read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for s in short:
                if s in text:
                    offenders.append(f"{rel} still names withdrawn {s}…")
        self.assertEqual(offenders, [], "; ".join(offenders))

    def test_every_allowance_is_still_needed_and_real(self):
        """An allowance that no longer applies is a stale exemption: it would let a future
        drift in unnoticed."""
        short = {w[:8] for w in WITHDRAWN + L6_WITHDRAWN}
        for rel in self.ALLOWED:
            path = R / rel
            self.assertTrue(path.is_file(), f"{rel} is allowed to keep history but is gone")
            text = path.read_text()
            self.assertTrue(any(s in text for s in short),
                            f"{rel} is exempted but names no withdrawn hash; drop the exemption")


class DocumentsAgree(unittest.TestCase):
    """A withdrawn hash may be *discussed* — the history is evidence — but never presented
    as the current one."""

    PRESENTED_AS_CURRENT = re.compile(
        r"(?:pinned image (?:is )?|app_image_sha256`? = |Pinned image: )\**`?([0-9a-f]{8})",
        re.IGNORECASE)

    def test_no_document_presents_a_withdrawn_image_as_pinned(self):
        current = PINNED["app_image_sha256"][:8]
        withdrawn8 = {w[:8] for w in WITHDRAWN}
        for rel in DOCS:
            text = (R / rel).read_text()
            for m in self.PRESENTED_AS_CURRENT.finditer(text):
                found = m.group(1).lower()
                self.assertNotIn(found, withdrawn8,
                                 f"{rel} presents withdrawn {found}… as the pinned image")
                self.assertEqual(found, current,
                                 f"{rel} names {found}… as pinned, manifest says {current}…")

    def test_the_canonical_table_names_the_current_image(self):
        row = next(l for l in (R / "docs/status.md").read_text().splitlines()
                   if l.startswith("| L5 the loop |"))
        self.assertIn(PINNED["app_image_sha256"][:8], row)
        # This guard has been retargeted twice rather than deleted: first from "never run on
        # hardware" (expired at session 1) to "must say HOLD" (expired at the owner's ruling
        # on session 4, 2026-09-01). It now pins the adjudication itself: the state is the
        # owner's scoped PASS, the adjudicated column names the owner and the date, and the
        # scope is stated in the row — so neither a wider claim nor a drift back to HOLD can
        # appear in the canonical table by accident.
        cells = row.split("|")
        state, adjudicated = cells[2], cells[3]
        # the state is what the field OPENS with; the history it goes on to tell may name
        # the HOLDs that preceded the ruling (a blunt "no HOLD anywhere" tripped on exactly
        # that and was pushed red — 0d52e5b — so the property is stated precisely here)
        self.assertTrue(state.strip().startswith("**PASS (scoped)**"),
                        "the canonical L5 state must open with the owner's scoped PASS")
        self.assertIn("owner", adjudicated); self.assertIn("2026-09-01", adjudicated)
        for scope_word in ("17A6", "956379fa", "a7c73d1f", "N = 8", "all-self-reporting",
                           "Not extrapolated"):
            self.assertIn(scope_word, row, f"the scope must stay in the row: {scope_word}")

    def test_the_drift_guard_catches_the_drift_it_exists_for(self):
        """Discrimination. Verified live once by editing the preregistration to name a
        withdrawn hash — the guard failed as it should — and kept here so it stays honest."""
        withdrawn8 = {w[:8] for w in WITHDRAWN}
        stale = f"the pinned image is `{WITHDRAWN[0][:8]}…`"
        found = self.PRESENTED_AS_CURRENT.search(stale)
        self.assertIsNotNone(found, "the pattern no longer matches how docs say 'pinned'")
        self.assertIn(found.group(1), withdrawn8)
        fresh = f"the pinned image is `{PINNED['app_image_sha256'][:8]}…`"
        self.assertNotIn(self.PRESENTED_AS_CURRENT.search(fresh).group(1), withdrawn8)

    def test_the_audit_policy_is_named_the_same_everywhere(self):
        policy = PINNED["audit_policy"]["policy"]
        from validators import records
        self.assertEqual(records.check_audit_policy(
            {"loop_records": []}, {})["policy"], policy)
        self.assertIn(policy, (R / "docs/l5_prereg.md").read_text())


if __name__ == "__main__":
    unittest.main()
