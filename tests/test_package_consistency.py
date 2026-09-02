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
        """With a next_image pinned, HEAD's sources build THAT image (the board-ready
        pinned one is historical and no longer reproducible from HEAD, as with L5)."""
        if not L6_BUILT.is_file():
            self.skipTest(f"{L6_BUILT} absent (out/ is gitignored); run IMAGE=p3_app_l6 firmware/bsp/build.sh")
        want = (L6.get("next_image") or L6_PINNED)["app_image_sha256"]   # HEAD builds the newest pin
        self.assertEqual(hashlib.sha256(L6_BUILT.read_bytes()).hexdigest(), want)

    def test_one_image_one_authority(self):
        """After the promotion (freeze batch 2026-09-01) there is exactly one current
        authority: pinned_at_build, board_ready, pull-v2, with the promotion recorded; a
        candidate, when one exists again, is next_image with board_ready false."""
        nxt = L6.get("next_image")
        if nxt is None:
            self.assertTrue(L6_PINNED["board_ready"])
            self.assertEqual(L6_PINNED["protocol"], "rec-v3")           # promotion 2026-09-02
            self.assertEqual(L6["prereg"]["protocol"], "rec-v3")
            self.assertIn("promoted", L6_PINNED["promoted_note"])
            sup = L6_PINNED["superseded_images"]
            self.assertEqual([s["sha256"][:8] for s in sup], ["bd1454cd", "e19e1b12"])
            for s in sup:
                self.assertIn("NOT defective", s["why"])
            self.assertEqual([w["sha256"][:8] for w in L6_PINNED["withdrawn_images"]], ["47b8fa09", "cd8360dc"])
            e = json.loads((R / "evidence/l6_next_build/build_evidence.json").read_text())
            self.assertEqual(e["image"]["bin_sha256"], L6_PINNED["app_image_sha256"],
                             "the promoted pin is the candidate the review passed")
            return
        self.assertFalse(nxt["board_ready"])
        self.assertNotEqual(nxt["app_image_sha256"], L6_PINNED["app_image_sha256"],
                            "the candidate must never silently replace the board-ready pin")

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

    def test_the_frozen_prereg_speaks_in_the_present_protocol(self):
        """Frozen-artifact review 2026-09-01: the frozen v0.3 text kept three v0.2 passages
        as if current. The frozen prereg may cite history, but must never present the
        push-era mechanism or the 'nothing measured' state as the present."""
        text = (R / "docs/l6_soak_prereg.md").read_text()
        self.assertNotIn("serve_audit", text, "the push-era call path presented as current")
        self.assertNotIn("No P3 session has\n  measured", text)
        self.assertNotIn("the per-candidate rate is unknown", text)
        self.assertNotIn("not implementable under the current wire protocol", text)
        self.assertIn("No PASS\n  calibration exists to pin", text)
        self.assertIn("v0.2 HISTORICAL — resolved by pull-v2", text)
        self.assertIn("`AUDIT_READY` → (`AUDITGET` → `AUDIT`)×chunks", text)
        self.assertIn("pull-v2", text)
        # v0.4 (2026-09-02): the frozen text preregisters rec-v3 in the present tense
        self.assertIn("FROZEN 2026-09-02", text.splitlines()[0]); self.assertIn("v0.4", text.splitlines()[0])
        for present in ("rec-v3", "`RECACK {seq}`", "`RECGET {seq}`", "STOP_REC", "rec_closure_findings",
                        "rec_control_findings", "D-r5", "403f4ab5", "historical_pull_v2", "may not be reused"):
            self.assertIn(present, text, present)
        self.assertNotIn("cd8360dc… is `next_image`", text)

    def test_the_v0_3_calibrations_are_historical_and_unpinned(self):
        """Promotion/freeze batch 2026-09-02: under rec-v3 the active C1/C2 pins are null;
        the pull-v2 reports stay on record as historical and are refused for S by the
        runner (tests/test_l6_runner.py checks the real files)."""
        for k in ("C1", "C2"):
            self.assertIsNone(L6["calibration"][k]["rate_report_sha256"], k)
        hist = L6["calibration"]["historical_pull_v2"]
        self.assertEqual(hist["C1"]["rate_report_sha256"][:8], "786dc3ec")
        self.assertEqual(hist["C2"]["rate_report_sha256"][:8], "a13e301f")
        for k in ("C1", "C2"):
            self.assertEqual(hist[k]["image_sha256"][:8], "e19e1b12"); self.assertEqual(hist[k]["protocol"], "pull-v2")
            self.assertIn("HISTORICAL", hist[k]["standing"])
            path = R / hist[k]["evidence"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hist[k]["rate_report_sha256"])
            self.assertNotIn("binding", json.loads(path.read_text()), "a pull-v2 report carries no rec-v3 binding")

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


class HardwareHistoryIsConsistent(unittest.TestCase):
    """Owner 2026-09-01 (C1 #1 review): the manifest said the current image had never run
    on hardware and the canonical row said "no C1/C2/S" in the same breath as recording
    C1 #1. Once a session evidence directory exists, the authoritative statements must
    say so, and no row may carry both a session record and its denial."""

    SESSIONS = sorted(p.name for p in (R / "evidence").glob("l6_17A6_*"))
    COUNT_KEYS = ("scored_records", "opening_baselines", "scheduled_candidates", "closing_baselines")

    @staticmethod
    def counts_from_run_log(d: Path) -> dict:
        """Derived from the evidence, not typed: a SCORED record without an arm is a
        baseline (seq 1 opening; the last seq on a COMPLETED epoch closing); with an arm it
        is a scheduled candidate. C1 #1's review caught "23 candidates" for 23 SCORED
        records of which one was the opening baseline."""
        log = json.loads((d / "run_log.json").read_text())
        recs = log["loop_records"]
        completed = log["session_summary"]["epoch_end"]["kind"] == "COMPLETED"
        last = max(r["seq"] for r in recs) if recs else 0
        scored = [r for r in recs if r["outcome"] == "SCORED"]
        opening = sum(1 for r in scored if r.get("arm") is None and r["seq"] == 1)
        closing = sum(1 for r in scored if r.get("arm") is None and completed and r["seq"] == last and last != 1)
        scheduled = sum(1 for r in recs if r.get("arm") is not None)
        assert opening + closing + scheduled == len(recs), "every record is a baseline or a scheduled candidate"
        return {"scored_records": len(scored), "opening_baselines": opening,
                "scheduled_candidates": scheduled, "closing_baselines": closing}

    def test_the_count_derivation_reads_c1_1_as_the_review_did(self):
        c = self.counts_from_run_log(R / "evidence/l6_17A6_2026-09-01-06-C1")
        self.assertEqual(c, {"scored_records": 23, "opening_baselines": 1, "scheduled_candidates": 22, "closing_baselines": 0})

    def test_no_authoritative_text_calls_records_candidates_or_clears_an_incomplete_image(self):
        row = next(l for l in (R / "docs/status.md").read_text().splitlines()
                   if l.startswith("| L6 calibration + soak |"))
        for text, where in ((row, "status row"), (L6_PINNED["standing"], "manifest standing"),
                            ((R / "docs/l6_c1_session1_findings.md").read_text(), "findings")):
            self.assertNotIn("23 candidates", text, where)
            self.assertNotIn("without defect", text, where)
            self.assertNotIn("showed no defect", text, where)

    def test_the_manifest_standing_matches_the_evidence_on_disk(self):
        standing = L6_PINNED["standing"]
        history = L6_PINNED.get("hardware_history", [])
        if self.SESSIONS:
            self.assertIn("RAN ON 17A6", standing)
            self.assertNotIn("Never run on hardware", standing)
            # the sessions belong to the superseded images: the standing must attribute them
            for s in L6_PINNED.get("superseded_images", []):
                self.assertIn(s["sha256"][:8], standing)
            self.assertEqual(len(history), len(self.SESSIONS), (history, self.SESSIONS))
            for h, d in zip(history, self.SESSIONS):
                self.assertTrue((R / h["evidence"]).is_dir(), h)
                self.assertIn(h["ruling"], d)
                self.assertRegex(h["outcome"], r"^(PASS|HOLD|KILL)")
                self.assertEqual({k: h[k] for k in self.COUNT_KEYS}, self.counts_from_run_log(R / h["evidence"]),
                                 f"{h['session']}: the history's counts are not the run log's")
        else:
            self.assertEqual(history, [])

    def test_the_canonical_row_does_not_deny_what_it_records(self):
        row = next(l for l in (R / "docs/status.md").read_text().splitlines()
                   if l.startswith("| L6 calibration + soak |"))
        if self.SESSIONS:
            self.assertIn("C1 #1", row)
            for denial in ("no C1/C2/S", "never run on hardware", "board untouched", "Never run on hardware"):
                self.assertNotIn(denial, row, f"the row records a session and still says {denial!r}")
        # a calibration pin exists only with a PASS session recorded for it
        for k in ("C1", "C2"):
            if L6["calibration"][k]["rate_report_sha256"]:
                self.assertIn(f"{k}", row)
                self.assertTrue(any(h["session"].startswith(k) and h["outcome"].startswith("PASS")
                                    for h in L6_PINNED.get("hardware_history", [])),
                                f"calibration.{k} is pinned without a PASS session in hardware_history")


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
        # the rec-v3 batch's first candidate, withdrawn DEFECTIVE in the owner's review 2026-09-02
        "docs/l6_rec_batch_package.md": "names the withdrawn first candidate and the four blockers that withdrew it",
        "docs/l6_rec_transaction_design.md": "§8: the review of the first candidate, by hash",
        "docs/import_manifest.md": "lists the preserved build record of the withdrawn candidate by its file name",
        "docs/l6_soak_prereg.md": "§1: names the withdrawn candidate as one the frozen text forbids to run",
        "docs/l6_soak_prereg_v0.5_draft.md": "§1: the self-contained v0.5 text carries the frozen text's forbidding "
                                             "of the withdrawn candidate verbatim (owner: no delta drafts)",
        "docs/l6_soak_prereg_v0.6_draft.md": "§1: the self-contained v0.6 text (v0.5 never frozen, carried verbatim) keeps "
                                             "the frozen text's forbidding of the withdrawn candidate",
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
