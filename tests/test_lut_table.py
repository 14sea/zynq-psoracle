"""`lut_truth_table` 1.0.0 against fabricmap's known-answer artifact (imported byte-for-byte).

Fixture: `known_answer.json` — LUT0 (`CLBLL_L.SLICEL_X0.ALUT`, SLICE_X2Y25 A6LUT), the
candidate's four touched frames, `selection.target_init`, `selection.mutable_mask`,
`selection.actual_init`. The table derived from the candidate frames through the certified
map must equal `target_init` on every mutable position; the candidate's own
`changed_content_bits` must be exactly the positions where the derived table differs from
the base within the mask.
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from validators import lut_table as lt  # noqa: E402

FM = REPO / "imported/fabricmap/gate_runs"
KA = json.load(open(FM / "claimb_round1_known_answer_2026_08_14/known_answer.json"))
LM = json.load(open(FM / "claimb_round1_carrier_2026_08_13_erratum006/local_map.json"))
LUT_KEY = KA["selection"]["map_lut_key"]


class TruthTable(unittest.TestCase):
    def setUp(self):
        self.pos = lt.mapped_positions(LM, LUT_KEY)
        self.frames = {int(f["far"], 16): [int(w, 16) for w in f["words"]] for f in KA["candidate"]["touched_frames"]}
        self.base_init = int(KA["selection"]["actual_init"], 16)
        self.target = int(KA["selection"]["target_init"], 16)
        self.mask = int(KA["selection"]["mutable_mask"], 16)

    def test_map_has_49_positions_and_the_mask_matches(self):
        self.assertEqual(len(self.pos), 49)
        self.assertEqual(lt.mutable_mask(self.pos), self.mask)

    def test_candidate_frames_derive_the_target_on_mutable_positions(self):
        table = lt.truth_table(self.frames, self.pos, self.base_init)
        self.assertEqual(table & self.mask, self.target & self.mask)
        self.assertEqual(table & ~self.mask & 0xFFFFFFFFFFFFFFFF, self.base_init & ~self.mask & 0xFFFFFFFFFFFFFFFF)

    def test_changed_content_bits_are_the_set_mapped_bits_of_the_candidate(self):
        """The artifact's `changed_content_bits` are the mapped positions the candidate SETS
        in otherwise-blank frames (26, all value 1) — not its differences from `actual_init`
        (three of them were already 1 in the base LUT). The derivation must reproduce that."""
        changed = {(int(b["far"], 16), b["word"], b["bit"]) for b in KA["candidate"]["changed_content_bits"]}
        self.assertTrue(all(b["value"] == 1 for b in KA["candidate"]["changed_content_bits"]))
        derived_set = {self.pos[i] for i in self.pos
                       if (self.frames[self.pos[i][0]][self.pos[i][1]] >> self.pos[i][2]) & 1}
        self.assertEqual(derived_set, changed)
        self.assertEqual(len(changed), KA["candidate"]["changed_content_bit_count"])

    def test_a_missing_frame_is_refused_not_defaulted(self):
        frames = dict(self.frames); frames.pop(0x00400A23)
        with self.assertRaises(ValueError):
            lt.truth_table(frames, self.pos, self.base_init)

    def test_every_position_is_in_word_51_of_a_target_frame(self):
        for far, word, bit in self.pos.values():
            self.assertIn(far, (0x00400A20, 0x00400A21, 0x00400A22, 0x00400A23))
            self.assertEqual(word, 51)
            self.assertLess(bit, 16)


if __name__ == "__main__":
    unittest.main()
