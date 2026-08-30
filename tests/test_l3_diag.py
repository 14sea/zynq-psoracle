"""The L3 diagnostic on fake boards that reproduce each hypothesis, and the pure adjudicator."""
import json, os, sys, tempfile, unittest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "host")); sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import l3_diag_runner as dg  # noqa: E402
import p3_gate as g  # noqa: E402
from test_l3_runner import FakeP3Board, FakeTransport, MANIFEST, TABLE, DUMMY, FAR_SETS, PHEN  # noqa: E402

KA = g.known_answer_candidate(PHEN)


class ZeroAfterTwoSets(FakeP3Board):
    """fabric holds the writes; PCAP readback returns zeros once >= 2 FAR sets were written"""
    def __init__(self, key):
        super().__init__(key); self.sets = set()
    def queue_dma(self, src, dst, src_len, dst_len):
        if src == dg.l3.WR_BUF | pp.DMA_HOLD_TAG and dst == pp.PCAP_ENDPOINT:
            words = [self.mem.get(dg.l3.WR_BUF + 4 * i, 0) for i in range(src_len)]
            self.sets.add(g.parse_stream(words, FAR_SETS)[0])
        if dst == pp.DST_BUF | pp.DMA_HOLD_TAG and len(self.sets) >= 2:
            self.deliver = lambda far: [0] * 202
        super().queue_dma(src, dst, src_len, dst_len)


class SecondWriteClearsA20(FakeP3Board):
    def queue_dma(self, src, dst, src_len, dst_len):
        super().queue_dma(src, dst, src_len, dst_len)
        if src == dg.l3.WR_BUF | pp.DMA_HOLD_TAG and dst == pp.PCAP_ENDPOINT and self.write_dmas >= 2:
            self.fabric[dg.A20] = [0] * 101


def jtag_of(board):
    return {"verdict": "READ", "config_status": "0x00000000",
            "frames": {f"{far:#010x}": {"frame_sha256": pr.frame_sha256(board.fabric[far]), "nonzero_words_in_frame": sum(1 for w in board.fabric[far] if w)}
                       for far in dg.CLOSING}}


class Diag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        self.key = d / "K.bin"; self.key.write_bytes(bytes(range(16))); os.chmod(self.key, 0o400)
        self.out = d / "ev"; self.out.mkdir()

    def tearDown(self): self.tmp.cleanup()

    def pcap(self, board):
        s = dg.run_pcap_phase(bsn.BoardSession(FakeTransport(board)), self.out, {"ruling": dg.RULING_TEXT},
                              {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "table": TABLE})
        self.assertTrue((self.out / "sealed.json").exists()); self.assertTrue((self.out / "jtag_request.json").exists())
        return s

    def test_healthy_board_no_reproduction(self):
        b = FakeP3Board(self.key); s = self.pcap(b)
        self.assertTrue(s["outcome"].startswith("NO_REPRODUCTION"), s["outcome"]); self.assertEqual(b.write_dmas, 3)
        self.assertEqual([len(p["reads"]) for p in s["phases"]], [1, 2, 3])
        v = dg.adjudicate(s, jtag_of(b)); self.assertEqual(v["verdict"], "NO_REPRODUCTION")

    def test_pcap_zero_hypothesis_is_named_and_writes_stop(self):
        b = ZeroAfterTwoSets(self.key); s = self.pcap(b)
        self.assertTrue(s["outcome"].startswith("MISMATCH_REPRODUCED at phase 1"), s["outcome"])
        self.assertEqual(b.write_dmas, 2, "no PCAP write after the mismatch")
        self.assertEqual(len(s["closing_reads"]), 3)
        v = dg.adjudicate(s, jtag_of(b)); self.assertEqual(v["verdict"], "PCAP_READBACK_ZERO", v)

    def test_fabric_blank_hypothesis_is_named(self):
        b = SecondWriteClearsA20(self.key); s = self.pcap(b)
        self.assertTrue(s["outcome"].startswith("MISMATCH_REPRODUCED at phase 1"))
        v = dg.adjudicate(s, jtag_of(b)); self.assertEqual(v["verdict"], "FABRIC_BLANK", v)

    def test_misplaced_content_is_named(self):
        b = FakeP3Board(self.key); s = self.pcap(b)
        b.fabric[dg.C1A] = list(KA[dg.A20])            # candidate content where base should be (JTAG sees it)
        v = dg.adjudicate(s, jtag_of(b)); self.assertEqual(v["verdict"], "FABRIC_MISPLACED", v)

    def test_jtag_not_read_is_hold(self):
        b = FakeP3Board(self.key); s = self.pcap(b)
        self.assertEqual(dg.adjudicate(s, {"verdict": "STOP", "stop_reason": "x"})["verdict"], "HOLD")

    def test_jtag_phase_refuses_without_seal_or_twice(self):
        self.assertEqual(dg.main(["--out", str(self.out), "--manifest", str(DUMMY / "carrier_manifest.json"), "--jtag"]), 2)
        (self.out / "sealed.json").write_text("{}"); (self.out / "summary_pcap.json").write_text("{}"); (self.out / "jtag.json").write_text("{}")
        self.assertEqual(dg.main(["--out", str(self.out), "--manifest", str(DUMMY / "carrier_manifest.json"), "--jtag"]), 2)


if __name__ == "__main__":
    unittest.main()
