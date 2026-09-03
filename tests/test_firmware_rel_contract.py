"""rel-v4 on the C source — the board's actual transactions run on the host over a pipe
(firmware/p3_rectx.c `p3_tx_run`, firmware/p3_pull.c `p3_pull_run`, firmware/p3_wire.c),
with THIS test — and where it says so the REAL host objects of host/l6_rel.py and
host/l6_audit_pull.py — playing the runner:

  * identtx: one IDENT and an IDENTACK; the IDENT resent on the bound, three times, then
    STOP_IDENT; a refused identity (the real IdentHost, no ack) exhausts the same way;
  * signtx: SIGNOK / SIGNREF acknowledge; SIGNGET resends the same bytes; the bound resends;
    exhaustion is STOP_SIGN; the forced control corrupts attempt 1 only; the previous
    record's RECACK is skipped (bounded) and any other acknowledgement is PROTOCOL; the
    real SignHost + NotaryRelay drive a clean exchange, a cached replay and a SIGNGET, with
    ONE signature and `audit_requested` folded into the SIGNOK the board reads;
  * termtx: TERMACK; TERMGET resends the same bytes; the bound; exhaustion halts; the real
    TermHost acknowledges and re-acknowledges; the TERM carries the closing control the
    validator reconstructs a lost CLOSE from;
  * pulltx: the real PullHost pulls a clean span; a lost READY is resent (same bytes) on the
    bound; a lost DONE draws AUDITWAIT and the replayed DONE completes the pull; exhausted
    waits give the audit up; READY resent three times without a GET gives up;
  * the serialiser: IDENT 1.3.0 echoes sign_retry_control and check_l6_identity verifies it;
    an indexed HB parses with its index; a STOP_SIGN record validates with its contract;
    a TERM without the control (a stopped epoch) carries no block.
"""
from __future__ import annotations

import subprocess as sp
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "tests"))
import bitstream_frames  # noqa: E402,F401
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_rel as rel  # noqa: E402
import test_firmware_wire_contract as wc  # noqa: E402
from validators import records  # noqa: E402

TOKEN = wc.TOKEN
CARRIER_SHA = wc.CARRIER_SHA
SEED = wc.SEED
COMMIT, TAG = "a" * 64, "b" * 32
TABLES = ["0" * 16] * 6


class Pipe:
    """The twin on a pipe with one interactive command: read the board's lines, write the
    host's; `!idle` lets the board's bound run out; `!raw` sends a line with no newline."""

    def __init__(self, exe: Path, cmd: str):
        self.proc = sp.Popen([str(exe)], stdin=sp.PIPE, stdout=sp.PIPE, text=True, bufsize=1)
        self.proc.stdin.write(cmd if cmd.endswith("\n") else cmd + "\n"); self.proc.stdin.flush()

    def write(self, line: str) -> None:
        self.proc.stdin.write(line if line.endswith("\n") else line + "\n"); self.proc.stdin.flush()

    def read(self) -> str:
        return self.proc.stdout.readline()

    def finish(self, tag: str) -> dict:
        line = self.read()
        while line and not line.startswith(tag):
            line = self.read()
        assert line.startswith(tag), line
        out = {}
        for kv in line[len(tag):].rstrip("\n").split(" "):
            if "=" in kv:
                k, v = kv.split("=", 1); out[k] = v
        # `why=` carries spaces: everything after "why=" is the reason
        if " why=" in line:
            out["why"] = line.split(" why=", 1)[1].rstrip("\n")
        self.proc.stdin.close(); self.proc.wait(timeout=10)
        return out


class RelContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = wc.build_twin()

    # ------------------------------------------------------------------ helpers
    def _ident_cmd(self, **kw) -> str:
        base = dict(idcode="0x03722093", uboot_epoch=7, carrier_sha256=CARRIER_SHA, nonce=f"{SEED:016x}",
                    status="0x900", fclk0=50000000, master_seed=7, schedule_mode="random_safe_forced",
                    operator_sha="0c" * 32, rec_control=1, sign_control=1)
        base.update(kw)
        return "identtx token=" + TOKEN + " " + " ".join(f"{k}={v}" for k, v in base.items())

    def _sign_cmd(self, seq=1, prev_seq=0, corrupt=0) -> str:
        return f"signtx token={TOKEN} seq={seq} app_epoch=0 genome={'0' * 80} nonce={SEED:016x} prev_seq={prev_seq} corrupt={corrupt}"

    def _term_cmd(self, **kw) -> str:
        base = dict(kind="COMPLETED", reason="budget", last_seq=2, closing_unsigned=1, closing_nb="3" * 16, closing_na="4" * 16)
        base.update(kw)
        return "termtx token=" + TOKEN + " " + " ".join(f"{k}={v}" for k, v in base.items())

    @staticmethod
    def ack(mtype: str, seq: int) -> str:
        return n.build_line(mtype, seq, TOKEN, n.encode_payload({"seq": seq}))

    # ------------------------------------------------------------------ IDENT
    def test_ident_one_transmission_one_ack(self):
        p = Pipe(self.exe, self._ident_cmd())
        line = p.read(); f = n.parse_line(line)
        self.assertEqual((f["type"], f["seq"]), (n.T_IDENT, 0))
        ident = n.decode_payload(f["payload"])
        self.assertEqual(ident["schema_version"], "1.3.0"); self.assertTrue(ident["sign_retry_control"]); self.assertEqual(ident["protocol"], "rel-v4")
        records.check_l6_identity(ident, 7, "random_safe_forced", "0c" * 32, protocol="rel-v4",
                                  rec_retry_control=True, sign_retry_control=True)
        p.write(self.ack(rel.T_IDENTACK, 0))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["acked"], res["ack_type"]), ("0", "1", "1", "IDENTACK"))

    def test_ident_resent_on_the_bound_three_times_then_stop_ident(self):
        p = Pipe(self.exe, self._ident_cmd())
        lines = []
        for _ in range(3):
            lines.append(p.read()); p.write("!idle")
        self.assertEqual(len(set(lines)), 1, "three identical transmissions")
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["idle"], res["acked"]), ("-1", "3", "3", "0"))
        self.assertIn("STOP_IDENT", res["why"])

    def test_the_real_ident_host_refuses_and_the_board_exhausts(self):
        sent = []
        host = rel.IdentHost(TOKEN, lambda ident: ["master_seed 7 != the page's 9"], send=sent.append)
        p = Pipe(self.exe, self._ident_cmd())
        for _ in range(3):
            host.on_line(p.read().rstrip("\n"))
            self.assertEqual(sent, [], "no IDENTACK for a refused identity")
            p.write("!idle")
        res = p.finish("!tx ")
        self.assertEqual(res["acked"], "0"); self.assertIn("STOP_IDENT", res["why"])
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["refused", "refused-repeat", "refused-repeat"])
        # and an accepted identity: the real host acknowledges once
        sent = []; host = rel.IdentHost(TOKEN, lambda ident: [], send=sent.append)
        p = Pipe(self.exe, self._ident_cmd())
        host.on_line(p.read().rstrip("\n")); p.write(sent[0])
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"]), ("0", "1")); self.assertTrue(host.established)

    def test_a_torn_ack_is_partial_and_the_next_transmission_follows(self):
        p = Pipe(self.exe, self._ident_cmd())
        first = p.read()
        p.write("!raw " + self.ack(rel.T_IDENTACK, 0).rstrip("\n")[:20])   # cut, no newline
        p.write("!idle")
        second = p.read()
        self.assertEqual(first, second)
        p.write(self.ack(rel.T_IDENTACK, 0))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["partial"]), ("0", "2", "1"))

    # ------------------------------------------------------------------ SIGNREQ
    def _signok(self, seq: int, audit=True) -> str:
        return n.build_line(n.T_SIGNOK, seq, TOKEN, n.encode_payload(
            {"schema": "sign_reply", "schema_version": "1.0.0", "seq": seq, "commit": COMMIT,
             "expected_tables": TABLES, "tag": TAG, "audit_requested": audit}))

    def test_signreq_signok_and_signref_both_acknowledge(self):
        p = Pipe(self.exe, self._sign_cmd())
        f = n.parse_line(p.read()); self.assertEqual((f["type"], f["seq"]), (n.T_SIGNREQ, 1))
        p.write(self._signok(1))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["ack_type"]), ("0", "1", "SIGNOK"))
        p = Pipe(self.exe, self._sign_cmd()); p.read()
        p.write(n.build_line(n.T_SIGNREF, 1, TOKEN, n.encode_payload({"schema": "sign_refusal", "schema_version": "1.0.0", "seq": 1, "finding_kinds": ["x"]})))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["ack_type"]), ("0", "SIGNREF"))

    def test_signget_and_the_bound_resend_the_same_bytes_exhaustion_is_stop_sign(self):
        p = Pipe(self.exe, self._sign_cmd())
        first = p.read()
        p.write(self.ack(rel.T_SIGNGET, 1)); second = p.read()
        p.write("!idle"); third = p.read()
        self.assertEqual(first, second); self.assertEqual(first, third)
        p.write("!idle")
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["gets"], res["idle"], res["acked"]), ("-1", "3", "1", "2", "0"))
        self.assertIn("STOP_SIGN", res["why"])

    def test_the_forced_control_corrupts_attempt_1_only(self):
        p = Pipe(self.exe, self._sign_cmd(corrupt=1))
        first = p.read()
        with self.assertRaises(n.CrcError):
            n.parse_line(first)
        p.write(self.ack(rel.T_SIGNGET, 1))
        second = p.read()
        n.parse_line(second)
        self.assertEqual(first[:-2], second[:-2]); self.assertNotEqual(first[-2], second[-2])
        p.write(self._signok(1))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["corrupted_first"]), ("0", "2", "1"))

    def test_the_previous_records_ack_is_skipped_bounded_and_another_seqs_is_protocol(self):
        p = Pipe(self.exe, self._sign_cmd(seq=5, prev_seq=4)); p.read()
        p.write(self.ack("RECACK", 4)); p.write(self.ack("RECGET", 4))
        p.write(self._signok(5))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["prev_acks"], res["ack_type"]), ("0", "2", "SIGNOK"))
        p = Pipe(self.exe, self._sign_cmd(seq=5, prev_seq=4)); p.read()
        p.write(self.ack("RECACK", 3))
        res = p.finish("!tx ")
        self.assertEqual(res["rc"], "-3"); self.assertIn("not the previous transaction's", res["why"])
        p = Pipe(self.exe, self._sign_cmd(seq=5, prev_seq=4)); p.read()
        for _ in range(9):
            p.write(self.ack("RECACK", 4))
        res = p.finish("!tx ")
        self.assertEqual(res["rc"], "-3"); self.assertIn("too many stale acknowledgements", res["why"])

    def test_the_real_sign_host_signs_once_replays_the_cached_reply_and_re_requests(self):
        rl = n.NotaryRelay(TOKEN, lambda req: {"commit": COMMIT, "expected_tables": TABLES, "tag": TAG}, drop_budget=8, clock=lambda: 0.0)
        sent = []
        host = rel.SignHost(TOKEN, rl, send=sent.append, audit_seqs={1})
        p = Pipe(self.exe, self._sign_cmd())
        line = p.read().rstrip("\n"); host.on_signreq(n.parse_line(line), line)
        self.assertEqual(len(sent), 1)
        # the reply is lost: the board resends on its bound and gets the CACHED reply
        p.write("!idle"); line2 = p.read().rstrip("\n")
        self.assertEqual(line, line2); host.on_signreq(n.parse_line(line2), line2)
        self.assertEqual(len(sent), 2); self.assertEqual(sent[0], sent[1]); self.assertEqual(len(rl.entries), 1); self.assertEqual(rl.entries[0]["replays"], 1)
        p.write(sent[1])
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["ack_type"]), ("0", "2", "SIGNOK"))
        # a corrupted request draws SIGNGET and the resend is signed once
        rl = n.NotaryRelay(TOKEN, lambda req: {"commit": COMMIT, "expected_tables": TABLES, "tag": TAG}, drop_budget=8, clock=lambda: 0.0)
        sent = []; host = rel.SignHost(TOKEN, rl, send=sent.append, audit_seqs=set())
        p = Pipe(self.exe, self._sign_cmd())
        line = p.read().rstrip("\n"); broken = line[:-1] + ("0" if line[-1] != "0" else "1")
        host.on_broken_line(broken, "crc"); self.assertEqual(n.parse_line(sent[-1])["type"], rel.T_SIGNGET)
        p.write(sent[-1]); line2 = p.read().rstrip("\n"); self.assertEqual(line, line2)
        host.on_signreq(n.parse_line(line2), line2); p.write(sent[-1])
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["gets"]), ("0", "1")); self.assertEqual(len(rl.entries), 1)
        self.assertFalse(n.decode_payload(n.parse_line(sent[-1])["payload"])["audit_requested"])

    # ------------------------------------------------------------------ TERM
    def test_term_ack_get_bound_and_exhaustion(self):
        p = Pipe(self.exe, self._term_cmd())
        first = p.read(); f = n.parse_line(first)
        self.assertEqual(f["type"], n.T_TERM)
        summary = n.decode_payload(f["payload"])
        self.assertEqual(rel.closing_control_findings(summary), [])
        self.assertEqual(rel.closing_from_term(summary)["nonce_before"], "3" * 16)
        p.write(self.ack(rel.T_TERMGET, 3)); second = p.read(); self.assertEqual(first, second)
        p.write(self.ack(rel.T_TERMACK, 3))
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"], res["gets"]), ("0", "2", "1"))
        p = Pipe(self.exe, self._term_cmd())
        for _ in range(3):
            p.read(); p.write("!idle")
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"]), ("-1", "3")); self.assertIn("TERM_UNACKED", res["why"])

    def test_the_real_term_host_acknowledges_once_and_re_acknowledges_the_resend(self):
        delivered, sent = [], []
        host = rel.TermHost(TOKEN, deliver=delivered.append, send=sent.append)
        p = Pipe(self.exe, self._term_cmd())
        line = p.read().rstrip("\n"); host.on_term(n.parse_line(line), line)
        self.assertEqual(len(delivered), 1); self.assertEqual(n.parse_line(sent[-1])["type"], rel.T_TERMACK)
        p.write("!idle")                                              # the ACK was lost: the resend
        line2 = p.read().rstrip("\n"); self.assertEqual(line, line2)
        host.on_term(n.parse_line(line2), line2)
        self.assertEqual(len(delivered), 1); self.assertEqual(host.ledger.acks_sent, 2)
        p.write(sent[-1])
        res = p.finish("!tx ")
        self.assertEqual((res["rc"], res["attempts"]), ("0", "2"))

    def test_a_stopped_epochs_term_carries_no_closing_control(self):
        p = Pipe(self.exe, self._term_cmd(kind="STOPPED", reason="STOP_SIGN", closing_unsigned=0, closing_baseline=0))
        summary = n.decode_payload(n.parse_line(p.read())["payload"])
        self.assertNotIn("closing_control", summary); self.assertEqual(rel.closing_control_findings(summary), [])
        p.write(self.ack(rel.T_TERMACK, 3)); p.finish("!tx ")

    # ------------------------------------------------------------------ the pull
    def _pull(self, faults_done=0, lose_ready=0):
        p = Pipe(self.exe, f"pulltx token={TOKEN} seq=1")
        sent = []
        host = ap.PullHost(TOKEN, 1, send=sent.append, clock=lambda: 0.0)
        return p, host, sent

    def test_the_real_pull_host_pulls_a_clean_span(self):
        p, host, sent = self._pull()
        ready = p.read().rstrip("\n"); host.on_line(ready)
        while not host.done:
            p.write(sent[-1]); chunk = p.read().rstrip("\n"); host.on_line(chunk)
        p.write(sent[-1])                                             # AUDITDONE
        res = p.finish("!pull ")
        self.assertEqual((res["rc"], res["done"], res["ready_sent"], res["gets"], res["waits"]), ("0", "1", "1", "8", "0"))
        self.assertEqual(len(host.chunks()), 8)

    def test_a_lost_ready_is_resent_with_the_same_bytes_and_three_losses_give_up(self):
        p, host, sent = self._pull()
        first = p.read(); p.write("!idle"); second = p.read()
        self.assertEqual(first, second)
        host.on_line(second.rstrip("\n"))
        while not host.done:
            p.write(sent[-1]); host.on_line(p.read().rstrip("\n"))
        p.write(sent[-1])
        res = p.finish("!pull ")
        self.assertEqual((res["rc"], res["ready_sent"]), ("0", "2"))
        p, host, sent = self._pull()
        lines = [p.read()]
        for _ in range(2):
            p.write("!idle"); lines.append(p.read())
        self.assertEqual(len(set(lines)), 1)
        p.write("!idle")
        res = p.finish("!pull ")
        self.assertEqual((res["rc"], res["ready_sent"], res["aborted"]), ("-1", "3", "1")); self.assertIn("never asked", res["why"])

    def test_a_lost_done_draws_auditwait_and_the_replayed_done_completes_the_pull(self):
        p, host, sent = self._pull()
        host.on_line(p.read().rstrip("\n"))
        while not host.done:
            p.write(sent[-1]); host.on_line(p.read().rstrip("\n"))
        p.write("!idle")                                              # the DONE was lost
        wait = p.read().rstrip("\n"); fw = n.parse_line(wait)
        self.assertEqual(fw["type"], rel.T_AUDITWAIT); self.assertEqual(n.decode_payload(fw["payload"])["served"], 8)
        host.on_wait(); self.assertEqual(host.ledger.done_replays, 1)
        p.write(sent[-1])                                             # the same DONE again
        res = p.finish("!pull ")
        self.assertEqual((res["rc"], res["done"], res["waits"]), ("0", "1", "1"))

    def test_three_unanswered_waits_give_the_audit_up(self):
        p, host, sent = self._pull()
        host.on_line(p.read().rstrip("\n"))
        while not host.done:
            p.write(sent[-1]); host.on_line(p.read().rstrip("\n"))
        waits = []
        for _ in range(3):
            p.write("!idle"); waits.append(n.parse_line(p.read().rstrip("\n"))["type"])
        self.assertEqual(waits, [rel.T_AUDITWAIT] * 3)
        p.write("!idle")
        res = p.finish("!pull ")
        self.assertEqual((res["rc"], res["waits"], res["aborted"], res["done"]), ("-1", "3", "1", "0"))
        self.assertIn("no AUDITDONE arrived", res["why"])

    # ------------------------------------------------------------------ serialiser
    def test_the_indexed_heartbeat_and_the_stop_sign_record_validate(self):
        twin = wc.Twin(self.exe)
        hb, = twin(f"hb token={TOKEN} seq=4 i=15")
        f = n.parse_line(hb); self.assertEqual(n.decode_payload(f["payload"]), {"i": 15})
        rec, = twin(f"rec token={TOKEN} seq=6 genome={'0' * 80} outcome=STOP_SIGN sign_stop_attempts=3 "
                    f"sign_stop_why=STOP_SIGN:_no_ack")
        r = n.decode_payload(n.parse_line(rec)["payload"])
        self.assertEqual(r["outcome"], "STOP_SIGN"); self.assertEqual(list(r["evidence"]), ["sign_stop"])
        self.assertEqual(r["verified"], "replayed-only"); records.validate(r)
        term, = twin(f"term token={TOKEN} last_seq=6 closing_restore=1 closing_baseline=1 closing_unsigned=1 "
                     f"closing_nb={'3' * 16} closing_na={'4' * 16} closing_fault=13 closing_status=0x982")
        s = n.decode_payload(n.parse_line(term)["payload"])
        self.assertEqual(rel.closing_control_findings(s), []); self.assertEqual(s["closing_control"]["fault"], 13)
        records.validate(s)


if __name__ == "__main__":
    unittest.main()
