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
        self.assertIn("never run on hardware", row,
                      "the table must keep saying the firmware has not run")

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
            {"loop_records": []})["policy"], policy)
        self.assertIn(policy, (R / "docs/l5_prereg.md").read_text())


if __name__ == "__main__":
    unittest.main()
