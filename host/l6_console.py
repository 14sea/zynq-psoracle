#!/usr/bin/env python3
"""The L6 console session: one inbound ledger, one CRC authority (design review 2026-09-01).

What C1 #3 showed. `run_l6` parsed every inbound line before the relay and `continue`d on
any `CrcError`, so no CRC-failed frame of any type — a broken `SIGNREQ` included — ever
reached `NotaryRelay.handle_line()`, the only place that counted drops against the D-s4
budget; the summary reported the relay's count, always zero, while the timeline had
counted two. This module owns the per-line handling so that:

  * the `Timeline` is the ONE inbound ledger: every CRC-failed inbound frame is counted
    there exactly once, by frame type as far as the bytes allow; `crc_dropped` for the
    summary, the budget, the crashed summary and the soak checks is read from it alone;
  * the D-s4 budget is enforced HERE, for every frame type: the first drop past the budget
    ends the epoch `PROTOCOL` (`PROTOCOL_CRC_BUDGET: n > budget`) and nothing after it is
    evidence;
  * a `FrameError` (a malformed `P3L5` line) is NOT a CRC drop: it is counted apart
    (`bad_frames`) and the collector's rule for it — `CRASHED` — is unchanged;
  * the relay never sees a CRC-failed line, so it can neither count nor end on one; its
    own budget is set to the same number for the record but is not the authority.

`on_line()` is pure with respect to I/O: sending is a callback, so a test can drive a whole
session's lines through the real Timeline, Collector and NotaryRelay.

rec-v3 (owner's batch after S #1, 2026-09-01): the loop record is a TRANSACTION
(host/l6_rec.py). This session is the host side of it, against the real Collector:

  * `pending_rec_seq` — the current candidate: the seq whose sign exchange the relay
    answered and whose record has not been accepted; only ITS record is acknowledged;
  * an accepted REC → `RECACK`; a CRC-failed or malformed line whose head reads
    `REC <pending>` → `RECGET` (bounded; the board's own wait is the authority beyond);
  * a byte-identical duplicate of the accepted record → re-`RECACK`, appended never; the
    same seq with other content → PROTOCOL; a REC for any other seq, or a SIGNREQ while a
    record is outstanding → PROTOCOL ("the board advanced without an acknowledgement");
  * every attempt, the original broken line included, is in the one inbound ledger (the
    Timeline) AND in the per-seq REC ledger (`rec_ledgers`, raw lines kept verbatim);
  * a malformed REC-shaped line during the pending window is a retry, not the collector's
    CRASHED; outside a transaction the collector's rules are unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_rec as rx  # noqa: E402
import l6_timing as lt  # noqa: E402


class ConsoleSession:
    def __init__(self, token: str, collector: n.Collector, relay: n.NotaryRelay, timeline: lt.Timeline,
                 audit_seqs: set[int], crc_budget: int, send):
        self.token, self.collector, self.relay, self.timeline = token, collector, relay, timeline
        self.audit_seqs, self.crc_budget, self.send = audit_seqs, crc_budget, send
        self.audit_sent_for: set[int] = set()
        # the host-paced pull (docs/l6_audit_pull_design.md): created on AUDIT_READY, fed
        # every line while pending, torn down on AUDITDONE/AUDITABORT; verified chunks go
        # to collector.audits, every failed attempt to `pull_ledgers`
        self.puller: ap.PullHost | None = None
        self.pull_ledgers: list[dict] = []
        # rec-v3: the REC transaction's host side (host/l6_rec.py): the accepted payload per
        # seq (idempotence is judged on the bytes) and a ledger per seq
        self.rec_payloads: dict[int, str] = {}
        self.rec_ledgers: dict[int, rx.RecLedger] = {}

    @property
    def crc_dropped(self) -> int:
        """The one number: every CRC-failed inbound frame, counted once, all types."""
        return self.timeline.crc_dropped

    @property
    def ended(self) -> bool:
        return self.collector.epoch_end is not None

    @property
    def pending_rec_seq(self) -> int | None:
        """The current candidate: its sign exchange was answered, its record not yet
        accepted. None between an accepted record and the next SIGNREQ."""
        s = self.relay.last_seq
        return s if s > self.collector.last_rec_seq else None

    def rec_ledgers_json(self) -> list[dict]:
        return [self.rec_ledgers[s].to_json() for s in sorted(self.rec_ledgers)]

    def _rec_ledger(self, seq: int) -> rx.RecLedger:
        return self.rec_ledgers.setdefault(seq, rx.RecLedger(seq))

    def _rec_tx(self, mtype: str, seq: int) -> None:
        self.send(n.build_line(mtype, seq, self.token, n.encode_payload({"seq": seq})), mtype, seq)

    def _protocol_end(self, reason: str) -> None:
        self.collector.epoch_end = {"kind": "PROTOCOL", "last_seq": self.collector.last_rec_seq, "reason": reason}

    def _on_broken_rec(self, line: str, outcome: str, t_mono: float) -> None:
        """A REC-shaped line for the pending candidate that did not verify: ask for it again
        (bounded). The line itself is already in the Timeline's ledger."""
        seq = self.pending_rec_seq
        led = self._rec_ledger(seq)
        led.note(outcome, line, t_mono)
        if led.gets_sent < rx.REC_HOST_MAX_GETS:
            led.gets_sent += 1
            self._rec_tx(rx.T_RECGET, seq)

    def _on_broken_line(self, line: str, outcome: str, t_mono: float) -> None:
        """CRC-failed or malformed: if it reads as the pending candidate's REC, a retry; if it
        reads as a corrupted RESEND of the record already accepted (the board resent because
        our RECACK was lost), it is ALSO asked for again — a broken line cannot be known to be
        the byte-identical duplicate that alone earns a RECACK (review 2026-09-02, blocker 2);
        the next CRC-valid resend is then compared with the accepted payload in `_on_rec`:
        equal → RECACK, different → PROTOCOL_REC. Anything else is not the transaction's."""
        t, s = rx.head_fields(line)
        if t != n.T_REC:
            return
        pending = self.pending_rec_seq
        if pending is not None and (s is None or s == pending):
            self._on_broken_rec(line, outcome, t_mono)
        elif s is not None and s == self.collector.last_rec_seq and s in self.rec_payloads:
            led = self._rec_ledger(s)
            led.note(outcome, line, t_mono)
            if led.gets_sent < rx.REC_HOST_MAX_GETS:
                led.gets_sent += 1
                self._rec_tx(rx.T_RECGET, s)

    def _on_rec(self, f: dict, line: str, t_mono: float) -> None:
        seq, pending = f["seq"], self.pending_rec_seq
        if seq == self.collector.last_rec_seq and seq in self.rec_payloads:
            led = self._rec_ledger(seq)
            if f["payload"] == self.rec_payloads[seq]:
                led.note("duplicate", line, t_mono)             # our RECACK was lost: say it again
                if led.acks_sent < rx.REC_MAX_ATTEMPTS:
                    led.acks_sent += 1
                    self._rec_tx(rx.T_RECACK, seq)
            else:
                led.note("conflict", line, t_mono)
                led.conflict = True
                self._protocol_end(f"PROTOCOL_REC: seq {seq} arrived twice with different content")
            return
        if pending is None or seq != pending or seq != self.collector.last_rec_seq + 1:
            self._protocol_end(f"PROTOCOL_REC: REC seq {seq} after {self.collector.last_rec_seq}"
                               + (f" while seq {pending} is the current candidate" if pending is not None
                                  else " with no candidate pending")
                               + " — the board advanced without an acknowledgement")
            return
        try:
            rec = n.decode_payload(f["payload"])
        except Exception:  # noqa: BLE001 — a CRC-valid line whose payload does not decode: ask again
            self._on_broken_rec(line, "malformed", t_mono)
            return
        if not isinstance(rec, dict) or rec.get("seq") != seq:
            self._on_broken_rec(line, "malformed", t_mono)
            return
        self.collector.on_line(line)                       # accepted ONCE; content is the validator's
        if self.collector.last_rec_seq == seq:
            self.rec_payloads[seq] = f["payload"]
            led = self._rec_ledger(seq)
            led.accepted = True
            led.note("ok", None, t_mono)
            led.acks_sent += 1
            self._rec_tx(rx.T_RECACK, seq)

    def _pull_send(self, line: str) -> None:
        f = n.parse_line(line)
        self.send(line, f["type"], f["seq"])

    def _pull_settle(self) -> None:
        """After feeding the puller a line: harvest verified chunks, tear down when over."""
        pl = self.puller
        if pl is None:
            return
        for c in pl.chunks():
            if c not in self.collector.audits:
                self.collector.audits.append(c)
        if not pl.pending:
            self.pull_ledgers.append({"seq": pl.seq, "done": pl.done, "failed": pl.failed, "why": pl.fail_reason,
                                      "attempts": pl.ledger.attempts, "crc_dropped": pl.ledger.crc_dropped,
                                      "timeouts": pl.ledger.timeouts, "lines_kept": pl.ledger.lines_kept})
            self.puller = None

    def tick(self, dt_s: float) -> None:
        if self.puller is not None:
            self.puller.tick(dt_s)
            self._pull_settle()

    def on_line(self, line: str, t_mono: float, t_wall: float) -> None:
        if self.ended:
            return                                  # after the end nothing is evidence
        self.timeline.observe(line, t_mono, t_wall)   # the ledger: frames, CRC drops, bad frames
        if not line.startswith(n.MAGIC):
            return                                  # console noise
        pulling = self.puller is not None and self.puller.pending
        try:
            f = n.parse_line(line)
        except n.CrcError:
            # counted by the ledger above; the budget is enforced here for EVERY type
            over = self.timeline.crc_dropped > self.crc_budget
            if pulling:
                # blocker 3: the failing line is an ATTEMPT of the pull first — recorded and
                # kept verbatim in the pull's own ledger — before any budget consequence
                self.puller.on_line(line)
                if over:
                    # The GLOBAL CRC authority wins the termination reason, even when the
                    # puller has just failed itself on retry exhaustion for the same line:
                    # the epoch's PROTOCOL reason and pulls[].why must be the same fact.
                    # The attempts and their raw lines are already in the ledger; _fail is
                    # idempotent, so at most ONE AUDITABORT ever goes to the board.
                    reason = f"PROTOCOL_CRC_BUDGET: {self.timeline.crc_dropped} > {self.crc_budget}"
                    if self.puller.failed:
                        self.puller.fail_reason = reason
                    else:
                        self.puller._fail(reason)
                self._pull_settle()
            if over:
                self.collector.epoch_end = {"kind": "PROTOCOL", "last_seq": self.collector.last_rec_seq,
                                            "reason": f"PROTOCOL_CRC_BUDGET: {self.timeline.crc_dropped} > {self.crc_budget}"}
                return
            self._on_broken_line(line, "crc", t_mono)     # rec-v3: a broken REC is asked for again
            return
        except n.FrameError:
            if pulling:
                self.puller.on_line(line)           # during a pull a malformed line is a retry, not CRASHED
                self._pull_settle()
                return
            if rx.head_fields(line)[0] == n.T_REC and (
                    self.pending_rec_seq is not None or rx.head_fields(line)[1] == self.collector.last_rec_seq):
                self._on_broken_line(line, "malformed", t_mono)   # rec-v3: a merged/torn REC line is a retry
                return
            self.collector.on_line(line)            # its rule: a malformed frame is CRASHED
            return
        if f["token"] != self.token:
            self.collector.on_line(line)            # a foreign token is the collector's refusal, never swallowed
            return
        if f["type"] == ap.T_READY and self.puller is None:
            # Transaction authority (whole-package review, blocker 1): a READY does not
            # authorise itself. The only candidate that may announce an audit is the one
            # whose sign exchange the relay just answered and whose record has not yet
            # arrived; any other READY is channel misbehaviour and ends the epoch PROTOCOL.
            expected = self.relay.last_seq
            if f["seq"] != expected or expected <= self.collector.last_rec_seq:
                self.collector.epoch_end = {"kind": "PROTOCOL", "last_seq": self.collector.last_rec_seq,
                                            "reason": f"PROTOCOL_PULL: AUDIT_READY for seq {f['seq']}, "
                                                      f"the current candidate is {expected}"}
                return
            self.collector.last_heard = self.collector.clock()   # valid pull traffic is liveness
            self.puller = ap.PullHost(self.token, f["seq"], send=self._pull_send)
            self.puller.on_line(line)
            self._pull_settle()
            return
        if pulling and f["type"] in (n.T_AUDIT, ap.T_READY):
            self.collector.last_heard = self.collector.clock()   # blocker 2: chunks + retries can
            self.puller.on_line(line)               # outlast 30 s and are not silence
            self._pull_settle()
            return
        if f["type"] == n.T_REC:
            self.collector.last_heard = self.collector.clock()
            self._on_rec(f, line, t_mono)           # rec-v3: accept once, acknowledge, never append twice
            return
        if f["type"] == n.T_SIGNREQ and self.pending_rec_seq is not None:
            # rec-v3 closure: no new candidate is signed while a record is outstanding — the
            # board may not have moved on without our acknowledgement
            self._protocol_end(f"PROTOCOL_REC: SIGNREQ seq {f['seq']} while the record of seq "
                               f"{self.pending_rec_seq} is unacknowledged — the board advanced without an acknowledgement")
            return
        self.collector.on_line(line)
        if f["type"] != n.T_SIGNREQ:
            return
        if f["seq"] in self.audit_seqs and f["seq"] not in self.audit_sent_for:
            self.audit_sent_for.add(f["seq"])
            self.send(n.build_line(n.T_AUDITREQ, f["seq"], self.token, n.encode_payload({"seq": f["seq"]})),
                      n.T_AUDITREQ, f["seq"])
        reply = self.relay.handle_line(line)        # a well-formed SIGNREQ only: the relay never sees a CRC failure
        if reply is not None:
            self.send(reply, n.T_SIGNREF if f" {n.T_SIGNREF} " in reply else n.T_SIGNOK, f["seq"])
