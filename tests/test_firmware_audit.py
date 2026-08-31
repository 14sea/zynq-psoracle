"""Source audit of the firmware (D1 spec §3, §4.6, §8; docs/l5_design.md §3).

`firmware/p3_app.c` has never been compiled — no ARM toolchain exists on this host and the
toolchain is an open item for the build authorisation. These tests are therefore the only
mechanical check on it, and they check the properties the interlock actually depends on:
no path to the MAC key register, no clock/reset/level-shifter write, only the four legal
DMA transactions, every PL access through the allowlisted accessors, no cache maintenance
where the MMU attribute is the fix, and no forbidden configuration command anywhere.

They are deliberately structural (parse the source, allowlist the symbols) rather than
textual, so that a new register access has to be added to an allowlist here before it can
appear there.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
FW = R / "firmware"
SOURCES = {p.name: p.read_text() for p in sorted(FW.glob("*.c")) + sorted(FW.glob("*.h"))}
APP = SOURCES["p3_app.c"]


def code_only(src: str) -> str:
    """Comments are documentation, not behaviour — a rule that says "no SHUTDOWN here" must
    not itself trip a search for SHUTDOWN. Forbidden-token checks run on code alone."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


CODE = {name: code_only(src) for name, src in SOURCES.items()}
APP_CODE = CODE["p3_app.c"]

# Every symbol the application may pass to Xil_Out32 / Xil_In32. A new one has to be
# justified here first — that is the point of the test.
WRITE_TARGETS = {
    "DEVCFG_INT_STS", "DEVCFG_DMA_SRC_ADDR", "DEVCFG_DMA_DEST_ADDR",
    "DEVCFG_DMA_SRC_LEN", "DEVCFG_DMA_DEST_LEN",   # the pinned DMA registers
    "P3_CMD_BUF", "P3_DST_BUF", "P3_WR_BUF",       # DDR buffers
    "P3_AXI_BASE",                                  # only inside axi_write()
}
READ_TARGETS = WRITE_TARGETS | {"DEVCFG_CTRL", "P3_PAGE_ADDR", "SLCR_PSS_IDCODE"}

# Registers that would change the machine under the experiment. None may be written.
FORBIDDEN_WRITE_ADDRESSES = {
    "0xF8000240": "FPGA_RST_CTRL",
    "0xF8000170": "FCLK0 control",
    "0xF8000180": "FCLK1 control",
    "0xF8000900": "level shifters",
    "0xF8000008": "SLCR unlock",
    "0xF8000004": "SLCR lock",
    "0xF8000200": "PSS_RST_CTRL",
}


class KeyCustody(unittest.TestCase):
    """D4: the key register is provisioned over JTAG by the signer; the application has no
    path to it, and no name for it."""

    def test_no_firmware_source_names_the_key_register(self):
        for name, src in SOURCES.items():
            for offset in ("0x2160", "0x2164", "0x2168", "0x216c", "0x216C"):
                self.assertNotIn(offset, src, f"{name} names the key register {offset}")
            self.assertNotIn("key_commit", src, f"{name} references key_commit")

    def test_the_axi_write_allowlist_cannot_reach_the_key_window(self):
        """The allowlist is bounded by construction: PAYLOAD (20) and TAG (4) words end at
        0x2160, which is where the key register begins."""
        self.assertIn("P3_PAYLOAD0 + 20u * 4u", APP)
        self.assertIn("P3_TAG0 + 4u * 4u", APP)
        self.assertEqual(0x2150 + 4 * 4, 0x2160)   # the tag window ends where the key starts


class RegisterDiscipline(unittest.TestCase):
    def targets(self, fn: str) -> set[str]:
        return set(re.findall(fn + r"\(\s*([A-Za-z_][A-Za-z0-9_]*)", APP))

    def test_every_write_target_is_allowlisted(self):
        self.assertTrue(self.targets("Xil_Out32"))
        self.assertLessEqual(self.targets("Xil_Out32"), WRITE_TARGETS)

    def test_every_read_target_is_allowlisted(self):
        self.assertTrue(self.targets("Xil_In32"))
        self.assertLessEqual(self.targets("Xil_In32"), READ_TARGETS)

    def test_no_clock_reset_or_level_shifter_write(self):
        for addr, what in FORBIDDEN_WRITE_ADDRESSES.items():
            self.assertNotIn(addr, APP, f"the application names {what} ({addr})")

    def test_the_only_slcr_access_is_the_idcode_read(self):
        """One SLCR symbol, defined once, read once, written never. (The literal
        0xF8000000u also appears as P3_ST_RESERVED — a STATUS bit mask, not an address —
        which is why this test reads symbols rather than hex literals.)"""
        self.assertEqual(re.findall(r"#define (SLCR_\w+) (0x[0-9A-Fa-f]+)u", APP_CODE),
                         [("SLCR_PSS_IDCODE", "0xF8000530")])
        self.assertEqual(len(re.findall(r"Xil_In32\(SLCR_PSS_IDCODE\)", APP_CODE)), 1)
        self.assertNotRegex(APP_CODE, r"Xil_Out32\(\s*SLCR")

    def test_pl_access_goes_only_through_the_checked_accessors(self):
        self.assertEqual(len(re.findall(r"Xil_In32\(P3_AXI_BASE", APP)), 1)
        self.assertEqual(len(re.findall(r"Xil_Out32\(P3_AXI_BASE", APP)), 1)
        for fn in ("axi_readable", "axi_writable"):
            self.assertIn(f"static int {fn}(uint32_t off)", APP)
        # both accessors refuse before touching the bus
        self.assertIn("if (!axi_readable(off))", APP)
        self.assertIn("if (!axi_writable(off))", APP)

    def test_no_cache_maintenance_calls(self):
        """The fix for the L3 diagnostic's defect is the MMU attribute, not per-op flushes:
        a flush regime is silently wrong the first time a call is missed."""
        for name, src in SOURCES.items():
            self.assertNotIn("Xil_DCacheFlush", src, name)
            self.assertNotIn("Xil_DCacheInvalidate", src, name)
        self.assertIn("Xil_SetTlbAttributes", APP)

    def test_every_instrument_buffer_is_mapped_non_cacheable(self):
        for buf in ("P3_CMD_BUF", "P3_DST_BUF", "P3_WR_BUF", "P3_PAGE_ADDR", "P3_RING_ADDR"):
            self.assertRegex(APP, r"Xil_SetTlbAttributes\(" + buf)


class DmaDiscipline(unittest.TestCase):
    def test_exactly_four_dma_transactions_are_declared(self):
        names = re.findall(r"static const p3_dma ([A-Z_0-9]+) = \{", APP)
        self.assertEqual(sorted(names), ["DMA_READ_CLEANUP", "DMA_READ_COMMAND",
                                         "DMA_READ_FRAME", "DMA_WRITE_ENVELOPE"])

    def test_no_dma_is_issued_outside_those_four(self):
        used = set(re.findall(r"devcfg_dma\(&([A-Z_0-9]+)", APP))
        self.assertEqual(used, {"DMA_WRITE_ENVELOPE", "DMA_READ_COMMAND", "DMA_READ_FRAME",
                                "DMA_READ_CLEANUP"})

    def test_the_dma_registers_are_written_in_the_pinned_order(self):
        order = re.findall(r"Xil_Out32\((DEVCFG_DMA_[A-Z_]+)", APP)
        self.assertEqual(order, ["DEVCFG_DMA_SRC_ADDR", "DEVCFG_DMA_DEST_ADDR",
                                 "DEVCFG_DMA_SRC_LEN", "DEVCFG_DMA_DEST_LEN"])

    def test_completion_is_d_p_done_not_dma_done(self):
        self.assertIn("sts & INT_STS_D_P_DONE", APP)
        self.assertNotRegex(APP, r"if \(sts & INT_STS_DMA_DONE\)")

    def test_error_bits_stop_the_epoch(self):
        self.assertIn("sts & INT_STS_ERROR_MASK", APP)
        self.assertIn("DEVCFG error bit after a DMA", APP)


class ConfigurationCommands(unittest.TestCase):
    """No startup transition, no ICAP, no CRC write — the line's standing rules (§8)."""

    def test_no_startup_transition_or_icape2_in_the_firmware_code(self):
        for name, src in CODE.items():
            for bad in ("SHUTDOWN", "GRESTORE", "JSTART", "AGHIGH", "ICAPE2"):
                self.assertNotIn(bad, src.upper(), f"{name}: {bad}")

    def test_the_only_icap_identifier_is_the_prjxray_ecc_port(self):
        """`icap_ecc` is prjxray's name for the frame-ECC arithmetic — a pure function over
        words, not an ICAPE2 primitive. Nothing else ICAP-shaped may appear."""
        found = set()
        for src in CODE.values():
            found |= {m.lower() for m in re.findall(r"\w*icap\w*", src, re.I)}
        self.assertEqual(found, {"icap_ecc"})

    def test_the_write_stream_uses_only_rcrc_wcfg_desync(self):
        derive = SOURCES["p3_derive.c"]
        cmds = set(re.findall(r"#define P3_CMD_([A-Z]+)", derive))
        self.assertEqual(cmds, {"RCRC", "WCFG", "DESYNC", "RCFG"})   # RCFG is the readback's

    def test_the_parser_refuses_any_other_register(self):
        derive = SOURCES["p3_derive.c"]
        self.assertIn("return -1; /* any other register, CRC included, is refused */", derive)


class StateMachine(unittest.TestCase):
    """The taxonomy of §3c, as the source implements it."""

    def test_the_four_epoch_end_kinds_exist(self):
        self.assertIn("P3_RUNNING = 0, P3_COMPLETED, P3_STOPPED, P3_PROTOCOL", APP)

    def test_a_gate_refusal_continues_the_session(self):
        block = APP[APP.index('if (!strcmp(type, "SIGNREF"))'):]
        block = block[:block.index("\n    }")]
        self.assertIn("S.refused++", block)
        self.assertIn("return 0;", block)              # continues …
        self.assertNotIn("p3_stop", block)             # … and never ends the epoch

    def test_the_first_cause_is_the_one_recorded(self):
        self.assertIn("if (S.kind == P3_RUNNING) { /* the first cause is the one recorded */", APP)

    def test_link2_binding_is_checked_before_any_dma(self):
        i_link2 = APP.index('strcmp(staged, commit)')
        i_write = APP.index("write_envelopes()", APP.index("static int run_candidate"))
        self.assertLess(i_link2, i_write, "the staged==commit binding must precede the DMA")

    def test_all_twelve_frames_are_read_before_judging(self):
        self.assertIn("for (i = 0; i < P3_TARGET_FRAMES; i++) /* all twelve read before judging",
                      APP)

    def test_no_arm_after_a_stop_only_a_restore_write(self):
        tail = APP[APP.index("the mandatory finally"):]
        self.assertIn("stage_streams() == 0 && write_envelopes() == 0", tail)
        self.assertNotIn("arm_attempt", tail)

    def test_the_closing_control_uses_the_last_signed_payload_with_a_zero_tag(self):
        block = APP[APP.index("static void closing_unsigned_control"):]
        block = block[:block.index("\nstatic void emit_summary")]
        self.assertIn('zero_tag[] = "' + "0" * 32 + '"', block)
        self.assertIn("S.last_commit", block)
        self.assertIn("KILL: the closing unsigned ARM validated", block)

    def test_the_search_is_only_an_interface(self):
        self.assertIn("extern int p3_search_next(", APP)
        self.assertIn("p3_search_next", SOURCES["p3_search.c"])
        self.assertNotIn("score", SOURCES["p3_search.c"].lower().split("Determinism")[0])

    def test_the_file_states_that_it_has_never_been_compiled(self):
        """The standing of this artifact is part of the artifact."""
        self.assertIn("NEVER COMPILED", APP)


if __name__ == "__main__":
    unittest.main()
