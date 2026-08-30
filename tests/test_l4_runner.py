"""L4 on the fake P3 board: link-1 refusal (host-only), corrupted staging refused at link 2
with no DMA, restore of all twelve frames to base verified at link 3, baseline score after a
signed ARM of the blank candidate equals fabricmap's published base scores."""

import json, os, sys, tempfile, unittest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "host")); sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
import board_session as bsn  # noqa: E402
import l4_runner as l4  # noqa: E402
import p3_gate as g  # noqa: E402
from test_l3_runner import FakeP3Board, FakeTransport, FixtureSigner, MANIFEST, TABLE, DUMMY, CONSTS, KA  # noqa: E402


class L4(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        self.key = d / "K.bin"; self.key.write_bytes(bytes(range(16))); os.chmod(self.key, 0o400)
        self.out = d / "ev"; self.out.mkdir()

    def tearDown(self): self.tmp.cleanup()

    def run_l4(self, board):
        session = bsn.BoardSession(FakeTransport(board))
        cfg = {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "consts": CONSTS, "table": TABLE, "signer": FixtureSigner(self.key, board)}
        return l4.run_l4(session, self.out, {"ruling": l4.RULING_TEXT}, cfg), board

    def test_gate_refused_record_is_host_only(self):
        rec = l4.gate_refused_record(g.load_manifest())
        self.assertEqual(rec["verdict"], "REFUSED_AT_LINK_1"); self.assertIn("target_frame", rec["kinds"]); self.assertEqual(rec["board_action"], "NONE")

    def test_full_session_passes_with_base_scores(self):
        s, b = self.run_l4(FakeP3Board(self.key))
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        self.assertEqual(s["stages"]["L4_1_corrupt_stage"], "REFUSED_AT_LINK_2")
        self.assertEqual(b.write_dmas, 3, "only the three restore writes")
        self.assertEqual(s["restore"]["verdict"], "RESTORED")
        self.assertEqual(s["baseline"]["scores"], KA["scores"]["base_restore"]["train"])
        self.assertTrue(all(all(w == 0 for w in b.fabric[int(h, 16)]) for h in MANIFEST["target_fars"]))
        self.assertIsInstance(s["run_log_validation"], dict)

    def test_a_corruption_the_reread_cannot_see_is_a_kill(self):
        class Lying(FakeP3Board):
            def word(self, addr):
                if l4.l3.WR_BUF <= addr < l4.l3.WR_BUF + 4 * l4.l3.STREAM_WORDS:
                    i = (addr - l4.l3.WR_BUF) // 4
                    if i == l4.CORRUPT_WORD: return self.mem.get(addr, 0) ^ 0x8000   # DDR reads back the original
                return super().word(addr)
        s, b = self.run_l4(Lying(self.key))
        self.assertTrue(s["outcome"].startswith("KILL"), s["outcome"]); self.assertEqual(b.write_dmas, 0)


if __name__ == "__main__":
    unittest.main()
