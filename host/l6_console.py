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
    (`bad_frames`); under `bad_frame_policy="crash"` (v0.6 and earlier) the collector's
    rule for it — `CRASHED` — is unchanged; under `bad_frame_policy="ledger"` (v0.7
    candidate, after S #2 2026-09-03-03) the line is in the ledger ONCE and goes no
    further: not acknowledged, not signed, no seq advanced, not the collector's — the
    transactions' own bounds recover (the board resends its REC / SIGNREQ / TERM on the
    bound), and `bad_frame_budget` is the terminal bound: the first bad frame past it
    ends the epoch `PROTOCOL_BAD_FRAME_BUDGET`, exactly as the D-s4 CRC budget does;
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


BAD_FRAME_CRASH = "crash"      # v0.6 and earlier: a malformed non-transaction line is the collector's CRASHED
BAD_FRAME_LEDGER = "ledger"    # v0.7 candidate: ledgered once, bounded by bad_frame_budget, never the collector's
BAD_FRAME_POLICIES = (BAD_FRAME_CRASH, BAD_FRAME_LEDGER)


class ConsoleSession:
    def __init__(self, token: str, collector: n.Collector, relay: n.NotaryRelay, timeline: lt.Timeline,
                 audit_seqs: set[int], crc_budget: int, send, reader=None, clock=None,
                 chunk_timeout_s: float = ap.CHUNK_TIMEOUT_S, protocol: str = "rec-v3", identity_check=None,
                 bad_frame_policy: str = BAD_FRAME_CRASH, bad_frame_budget: int | None = None):
        self.token, self.collector, self.relay, self.timeline = token, collector, relay, timeline
        self.audit_seqs, self.crc_budget, self.send = audit_seqs, crc_budget, send
        if bad_frame_policy not in BAD_FRAME_POLICIES:
            raise ValueError(f"bad_frame_policy {bad_frame_policy!r} is not one of {BAD_FRAME_POLICIES}")
        if bad_frame_policy == BAD_FRAME_LEDGER:
            if isinstance(bad_frame_budget, bool) or not isinstance(bad_frame_budget, int):
                raise ValueError("bad_frame_policy 'ledger' needs an integer bad_frame_budget (the terminal bound); "
                                 "unbounded tolerance of malformed lines is refused")
            if bad_frame_budget < 0:
                raise ValueError(f"bad_frame_budget {bad_frame_budget} is negative: the terminal bound must be >= 0")
        self.bad_frame_policy, self.bad_frame_budget = bad_frame_policy, bad_frame_budget
        # the protocol switch (owner 2026-09-02): rec-v3 is exactly what ran C1 #5; rel-v4
        # (host/l6_rel.py) adds the IDENT handshake, the SIGNREQ transaction with the
        # cached reply, AUDITWAIT replays, the TERM transaction and CLOSE-from-TERM. Every
        # rel-v4 branch below is guarded by `self.rel`; under rec-v3 none of it runs.
        import l6_rel as rel
        self.protocol = protocol
        self.rel = protocol == rel.PROTOCOL
        self.ident = self.signer = self.termhost = None
        self.last_pull: ap.PullHost | None = None
        self.linger_until: float | None = None    # rel-v4: read on after the TERM for the board's resends
        self.closing_conflict: dict | None = None  # rel-v4: CLOSE and TERM.closing_control disagree
        if self.rel:
            clk = clock or (reader.mono if reader is not None else None) or __import__("time").monotonic
            self.ident = rel.IdentHost(token, identity_check or (lambda ident: []), send=self._rel_send, clock=clk)
            self.signer = rel.SignHost(token, relay, send=self._rel_send, audit_seqs=audit_seqs, clock=clk)
            self.termhost = rel.TermHost(token, deliver=self._deliver_term, send=self._rel_send, clock=clk)
        # C1 #5 (owner's ruling 2026-09-02): the reader is the session's so a pull timeout can
        # quarantine a torn residue before the resend, and the reader's own resync fragments
        # reach the timeline; the clock arms the pull's monotonic deadline
        self.reader = reader
        self.clock = clock or (reader.mono if reader is not None else None) or __import__("time").monotonic
        self.chunk_timeout_s = chunk_timeout_s
        self.audit_sent_for: set[int] = set()
        # the host-paced pull (docs/l6_audit_pull_design.md): created on AUDIT_READY, fed
        # every line while pending, torn down on AUDITDONE/AUDITABORT; verified chunks go
        # to collector.audits, every failed attempt to `pull_ledgers`
        self.puller: ap.PullHost | None = None
        self._pulls: list[ap.PullHost] = []       # every settled pull; `pull_ledgers` renders them LIVE
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

    def _rel_send(self, line: str) -> None:
        f = n.parse_line(line)
        self.send(line, f["type"], f["seq"])

    @staticmethod
    def _pull_json(pl: ap.PullHost) -> dict:
        led = pl.ledger
        return {"seq": pl.seq, "done": pl.done, "failed": pl.failed, "why": pl.fail_reason,
                "attempts": led.attempts, "crc_dropped": led.crc_dropped, "timeouts": led.timeouts,
                "lines_kept": led.lines_kept, "duplicates": led.duplicates, "waits_seen": led.waits_seen,
                "done_replays": led.done_replays, "ready_dups": led.ready_dups,
                "waits_exhausted": led.waits_seen >= ap.DONE_REPLAY_MAX}

    @property
    def pull_ledgers(self) -> list[dict]:
        """Every settled pull's ledger, rendered from the LIVE objects at the time of the
        call (review 2026-09-02, item 1: a copy taken at settle time missed the AUDITWAIT
        replays that came after it)."""
        return [self._pull_json(pl) for pl in self._pulls]

    def lingering(self, now: float | None = None) -> bool:
        """rel-v4: after the first TERM the board may resend it (our TERMACK lost) for up to
        TERM_LINGER_S; the runner keeps reading that long so the resend is re-acknowledged
        (review 2026-09-02, item 3). Never under rec-v3."""
        if not self.rel or self.linger_until is None:
            return False
        return (self.clock() if now is None else now) < self.linger_until

    def _deliver_term(self, line: str) -> None:
        """rel-v4: the first CRC-valid TERM reaches the collector once; a lost CLOSE is
        reconstructed from the TERM's `closing_control` (marked source TERM); a CLOSE that
        did arrive is COMPARED with it (review 2026-09-02, item 7) — a disagreement is a
        recorded conflict the closure check turns into a finding."""
        import l6_rel as rel
        self.collector.on_line(line)
        self.linger_until = self.clock() + rel.TERM_LINGER_S
        summary = self.collector.session_summary
        if not isinstance(summary, dict):
            return
        cn = rel.closing_from_term(summary)
        have = self.collector.closing_negative
        if have is None:
            if cn is not None:
                self.collector.closing_negative = cn
        elif cn is not None:
            keys = ("fault", "kind", "status", "nonce_before", "nonce_after")
            if any(have.get(k) != cn.get(k) for k in keys):
                self.closing_conflict = {"close": {k: have.get(k) for k in keys}, "term": {k: cn.get(k) for k in keys}}

    def rel_ledgers_json(self) -> dict:
        """rel-v4's transaction ledgers for audits.json (empty under rec-v3)."""
        if not self.rel:
            return {}
        return {"ident": dict(self.ident.ledger.to_json(), refused=self.ident.refused, findings=list(self.ident.findings)),
                "signs": self.signer.ledgers_json(),
                "term": self.termhost.ledger.to_json() if self.termhost.ledger else None,
                "closing_conflict": self.closing_conflict}

    def _on_pull_timeout(self, seq: int, chunk: int) -> None:
        """The chunk deadline passed: whatever unterminated bytes the reader holds are a torn
        reply (C1 #5's 576 bytes) — quarantined now, never glued to the resend."""
        if self.reader is None:
            return
        self.reader.quarantine(f"pull timeout: seq {seq} chunk {chunk}")
        self.absorb_fragments()

    def absorb_fragments(self) -> None:
        """Every fragment the reader quarantined since the last call goes to the timeline."""
        if self.reader is None:
            return
        for frag in self.reader.take_fragments():
            self.timeline.note_fragment(frag)

    def _pull_settle(self) -> None:
        """After feeding the puller a line: harvest verified chunks, tear down when over."""
        pl = self.puller
        if pl is None:
            return
        for c in pl.chunks():
            if c not in self.collector.audits:
                self.collector.audits.append(c)
        if not pl.pending:
            self._pulls.append(pl)                     # rendered live by `pull_ledgers`
            self.last_pull = pl                        # rel-v4: AUDITWAIT may still ask for its DONE
            self.puller = None

    def tick(self, dt_s: float | None = None) -> None:
        """Once per runner loop: the reader's resync fragments into the ledger, the pull's
        monotonic deadline checked (`dt_s` is the old call shape, ignored)."""
        self.absorb_fragments()
        if self.puller is not None:
            self.puller.tick()
            self._pull_settle()

    def on_line(self, line: str, t_mono: float, t_wall: float) -> None:
        if self.ended:
            # after the end nothing is evidence — except, under rel-v4, the board's TERM
            # resend, which is re-acknowledged (not observed) so the board can halt
            if self.rel and line.startswith(n.MAGIC) and rx.head_fields(line)[0] == n.T_TERM:
                try:
                    f = n.parse_line(line)
                except n.CrcError:
                    self.termhost.on_broken_line(line, "crc"); return
                except n.FrameError:
                    self.termhost.on_broken_line(line, "malformed"); return
                if f["token"] == self.token:
                    self.termhost.on_term(f, line)
            return
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
            if self.rel and (self.ident.on_broken_line(line, "crc") or self.signer.on_broken_line(line, "crc")
                             or self.termhost.on_broken_line(line, "crc")):
                return                              # rel-v4: a broken IDENT is ledgered; SIGNREQ/TERM asked for again
            self._on_broken_line(line, "crc", t_mono)     # rec-v3: a broken REC is asked for again
            return
        except n.FrameError:
            # v0.7 candidate (S #2, 2026-09-03-03: an HB-shaped line glued to the tail of
            # REC 145 ended the epoch here, 0.2 s before the port closed, and the board's own
            # REC resend was never seen). The line is already in the ledger, ONCE
            # (`timeline.bad_frames`, counted by `Timeline.observe` for every shape). Under
            # the ledger policy it is not acknowledged, not signed, advances no seq and does
            # not refresh the collector's liveness; the transactions' own bounds recover.
            #
            # The budget is GLOBAL and immediate, exactly as the D-s4 CRC budget above is
            # (owner's review 2026-09-03, blocker 1: it used to sit AFTER the transaction
            # routing, so a REC/IDENT/SIGNREQ/TERM-shaped or in-pull malformed line escaped
            # it and a budget of 0 still drew a RECGET). Past the budget the global reason
            # wins: no transaction is advanced, no re-request is sent, and the failing line
            # stays in the ledgers that already hold it.
            over = (self.bad_frame_policy == BAD_FRAME_LEDGER
                    and self.timeline.bad_frames > self.bad_frame_budget)
            reason = f"PROTOCOL_BAD_FRAME_BUDGET: {self.timeline.bad_frames} > {self.bad_frame_budget}"
            if pulling:
                # the failing line is an ATTEMPT of the pull first — recorded and kept
                # verbatim in the pull's own ledger — before any budget consequence. Past
                # the bound the pull may still LEDGER it but must not ask again: the epoch
                # is over, and a retry after it would be exactly the misleading recovery
                # the owner refused, so the puller's sender is silenced for this line.
                if over:
                    outbound, self.puller.send = self.puller.send, lambda *_a, **_k: None
                    try:
                        self.puller.on_line(line)
                    finally:
                        self.puller.send = outbound
                    if self.puller.failed:
                        self.puller.fail_reason = reason
                    else:
                        self.puller._fail(reason)
                    self._pull_settle()
                    self._protocol_end(reason)
                    return
                self.puller.on_line(line)           # during a pull a malformed line is a retry, not CRASHED
                self._pull_settle()
                return
            if over:
                self._protocol_end(reason)          # the epoch is over: nothing after it is evidence
                return
            if rx.head_fields(line)[0] == n.T_REC and (
                    self.pending_rec_seq is not None or rx.head_fields(line)[1] == self.collector.last_rec_seq):
                self._on_broken_line(line, "malformed", t_mono)   # rec-v3: a merged/torn REC line is a retry
                return
            if self.rel and (self.ident.on_broken_line(line, "malformed") or self.signer.on_broken_line(line, "malformed")
                             or self.termhost.on_broken_line(line, "malformed")):
                return                              # rel-v4: a torn/merged IDENT/SIGNREQ/TERM is not the collector's CRASHED
            if self.bad_frame_policy == BAD_FRAME_LEDGER:
                return                              # ledgered, within the budget, and no transaction's
            self.collector.on_line(line)            # v0.6 and earlier: a malformed frame is CRASHED
            return
        if f["token"] != self.token:
            self.collector.on_line(line)            # a foreign token is the collector's refusal, never swallowed
            return
        if self.rel:
            import l6_rel as rel
            if f["type"] == n.T_IDENT:
                self.ident.on_line(line)            # verified before it is acknowledged; refused = no ack, no end
                if self.ident.protocol_end:         # a different second IDENT: channel misbehaviour
                    self._protocol_end(self.ident.protocol_end)
                    return
                self.collector.on_line(line)        # the declared identity is evidence either way
                return
            if f["type"] == rel.T_AUDITWAIT:
                pl = self.puller if (self.puller is not None and self.puller.seq == f["seq"]) else self.last_pull
                if pl is not None and pl.seq == f["seq"]:
                    self.collector.last_heard = self.collector.clock()
                    pl.on_wait()                    # the same DONE/ABORT again, bounded
                return
            if f["type"] == n.T_TERM:
                self.collector.last_heard = self.collector.clock()
                self.termhost.on_term(f, line)      # delivered once, acknowledged, re-acknowledged
                if self.termhost.protocol_end:
                    self._protocol_end(self.termhost.protocol_end)
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
            self.puller = ap.PullHost(self.token, f["seq"], send=self._pull_send, clock=self.clock,
                                      timeout_s=self.chunk_timeout_s, on_timeout=self._on_pull_timeout)
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
        if f["type"] == n.T_SIGNREQ and self.pending_rec_seq is not None and not (self.rel and f["seq"] == self.pending_rec_seq):
            # (rel-v4: a SIGNREQ resent for the SAME seq is the transaction asking for its
            # reply again, not the board advancing; a NEW seq over an outstanding record is)
            # rec-v3 closure: no new candidate is signed while a record is outstanding — the
            # board may not have moved on without our acknowledgement
            self._protocol_end(f"PROTOCOL_REC: SIGNREQ seq {f['seq']} while the record of seq "
                               f"{self.pending_rec_seq} is unacknowledged — the board advanced without an acknowledgement")
            return
        self.collector.on_line(line)
        if f["type"] != n.T_SIGNREQ:
            return
        if self.rel:
            if not self.ident.established:
                self._protocol_end("PROTOCOL_IDENT: a SIGNREQ " + ("after the identity was refused" if self.ident.refused
                                   else "before the identity handshake completed"))
                return
            self.signer.on_signreq(f, line)         # one signature per seq; a resend gets the cached reply
            if self.signer.protocol_end:
                self._protocol_end(self.signer.protocol_end)
            return
        if f["seq"] in self.audit_seqs and f["seq"] not in self.audit_sent_for:
            self.audit_sent_for.add(f["seq"])
            self.send(n.build_line(n.T_AUDITREQ, f["seq"], self.token, n.encode_payload({"seq": f["seq"]})),
                      n.T_AUDITREQ, f["seq"])
        reply = self.relay.handle_line(line)        # a well-formed SIGNREQ only: the relay never sees a CRC failure
        if reply is not None:
            self.send(reply, n.T_SIGNREF if f" {n.T_SIGNREF} " in reply else n.T_SIGNOK, f["seq"])
