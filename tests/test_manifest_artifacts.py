"""The committed build artifacts and manifests agree with each other and with the schema."""

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from validators.records import validate  # noqa: E402

DUMMY = REPO / "builds/p3"


class DummyKeyBuild(unittest.TestCase):
    """The public build: the bitstream carries no key (D4 option A)."""

    def test_manifest_validates_and_matches_the_bitstream(self):
        m = json.loads((DUMMY / "carrier_manifest.json").read_text())
        validate(m)
        self.assertEqual(hashlib.sha256((DUMMY / "p3.bit").read_bytes()).hexdigest(), m["bitstream_sha256"])
        b = json.loads((DUMMY / "p3_build.json").read_text())
        self.assertEqual(b["bitstream_sha256"], m["bitstream_sha256"])
        self.assertTrue(b["routed"]); self.assertEqual(b["cell_isolation"], "passed"); self.assertGreater(b["wns_ns"], 0)

    def test_target_frames_blank_and_no_icap(self):
        m = json.loads((DUMMY / "carrier_manifest.json").read_text())
        self.assertTrue(m["no_icap"])
        self.assertEqual(set(m["target_frames_nonzero_words"].values()), {0})
        self.assertEqual(len(m["target_fars"]), 12)
        self.assertIn("0x00400a20", [f.lower() for f in m["target_fars"]])

    def test_axi_map_matches_the_rtl_register_file(self):
        m = json.loads((DUMMY / "carrier_manifest.json").read_text())
        axi = m["axi"]
        self.assertEqual(axi["stable_state"], [0x2004, 0x2008, 0x2010, 0x2014, 0x2018, 0x201C, 0x2020, 0x2024])
        self.assertEqual(axi["heartbeat"]["offset"], 0x2028)
        self.assertIsNone(axi["heartbeat"]["advances_per_s_min"], "bounds are pinned only at L2")
        self.assertEqual(axi["arm_payload"]["first"], 0x2100); self.assertTrue(axi["arm_payload"]["write_only"])
        rtl = (REPO / "rtl/p3_axil.v").read_text()
        for off in ("2004", "2008", "2028", "202C", "2030", "2100", "2150", "2200", "2240"):
            self.assertIn(f"16'h{off}", rtl)

    def test_isolation_evidence_verdicts(self):
        iso = (DUMMY / "isolation.txt").read_text()
        self.assertIn("target cells: 6", iso)
        self.assertIn("flush cells:  0", iso)

    def test_manifest_says_the_key_is_runtime_provisioned(self):
        m = json.loads((DUMMY / "carrier_manifest.json").read_text())
        self.assertNotIn("key_id", m["mac"]); self.assertIn("runtime-provisioned", m["mac"]["key"])
        self.assertEqual(m["mac"]["key_loaded_status_bit"], 11); self.assertEqual(m["mac"]["fault_nokey"], 12)
        self.assertNotIn("KEY=", (REPO / "vivado/p3/build_p3.tcl").read_text())

    def test_key_is_not_in_any_committed_file(self):
        """A real key file must never be tracked."""
        tracked = (REPO / "docs/import_manifest.md").read_text()
        self.assertNotIn("keys/K.bin", tracked)
        self.assertFalse((REPO / "keys/K.bin").exists() and "keys/" not in (REPO / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
