"""The firmware's MMIO allowlist must not exceed the RTL's AXI-Lite decode.

Session 2 died on exactly this. `axi_readable()` had been widened to permit a read of
`CTRL` (`0x2000`) for instrumentation; `rtl/p3_axil.v` decodes `CTRL` **write-only**, so the
read was SLVERR and on this board a data abort. The application vanished mid-session, the
required evidence was never emitted, and two rulings were spent on the defect. The widening
rested on a register *name* seen elsewhere -- `pcap_probe_plan.REG["CTRL"]`, which is
DEVCFG's `0xF8007000`, a different register in a different peripheral.

A set comparison of the two decodes takes milliseconds and catches it before the board.

**Both sides are parsed from source**, never restated here: a hand-kept copy of either map
is one more thing that can drift, which is the failure this test exists to prevent.

Direction matters:
  * `app - rtl` MUST be empty, on read and on write. An app read the RTL does not decode is
    a latent data abort; an app write it does not decode is a silent SLVERR.
  * `rtl - app` may be non-empty and is reported, not failed: the RTL decodes the key window
    `0x2160..0x216F`, which the application must never name or touch (D4).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
APP = (R / "firmware/p3_app.c").read_text()
RTL = (R / "rtl/p3_axil.v").read_text()

DEFINES = {m.group(1): int(m.group(2), 16)
           for m in re.finditer(r"#define (P3_\w+) (0x[0-9A-Fa-f]+)u", APP)}


def _fn_body(src: str, name: str) -> str:
    start = src.index(f"static int {name}(uint32_t off)")
    return src[start:src.index("\n}", start)]


def app_offsets(fn: str) -> set[int]:
    """Offsets `axi_readable`/`axi_writable` return 1 for, from their own source."""
    body = _fn_body(APP, fn)
    out: set[int] = set()
    for m in re.finditer(r"off == (P3_\w+)", body):
        out.add(DEFINES[m.group(1)])
    for m in re.finditer(r"off >= (P3_\w+) && off < P3_\w+ \+ (\d+)u \* 4u", body):
        base, n = DEFINES[m.group(1)], int(m.group(2))
        out.update(base + 4 * i for i in range(n))
    return out


def rtl_offsets(sig: str) -> set[int]:
    """Offsets the RTL decodes for `ra` (read) or `wa` (write), from the decode itself."""
    out: set[int] = set()
    for m in re.finditer(sig + r" == 16'h([0-9A-Fa-f]{4})", RTL):
        out.add(int(m.group(1), 16))
    for m in re.finditer(sig + r" >= 16'h([0-9A-Fa-f]{4})\)? && \(?" + sig
                         + r" < 16'h([0-9A-Fa-f]{4})", RTL):
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        out.update(range(lo, hi, 4))          # every decode is word-aligned (ra[1:0]==0)
    return out


class ParsersActuallyParsed(unittest.TestCase):
    """Guard the guard. If a regex stopped matching, both sides would come back empty and
    every set difference below would pass vacuously — the exact shape of a test that is
    green because it checks nothing."""

    def test_the_app_map_was_parsed(self):
        self.assertGreaterEqual(len(DEFINES), 10, "the P3_* define table did not parse")
        self.assertGreaterEqual(len(app_offsets("axi_readable")), 20)
        self.assertGreaterEqual(len(app_offsets("axi_writable")), 20)

    def test_the_rtl_decode_was_parsed(self):
        self.assertGreaterEqual(len(rtl_offsets("ra")), 20, "the RTL read decode did not parse")
        self.assertGreaterEqual(len(rtl_offsets("wa")), 20, "the RTL write decode did not parse")

    def test_known_anchors_are_present_on_both_sides(self):
        self.assertIn(DEFINES["P3_STATUS"], rtl_offsets("ra"))      # 0x2004, readable
        self.assertIn(DEFINES["P3_CTRL"], rtl_offsets("wa"))        # 0x2000, writable
        self.assertNotIn(DEFINES["P3_CTRL"], rtl_offsets("ra"))     # …and NOT readable


class AppNeverExceedsTheRtlContract(unittest.TestCase):
    def test_no_app_read_outside_the_rtl_read_decode(self):
        extra = app_offsets("axi_readable") - rtl_offsets("ra")
        self.assertEqual(
            sorted(hex(x) for x in extra), [],
            "the application may read an offset the RTL does not decode: SLVERR, and on this "
            "board a data abort. Do NOT widen the RTL to suit an instrument — drop the read "
            "and record the value as unavailable.")

    def test_no_app_write_outside_the_rtl_write_decode(self):
        extra = app_offsets("axi_writable") - rtl_offsets("wa")
        self.assertEqual(sorted(hex(x) for x in extra), [],
                         "the application may write an offset the RTL does not decode: SLVERR")

    def test_the_key_window_is_decoded_by_rtl_and_absent_from_the_app(self):
        """The one intended `rtl - app` difference, asserted so it stays intentional (D4)."""
        key = set(range(0x2160, 0x2170, 4))
        self.assertTrue(key <= rtl_offsets("wa"), "the RTL should decode the key window")
        self.assertEqual(key & app_offsets("axi_writable"), set(),
                         "the application must have no path to the key register")
        self.assertEqual(key & app_offsets("axi_readable"), set())


class CtrlIsWriteOnly(unittest.TestCase):
    """The specific regression. Named so a future reader sees why it is here."""

    def test_the_app_does_not_read_ctrl(self):
        self.assertNotIn(DEFINES["P3_CTRL"], app_offsets("axi_readable"),
                         "CTRL is write-only in the RTL; reading it killed session 2")
        self.assertNotIn("axi_read(P3_CTRL)", APP)

    def test_the_arm_record_says_the_readback_is_unavailable(self):
        """Dropping the read must not silently drop the question."""
        wire = (R / "firmware/p3_wire.c").read_text()
        self.assertIn("ctrl_readback", wire)
        self.assertIn("unavailable", wire)


if __name__ == "__main__":
    unittest.main()
