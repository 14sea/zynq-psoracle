"""P1 — write plan guards, the runner chain, PRE_WRITE_CONTENT, and the terminal JTAG.

Every test names the `docs/p1_spec.md` clause it checks. No board, no port, no openocd:
`P1Fake` extends the S1–S3 fake with a frame store that a PCAP write DMA updates, and the
terminal JTAG verifier is replaced by a callable that reads that same store.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import board_session as bsn  # noqa: E402
import frame_ecc as fe  # noqa: E402
import p1_runner as p1  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import pcap_write_plan as wp  # noqa: E402
from test_s0b_runner import FRAMES, TABLE, FakeUBoot, FakeTransport  # noqa: E402

BASE = wp.base_frames()


class P1Fake(FakeUBoot):
    """A devcfg whose PCAP write DMA parses the stream in DDR and updates a frame store."""

    def __init__(self, *, writes_land=True, land_only_first=False, **kw):
        super().__init__(**kw)
        self.store = {wp.TARGET_FAR: list(FRAMES[wp.TARGET_FAR]),
                      wp.PAD_FAR: list(FRAMES[wp.PAD_FAR])}
        self.writes_land, self.land_only_first = writes_land, land_only_first
        self.writes = 0

    def queue_dma(self, src, dst, src_len, dst_len):
        if dst == pp.PCAP_ENDPOINT and src == (wp.WR_BUF | pp.DMA_HOLD_TAG):
            words = [self.mem.get(wp.WR_BUF + 4 * i, 0) for i in range(src_len)]
            self.writes += 1
            land = self.writes_land and not (self.land_only_first and self.writes > 1)
            if land:
                far = words[words.index(wp.t1(True, wp.REG_FAR, 1)) + 1]
                k = words.index(wp.t2_write(wp.FDRI_WORDS)) + 1
                self.store[far] = words[k:k + wp.FRAME_WORDS]
                self.store[far + 1] = words[k + wp.FRAME_WORDS:k + 2 * wp.FRAME_WORDS]
            self.mem[pp.REG["INT_STS"]] |= pp.INT_STS_D_P_DONE | pp.INT_STS_DMA_DONE
            self.mem[pp.REG["INT_STS"]] |= self.error_bits
            return
        if dst == pp.DST_BUF | pp.DMA_HOLD_TAG and dst_len == pp.READBACK_WORDS:
            far = self.far_in_cmd_buf()
            if far in self.store and not self.deliver:
                words = [0] * pp.FRAME_WORDS + self.store[far]
                for i, w in enumerate(words):
                    self.mem[pp.DST_BUF + 4 * i] = w
                self.mem[pp.REG["INT_STS"]] |= pp.INT_STS_D_P_DONE | pp.INT_STS_DMA_DONE
                return
        super().queue_dma(src, dst, src_len, dst_len)


def fake_jtag(board: P1Fake):
    def run(out_dir: Path):
        rec = {"verdict": "READ", "config_status": "0x00000000",
               "frames": {f"{far:#010x}": {"frame_sha256": wp.pp_sha(board.store[far])}
                          for far in (wp.TARGET_FAR, wp.PAD_FAR)}}
        (out_dir / "jtag.json").write_text(json.dumps(rec))
        return rec
    return run


def ruling():
    return {"ruling": p1.RULING_TEXT, "boardid": "17A6", "granted_by": "test", "date": "t"}


def run_chain(board: P1Fake, jtag=None):
    out = Path(tempfile.mkdtemp())
    s = bsn.BoardSession(FakeTransport(board))
    return p1.run_p1(s, out, ruling(), TABLE, BASE, jtag or fake_jtag(board)), out, board


# ====================================================================== the write plan


class WritePlanGuards(unittest.TestCase):
    """p1_spec §2, §4: content-bit-only, pinned stream shape, pinned DMA tuple."""

    def test_pinned_hashes_match_the_builders(self):
        p1.pinned_check(BASE)
        self.assertEqual(wp.build_write_plan("A", BASE)["frame_after_sha256"], p1.A_SHA256)
        self.assertEqual(wp.build_write_plan("B", BASE)["frame_after_sha256"], p1.B_SHA256)
        self.assertTrue(all(w == 0 for w in BASE[wp.TARGET_FAR]))

    def test_frame_differs_from_base_only_in_words_50_and_51(self):
        for n in ("A", "B"):
            f = wp.build_write_plan(n, BASE)["frame_after"]
            diff = [k for k, (a, b) in enumerate(zip(f, BASE[wp.TARGET_FAR])) if a != b]
            self.assertTrue(set(diff) <= {50, 51}, diff)
            self.assertEqual(f[51] & ~wp.INIT_MASK, 0)
            self.assertTrue(fe.frame_is_consistent(f))

    def test_patterns_are_disjoint_nonzero_inside_the_mask(self):
        self.assertEqual(wp.PATTERN_A & wp.PATTERN_B, 0)
        self.assertEqual(wp.PATTERN_A & ~wp.INIT_MASK, 0)
        self.assertEqual(wp.PATTERN_B & ~wp.INIT_MASK, 0)
        self.assertNotIn(p1.A_SHA256, TABLE["reverse"])
        self.assertNotIn(p1.B_SHA256, TABLE["reverse"])

    def test_stream_shape_and_dma_tuple(self):
        plan = wp.build_write_plan("A", BASE)
        s = plan["stream"]
        self.assertEqual(len(s), 231)
        self.assertEqual(s[:8], [0xFFFFFFFF] * 8)
        self.assertEqual(s[8], 0xAA995566)
        self.assertEqual(s[-6:-4], [0x30008001, 0x0000000D])
        self.assertEqual(tuple(plan["dma_transaction"]), (wp.WR_BUF | 1, 0xFFFFFFFF, 231, 0))
        self.assertNotIn(0x30000001, s, "a CRC-register write is not part of the stream")

    def _mutant(self, mutate):
        plan = wp.build_write_plan("A", BASE)
        words = list(plan["stream"])
        mutate(words)
        with self.assertRaises(ValueError):
            wp.validate_write_stream(words, BASE)

    def test_forbidden_commands_and_registers_are_refused(self):
        k = wp.FDRI_DATA_OFFSET
        self._mutant(lambda w: w.__setitem__(11, 0xA))                       # RCRC -> GRESTORE
        self._mutant(lambda w: w.__setitem__(11, 0xB))                       # SHUTDOWN
        self._mutant(lambda w: w.__setitem__(17, 0x5))                       # WCFG -> START
        self._mutant(lambda w: w.__setitem__(-5, 0xC))                       # DESYNC -> GCAPTURE
        self._mutant(lambda w: w.__setitem__(20, 0x00400A21))                # FAR moved
        self._mutant(lambda w: w.__setitem__(22, wp.t2_write(101)))          # FDRI count
        self._mutant(lambda w: w.__setitem__(k + 10, 1))                     # routing word touched
        self._mutant(lambda w: w.__setitem__(k + 51, w[k + 51] | 0x40))      # outside the mask
        self._mutant(lambda w: w.__setitem__(k + 51, 0x0001))                # not a pinned pattern
        self._mutant(lambda w: w.__setitem__(k + 50, w[k + 50] ^ 1))         # ECC wrong
        self._mutant(lambda w: w.__setitem__(k + 101 + 3, 7))                # pad not base
        self._mutant(lambda w: w.__setitem__(-4, 0x30000001))                # CRC write
        self._mutant(lambda w: w.__setitem__(15, 0x03631093))                # wrong IDCODE

    def test_a_tampered_write_plan_is_refused_by_the_runner_before_any_send(self):
        board = P1Fake()
        s = bsn.BoardSession(FakeTransport(board))
        pr.precheck(s); s.verify_identity()
        s.load_carrier(bsn.SETUP_LOAD_CAPABILITY, pr.CARRIER_BIT, pr.CARRIER_SHA256,
                       Path(tempfile.mkdtemp()) / "y.log")
        plan = wp.build_write_plan("A", BASE)
        plan["int_sts_error_mask"] = 0
        n = len(board.sent)
        with self.assertRaises(ValueError):
            p1.execute_write_plan(bsn.CONFIG_READ_CAPABILITY, s, plan, BASE, "w")
        self.assertEqual(len(board.sent), n)
        plan = wp.build_write_plan("A", BASE)
        plan["uboot_script"][0]["cmd"] = "mw.l 0xf8007000 0x00000000 1"
        with self.assertRaises(ValueError):
            p1.execute_write_plan(bsn.CONFIG_READ_CAPABILITY, s, plan, BASE, "w")
        self.assertEqual(len(board.sent), n)

    def test_ctrl_is_recorded_before_and_after_the_write_and_must_not_change(self):
        """p1_spec §1: CTRL incl. PCAP_RATE_EN stays as found; asserted, not assumed."""
        summary, out, _ = run_chain(P1Fake())
        rec = json.loads((out / "P1_1_write_A.json").read_text())
        self.assertEqual(rec["observations"]["ctrl_before"], "0x4e00e07f")
        self.assertEqual(rec["observations"]["ctrl_after"], "0x4e00e07f")
        board = P1Fake()
        real = board.reply

        def flip_rate_en(line):
            out_ = real(line)
            # only once the FIRST write DMA has been queued (reads also queue DMAs)
            if board.writes == 1 and line.startswith(f"mw.l {pp.REG['DMA_DEST_LEN']:#010x}"):
                board.mem[pp.REG["CTRL"]] &= ~(1 << 25)      # something cleared PCAP_RATE_EN
            return out_
        board.reply = flip_rate_en
        summary, _, _ = run_chain(board)
        self.assertTrue(summary["outcome"].startswith("STOP PRECONDITION"), summary["outcome"])
        self.assertIn("CTRL changed", summary["outcome"])

    def test_the_write_clear_excludes_pcfg_done(self):
        plan = wp.build_write_plan("A", BASE)
        clears = [st["cmd"] for st in plan["uboot_script"] if st["step"] == "clear-write"]
        self.assertEqual(clears, [f"mw.l 0xf800700c {pp.INT_STS_CLEAR_MASK:#010x} 1"])
        self.assertFalse(pp.INT_STS_CLEAR_MASK & pp.INT_STS_PCFG_DONE)


# ====================================================================== the chain


class Chain(unittest.TestCase):
    """p1_spec §5: order, gates, PRE_WRITE_CONTENT, three conjuncts."""

    def test_full_chain_passes(self):
        summary, out, board = run_chain(P1Fake())
        self.assertEqual(summary["outcome"], "PASS", summary["outcome"])
        names = sorted(p.stem for p in out.glob("P1_*.json"))
        self.assertEqual(names, ["P1_0_baseline", "P1_1_write_A", "P1_2_read_A_0", "P1_2_read_A_1",
                                 "P1_3_write_B", "P1_4_read_B_0", "P1_4_read_B_1"])
        self.assertEqual(summary["stages"]["P1_5_jtag"], "PASS")
        self.assertTrue(summary["jtag"]["target_matches_B"])
        self.assertEqual(board.store[wp.TARGET_FAR][51], wp.PATTERN_B)
        self.assertTrue((out / "sealed.json").exists())
        rec = json.loads((out / "P1_4_read_B_0.json").read_text())
        self.assertEqual(rec["verdict"], "PASS")
        self.assertEqual(rec["expected"]["frame_sha256"], p1.B_SHA256)
        self.assertEqual(rec["previous_sha256"], p1.A_SHA256)

    def test_order_baseline_writes_reads_seal_then_jtag(self):
        calls = []
        board = P1Fake()
        real = fake_jtag(board)

        def spy(out_dir):
            calls.append(("jtag", len(board.sent)))
            return real(out_dir)
        summary, out, _ = run_chain(board, spy)
        self.assertEqual(summary["outcome"], "PASS")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], len(board.sent), "the board was touched after the JTAG step")
        sent = board.sent
        fdri_far = f"mw.l {wp.WR_BUF + 4 * 20:#010x} 0x00400a20 1"
        first_write = sent.index(fdri_far)
        first_read = sent.index("dcache off")
        self.assertLess(first_read, first_write, "baseline read must precede the first write")

    def test_pre_write_content_at_step_5_is_unambiguous(self):
        summary, out, _ = run_chain(P1Fake(land_only_first=True))
        self.assertTrue(summary["outcome"].startswith("STOP PRE_WRITE_CONTENT"), summary["outcome"])
        rec = json.loads((out / "P1_4_read_B_0.json").read_text())
        self.assertEqual(rec["verdict"], "PRE_WRITE_CONTENT")
        self.assertEqual(rec["verdict_before_reclassification"], "NO_MATCH")
        self.assertEqual(rec["frame_sha256"], p1.A_SHA256)
        self.assertFalse((out / "P1_4_read_B_1.json").exists(), "second read attempted after a stop")
        self.assertFalse((out / "jtag.json").exists(), "JTAG ran after a stop")

    def test_pre_write_content_at_step_3_coincides_with_blank(self):
        summary, out, _ = run_chain(P1Fake(writes_land=False))
        self.assertTrue(summary["outcome"].startswith("STOP PRE_WRITE_CONTENT"))
        rec = json.loads((out / "P1_2_read_A_0.json").read_text())
        self.assertEqual(rec["verdict_before_reclassification"], "BLANK")

    def test_baseline_not_blank_stops_before_any_write(self):
        board = P1Fake()
        board.store[wp.TARGET_FAR] = list(FRAMES[0xB99])       # someone left content there
        summary, out, _ = run_chain(board)
        self.assertTrue(summary["outcome"].startswith("STOP"), summary["outcome"])
        self.assertEqual(board.writes, 0)

    def test_jtag_mismatch_is_not_a_pass(self):
        board = P1Fake()

        def lying_jtag(out_dir):
            rec = {"verdict": "READ", "frames": {f"{wp.TARGET_FAR:#010x}": {"frame_sha256": p1.A_SHA256},
                                                 f"{wp.PAD_FAR:#010x}": {"frame_sha256": p1.PAD_SHA256}}}
            (out_dir / "jtag.json").write_text(json.dumps(rec)); return rec
        summary, _, _ = run_chain(board, lying_jtag)
        self.assertTrue(summary["outcome"].startswith("STOP JTAG_MISMATCH"))

    def test_jtag_that_cannot_read_is_hold_not_pass(self):
        def dead_jtag(out_dir):
            rec = {"verdict": "STOP", "stop_reason": "ProbeStop: the chain never returned an IDCODE"}
            (out_dir / "jtag.json").write_text(json.dumps(rec)); return rec
        summary, _, _ = run_chain(P1Fake(), dead_jtag)
        self.assertTrue(summary["outcome"].startswith("HOLD"))

    def test_write_error_bits_stop_with_raw_names(self):
        summary, out, _ = run_chain(P1Fake(error_bits=1 << 15))
        self.assertTrue(summary["outcome"].startswith("STOP DMA_ERROR"), summary["outcome"])

    def test_ruling_text_is_p1_specific(self):
        d = Path(tempfile.mkdtemp())
        p = d / "r.json"
        p.write_text(json.dumps({"ruling": "whole-of-probe S1-S3", "boardid": "17A6",
                                 "granted_by": "x", "date": "y"}))
        with self.assertRaises(bsn.SessionRefusal):
            pr.check_ruling(p, text=p1.RULING_TEXT)
        p.write_text(json.dumps(ruling()))
        self.assertEqual(pr.check_ruling(p, text=p1.RULING_TEXT)["ruling"], p1.RULING_TEXT)

    def test_jtag_verdict_requires_crc_error_clear(self):
        """p1_spec §4b: omitting the CRC write must leave STAT.CRC_ERROR = 0; unknown is not 0."""
        frames = {f"{wp.TARGET_FAR:#010x}": {"frame_sha256": p1.B_SHA256},
                  f"{wp.PAD_FAR:#010x}": {"frame_sha256": p1.PAD_SHA256}}
        self.assertEqual(p1.jtag_verdict({"verdict": "READ", "frames": frames,
                                          "config_status": "0x00000001"})["verdict"], "MISMATCH")
        self.assertEqual(p1.jtag_verdict({"verdict": "READ", "frames": frames})["verdict"], "MISMATCH")
        self.assertEqual(p1.jtag_verdict({"verdict": "READ", "frames": frames,
                                          "config_status": "0x00000000"})["verdict"], "PASS")

    def test_jtag_verdict_requires_both_frames(self):
        v = p1.jtag_verdict({"verdict": "READ", "frames": {
            f"{wp.TARGET_FAR:#010x}": {"frame_sha256": p1.B_SHA256}}})
        self.assertEqual(v["verdict"], "MISMATCH")

    def test_imported_probe_forbids_writes_by_construction(self):
        import probe_jtag_config_read as pj
        self.assertIn("JPROGRAM", pj.FORBIDDEN_IR)
        self.assertNotIn("CFG_IN_WRITE", pj.IR)
        self.assertEqual(pj.READ_WORDS, 202)


class CarrierHeader(unittest.TestCase):
    """p1_spec §4b: readback CRC is off on this carrier — decoded from the bitstream."""

    REG = {0: "CRC", 1: "FAR", 4: "CMD", 9: "COR0", 12: "IDCODE", 14: "COR1", 19: "RBCRC_SW"}

    def header_writes(self):
        import bitstream_frames as bf
        words, _ = bf.config_words(pr.CARRIER_BIT)
        out, i = {}, 0
        while i < len(words):
            w = words[i]
            if w in (0x20000000, 0xFFFFFFFF, 0xAA995566):
                i += 1
                continue
            if (w >> 29) == 1 and ((w >> 27) & 3) == 2:
                reg, cnt = (w >> 13) & 0x3FFF, w & 0x7FF
                if reg == 2:                       # FDRI: the header is over
                    break
                if cnt == 1:
                    out.setdefault(self.REG.get(reg, reg), []).append(words[i + 1])
                i += 1 + cnt
            else:
                i += 1
        return out

    def test_cor1_and_rbcrc_sw_are_zero(self):
        h = self.header_writes()
        self.assertEqual(h["COR1"], [0])
        self.assertEqual(h["RBCRC_SW"], [0])
        self.assertEqual(h["IDCODE"], [wp.IDCODE_XC7Z010])
        self.assertIn(wp.CMD_RCRC, h["CMD"])

    def test_lut0_bits_in_this_frame_are_the_pinned_mask(self):
        """The 14 positions from the certified map, restated as data the test can check."""
        positions = {15, 14, 13, 12, 11, 10, 9, 8, 7, 4, 3, 2, 1, 0}
        self.assertEqual(sum(1 << b for b in positions), wp.INIT_MASK)
        self.assertEqual(bin(wp.INIT_MASK).count("1"), 14)


if __name__ == "__main__":
    unittest.main()
