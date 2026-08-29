"""P2 — observable allowlist, FCLK0 decode, continuity adjudication, the runner chain.

Every test names the `docs/p2_spec.md` clause it checks. No board, no port. `P2Fake`
extends the P1 fake with the carrier's eight AXI registers and the PLL/divisor registers;
hooks let a test perturb the observable at a chosen step.
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
import p1_runner as p1  # noqa: E402
import p2_observe as ob  # noqa: E402
import p2_runner as p2  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_write_plan as wp  # noqa: E402
from test_p1 import BASE, TABLE, P1Fake, FakeTransport  # noqa: E402

FRESH = {ob.STATUS: 0x00000080, ob.FAULT: 0, **{a: 0 for a in ob.SCORES}}
PLLS = {ob.IO_PLL_CTRL: (48 << 12) | 8, ob.ARM_PLL_CTRL: (40 << 12) | 8,
        ob.DDR_PLL_CTRL: (32 << 12) | 8, ob.FPGA0_CLK_CTRL: 0x00400800}
# the 4203's vendor ps7_init: IO PLL 48 × 33.33 = 1600 MHz; FPGA0_CLK_CTRL 0x00400800 →
# IO PLL / 8 / 4 = 50 MHz (fabricmap board_set_fclk50 KNOWN_DIVISORS[1600] = (8, 4))


class P2Fake(P1Fake):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.mem.update(FRESH)
        self.mem.update(PLLS)
        self.perturb_at = None          # ("read", i) | ("control",) | ("write",)
        self.reads_done = 0

    def queue_dma(self, src, dst, src_len, dst_len):
        super().queue_dma(src, dst, src_len, dst_len)
        if dst == pp.DST_BUF | pp.DMA_HOLD_TAG:
            self.reads_done += 1
            if self.perturb_at == ("read", self.reads_done - 1):
                self.mem[ob.SCORES[2]] = 7          # a scorer counter moved during a read
        if dst == pp.PCAP_ENDPOINT and src == (wp.WR_BUF | pp.DMA_HOLD_TAG) and self.perturb_at == ("write",):
            self.mem[ob.FAULT] = 8                  # 'readback' fault appeared on the write


def run(board, sleeps=None):
    out = Path(tempfile.mkdtemp())
    s = bsn.BoardSession(FakeTransport(board))
    sleeps = sleeps if sleeps is not None else []

    def fake_sleep(t):
        sleeps.append(t)
        if board.perturb_at == ("control",) and len(sleeps) == 1:
            board.mem[ob.STATUS] |= 1 << 10          # drifts by itself
    ruling = {"ruling": p2.RULING_TEXT, "boardid": "17A6", "granted_by": "t", "date": "t"}
    return p2.run_p2(s, out, ruling, TABLE, BASE, sleep=fake_sleep), out, board


class Observable(unittest.TestCase):
    """p2_spec §2: eight words, eight addresses, nothing else; liveness."""

    def test_observable_is_the_eight_pinned_addresses_in_order(self):
        self.assertEqual(ob.OBSERVABLE, (0x43C02004, 0x43C02008, 0x43C02010, 0x43C02014,
                                         0x43C02018, 0x43C0201C, 0x43C02020, 0x43C02024))
        self.assertNotIn(0x43C02000, ob.ALLOWED_AXI)    # CTRL is never read or written
        self.assertNotIn(0x43C0200C, ob.ALLOWED_AXI)    # undecoded → SLVERR → reset

    def test_observer_refuses_any_other_read(self):
        s = bsn.BoardSession(FakeTransport(P2Fake()))
        o = p2._Observer(s)
        with self.assertRaises(bsn.SessionRefusal):
            o.word("md.l 0x43c0200c 1", 0x43C0200C)
        with self.assertRaises(bsn.SessionRefusal):
            o.word("md.l 0x43c02000 1", 0x43C02000)
        with self.assertRaises(bsn.SessionRefusal):
            o.word("md.l 0x43c02004 0x2", 0x43C02004)

    def test_liveness_rules(self):
        self.assertEqual(ob.liveness_problems(FRESH), [])
        self.assertTrue(ob.liveness_problems({**FRESH, ob.STATUS: 0}))
        self.assertTrue(ob.liveness_problems({**FRESH, ob.STATUS: 0x08000080}))


class Fclk0(unittest.TestCase):
    """p2_spec §2: FCLK0 decoded from registers, never a remembered constant."""

    def test_decode_matches_the_pinned_fresh_power_value_on_17A6(self):
        # FPGA0_CLK_CTRL 0x00400800: SRCSEL 0 (IO PLL), DIV0 = 8, DIV1 = 4. For 50 MHz the
        # IO PLL must be 1600 MHz (fdiv 48): 1600/8/4 = 50 — the 4203's IO PLL (memory).
        f = ob.fclk0_mhz(io_pll=(48 << 12), arm_pll=(40 << 12), ddr_pll=(32 << 12), clk_ctrl=0x00400800)
        self.assertEqual((f["div0"], f["div1"]), (8, 4))
        self.assertAlmostEqual(f["pll_mhz"], 1600.0, places=0)
        self.assertAlmostEqual(f["mhz"], 50.0, places=2)
        self.assertTrue(f["ok"])
        # the 4205's 1000 MHz IO PLL with the same divisors is 31.25 MHz → not ok
        g = ob.fclk0_mhz(io_pll=(30 << 12), arm_pll=0, ddr_pll=0, clk_ctrl=0x00400800)
        self.assertFalse(g["ok"])

    def test_zero_divisor_is_refused(self):
        with self.assertRaises(ValueError):
            ob.fclk0_mhz(48 << 12, 0, 0, 0x00000000)


class Adjudication(unittest.TestCase):
    """p2_spec §3, §5: control first; HOLD vs attributable violation."""

    def test_pass_when_all_equal(self):
        v = ob.adjudicate(FRESH, [("P2_2_control", dict(FRESH)), ("P2_3_read_0", dict(FRESH))])
        self.assertEqual(v["verdict"], "PASS")

    def test_control_drift_is_hold_not_violation(self):
        v = ob.adjudicate(FRESH, [("P2_2_control", {**FRESH, ob.STATUS: 0x480}),
                                  ("P2_3_read_0", {**FRESH, ob.STATUS: 0x480})])
        self.assertEqual(v["verdict"], "CONTROL_UNSTABLE")

    def test_violation_names_first_step_and_words(self):
        v = ob.adjudicate(FRESH, [("P2_2_control", dict(FRESH)), ("P2_3_read_0", dict(FRESH)),
                                  ("P2_3_read_1", {**FRESH, ob.SCORES[2]: 7})])
        self.assertEqual(v["verdict"], "CONTINUITY_VIOLATION")
        self.assertEqual(v["at"], "P2_3_read_1")
        self.assertEqual(v["diff"][0]["address"], f"{ob.SCORES[2]:#010x}")
        self.assertTrue(v["attributable"])

    def test_control_must_come_first(self):
        with self.assertRaises(ValueError):
            ob.adjudicate(FRESH, [("P2_3_read_0", dict(FRESH))])


class Chain(unittest.TestCase):
    """p2_spec §4: order, samples after every PCAP step, the write arm, the outcomes."""

    def test_full_chain_passes(self):
        sleeps = []
        summary, out, board = run(P2Fake(), sleeps)
        self.assertEqual(summary["outcome"], "PASS", summary["outcome"])
        names = [s["step"] for s in summary["samples"]]
        self.assertEqual(names, ["P2_1_baseline", "P2_2_control"] + [f"P2_3_read_{i}" for i in range(10)]
                         + ["P2_4_post", "P2_5_write", "P2_6_readback"])
        self.assertEqual(summary["continuity"]["compared"], 14)
        self.assertEqual(sleeps[0], p2.T_CONTROL_DERIVED_S)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(summary["fclk0"]["ok"])
        self.assertEqual(board.store[wp.TARGET_FAR][51], wp.PATTERN_A)
        rec = json.loads((out / "P2_3_read_0.json").read_text())
        self.assertEqual(rec["observable_diff"], [])
        self.assertEqual(rec["expected"]["frame_sha256"], p2.READ_EXPECTED)

    def test_control_first_then_reads(self):
        summary, out, board = run(P2Fake())
        sent = board.sent
        first_read = sent.index("dcache off")
        control_sample = [i for i, c in enumerate(sent) if c == f"md.l {ob.STATUS:#010x} 1"][1]
        self.assertLess(control_sample, first_read)

    def test_unstable_control_is_hold_and_no_pcap_read_happens(self):
        board = P2Fake(); board.perturb_at = ("control",)
        summary, out, board = run(board)
        self.assertTrue(summary["outcome"].startswith("HOLD CONTROL_UNSTABLE"), summary["outcome"])
        self.assertNotIn("dcache off", board.sent)
        self.assertEqual(board.writes, 0)

    def test_perturbation_during_a_read_is_an_attributable_violation(self):
        board = P2Fake(); board.perturb_at = ("read", 3)
        summary, _, _ = run(board)
        self.assertTrue(summary["outcome"].startswith("STOP CONTINUITY_VIOLATION at P2_3_read_3"), summary["outcome"])
        self.assertTrue(summary["continuity"]["attributable"])

    def test_perturbation_by_the_write_is_named_at_the_write(self):
        board = P2Fake(); board.perturb_at = ("write",)
        summary, _, _ = run(board)
        self.assertTrue(summary["outcome"].startswith("STOP CONTINUITY_VIOLATION at P2_5_write"), summary["outcome"])

    def test_wrong_fclk0_stops_before_any_axi_read(self):
        board = P2Fake(); board.mem[ob.IO_PLL_CTRL] = 30 << 12       # 1000 MHz PLL → 31.25 MHz
        summary, _, board = run(board)
        self.assertTrue(summary["outcome"].startswith("STOP PRECONDITION"), summary["outcome"])
        self.assertNotIn(f"md.l {ob.STATUS:#010x} 1", board.sent)

    def test_dead_axi_is_a_precondition_class_stop(self):
        board = P2Fake(); board.mem[ob.STATUS] = 0
        summary, _, _ = run(board)
        self.assertTrue(summary["outcome"].startswith("STOP AXI_NOT_ALIVE"), summary["outcome"])

    def test_no_axi_write_and_no_ctrl_touch_anywhere(self):
        summary, _, board = run(P2Fake())
        self.assertFalse(any(c.startswith("mw.l 0x43c0") for c in board.sent))
        self.assertFalse(any(c.startswith("mw.l 0xf8007000") for c in board.sent))

    def test_ruling_text_is_p2_specific(self):
        import pcap_probe_runner as pr
        d = Path(tempfile.mkdtemp()); p = d / "r.json"
        p.write_text(json.dumps({"ruling": "whole-of-probe P1", "boardid": "17A6", "granted_by": "x", "date": "y"}))
        with self.assertRaises(bsn.SessionRefusal):
            pr.check_ruling(p, text=p2.RULING_TEXT)


if __name__ == "__main__":
    unittest.main()
