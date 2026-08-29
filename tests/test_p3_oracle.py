"""host/p3_oracle.py pinned to fabricmap's artifacts: the LOC→key rule reproduces every LUT's
mutable mask; the known answer's expected tables and predicted scores equal the published
`known_answer.json` values (train and holdout, candidate and base)."""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "host"))
import p3_gate as g  # noqa: E402
import p3_oracle as po  # noqa: E402

KA = json.load(open(REPO / "imported/fabricmap/gate_runs/claimb_round1_known_answer_2026_08_14/known_answer.json"))


class Oracle(unittest.TestCase):
    def setUp(self):
        self.c = po.load_constants()
        self.m = g.load_manifest()

    def test_six_luts_keys_and_columns(self):
        keys = [l["key"] for l in self.c["luts"]]
        self.assertEqual(keys, ["CLBLL_L.SLICEL_X0.ALUT", "CLBLL_L.SLICEL_X0.DLUT", "CLBLM_L.SLICEL_X1.ALUT",
                                "CLBLM_L.SLICEL_X1.DLUT", "CLBLM_L.SLICEM_X0.ALUT", "CLBLM_L.SLICEM_X0.DLUT"])
        self.assertEqual(self.c["luts"][0]["target"], int(KA["selection"]["target_init"], 16))
        self.assertTrue(all(l["base_init"] == 0 for l in self.c["luts"]))

    def test_known_answer_tables_and_scores(self):
        cand = g.known_answer_candidate(self.m)
        tables = po.expected_tables(cand, self.c)
        self.assertEqual(tables[0], int(KA["selection"]["actual_init"], 16))
        self.assertEqual(tables[1:], [0] * 5)
        self.assertEqual(po.predict_scores(tables, self.c), KA["scores"]["candidate"]["train"])
        self.assertEqual(po.predict_scores(tables, self.c, holdout=True), KA["scores"]["candidate"]["holdout"])
        base_tables = po.expected_tables({f: [0] * 101 for f in cand}, self.c)
        self.assertEqual(po.predict_scores(base_tables, self.c), KA["scores"]["base_restore"]["train"])
        self.assertEqual(po.predict_scores(base_tables, self.c, holdout=True), KA["scores"]["base_restore"]["holdout"])

    def test_a_site_outside_the_target_columns_is_refused(self):
        with self.assertRaises(ValueError):
            po._key("SLICE_X4Y25", "A6LUT")

    def test_axi_map_matches_the_dummy_manifest(self):
        m = json.load(open(REPO / "builds/p3/carrier_manifest.json"))["axi"]
        self.assertEqual(m["stable_state"], [po.STATUS, po.FAULT, *po.SCORES])
        self.assertEqual(m["arm_payload"]["first"], po.PAYLOAD[0]); self.assertEqual(m["arm_payload"]["tag_first"], po.TAG[0])
        self.assertEqual(m["hw_candidate_commit"]["first"], po.HW_COMMIT[0]); self.assertEqual(m["functional_readout"]["first"], po.READOUT[0])
        self.assertEqual(m["nonce"]["lo"], po.NONCE_LO); self.assertEqual(m["heartbeat"]["offset"], po.HEARTBEAT)
        self.assertTrue(po.READABLE.isdisjoint(po.WRITABLE))


if __name__ == "__main__":
    unittest.main()
