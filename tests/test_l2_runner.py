"""L2 = P2b on the fake P3 board with a fake clock: the heartbeat model is time-based
(50 MHz × fake seconds), the runner's waits advance the clock. Proves the sequencing, the
two-invariant adjudication (control first), the STOP/HOLD kinds and the observe allowlist."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "host")); sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
import board_session as bsn  # noqa: E402
import l2_heartbeat as hb  # noqa: E402
import l2_runner as l2  # noqa: E402
import p3_oracle as po  # noqa: E402
from test_l3_runner import FakeP3Board, FakeTransport, MANIFEST, TABLE, DUMMY  # noqa: E402

F = 50e6


class Clock:
    def __init__(self): self.t = 100.0
    def now(self): return self.t
    def sleep(self, s): self.t += s


class TimedBoard(FakeP3Board):
    """heartbeat = ticks of the fake clock; each console reply costs 20 ms of fake time."""
    def __init__(self, key, clock: Clock, rate=F, stall_after=None, reply_cost=0.020, **kw):
        super().__init__(key, **kw)
        self.clock, self.rate, self.stall_after, self.reply_cost = clock, rate, stall_after, reply_cost
        self.stalled_at = None
        # PLL decode for FCLK0 = 1600 MHz / 8 / 4 = 50 MHz (FPGA0_CLK_CTRL 0x00400800 is in the base fake)
        self.mem[0xF8000108] = 48 << 12; self.mem[0xF8000100] = 40 << 12; self.mem[0xF8000104] = 32 << 12

    def reply(self, line):
        self.clock.t += self.reply_cost
        return super().reply(line)

    def word(self, addr):
        if addr == po.axi(po.HEARTBEAT):
            if self.stall_after and self.write_dmas >= self.stall_after and self.stalled_at is None:
                self.stalled_at = self.clock.t
            t = self.stalled_at if self.stalled_at is not None else self.clock.t
            return int(t * self.rate) & 0xFFFFFFFF
        return super().word(addr)


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.key = root / "K.bin"; self.key.write_bytes(bytes(range(16))); os.chmod(self.key, 0o400)
        self.out = root / "ev"; self.out.mkdir()
        self.clock = Clock()

    def tearDown(self): self.tmp.cleanup()

    def run_l2(self, board):
        session = bsn.BoardSession(FakeTransport(board))
        cfg = {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "table": TABLE}
        return l2.run_l2(session, self.out, {"ruling": l2.RULING_TEXT}, cfg, sleep=self.clock.sleep, clock=self.clock.now), board


class L2(Harness):
    def test_pass_with_both_invariants(self):
        s, b = self.run_l2(TimedBoard(self.key, self.clock))
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        self.assertEqual(s["continuity"]["state"]["verdict"], "PASS")
        self.assertEqual(s["continuity"]["heartbeat"]["verdict"], "PASS")
        self.assertGreaterEqual(len(s["continuity"]["heartbeat"]["intervals"]), 14)   # 15 named samples + sub-samples
        self.assertEqual(b.write_dmas, 1)
        self.assertTrue(0.95 * F <= s["measured_envelope"]["ticks_per_s_min"] <= s["measured_envelope"]["ticks_per_s_max"] <= 1.05 * F)
        self.assertEqual(len(list(self.out.glob("L2_3_read_*.json"))), 10)

    def test_phases_longer_than_the_wrap_are_covered_by_sub_samples(self):
        """run #2 on 17A6: post-wait 189 s and staging 113 s exceed 2^32/50 MHz = 85.9 s. With a
        0.2 s console (staging = 534 x 0.2 = 107 s, reads ~ 0.2 x ~60 lines) every interval must
        stay under TICK_S + one command and the run must PASS."""
        s, b = self.run_l2(TimedBoard(self.key, self.clock, reply_cost=0.2))
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        iv = s["continuity"]["heartbeat"]["intervals"]
        self.assertTrue(all(v["dt_s"] <= l2.TICK_S + 5 for v in iv), max(v["dt_s"] for v in iv))
        self.assertTrue(any("L2_5_stage_" in v["to"] for v in iv) and any("L2_4_post_wait_" in v["to"] for v in iv))
        self.assertGreater(len(iv), 14)

    def test_a_host_exception_is_still_an_outcome(self):
        board = TimedBoard(self.key, self.clock)
        orig = l2.hb.adjudicate
        l2.hb.adjudicate = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
        try:
            s, b = self.run_l2(board)
        finally:
            l2.hb.adjudicate = orig
        self.assertTrue(s["outcome"].startswith("CRASHED host-side: ValueError"), s["outcome"]); self.assertIn("traceback", s)

    def test_heartbeat_stall_after_the_write_is_an_attributable_stop(self):
        s, b = self.run_l2(TimedBoard(self.key, self.clock, stall_after=1))
        self.assertTrue(s["outcome"].startswith("STOP CONTINUITY_VIOLATION at L2_6_readback"), s["outcome"])
        self.assertEqual(s["continuity"]["heartbeat"]["kind"], "STALLED")

    def test_runaway_clock_fails_the_control_first(self):
        s, b = self.run_l2(TimedBoard(self.key, self.clock, rate=2 * F))
        self.assertTrue(s["outcome"].startswith("HOLD CONTROL_UNSTABLE"), s["outcome"])
        self.assertEqual(b.write_dmas, 0)

    def test_observer_allowlist(self):
        class Never:
            def read_command(self, *a): raise AssertionError("a line was formed")
        o = l2._Observer(Never(), self.clock.now)
        with self.assertRaises(bsn.SessionRefusal): o.word(f"md.l {po.axi(po.NONCE_LO):#010x} 1", po.axi(po.NONCE_LO))
        with self.assertRaises(bsn.SessionRefusal): o.word("md.l 0x43c02028 2", po.axi(po.HEARTBEAT))


class Envelope(unittest.TestCase):
    def test_bounds_and_wrap(self):
        lo, hi = hb.envelope(F, 1.0)
        self.assertLess(lo, F); self.assertGreater(hi, F)
        self.assertEqual(hb.delta(0xFFFFFFF0, 0x10), 0x20)
        with self.assertRaises(ValueError): hb.envelope(F, 61.0)
        with self.assertRaises(ValueError): hb.envelope(F, 0.0)

    def test_adjudicate_requires_the_control_second(self):
        with self.assertRaises(ValueError):
            hb.adjudicate(F, [("a", 0.0, 0), ("b", 1.0, 1)])
        v = hb.adjudicate(F, [("L2_1_baseline", 0.0, 0), ("L2_2_control", 1.0, int(F)), ("L2_3_read_0", 2.0, int(2 * F))])
        self.assertEqual(v["verdict"], "PASS")
        v = hb.adjudicate(F, [("L2_1_baseline", 0.0, 0), ("L2_2_control", 1.0, int(F)), ("L2_3_read_0", 2.0, int(F))])
        self.assertEqual((v["verdict"], v["kind"]), ("CONTINUITY_VIOLATION", "STALLED"))


if __name__ == "__main__":
    unittest.main()
