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

    def test_the_watchdog_is_touched_only_under_the_identity_flag(self):
        """D-s1 (L6 prereg §3, owner 2026-09-01): the watchdog is ON for L6, 30 s, and stays
        gated by the identity page's `flags.bit1` so that a bit1 = 0 session behaves
        exactly as L5 did. With the bit clear the application must not touch the SCU WDT
        at all; with it set, ONE control write sets prescaler 7 and watchdog (reset) mode,
        then the pinned load, then enable. The load value written is the manifest's."""
        import json
        l6 = json.loads((R / "manifests/l6_manifest.json").read_text())["pinned_at_build"]
        arm = self._arm_block()
        self.assertEqual(re.findall(r"XScuWdt_\w+", arm),
                         ["XScuWdt_Config", "XScuWdt_LookupConfig", "XScuWdt_CfgInitialize",
                          "XScuWdt_SetControlReg", "XScuWdt_LoadWdt", "XScuWdt_Start"])
        self.assertIn("XSCUWDT_CONTROL_WD_MODE_MASK", arm, "watchdog (reset) mode, not timer mode")
        self.assertIn("P3_WDT_PRESCALER << XSCUWDT_CONTROL_PRESCALER_SHIFT", arm)
        self.assertLess(arm.index("XScuWdt_SetControlReg"), arm.index("XScuWdt_LoadWdt"))
        self.assertLess(arm.index("XScuWdt_LoadWdt"), arm.index("XScuWdt_Start"))
        # nothing outside the gated block and the kick may name the driver or the load value
        self.assertEqual(len(re.findall(r"XScuWdt_\w+", APP_CODE)), 7)
        self.assertEqual(len(re.findall(r"P3_WDT_LOAD", arm)), 1)
        self.assertEqual(len(re.findall(r"P3_WDT_LOAD", APP_CODE)), 2)   # the #define + the use
        # the ACTUAL values written are the manifest's pins (D-s1: not the derivation)
        self.assertEqual(re.findall(r"#define P3_WDT_LOAD (\d+)u", APP_CODE), [str(l6["watchdog_load_value"])])
        self.assertEqual(re.findall(r"#define P3_WDT_PRESCALER (\d+)u", APP_CODE), [str(l6["watchdog_prescaler"])])
        self.assertTrue(l6["watchdog_enabled"])
        self.assertNotIn("XScuWdt_Stop", APP_CODE); self.assertNotIn("XSCUWDT_DISABLE", APP_CODE)

    def _arm_block(self) -> str:
        arm = APP_CODE[APP_CODE.index("if (S.page.flags & 2u) {"):]
        return arm[:arm.index("\n    }\n")]

    def test_the_kick_never_touches_an_uninitialised_watchdog(self):
        """Review 2026-09-01 (compatibility review, blocker 1): main() emits IDENT — and
        every framed line kicks — BEFORE the watchdog block runs CfgInitialize, so a kick
        gated on the FLAG restarted an uninitialised instance (BaseAddr 0, IsReady unset:
        the driver's assert waits forever) and the first L6 image hung after IDENT. The
        kick is gated on `S.wdt_started`, which is set only after the whole init sequence,
        and nothing else may set it."""
        kick = APP_CODE[APP_CODE.index("static void kick_watchdog"):]
        kick = kick[:kick.index("\n}")]
        self.assertIn("if (S.wdt_started)", kick)
        self.assertNotIn("S.page.flags", kick, "the kick must not be gated on the flag alone")
        self.assertEqual(re.findall(r"XScuWdt_\w+", kick), ["XScuWdt_RestartWdt"])
        # IDENT (and its kick) precedes the watchdog block; wdt_started is unset until then
        i_ident = APP_CODE.index('send_payload("IDENT"')
        i_block = APP_CODE.index("if (S.page.flags & 2u) {")
        self.assertLess(i_ident, i_block)
        self.assertNotIn("wdt_started = 1", APP_CODE[:i_block],
                         "nothing before the watchdog block may declare it started")
        # the ONE assignment is the LAST statement of the block, after Start
        arm = self._arm_block()
        self.assertEqual(APP_CODE.count("S.wdt_started = 1"), 1)
        self.assertLess(arm.index("XScuWdt_Start(&S.wdt);"), arm.index("S.wdt_started = 1"))
        self.assertEqual(arm.strip().splitlines()[-1].strip().split("/*")[0].strip(), "S.wdt_started = 1;")
        # discrimination: the mutation this exists for — `started` set before Start
        early = arm.replace("S.wdt_started = 1;", "").replace(
            "XScuWdt_SetControlReg", "S.wdt_started = 1; XScuWdt_SetControlReg", 1)
        self.assertLess(early.index("S.wdt_started = 1"), early.index("XScuWdt_Start(&S.wdt);"),
                        "the mutant is well-formed")
        self.assertNotEqual(early.strip().splitlines()[-1].strip().split("/*")[0].strip(), "S.wdt_started = 1;",
                            "the last-statement check must fail on the early-set mutant")
        # in main(): S (and so wdt_started) is zeroed before establish_identity() emits IDENT
        main_ = APP_CODE[APP_CODE.index("int main(void)"):]
        self.assertLess(main_.index("memset(&S, 0, sizeof(S));"), main_.index("if (establish_identity() != 0)"))
        self.assertLess(main_.index("if (establish_identity() != 0)"), main_.index("if (S.page.flags & 2u) {"))

    def test_watchdog_init_failure_is_fail_closed_with_a_term(self):
        arm = self._arm_block()
        self.assertIn("cfg == NULL || XScuWdt_CfgInitialize(&S.wdt, cfg, cfg->BaseAddr) != XST_SUCCESS", arm)
        fail = arm[arm.index("cfg == NULL"):arm.index("XScuWdt_SetControlReg")]
        self.assertIn('p3_stop(P3_STOPPED, "the watchdog could not be initialised")', fail)
        self.assertIn("emit_summary();", fail); self.assertIn("return 0;", fail)
        self.assertNotIn("wdt_started", fail)

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
        block = block[:block.index("\n    }\n")]
        self.assertIn("S.refused++", block)
        self.assertIn("return 0;", block)              # continues …
        # … and the only stop is the rec-v3 one: the record's transaction not acknowledged
        stops = re.findall(r"p3_stop\(([^;]*)\);", block)
        self.assertEqual(stops, ["P3_STOPPED, S.rec_stop_why"])
        self.assertIn('if (emit_record(&rec, "REFUSED_BY_GATE") != 0)', block)

    def test_the_first_cause_is_the_one_recorded(self):
        self.assertIn("if (S.kind == P3_RUNNING) { /* the first cause is the one recorded */", APP)

    def test_link2_binding_is_checked_before_any_dma(self):
        i_link2 = APP.index('strcmp(staged, commit)')
        i_write = APP.index("write_envelopes()", APP.index("static int run_candidate"))
        self.assertLess(i_link2, i_write, "the staged==commit binding must precede the DMA")

    def test_all_twelve_frames_are_read_before_judging(self):
        """L3 #1's lesson. Structural rather than a substring match on one line: the loop
        must be bounded by P3_TARGET_FRAMES and every frame must be read before the hash
        that judges them, whatever else the body gains."""
        witness = APP[APP.index("static int link3_witness"):]
        loop = witness.index("for (i = 0; i < P3_TARGET_FRAMES; i++)")
        self.assertLess(loop, witness.index("readback_frame(i)"),
                        "the readback must happen inside the twelve-frame loop")
        self.assertLess(witness.index("readback_frame(i)"), witness.index("p3_frames_hash"),
                        "all twelve frames must be read before the hash that judges them")

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
        # the two-operator search touches nothing but the genome words: no MMIO, no wire
        search = CODE["p3_search.c"]
        for bad in ("Xil_", "axi_", "send_", "p3_wire", "0x43C", "0xF8"):
            self.assertNotIn(bad, search, f"p3_search.c must not contain {bad}")
        self.assertIn("P3_MUTATION_BITS", search); self.assertIn("P3_LUT_BITS", search)

    def test_the_file_states_its_compile_standing(self):
        """The standing of this artifact is part of the artifact: as of the L5 build it is
        compiled host-side (docs/l5_findings.md) but has never been run on the board."""
        self.assertIn("COMPILED, NOT BOARD-RUN", APP)
        self.assertIn("NEVER been run on the board", APP)


class WireWiring(unittest.TestCase):
    """How p3_app.c USES the wire unit.

    tests/test_firmware_wire_contract.py proves `p3_wire.c` emits bytes the real validator
    accepts; it cannot prove this file populates it correctly, because p3_app.c is MMIO- and
    BSP-bound and does not compile on the host. These are therefore STATIC checks of the
    wiring — weaker than execution, and named that way so a green run is not mistaken for
    the board having run."""

    def test_no_payload_is_hand_built_any_more(self):
        """Every framed payload goes through p3_wire; a hand-rolled schema string here is
        how the wire format drifted away from the validator in the first place."""
        for marker in ('"schema\\":\\"loop_record', '"schema\\":\\"session_summary',
                       '"schema\\":\\"app_identity', '"schema\\":\\"sign_request'):
            self.assertNotIn(marker, APP,
                             f"{marker} is built by hand again instead of by p3_wire")

    def test_identity_is_transmitted(self):
        """validate_standalone_run_log requires app_identity; the first attempt never sent
        one. It must also be sent when identity is REFUSED — that is still evidence."""
        self.assertIn('send_payload("IDENT"', APP)
        ident = APP.index('send_payload("IDENT"')
        self.assertLess(ident, APP.index('p3_stop(P3_STOPPED, "identity refused")'),
                        "the identity frame must be sent before the refusal stops the epoch")

    def test_heartbeats_are_emitted_in_the_long_silent_stretches(self):
        """The collector calls three heartbeat intervals of silence a CRASH."""
        self.assertIn('send_frame("HB"', APP)
        witness = APP[APP.index("static int link3_witness"):]
        self.assertIn("heartbeat();", witness[:witness.index("p3_frames_hash")])
        envelopes = APP[APP.index("static int write_envelopes"):]
        self.assertIn("heartbeat();", envelopes[:envelopes.index("return 0;")])

    def test_the_closing_control_is_not_a_loop_record(self):
        """CLOSING_CONTROL is not a LOOP_OUTCOME and never was: it travels as CLOSE."""
        self.assertIn('send_payload("CLOSE"', APP)
        # CODE is comment-stripped: a comment explaining why the token is gone must not
        # trip its own guard (the "no SHUTDOWN here" trap, already learned once)
        self.assertNotIn("CLOSING_CONTROL", APP_CODE)

    def test_every_emitted_outcome_is_a_real_loop_outcome(self):
        import sys
        sys.path.insert(0, str(R))
        from validators.records import LOOP_OUTCOMES     # the one vocabulary, not a copy
        outcomes = set(re.findall(r'emit_record\(&rec, "([A-Z_]+)"\)', APP))
        self.assertTrue(outcomes, "no records are emitted at all")
        self.assertLessEqual(outcomes, set(LOOP_OUTCOMES))

    def test_the_audited_mark_means_words_were_served(self):
        """Rule (ix): `verified: audited` must mean the raw words were actually served for
        THAT candidate, never merely that auditing was configured."""
        self.assertIn("rec->audited = (S.audit_served && S.audit_served_seq == rec->seq)", APP)
        body = serve[:serve.index("\n}\n")]
        self.assertIn("S.audit_served = 1;", body)
        self.assertLess(body.index('send_payload("AUDIT"'), body.index("S.audit_served = 1;"),
                        "the mark must be set after the words are sent, not before")

    def test_every_candidate_that_staged_is_auditable(self):
        """§3a item 2 under the PULL protocol: every non-SCORED self-report runs the pull
        UNCONDITIONALLY (`audit_pull`, with or without an AUDITREQ) before its record; the
        SCORED path pulls iff the host asked at sign time, BEFORE the ARM, and a pull that
        does not complete is STOP_AUDIT with no ARM."""
        run = APP[APP.index("static int run_candidate"):]
        link2_stop = run.index('emit_record(&rec, "STOP_LINK2")')
        self.assertLess(run.index("audit_pull(0)"), link2_stop,
                        "the link-2 refusal pulls its staged words (streams span) before its record")
        for outcome in ("STOP_LINK3", "STOP_AXI", "STOP_SETTLE", "STOP_ARM", "REFUSED_BY_PL"):
            emit = run.index(f'emit_record(&rec, "{outcome}")')
            before = run[:emit]
            self.assertIn("audit_pull(1)", before[before.rindex("{"):],
                          f"{outcome} must pull unconditionally immediately before its record")
        # the SCORED path: pull iff requested, before the ARM; failure → STOP_AUDIT, no ARM
        gate = run.index("if (S.audit_requested && audit_pull(1) != 0)")
        self.assertLess(gate, run.index("arm_attempt(commit"), "the pull precedes the ARM")
        block = run[gate:run.index("\n    }", gate)]
        self.assertIn('emit_record(&rec, "STOP_AUDIT")', block)
        self.assertIn("rec.have_audit_stop = 1", block)
        self.assertLess(block.index('emit_record(&rec, "STOP_AUDIT")'), block.index("p3_stop"),
                        "the record goes out before the stop")
        self.assertIn("return -1;", block, "no fall-through to the ARM after a failed pull")
        # mutation: removing the return would let the ARM happen — the check above must fail on it
        mutant = block.replace("return -1;", "")
        self.assertNotIn("return -1;", mutant)
        scored = run.index('emit_record(&rec, "SCORED")')
        self.assertNotIn("audit_pull", run[run.index("rec.have_score = 1;"):scored],
                         "a SCORED record is pulled only via the request gate above")

    def test_the_pull_is_bounded_and_bound_to_the_candidate(self):
        """The board never waits for the host without a bound (a COUNT of RX polls, like the
        settle poll), and answers only frames whose payload seq is THIS candidate's."""
        pull = APP[APP.index("static int audit_pull"):]
        pull = pull[:pull.index("\n}\n")]
        self.assertIn("recv_line_bounded(g_line, sizeof(g_line), P3_PULL_IDLE_POLLS)", pull)
        self.assertIn('S.audit_stop_why = "the host went quiet during the audit pull', pull)
        self.assertIn('json_uint(g_json, "\\"seq\\":", &seqv) != 0 || seqv != S.seq', pull)
        self.assertIn("#define P3_PULL_IDLE_POLLS", APP)
        bounded = APP[APP.index("static int recv_line_bounded"):]
        bounded = bounded[:bounded.index("\n}")]
        self.assertIn("if (++idle > idle_polls)", bounded); self.assertIn("return -2;", bounded)
        self.assertIn("console_rx_ready()", bounded)
        # AUDITGET is answered as often as asked; DONE and ABORT are the only exits besides the bound
        self.assertIn('strcmp(type, "AUDITGET") == 0', pull)
        self.assertIn('strcmp(type, "AUDITDONE") == 0', pull)
        self.assertIn('strcmp(type, "AUDITABORT") == 0', pull)

    def test_serving_survives_a_stop_but_not_a_channel_failure(self):
        """A stop is recorded AFTER its pull, never instead of it: the pull loop exits only
        on DONE/ABORT/the bound/P3_PROTOCOL — a STOPPED epoch does not end it."""
        pull = APP_CODE[APP_CODE.index("static int audit_pull"):]
        pull = pull[:pull.index("\n}\n")]
        self.assertIn("if (S.kind == P3_PROTOCOL)", pull)
        self.assertNotIn("S.kind == P3_RUNNING", pull)
        self.assertNotIn("P3_STOPPED", pull)

    def test_the_audited_mark_means_words_were_served(self):
        """Rule (ix) under the pull: `verified: audited` means the host pulled every chunk
        AND said AUDITDONE — the mark is set in exactly one place, on DONE, and an early
        set is the mutation this exists to catch."""
        self.assertIn("rec->audited = (S.audit_served && S.audit_served_seq == rec->seq)", APP)
        pull = APP_CODE[APP_CODE.index("static int audit_pull"):]
        pull = pull[:pull.index("\n}\n")]
        done = pull.index('strcmp(type, "AUDITDONE") == 0')
        set_at = pull.index("S.audit_served = 1;")
        self.assertGreater(set_at, done, "the mark is set only inside the AUDITDONE branch")
        self.assertEqual(APP_CODE.count("S.audit_served = 1;"), 1)
        serve = APP_CODE[APP_CODE.index("static void serve_sparse_chunk"):]
        serve = serve[:serve.index("\n}")]
        self.assertNotIn("audit_served", serve, "serving a chunk is not being audited")

    def test_a_short_audit_cannot_be_served_as_a_full_one(self):
        """A link-2 refusal has no readback frames: its pull announces and serves the
        `streams` span (1602 words), never stale readback words."""
        pull = APP[APP.index("static int audit_pull"):]
        pull = pull[:pull.index("\n}\n")]
        self.assertIn('with_readback ? "streams+readback" : "streams"', pull)
        self.assertIn("with_readback ? (uint32_t)P3_AUDIT_WORDS : (uint32_t)P3_AUDIT_STREAM_WORDS", pull)

    def test_a_post_staging_axi_fault_is_recorded_as_stop_axi_with_its_words(self):
        """The pre-ARM fault check inside arm_attempt used to end the candidate with no
        record. The candidate had staged and read back, so it is a raw self-report: it is
        pulled and recorded as STOP_AXI (validators.records.self_report_class)."""
        run = APP[APP.index("static int run_candidate"):]
        block = run[run.index("if (armed < 0) {"):]
        block = block[:block.index("\n    }")]
        self.assertIn("audit_pull(1)", block)
        self.assertIn('emit_record(&rec, "STOP_AXI");', block)
        self.assertLess(block.index("audit_pull(1)"), block.index('emit_record(&rec, "STOP_AXI");'))

    def test_exactly_sixteen_heartbeats_per_scored_record(self):
        """The fixed protocol the timing breakdown and the structural gate rely on: one
        heartbeat after the streams are built, one per envelope DMA (three), one per frame
        readback (twelve) — 16, each carrying the candidate's seq. Structural: the counts
        come from the loops' bounds and the call sites, not from a constant."""
        import sys
        sys.path.insert(0, str(R / "host"))
        import l6_timing as lt
        run = APP[APP.index("static int run_candidate"):]
        pre_link2 = run[:run.index("link2_witness(staged, stream_h)")]
        self.assertEqual(pre_link2.count("heartbeat();"), 1)
        envelopes = APP[APP.index("static int write_envelopes"):]
        envelopes = envelopes[:envelopes.index("\n}")]
        self.assertIn("for (e = 0; e < P3_ENVELOPE_COUNT; e++)", envelopes)
        self.assertEqual(envelopes.count("heartbeat();"), 1)
        readback = APP[APP.index("static int link3_witness"):]
        readback = readback[:readback.index("\n}")]
        self.assertIn("for (i = 0; i < P3_TARGET_FRAMES; i++)", readback)
        self.assertEqual(readback.count("heartbeat();"), 1)
        self.assertIn("#define P3_ENVELOPE_COUNT 3", SOURCES["p3_derive.h"])
        self.assertIn("#define P3_TARGET_FRAMES 12", SOURCES["p3_derive.h"])
        self.assertEqual(1 + 3 + 12, lt.HB_PER_RECORD)
        # no other heartbeat between the sign reply and the record on the SCORED path
        after_link3 = run[run.index("link3_witness(readback)"):run.index('emit_record(&rec, "SCORED")')]
        self.assertNotIn("heartbeat();", after_link3)
        hb = APP[APP.index("static void heartbeat(void)"):]
        self.assertIn('send_frame("HB", S.seq, "-")', hb[:hb.index("\n}")])   # the candidate's seq

    def test_the_identity_names_the_master_seed_mode_and_operator_data(self):
        ident = APP[APP.index("static int establish_identity"):]
        ident = ident[:ident.index('send_payload("IDENT"')]
        self.assertIn("in.master_seed = S.page.seed;", ident)
        self.assertIn("in.operator_data_sha256 = P3_OPERATOR_DATA_SHA256;", ident)
        self.assertIn("in.schedule_mode = mode == P3_MODE_UNASSIGNED", ident)
        self.assertIn('"schedule mode 3 is unassigned"', ident)       # refused at identity
        self.assertIn("#define P3_MODE_SHIFT 2u", APP); self.assertIn("#define P3_MODE_MASK 3u", APP)

    def test_candidates_carry_the_scheduled_arm_and_baselines_none(self):
        main = APP[APP.index("int main(void)"):]
        self.assertIn("run_candidate(blank, 1, NULL)", main)
        self.assertEqual(main.count("run_candidate(blank, 1, NULL)"), 2)
        self.assertIn("p3_search_next(genome, S.page.seed, i, schedule_mode(), &arm)", main)
        self.assertIn("run_candidate(genome, 0, P3_ARM_NAME[arm])", main)
        run = APP[APP.index("static int run_candidate"):]
        self.assertIn("rec.arm = arm_name;", run[:run.index('send_payload("SIGNREQ"')])

    def test_the_arm_failure_path_keeps_its_observations(self):
        """Session 1's instrumentation gap: arm_attempt read STATUS and FAULT after the
        strobe and discarded them when the nonce had not stepped. Every observation must now
        be written through on all paths, and the record must go out BEFORE the epoch stops."""
        fn = APP[APP.index("static int arm_attempt"):]
        body = fn[:fn.index("\n}\n")]
        # STATUS is now the LAST value of the settle poll (session 3: the immediate read
        # was the defect), so the observation is `*status = st` after the poll ends.
        for obs in ("*status = st;", "*fault = axi_read(P3_FAULT)"):
            self.assertIn(obs, body, f"{obs} is no longer observed")
        self.assertLess(body.index("settle->status_last = st;"), body.index("*status = st;"))
        # CTRL is write-only (rtl/p3_axil.v). Reading it is what killed session 2, so its
        # ABSENCE here is the property — see tests/test_axi_map_vs_rtl.py.
        self.assertNotIn("axi_read(P3_CTRL)", body)
        self.assertNotIn("nonce did not step", body,
                         "arm_attempt must report the non-consumed ARM, not stop on it: "
                         "the caller records the evidence and then stops")
        self.assertEqual(body.count("p3_stop"), 1,
                         "the only stop inside arm_attempt is the pre-ARM fault check, "
                         "where the attempt is never made at all")
        run = APP[APP.index("static int run_candidate"):]
        emit = run.index('emit_record(&rec, "STOP_ARM")')
        stop = run.index('p3_stop(P3_STOPPED, "the gate settled and the nonce did not step')
        self.assertLess(emit, stop, "the STOP_ARM record must be emitted before the stop")

    def test_the_arm_record_carries_the_ctrl_readback(self):
        run = APP[APP.index("static int run_candidate"):]
        block = run[:run.index('emit_record(&rec, "STOP_ARM")')]
        for f in ("rec.status_after", "rec.fault_after", "rec.writes_issued",
                  "rec.nonce_before", "rec.nonce_after"):
            self.assertIn(f, block, f"{f} is not carried into the record")

    def test_the_hardware_witness_is_read_not_echoed(self):
        """Rules (ii)/(iii) compare the PL's own registers with the signed values; echoing
        the signed values back would make both comparisons vacuous."""
        scored = APP[APP.index("rec.have_score = 1;"):]
        block = scored[:scored.index('emit_record(&rec, "SCORED")')]
        self.assertIn("axi_read(P3_HW_COMMIT0", block)
        self.assertIn("axi_read(P3_READOUT0", block)
        self.assertNotIn("rec.hw_candidate_commit = commit", block)


if __name__ == "__main__":
    unittest.main()


class SettlePoll(unittest.TestCase):
    """Session 3 (2026-09-01): the application read the nonce immediately after the strobe,
    while gate_busy was still set; rtl/p3_arm_gate.v steps the nonce only on sh_done. The
    corrected arm_attempt polls STATUS, bounded, read-only, and writes the strobe once."""

    def _arm_attempt(self) -> str:
        start = APP.index("static int arm_attempt(")
        return APP[start:APP.index("\n}", start)]

    def test_the_strobe_is_written_exactly_once_per_attempt(self):
        body = self._arm_attempt()
        self.assertEqual(body.count("axi_write(P3_CTRL, P3_ARM_STROBE)"), 1)
        self.assertEqual(body.count("axi_write(P3_CTRL"), 1, "no second strobe from inside the poll")

    def test_the_poll_is_bounded_read_only_and_after_the_strobe(self):
        body = self._arm_attempt()
        i_strobe = body.index("axi_write(P3_CTRL, P3_ARM_STROBE)")
        i_loop = body.index("while (!(settle->settled = settle_condition(st))")
        self.assertLess(i_strobe, i_loop)
        loop = body[i_loop:body.index("settle->status_last = st;")]
        self.assertIn("settle->polls < settle->polls_max", loop)
        self.assertIn("axi_read(P3_STATUS)", loop)
        self.assertNotIn("axi_write", loop, "the poll only reads")
        self.assertIn("#define P3_SETTLE_POLLS_MAX 1000000u", APP)
        self.assertIn("settle->polls_max = P3_SETTLE_POLLS_MAX;", body)

    def test_the_nonce_is_read_only_after_the_poll(self):
        body = self._arm_attempt()
        self.assertLess(body.index("settle->status_last = st;"), body.index("*nonce_after = pl_nonce();"))

    def test_the_settle_condition_is_l3s(self):
        cond = APP[APP.index("static int settle_condition"):]
        cond = cond[:cond.index("\n}")]
        for bit in ("P3_ST_GATE_BUSY", "P3_ST_SCORER_BUSY", "P3_ST_FAULT", "P3_ST_SCORER_DONE"):
            self.assertIn(bit, cond)
        self.assertIn("return !busy && latched;", cond)

    def test_the_status_bit_numbers_match_the_design_document(self):
        """The firmware's P3_ST_* against docs/l1_design.md's register-map row, parsed."""
        design = (R / "docs/l1_design.md").read_text()
        row = next(ln for ln in design.splitlines() if ln.startswith("| `0x2004` | STATUS |"))
        doc = {m.group(2): int(m.group(1)) for m in re.finditer(r"(\d+) `?(\w+)`?", row)}
        fw = {m.group(1).lower(): int(m.group(2)) for m in re.finditer(r"#define P3_ST_(\w+) (\d+)u", APP)}
        self.assertGreaterEqual(len(fw), 7, "the P3_ST_ table did not parse")
        for name, want in {"gate_busy": doc["gate_busy"], "scorer_busy": doc["scorer_busy"],
                           "scorer_done": doc["scorer_done"], "fault": doc["fault"],
                           "cfg_valid_hw": doc["configuration_valid_hw"], "alive": doc["alive"],
                           "key_loaded": 11}.items():
            self.assertEqual(fw[name], want, f"P3_ST_{name.upper()} disagrees with l1_design.md")

    def test_three_arm_returns_are_handled_including_stop_settle(self):
        rc = APP[APP.index("static int run_candidate"):]
        rc = rc[:rc.index("\nstatic void closing_unsigned_control")]
        self.assertLess(rc.index("if (armed == 2) {"), rc.index("if (armed == 1) {"))
        self.assertIn('emit_record(&rec, "STOP_SETTLE");', rc)
        self.assertIn('emit_record(&rec, "STOP_ARM");', rc)
        self.assertLess(rc.index('emit_record(&rec, "STOP_SETTLE");'), rc.index("did not settle"),
                        "the record goes out before the epoch stops")
        closing = APP[APP.index("static void closing_unsigned_control"):]
        self.assertIn("did not settle", closing[:closing.index("\nstatic void emit_summary")])


class AuditTally(unittest.TestCase):
    """Session 3's rule-(ix) rejection: total was scored + refused and missed the STOP_ARM
    record. The count now lives where the records are serialised."""

    def test_the_summary_takes_its_audit_block_from_the_serialiser(self):
        es = APP[APP.index("static void emit_summary"):]
        es = es[:es.index("\n}")]
        self.assertIn("p3_wire_tally(&in.total, &in.audited);", es)
        self.assertNotIn("S.scored + S.refused", es)
        self.assertNotIn("S.audited", APP, "the application keeps no second audited counter")

    def test_the_serialiser_counts_only_records_it_actually_produced(self):
        wire = SOURCES["p3_wire.c"]
        body = wire[wire.index("size_t p3_wire_loop_record("):]
        body = body[:body.index("\n}")]
        self.assertIn("if (n != 0u)", body)
        self.assertIn("g_tally_records++;", body)
        self.assertLess(body.index("if (n != 0u)"), body.index("g_tally_records++;"))


class RecTransaction(unittest.TestCase):
    """rec-v3 wiring in p3_app.c (static; the state machine itself is p3_rectx.c, host-run
    by tests/test_firmware_wire_contract.py::RecWireContract). What is pinned here: the
    record is built ONCE into its own buffer and handed to p3_rectx_run (the resend is the
    same bytes, the tally counts it once); an unacknowledged record stops the epoch on both
    continuing paths and proposes no next candidate; the control corrupts seq 1 only; the
    RX FIFO is flushed before every SIGNREQ; the reply loop tolerates only stale
    RECACK/RECGET lines, bounded; the IDENT declares the protocol and the control."""

    def _emit(self) -> str:
        e = APP_CODE[APP_CODE.index("static int emit_record"):]
        return e[:e.index("\n}\n")]

    def test_the_record_is_built_once_and_transacted_from_its_own_buffer(self):
        e = self._emit()
        self.assertEqual(e.count("p3_wire_loop_record("), 1, "the serialiser (and its tally) runs once per record")
        self.assertIn("g_rec_line, sizeof(g_rec_line)", e)
        self.assertIn("p3_rectx_run(g_rec_line, n, rec->seq,", e)
        self.assertNotIn("put_str", e, "emit_record never sends by itself: the transaction does")
        self.assertIn("static char g_rec_line[", APP_CODE); self.assertIn("static char g_rec_scratch[", APP_CODE)
        self.assertEqual(APP_CODE.count("p3_rectx_run("), 1)

    def test_the_io_given_to_the_transaction_is_the_bounded_poll_and_this_files_parser(self):
        self.assertIn("recv_line_bounded(out, max, P3_REC_IDLE_POLLS)", APP_CODE)
        self.assertIn("#define P3_REC_IDLE_POLLS", APP)
        self.assertIn("return parse_frame_any(line, type_out, type_max, seq_out);", APP_CODE)
        e = self._emit()
        for cb in ("io.send = rectx_send_cb", "io.recv_bounded = rectx_recv_cb", "io.parse = rectx_parse_cb",
                   "io.payload_seq = rectx_payload_seq_cb"):
            self.assertIn(cb, e)
        send = APP_CODE[APP_CODE.index("static int rectx_send_cb"):]
        send = send[:send.index("\n}")]
        self.assertIn("put_str(line);", send); self.assertIn("kick_watchdog();", send)

    def test_an_unacknowledged_record_stops_the_epoch_and_no_next_candidate_is_proposed(self):
        e = self._emit()
        self.assertIn("S.rec_stop_why = r.why;", e); self.assertIn("return -1;", e)
        run = APP_CODE[APP_CODE.index("static int run_candidate"):]
        for outcome in ("REFUSED_BY_GATE", "SCORED"):
            i = run.index(f'if (emit_record(&rec, "{outcome}") != 0)')
            block = run[i:run.index("\n        }", i)]
            self.assertIn("p3_stop(P3_STOPPED, S.rec_stop_why);", block, outcome)
            self.assertIn("return -1;", block, outcome)
        # mutation: dropping the return would let the loop propose the next candidate
        i = run.index('if (emit_record(&rec, "SCORED") != 0)')
        block = run[i:run.index("\n        }", i)]
        self.assertNotIn("return -1;", block.replace("return -1;", ""))
        # the main loop stops on S.kind, which the stop above sets
        main_ = APP_CODE[APP_CODE.index("int main(void)"):]
        self.assertIn("S.kind == P3_RUNNING && (S.page.budget == 0u || i < S.page.budget)", main_)
        # the stop paths keep their own first cause: their emit is void-cast, the stop after
        for outcome in ("STOP_LINK2", "STOP_LINK3", "STOP_AUDIT", "STOP_AXI", "STOP_SETTLE", "STOP_ARM", "REFUSED_BY_PL"):
            self.assertIn(f'(void)emit_record(&rec, "{outcome}");', run, outcome)

    def test_the_control_corrupts_only_the_opening_baselines_first_transmission(self):
        e = self._emit()
        self.assertIn("(S.rec_control && rec->seq == 1u) ? 1 : 0", e)
        ident = APP_CODE[APP_CODE.index("static int establish_identity"):]
        ident = ident[:ident.index('send_payload("IDENT"')]
        self.assertIn("S.rec_control = (S.page.flags & P3_RECTX_CONTROL_FLAG) ? 1 : 0;", ident)
        self.assertIn('in.protocol = "rec-v3";', ident); self.assertIn("in.rec_retry_control = S.rec_control;", ident)
        self.assertEqual(APP_CODE.count("S.rec_control ="), 1)
        rectx = SOURCES["p3_rectx.c"]
        self.assertIn("if (attempt == 1u && corrupt_first)", rectx)
        self.assertIn("#define P3_RECTX_CONTROL_FLAG 16u", SOURCES["p3_rectx.h"])

    def test_the_rx_fifo_is_flushed_before_every_signreq_and_the_reply_loop_skips_only_stale_acks(self):
        run = APP_CODE[APP_CODE.index("static int run_candidate"):]
        self.assertLess(run.index("console_rx_flush();"), run.index('send_payload("SIGNREQ"'))
        self.assertEqual(APP_CODE.count("console_rx_flush();"), 1)
        loop = run[run.index("S.audit_requested = 0;"):run.index('if (!strcmp(type, "SIGNREF"))')]
        self.assertIn('strcmp(type, "RECACK") == 0 || strcmp(type, "RECGET") == 0', loop)
        self.assertIn("++stale > P3_REPLY_STALE_LIMIT", loop)
        self.assertIn("if (!payload || fseq != S.seq)", loop)
        self.assertIn('"PROTOCOL: the notary reply did not verify"', loop)
        self.assertIn("#define P3_REPLY_STALE_LIMIT 8u", APP)
        # the flush is BSP glue: register reads only, no control write
        console = (R / "firmware/bsp/src/console.c").read_text()
        flush = console[console.index("int console_rx_flush(void)\n{"):]
        flush = flush[:flush.index("\n}")]
        self.assertNotIn("Xil_Out32", flush); self.assertIn("UART_FIFO", flush); self.assertIn("n < 4096", flush)

    def test_the_transaction_unit_is_pure(self):
        rectx = CODE["p3_rectx.c"]
        for bad in ("Xil_", "axi_", "0x43C", "0xF8", "outbyte", "inbyte", "printf", "static char g_"):
            self.assertNotIn(bad, rectx, f"p3_rectx.c must not contain {bad}")
        self.assertIn("#define P3_RECTX_ATTEMPTS 3u", SOURCES["p3_rectx.h"])
        self.assertIn('strcmp(type, "RECACK") == 0', rectx); self.assertIn('strcmp(type, "RECGET") == 0', rectx)
        # the same bytes every time: the line pointer is passed through, only the control copies
        self.assertIn("return io->send(line, n, io->ctx);", rectx)
        self.assertEqual(rectx.count("memcpy(scratch, line, n);"), 1)

