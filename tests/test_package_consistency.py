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
sys.path.insert(0, str(R / "host"))     # the S-plan guard imports l6_runner; the module must not depend on test order (owner 2026-09-03)

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
        """After a promotion there is exactly one current authority: pinned_at_build,
        board_ready, with the promotion recorded; a candidate, when one exists again, is
        next_image with board_ready false. Promotion 2026-09-03 (owner's batch): 5deee74c…
        rel-v4 is the pin; 403f4ab5… joins the superseded (NOT defective) with its C1 #5."""
        nxt = L6.get("next_image")
        # the history's exact sets hold whether or not a candidate exists (review
        # 2026-09-03, evidence closure: these guards used to sit in the no-candidate
        # branch and did not run while a next_image was pinned)
        self.assertTrue(L6_PINNED["board_ready"])
        self.assertEqual(L6_PINNED["protocol"], "rel-v4")           # promotion 2026-09-03
        self.assertEqual(L6["prereg"]["protocol"], "rel-v4")
        self.assertEqual(L6_PINNED["app_image_sha256"][:8], "5deee74c")
        self.assertEqual(L6_PINNED["elf_sha256"][:8], "ebe97ce6"); self.assertEqual(L6_PINNED["app_image_bytes"], 98324)
        self.assertIn("promoted", L6_PINNED["promoted_note"])
        sup = L6_PINNED["superseded_images"]
        self.assertEqual([s["sha256"][:8] for s in sup], ["bd1454cd", "e19e1b12", "403f4ab5"])
        for s in sup:
            self.assertIn("NOT defective", s["why"])
        self.assertIn("C1 #5", sup[-1]["why"]); self.assertIn("HOLD", sup[-1]["why"])   # the history is kept, not re-judged
        self.assertEqual([w["sha256"][:8] for w in L6_PINNED["withdrawn_images"]], ["47b8fa09", "cd8360dc", "734d6c04"])
        for w in L6_PINNED["withdrawn_images"]:
            self.assertIn("DEFECTIVE", w["why"]); self.assertIn("must not run", w["why"])
        e = json.loads((R / "evidence/l6_next_build/build_evidence.json").read_text())
        if nxt is None:
            self.assertEqual(e["image"]["bin_sha256"], L6_PINNED["app_image_sha256"],
                             "the promoted pin is the candidate the review passed")
            self.assertNotIn("next_prereg", L6, "a frozen prereg leaves no draft entry behind (history lives in prereg.*)")
            return
        self.assertFalse(nxt["board_ready"])
        self.assertNotEqual(nxt["app_image_sha256"], L6_PINNED["app_image_sha256"],
                            "the candidate must never silently replace the board-ready pin")
        self.assertNotIn(nxt["app_image_sha256"], L6_WITHDRAWN, "a withdrawn image can never be the candidate")
        self.assertEqual(e["image"]["bin_sha256"], nxt["app_image_sha256"],
                         "the live next-build evidence is the candidate's")
        self.assertEqual(e["image"]["elf_sha256"], nxt["elf_sha256"])

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
        self.assertIn("exists to pin", text)
        self.assertIn("v0.2 HISTORICAL — resolved by pull-v2", text)
        self.assertIn("`AUDIT_READY` → (`AUDITGET` → `AUDIT`)×chunks", text)
        self.assertIn("pull-v2", text)
        # v0.4 (2026-09-02) preregistered rec-v3 in the present tense; v0.6 keeps rec-v3's
        # record transaction and adds rel-v4 on top
        for present in ("rec-v3", "`RECACK {seq}`", "`RECGET {seq}`", "STOP_REC", "rec_closure_findings",
                        "rec_control_findings", "D-r5", "403f4ab5", "historical_pull_v2", "None may be reused"):
            self.assertIn(present, text, present)
        self.assertNotIn("cd8360dc… is `next_image`", text)
        # v0.6 (2026-09-03): rel-v4 in the present tense, the promoted image, no draft residue
        self.assertIn("FROZEN 2026-09-03", text.splitlines()[0]); self.assertIn("v0.6", text.splitlines()[0])
        for present in ("rel-v4", "5deee74c", "`pinned_at_build`", "`board_ready: true`", "IDENTACK", "SIGNGET",
                        "AUDITWAIT", "TERMACK", "STOP_SIGN", "STOP_IDENT", "rel_closure_findings", "rel_control_findings",
                        "rel_recovery_findings", "hb_missing_budget", "revision 4", "No PASS calibration",
                        "exists to pin under v0.6", "No rec-v3 calibration was ever pinned", "12799ef9",
                        "**v0.5 was\n> never frozen**", "TRIGGERED through", "exactly ONE rel-v4 C1",
                        "not re-judged", "734d6c04", "image has not run on hardware"):
            self.assertIn(present, text, present)

    # the owner's list (2026-09-03) of the draft's present-tense drift that must never be
    # frozen as the current state again — plus the draft's own standing words
    V06_STALE_AS_PRESENT = ("DRAFT, NOT FROZEN", "NOT FROZEN", "becomes v0.6 at the", "not yet started", "not\n   started",
                            "firmware batch opened", "revision 2", "rev. 2", "next_image", "board_ready: false",
                            "pending the short re-review", "then this text is frozen", "promoted at the freeze",
                            "pending review", "the correction batch, pending", "next_prereg", "is the owner's to start",
                            "proposed, not ruled", "and proposed (D-p1")

    def test_the_frozen_v06_carries_none_of_the_drafts_stale_present_tense(self):
        """Freeze-time guard (owner 2026-09-03): the v0.6 draft could not be frozen as it
        stood — it said the reliability design was revision 2 (it is 4), the firmware batch
        'not yet started' (delivered, reviewed HOLD → PASS → PASS), 5deee74c… 'next_image /
        board_ready: false' (promoted), and 'pending the short re-review' (done). None of
        those may appear in the frozen text; the manifest's own standing strings and the
        firmware package's standing block are held to the same words."""
        text = (R / "docs/l6_soak_prereg.md").read_text()
        for stale in self.V06_STALE_AS_PRESENT:
            self.assertNotIn(stale, text, f"frozen v0.6 still says {stale!r}")
        self.assertEqual(L6["prereg"]["version"], "v0.6")
        manifest_present = " ".join([L6["status"], L6["prereg"]["frozen"], L6_PINNED["standing"],
                                     L6_PINNED["promoted_note"], L6["calibration"]["note"]])
        for stale in ("revision 2", "not yet started", "board_ready: false", "board_ready false",
                      "pending the short re-review", "next_prereg", "is next_image", "as next_image", "NEVER run"):
            self.assertNotIn(stale, manifest_present, f"manifest standing still says {stale!r}")
        self.assertIn("revision 4", L6["prereg"]["draft_history"]["reliability_design"])
        # the draft's review chain survives only as history, in the past tense
        hist = L6["prereg"]["draft_history"]["note"]
        self.assertIn("HISTORICAL", hist); self.assertIn("past tense", hist); self.assertIn("promoted to pinned_at_build", hist)
        pkg = (R / "docs/l6_rel_firmware_package.md").read_text()
        standing = pkg.split("## 0.")[0]
        for present in ("evidence-closure review of §8 = PASS", "PROMOTED", "`pinned_at_build`", "`board_ready: true`", "57cc22b"):
            self.assertIn(present, standing, present)
        for stale in ("is `next_image`", "`board_ready: false`; it has NEVER", "no promotion, no freeze"):
            self.assertNotIn(stale, standing, stale)
        self.assertIn("## 8.", pkg)
        s8 = pkg.split("## 8.")[1]
        self.assertIn("**Final standing", s8); self.assertIn("PASS", s8.split("**Final standing")[1])
        self.assertIn("HOLD", s8, "the re-review's HOLD stays in §8 as the process record")

    def test_the_v06_freeze_keeps_the_history_chain_intact(self):
        """The promotion/freeze batch (owner 2026-09-03): v0.4's entry joins the supersedes
        chain with its hash and its C1 #5 unchanged; the v0.5 draft is on record as never
        frozen; the draft's pass-condition bounds are merged into pass_conditions with the
        values the tests exercised; the pull-v2 calibrations are still refused and no
        rec-v3 calibration exists to reuse."""
        chain = L6["prereg"]["supersedes"]
        self.assertEqual([(s["version"], s["sha256"][:8], s["protocol"]) for s in chain],
                         [("v0.4", "12799ef9", "rec-v3"), ("v0.3", "8daa81f2", "pull-v2"), ("v0.2", "90f5fa69", "push-v1")])
        self.assertIn("C1 #5", chain[0]["note"]); self.assertIn("HOLD, permanent", chain[0]["note"])
        self.assertEqual(L6["prereg"]["never_frozen"][0]["version"], "v0.5-draft")
        pc = L6["pass_conditions"]
        self.assertEqual({k: pc[k] for k in ("nominal_cov_max", "min_clean_periods", "max_recovered_candidates",
                                              "max_pull_timeouts", "max_bad_frames", "max_fragments")},
                         {"nominal_cov_max": 0.1, "min_clean_periods": 60, "max_recovered_candidates": 3,
                          "max_pull_timeouts": 3, "max_bad_frames": 3, "max_fragments": 3})
        self.assertEqual({k: pc[k] for k in ("max_sign_retries", "max_ready_resends", "max_ident_repeats",
                                              "max_term_retries", "max_done_replays")}, dict.fromkeys(
                             ("max_sign_retries", "max_ready_resends", "max_ident_repeats", "max_term_retries", "max_done_replays"), 3))
        self.assertEqual(pc["cov_max"], 0.1, "v0.4's inclusive bound stays on record")
        self.assertIn("historical_rec_v3", L6["calibration"])
        self.assertIn("C1 #5", L6["calibration"]["historical_rec_v3"]["note"])
        for k in ("C1", "C2"):
            self.assertIn("rel-v4", L6["calibration"]["historical_pull_v2"][k]["standing"])
        # the archived record of the superseded rec-v3 pin closes on disk under its own name
        e = json.loads((R / "evidence/l6_build/build_evidence_403f4ab5.json").read_text())
        self.assertEqual(e["image"]["bin_sha256"][:8], "403f4ab5"); self.assertEqual(e["image"]["elf_sha256"][:8], "8687ef8d")
        self.assertEqual(e["linker_map"]["path"], "evidence/l6_build/p3_app_l6_403f4ab5.map")
        self.assertEqual(e["linker_map"]["sha256"][:8], "963dcd0f")
        self.assertEqual(L6_PINNED["superseded_images"][-1]["build_evidence"], "evidence/l6_build/build_evidence_403f4ab5.json")

    def test_the_v0_3_calibrations_are_historical_and_unpinned(self):
        """Promotion/freeze batch 2026-09-02: under rec-v3 the active C1/C2 pins were null;
        the pull-v2 reports stay on record as historical and are refused for S by the
        runner (tests/test_l6_runner.py checks the real files). Owner 2026-09-03: C1 #6 and
        C2 #2 (rel-v4, v0.6) PASS adjudicated and pinned — each pin is the bytes on disk,
        binds the current pins, its three input files hash, and the words follow the pin."""
        expected = {"C1": ("08222f85", "C1 #6", "2026-09-03-01", "random_safe_forced"),
                    "C2": ("959790d0", "C2 #2", "2026-09-03-02", "map_guided_forced")}
        for k, (sha8, session, ruling, mode) in expected.items():
            c = L6["calibration"][k]
            self.assertEqual(c["rate_report_sha256"][:8], sha8, k); self.assertEqual((c["session"], c["ruling"]), (session, ruling))
            path = R / c["evidence"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), c["rate_report_sha256"], f"{k}: the pin is the bytes on disk")
            rep = json.loads(path.read_text())
            self.assertEqual(rep["binding"], c["binding"]); self.assertEqual(rep["inputs"], c["inputs"])
            self.assertEqual(c["binding"], {"image_sha256": L6_PINNED["app_image_sha256"], "prereg_sha256": L6["prereg"]["sha256"],
                                            "protocol": "rel-v4", "session": k, "schedule_mode": mode,
                                            "master_seed": L6["sessions"][k]["master_seed"]}, f"{k}: the pin binds the current pins")
            for name, sha in c["inputs"].items():                    # D-t2: the three input files still hash to the report's inputs
                self.assertEqual(hashlib.sha256((path.parent / f"{name}.json").read_bytes()).hexdigest(), sha, name)
            self.assertTrue(any(h["session"] == session and h["outcome"].startswith("PASS") for h in L6_PINNED["hardware_history"]))
            self.assertIn("C1 #5", c["note"]); self.assertIn("HOLD", c["note"]); self.assertIn("ACTIVE", c["standing"])
            # owner's check 2026-09-03: the structured pin was right while three narrative strings
            # still called the C1 report a candidate awaiting the pin — the words must follow the pin
            narrative = {"status": L6["status"], "standing": L6_PINNED["standing"], "calibration.note": L6["calibration"]["note"],
                         "history note": next(h for h in L6_PINNED["hardware_history"] if h["session"] == session)["note"]}
            for where, text in narrative.items():
                for stale in (f"candidate for calibration.{k}", "pinned only by the owner",
                              f"awaiting the owner's adjudication and the calibration.{k} pin",
                              f"awaiting the owner's independent review before any calibration.{k} pin",
                              f"calibration.{k} is null", "calibration.C1/C2 are null", "C1/C2 are null"):
                    self.assertNotIn(stale, text, f"{where} still says {stale!r} with calibration.{k} pinned")
            self.assertIn("PINNED", narrative["standing"]); self.assertIn("PINNED", narrative["history note"])
        self.assertIn("PINNED", L6["status"]); self.assertIn("Both v0.6 calibrations are pinned", L6["status"])
        # with both pins the S plan is derived by the runner from the two PLANNING rates (D-t1) —
        # the owner's independently derived numbers (2026-09-03), never typed into a ruling
        import l6_runner as l6
        reps = {k: json.loads((R / L6["calibration"][k]["evidence"]).read_text()) for k in ("C1", "C2")}
        plan = l6.plan_session(L6, "S", None, 7200.0, reps, None)
        self.assertEqual((plan["n"], len(plan["audit_seqs"]), plan["expected_frames"]["total"], plan["crc_budget"],
                          plan["session_timeout_s"], plan["master_seed"], plan["mode"]),
                         (6061, 382, 112575, 451, 8702, 1278628687, "abba"))
        self.assertTrue(plan["inputs"]["rate_source"].startswith("planning"))
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


class BuildEvidenceClosure(unittest.TestCase):
    """Every build-evidence record under evidence/ (the live ones and the archived
    `build_evidence_<hash>.json` of superseded / withdrawn images) must close on disk: a
    non-empty artifact path resolves to a file whose sha256 is the one recorded, or says
    explicitly that the artifact is unavailable (hash-only). Review 2026-09-03 (evidence
    closure): the archived records carried the LIVE paths of their build, which resolved to
    a later image's map and binary — a record that names a path with different content is
    worse than one that names no path."""

    HASH_ONLY = "historical artifact unavailable — hash-only"
    RECORDS = sorted(R.glob("evidence/*/build_evidence*.json"))

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_there_are_records_to_check(self):
        self.assertGreaterEqual(len(self.RECORDS), 8, [str(r) for r in self.RECORDS])
        self.assertTrue(any(r.name != "build_evidence.json" for r in self.RECORDS), "archived records exist")

    def test_every_linker_map_path_exists_and_hashes(self):
        for rec in self.RECORDS:
            with self.subTest(record=str(rec.relative_to(R))):
                e = json.loads(rec.read_text())
                lm = e["linker_map"]
                self.assertTrue(lm.get("path"), "a linker map path is recorded")
                p = R / lm["path"]
                self.assertTrue(p.is_file(), f"{lm['path']} is absent")
                self.assertEqual(self._sha(p), lm["sha256"], f"{lm['path']} is not the map this record hashed")

    def test_every_cited_test_report_exists_and_hashes(self):
        for rec in self.RECORDS:
            with self.subTest(record=str(rec.relative_to(R))):
                e = json.loads(rec.read_text())
                t = e.get("tests") or {}
                if not t.get("report"):
                    self.assertNotEqual(rec.name, "build_evidence.json", "a live record cites its green report")
                    continue
                p = R / t["report"]
                self.assertTrue(p.is_file(), f"{t['report']} is absent")
                if "report_sha256" in t:
                    self.assertEqual(self._sha(p), t["report_sha256"], f"{t['report']} is not the report this record hashed")

    def test_every_binary_path_hashes_or_is_declared_unavailable(self):
        for rec in self.RECORDS:
            with self.subTest(record=str(rec.relative_to(R))):
                e = json.loads(rec.read_text())
                b = e["image"]["bin"]
                self.assertTrue(b, "the binary is named, or declared unavailable")
                archived = rec.name != "build_evidence.json"
                if b.startswith(self.HASH_ONLY):
                    note = e.get("archived") or e.get("binary_unavailable")
                    self.assertIsNotNone(note, "a hash-only record says why")
                    self.assertTrue(note["why"].strip()); self.assertTrue(note["hashes_unchanged"])
                    continue
                p = R / b
                if archived:
                    self.fail(f"an archived record names a live path ({b}) that would resolve to another image")
                if not p.is_file():
                    continue                                # out/ is gitignored; the live record's build may be absent here
                self.assertEqual(self._sha(p), e["image"]["bin_sha256"],
                                 f"{b} is not the image this record hashed — a live path must resolve to the "
                                 "recorded content or be replaced by the hash-only marker")

    def test_archived_records_keep_their_hashes_and_name_the_archived_map(self):
        for rec in self.RECORDS:
            if rec.name == "build_evidence.json":
                continue
            with self.subTest(record=str(rec.relative_to(R))):
                e = json.loads(rec.read_text())
                tag = rec.stem.split("_")[-1]
                self.assertTrue(e["image"]["bin_sha256"].startswith(tag), "the file is named by the image it records")
                self.assertEqual(Path(e["linker_map"]["path"]).name, f"p3_app_l6_{tag}.map")
                a = e["archived"]
                self.assertTrue(a["hashes_unchanged"]); self.assertTrue(a["why"].strip())
                self.assertEqual(a["original_paths"]["linker_map.path"], f"{rec.parent.relative_to(R)}/p3_app_l6.map")


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
        "docs/l6_rel_firmware_package.md": "names the withdrawn first rel-v4 candidate and the review that withdrew it (§7)",
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
