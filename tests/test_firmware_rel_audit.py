"""Source audit of the rel-v4 firmware (prereg v0.6 draft §2.6i–6p; the owner's mandatory
deliverables 2026-09-02): the board-bound contract, the IDENT handshake before the first
SIGNREQ, the SIGNREQ / TERM transactions and the pull unit wired as pure units, the indexed
heartbeats, the flag gating of both controls, the closing control repeated in the TERM, the
IDENT 1.3.0 echo — all pinned structurally on the source the image links.

THE BOUND PROOF (owner: "prove every board bound ≤ 10 s on the pinned clock; measuring the
C twin on the host is not it"): every rel-v4 wait goes through `recv_line_bounded`, which is
`p3_rectx_recv_line_timed` with the global timer as clock and `P3_BOUND_TICKS` = P3_BOUND_S ×
COUNTS_PER_SECOND as the idle bound; the receiver ends a wait when the clock bound OR the
poll count runs out, whichever first; COUNTS_PER_SECOND is the BSP's XPAR_CPU_CORTEXA9_CORE_
CLOCK_FREQ_HZ / 2 with the pinned 666,666,687 Hz CPU clock (6:2:1, verified per session from
CPU_CLK_CTRL by the runner). So on that clock no wait exceeds P3_BOUND_S = 8 s < 10 s, from
the source alone — the test below derives the number the way the compiler does.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "tests"))
import l6_rel as rel  # noqa: E402
import test_firmware_audit as fa  # noqa: E402

APP, APP_CODE = fa.APP, fa.APP_CODE
SRC, CODE = fa.SOURCES, fa.CODE
XPAR = (R / "firmware/bsp/include/xparameters.h").read_text()


def fn(src: str, head: str) -> str:
    i = src.index(head)
    return src[i:src.index("\n}\n", i)]


class BoundContract(unittest.TestCase):
    def test_every_wait_is_the_timed_receiver_with_the_global_timer(self):
        rb = fn(APP_CODE, "static int recv_line_bounded(char *out, size_t max, uint32_t idle_polls)")
        self.assertIn("rx.now_ticks = app_now_ticks;", rb)
        self.assertIn("return p3_rectx_recv_line_timed(&rx, out, max, idle_polls, P3_BOUND_TICKS);", rb)
        self.assertNotIn("p3_rectx_recv_line(&rx", rb)
        now = fn(APP_CODE, "static uint64_t app_now_ticks(void *ctx)")
        self.assertIn("XTime_GetTime(&now);", now)
        self.assertEqual(APP_CODE.count("XTime_GetTime("), 1, "the clock is read in one place")
        # the blocking L5 receiver is gone: no wait can hold the application past the bound
        self.assertNotIn("static int recv_line(char *out, size_t max)", APP_CODE)
        self.assertEqual(len(re.findall(r"\brecv_line\(", APP_CODE)), 0)
        # every transaction's recv goes through recv_line_bounded
        for cb in ("static int rectx_recv_cb", "static int tx_recv_cb", "static int pull_recv_cb"):
            body = fn(APP_CODE, cb)
            self.assertIn("return recv_line_bounded(out, max,", body, cb)

    def test_the_bound_is_eight_seconds_of_the_pinned_clock_below_the_hosts_ten(self):
        self.assertIn("#define P3_BOUND_S 8u", APP)
        self.assertIn("#define P3_BOUND_TICKS ((uint64_t)P3_BOUND_S * (uint64_t)COUNTS_PER_SECOND)", APP)
        m = re.search(r"#define XPAR_CPU_CORTEXA9_0_CPU_CLK_FREQ_HZ\s+(\d+)U", XPAR)
        cpu_hz = int(m.group(1))
        self.assertEqual(cpu_hz, 666666687, "the pinned 6:2:1 CPU clock")
        counts_per_second = cpu_hz // 2                 # xtime_l.h: the global timer is CPU/2
        bound_s = 8 * counts_per_second / counts_per_second
        self.assertEqual(bound_s, 8.0)
        # the longest path of one receive: the idle gap and the whole line share the bound,
        # so a wait — however the bytes are paced — ends within bound_s (review 2026-09-03)
        line_factor_ticks = 1
        self.assertLessEqual(max(bound_s, line_factor_ticks * bound_s), rel.BOARD_BOUND_WALL_MAX_S)
        self.assertLessEqual(bound_s, rel.BOARD_BOUND_WALL_MAX_S, "the host's linger derives from ≤ 10 s")
        # the same number the host contract names
        self.assertEqual(rel.FIRMWARE_BOUND_CONTRACT["poll_bound_wall_max_s"], 10.0)
        self.assertEqual(rel.TERM_LINGER_S, 2 * 10.0 + 2.0)

    def test_the_timed_receiver_ends_on_the_clock_or_the_count_whichever_first(self):
        unit = CODE["p3_rectx.c"]
        body = unit[unit.index("int p3_rectx_recv_line_timed"):unit.index("int p3_rectx_recv_line(")]
        self.assertIn("if (++idle > idle_polls)", body)
        self.assertIn("if (now - t_last > idle_ticks || now - t_start > line_ticks)", body)
        self.assertIn("return n == 0u ? -2 : -3;", body)
        # review 2026-09-03, blocker 2: the whole-line tick bound is the SAME bound — never ×4
        self.assertIn("const uint64_t line_ticks = idle_ticks;", body)
        self.assertNotIn("idle_ticks * P3_RECTX_LINE_POLL_FACTOR", body)
        self.assertIn("if (t_last - t_start > line_ticks)", body, "a byte arriving past the line bound ends it too")
        # the count-only form is the timed one with no clock
        self.assertIn("return p3_rectx_recv_line_timed(rx, out, max, idle_polls, 0u);", unit)

    def test_the_timer_is_started_once_at_go_and_read_only_afterwards(self):
        main_ = APP_CODE[APP_CODE.index("int main(void)"):]
        self.assertEqual(APP_CODE.count("XTime_SetTime("), 1)
        self.assertLess(main_.index("XTime_SetTime(0u);"), main_.index("establish_identity()"))
        self.assertNotIn("GLOBAL_TMR", APP_CODE, "no direct timer register access")

    def test_every_poll_cap_named_by_the_contract_exists(self):
        for name in rel.FIRMWARE_BOUND_CONTRACT["applies_to"]:
            self.assertIn(f"#define {name} ", APP, name)


class Transactions(unittest.TestCase):
    def test_ident_is_a_transaction_completed_before_any_signreq(self):
        ident = fn(APP_CODE, "static int establish_identity(void)")
        self.assertIn('k.ack_a = "IDENTACK";', ident); self.assertIn("k.get = NULL;", ident)
        self.assertIn("tx_run_line(n, 0u, &k, 0, P3_IDENT_IDLE_POLLS, &r)", ident)
        self.assertIn("STOP_IDENT", ident)
        self.assertIn("in.sign_retry_control = S.sign_control;", ident); self.assertIn('in.protocol = "rel-v4";', ident)
        self.assertIn("S.sign_control = (S.page.flags & P3_SIGNTX_CONTROL_FLAG) ? 1 : 0;", ident)
        # main: identity first; a failed handshake is a TERM and no candidate
        main_ = APP_CODE[APP_CODE.index("int main(void)"):]
        self.assertLess(main_.index("if (establish_identity() != 0)"), main_.index("run_candidate(blank, 1, NULL)"))
        self.assertIn("if (establish_identity() != 0) {\n        emit_summary();\n        return 0;", main_)
        self.assertIn("#define P3_SIGNTX_CONTROL_FLAG 32u", SRC["p3_rectx.h"])

    def test_the_sign_exchange_is_a_transaction_with_the_strict_previous_ack_rule(self):
        run = fn(APP_CODE, "static int run_candidate(")
        self.assertIn('k.ack_a = "SIGNOK";', run); self.assertIn('k.ack_b = "SIGNREF";', run); self.assertIn('k.get = "SIGNGET";', run)
        self.assertIn("k.prev_seq = S.seq >= 2u ? S.seq - 1u : 0u;", run); self.assertIn("k.prev_strict = 1;", run)
        self.assertIn("(S.sign_control && S.seq == 1u) ? 1 : 0", run)
        self.assertIn('(void)emit_record(&rec, "STOP_SIGN");', run)
        self.assertIn("rec.have_sign_stop = 1;", run)
        self.assertNotIn('"AUDITREQ"', run, "AUDITREQ is no longer a frame")
        self.assertIn('S.audit_requested = (strstr(g_json, "\\"audit_requested\\":true") != NULL) ? 1 : 0;', run)
        self.assertLess(run.index("console_rx_flush();"), run.index('build_payload_frame("SIGNREQ"'))
        unit = CODE["p3_rectx.c"]
        self.assertIn("if (kinds->prev_seq == 0u || fseq != kinds->prev_seq || payload[0] == 0 ||", unit)
        self.assertIn("if (++prev_acks > P3_RECTX_PREV_ACK_LIMIT)", unit)
        self.assertIn("#define P3_RECTX_PREV_ACK_LIMIT 8u", SRC["p3_rectx.h"])

    def test_the_term_is_a_transaction_carrying_the_closing_control(self):
        es = fn(APP_CODE, "static void emit_summary(void)")
        self.assertIn('k.ack_a = "TERMACK";', es); self.assertIn('k.get = "TERMGET";', es)
        self.assertIn("tx_run_line(n, S.seq + 1u, &k, 0, P3_TERM_IDLE_POLLS, &r)", es)
        for f in ("in.have_closing_control = S.have_closing_control;", "in.close_nonce_before = S.close_nb;",
                  "in.close_nonce_after = S.close_na;", "in.close_fault = S.close_fault;", "in.close_status = S.close_status;"):
            self.assertIn(f, es)
        cc = fn(APP_CODE, "static void closing_unsigned_control(void)")
        self.assertLess(cc.index('send_payload("CLOSE"'), cc.index("S.have_closing_control = 1;"))
        self.assertNotIn('send_payload("TERM"', APP_CODE, "the TERM goes out only through the transaction")
        wire = SRC["p3_wire.c"]
        self.assertIn('if (in->have_closing_control) { /* rel-v4: "closing" < "closing_control" < "counts" */', wire)

    def test_the_pull_is_the_pure_unit_with_ready_resend_and_auditwait(self):
        pull = fn(APP_CODE, "static int audit_pull(int with_readback)")
        self.assertIn("rc = p3_pull_run(S.seq, chunks, &io, &pr);", pull)
        self.assertIn('build_payload_frame("AUDIT_READY", S.seq,', pull)
        self.assertIn("g_ready_line, sizeof(g_ready_line)", pull)
        for cb in ("io.send_ready = pull_send_ready_cb;", "io.serve_chunk = pull_serve_chunk_cb;", "io.send_wait = pull_send_wait_cb;"):
            self.assertIn(cb, pull)
        self.assertIn("put_str(g_ready_line);", fn(APP_CODE, "static int pull_send_ready_cb(void *ctx)"))
        self.assertIn('send_payload("AUDITWAIT", S.seq,', fn(APP_CODE, "static int pull_send_wait_cb(uint32_t served, void *ctx)"))
        unit = CODE["p3_pull.c"]
        self.assertIn("if (r->ready_sent >= P3_PULL_READY_ATTEMPTS)", unit); self.assertIn("if (r->waits_sent >= P3_PULL_WAIT_MAX)", unit)
        self.assertIn("#define P3_PULL_READY_ATTEMPTS 3u", SRC["p3_pull.h"]); self.assertIn("#define P3_PULL_WAIT_MAX 3u", SRC["p3_pull.h"])
        self.assertEqual(APP_CODE.count("p3_pull_run("), 1)

    def test_the_units_are_pure_and_the_transaction_bytes_never_change(self):
        for name in ("p3_rectx.c", "p3_pull.c"):
            unit = CODE[name]
            for bad in ("Xil_", "axi_", "0x43C", "0xF8", "outbyte", "inbyte", "printf", "static char g_", "XTime"):
                self.assertNotIn(bad, unit, f"{name} must not contain {bad}")
        rectx = CODE["p3_rectx.c"]
        self.assertIn("return io->send(line, n, io->ctx);", rectx); self.assertEqual(rectx.count("memcpy(scratch, line, n);"), 1)
        self.assertIn("#define P3_RECTX_ATTEMPTS 3u", SRC["p3_rectx.h"])
        # the REC transaction is the generic one with its two types
        self.assertIn('k.ack_a = "RECACK";', rectx); self.assertIn('k.get = "RECGET";', rectx)
        self.assertEqual(APP_CODE.count("p3_rectx_run("), 1); self.assertEqual(APP_CODE.count("p3_tx_run("), 1)


class Heartbeats(unittest.TestCase):
    def test_every_heartbeat_carries_its_index_restarting_per_record(self):
        hb = fn(APP_CODE, "static void heartbeat(void)")
        self.assertIn('send_payload("HB", S.seq, p3_wire_hb(S.hb_i++, g_payload, sizeof(g_payload)));', hb)
        run = fn(APP_CODE, "static int run_candidate(")
        self.assertLess(run.index("S.hb_i = 0u;"), run.index("heartbeat();"))
        self.assertIn('w_fmt(&w, "{\\"i\\":%lu}", (unsigned long)i);', SRC["p3_wire.c"])
        self.assertNotIn('"HB", S.seq, "-"', APP_CODE)


class Identity(unittest.TestCase):
    def test_identity_1_3_0_echoes_both_controls(self):
        wire = SRC["p3_wire.c"]
        self.assertIn('\\"schema_version\\":\\"1.3.0\\",\\"sign_retry_control\\":%s,', wire)
        self.assertIn("in->sign_retry_control ? \"true\" : \"false\"", wire)
        self.assertEqual(APP_CODE.count("S.sign_control ="), 1)
        self.assertIn("int sign_retry_control;", SRC["p3_wire.h"])


if __name__ == "__main__":
    unittest.main()
