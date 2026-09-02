#!/usr/bin/env python3
"""rel-v4 — the reliability revision of the P3 wire protocol, HOST SIDE and BOARD TWINS
(`docs/l6_frame_reliability_design.md`; owner's ruling 2026-09-02: host state machines,
caches, validator and twin models first, behind a protocol switch, rec-v3 unchanged; the
firmware batch only after this batch is reviewed). Nothing here runs on the board; the
board classes are the twins the C code must match (the same pattern as `l6_rec.py` and
`l6_audit_pull.PullBoard`).

Every board→host frame becomes re-requestable, reconstructible or budgeted:

    IDENT        board → host, then WAIT for IDENTACK {seq 0}; resent on the bound, ≤ 3;
                 exhausted → STOP_IDENT (TERM, no SIGNREQ). The host acknowledges ONLY an
                 identity it verified; the handshake completes BEFORE the first SIGNREQ
                 (a SIGNREQ with no established identity is PROTOCOL_IDENT).
    SIGNREQ      a transaction: the board waits bounded for SIGNOK/SIGNREF; on SIGNGET
                 {seq} or the bound it resends the SAME bytes, ≤ 3; exhausted → STOP_SIGN
                 (a terminal record; §5). The host: a broken SIGNREQ-shaped line for the
                 expected seq → SIGNGET; a byte-identical duplicate → the CACHED reply
                 replayed (no second signature, no nonce step; the notary entry counts
                 replays); a same-seq SIGNREQ with other bytes → PROTOCOL_SIGN.
    AUDITREQ     no longer a frame: `audit_requested` rides in the SIGNOK payload.
    AUDIT_READY  resent on the board's idle bound while no AUDITGET was seen, ≤ 3, then the
                 pull aborts as before; a duplicate READY is ignored by a pending pull.
    AUDITDONE    a completion handshake: after the last chunk the board waits bounded for
                 AUDITDONE/AUDITABORT; on its bound it sends AUDITWAIT {seq, served} and
                 the host REPLAYS the same DONE/ABORT line, ≤ 3; exhausted → the board gives
                 the audit up exactly as today (a SCORED-path pull without DONE is
                 STOP_AUDIT, no ARM; a non-SCORED path keeps its outcome, replayed-only) —
                 and the host, having counted the WAIT_MAX announcements, marks the pull
                 `unconfirmed`, so the two sides disagree by design and visibly, never
                 silently.
    HB           carries its index {i: 0..15}; a lost heartbeat is identified, a duplicate
                 harmless; missing heartbeats are budgeted (`hb_missing_budget`).
    CLOSE        still sent; its fields also ride in TERM (`closing_control`), so a lost
                 CLOSE is reconstructed from the (re-requestable) TERM.
    TERM         a transaction: TERMACK / TERMGET, the same bytes, ≤ 3; then the board halts.

The board bounds are COUNTS of RX polls in C (`P3_*_IDLE_POLLS`), modelled here as
seconds; the host bounds are counts of lines sent.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_reader as lrd  # noqa: E402
from l6_rec import head_fields  # noqa: E402

PROTOCOL = "rel-v4"
T_IDENTACK, T_SIGNGET, T_TERMACK, T_TERMGET = "IDENTACK", "SIGNGET", "TERMACK", "TERMGET"
T_AUDITWAIT = "AUDITWAIT"
HOST_TYPES = (T_IDENTACK, T_SIGNGET, T_TERMACK, T_TERMGET)
BOARD_TYPES = (T_AUDITWAIT,)
MAX_ATTEMPTS = 3                  # board: first transmission + two resends (IDENT, SIGNREQ, AUDIT_READY, TERM)
WAIT_MAX = 3                      # board: AUDITWAIT announcements before giving the audit up
HOST_MAX_GETS = 2                 # host: SIGNGET / TERMGET per seq
HOST_MAX_REPLAYS = MAX_ATTEMPTS   # host: cached-reply replays, DONE replays, re-ACKs per seq
# The board's idle bound before a resend is a COUNT of RX polls in C (`P3_*_IDLE_POLLS`).
# The host's linger after the first TERM assumes an upper bound on that count's WALL time,
# so the relation is a contract the firmware batch must prove (review 2026-09-02, item 4):
#   every rel-v4 wait bound (IDENT, SIGNREQ, AUDIT_READY, AUDITWAIT, REC, TERM) ≤
#   BOARD_BOUND_WALL_MAX_S of wall-clock on the pinned clocks (CPU 6:2:1, the poll loop's
#   measured cost), pinned as a poll count in the image and shown by a source-audit test and
#   the C twin's timing; TERM_LINGER_S is derived from it, never the other way round.
BOARD_BOUND_WALL_MAX_S = 10.0     # contract: the wall-time upper bound of one board bound
BOARD_BOUND_S = BOARD_BOUND_WALL_MAX_S   # the twins model the bound at its upper bound
LINGER_MARGIN_S = 2.0
# host: after the first TERM the runner keeps reading for the board's possible resends (our
# TERMACK may have been lost): two more transmissions, one bound apart, plus a margin
TERM_LINGER_S = (MAX_ATTEMPTS - 1) * BOARD_BOUND_WALL_MAX_S + LINGER_MARGIN_S
FIRMWARE_BOUND_CONTRACT = {
    "poll_bound_wall_max_s": BOARD_BOUND_WALL_MAX_S,
    "applies_to": ("P3_IDENT_IDLE_POLLS", "P3_SIGN_IDLE_POLLS", "P3_PULL_IDLE_POLLS", "P3_REC_IDLE_POLLS", "P3_TERM_IDLE_POLLS"),
    "proof": "firmware batch: the poll count pinned in the image, its wall time on the pinned clocks bounded in a "
             "source-audit test (tests/test_firmware_audit.py) and measured by the C twin; the host derives "
             "TERM_LINGER_S = (MAX_ATTEMPTS - 1) * poll_bound_wall_max_s + LINGER_MARGIN_S",
}
CLOSING_CONTROL_FIELDS = ("fault", "kind", "status", "nonce_before", "nonce_after")
HB_PER_RECORD = 16
STOP_IDENT, STOP_SIGN = "STOP_IDENT", "STOP_SIGN"
# a broken line whose head reads as one of these is asked for again by the host
GETTABLE = {n.T_SIGNREQ: T_SIGNGET, n.T_TERM: T_TERMGET}


def hb_missing_budget(scored_records: int) -> int:
    """The preregistered bound on missing heartbeats over a session: floor(R / 1000) with
    R = the number of SCORED records (the records the protocol fixes 16 HB for). With at
    most one heartbeat missing per record (`heartbeat_findings_rel`) this means: at least
    99.9 % of the SCORED records carry all 16 heartbeats (NOT "99.9 % of the 16 R frames"
    — review 2026-09-02); rounded DOWN, so a 64-candidate calibration (R = 66) tolerates
    none and a 2 h soak (R ≈ 6541) tolerates 6."""
    if scored_records < 0:
        raise ValueError("scored_records must be >= 0")
    return math.floor(scored_records / 1000)


def hb_line(token: str, seq: int, i: int) -> str:
    return n.build_line(n.T_HB, seq, token, n.encode_payload({"i": i}))


def _payload(f: dict) -> dict:
    return n.decode_payload(f["payload"]) if f["payload"] != "-" else {}


# ------------------------------------------------------------------ the boards (twins)


class ResendBoard:
    """The firmware's bounded resend for one frame: send, wait for an acknowledging type
    (or a re-request), resend the SAME bytes on the re-request or the bound, give up after
    MAX_ATTEMPTS. IDENT, SIGNREQ and TERM are instances; `p3_rectx.c` is the C shape."""

    def __init__(self, token: str, seq: int, line: str, ack_types: tuple, get_types: tuple, stop_name: str):
        self.token, self.seq = token, seq
        self.line = line if line.endswith("\n") else line + "\n"
        self.ack_types, self.get_types, self.stop_name = ack_types, get_types, stop_name
        self.attempts = 0
        self.state = "IDLE"            # IDLE → WAIT_ACK → DONE | EXHAUSTED
        self.idle_s = 0.0
        self.acked = False
        self.ack_frame: dict | None = None
        self.why = ""

    def start(self) -> list[str]:
        return self._send()

    def _send(self) -> list[str]:
        if self.attempts >= MAX_ATTEMPTS:
            self.state, self.why = "EXHAUSTED", f"{self.stop_name}: no acknowledgement after {MAX_ATTEMPTS} attempts"
            return []
        self.attempts += 1
        self.state, self.idle_s = "WAIT_ACK", 0.0
        return [self.line]

    def on_host_line(self, line: str) -> list[str]:
        if self.state != "WAIT_ACK":
            return []
        try:
            f = n.parse_line(line)
        except (n.CrcError, n.FrameError):
            return []                              # a broken host line: keep waiting, within the bound
        if f["token"] != self.token or f["seq"] != self.seq:
            return []
        try:
            p = _payload(f)
        except Exception:  # noqa: BLE001
            return []
        if p.get("seq", self.seq) != self.seq:
            return []
        if f["type"] in self.ack_types:
            self.acked, self.state, self.ack_frame = True, "DONE", {"type": f["type"], "payload": p}
            return []
        if f["type"] in self.get_types:
            return self._send()
        return []

    def tick(self, dt_s: float) -> list[str]:
        if self.state != "WAIT_ACK":
            return []
        self.idle_s += dt_s
        if self.idle_s > BOARD_BOUND_S:
            return self._send()
        return []

    def finish(self) -> dict:
        if self.state == "WAIT_ACK":
            raise RuntimeError("finish() before the transaction ended")
        return {"acked": self.acked, "attempts": self.attempts, "why": self.why}


class IdentBoard(ResendBoard):
    def __init__(self, token: str, ident_line: str):
        super().__init__(token, 0, ident_line, (T_IDENTACK,), (), STOP_IDENT)


class SignBoard(ResendBoard):
    """After the ack: `reply_type`, `reply` (the payload) and `audit_requested` (from the
    SIGNOK payload — no separate AUDITREQ frame under rel-v4)."""

    def __init__(self, token: str, seq: int, signreq_line: str):
        super().__init__(token, seq, signreq_line, (n.T_SIGNOK, n.T_SIGNREF), (T_SIGNGET,), STOP_SIGN)

    @property
    def reply_type(self) -> str | None:
        return self.ack_frame["type"] if self.ack_frame else None

    @property
    def audit_requested(self) -> bool:
        return bool(self.ack_frame and self.ack_frame["type"] == n.T_SIGNOK and self.ack_frame["payload"].get("audit_requested"))


class TermBoard(ResendBoard):
    def __init__(self, token: str, seq: int, term_line: str):
        super().__init__(token, seq, term_line, (T_TERMACK,), (T_TERMGET,), "TERM_UNACKED")


class ReadyBoard(ap.PullBoard):
    """`PullBoard` plus rel-v4: AUDIT_READY resent on the idle bound while no AUDITGET was
    seen (≤ MAX_ATTEMPTS), and after the last chunk a bounded wait for AUDITDONE/ABORT
    with AUDITWAIT announcements (≤ WAIT_MAX) before the audit is given up."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.ready_line: str | None = None
        self.ready_sent = 0
        self.gets_seen = 0
        self.waits_sent = 0

    def start(self) -> list[str]:
        lines = super().start()
        if lines:
            self.ready_line, self.ready_sent = lines[0], 1
        return lines

    def on_host_line(self, line: str) -> list[str]:
        before = self.state
        out = super().on_host_line(line)
        if out:
            self.gets_seen += 1
        if before == "PULL" and self.state == "PULL" and out:
            # the last chunk served: the pull is complete on our side, DONE is what we wait for
            if len(self.served) == ap.au.sparse_chunk_count(len(self.words)) and all(
                    c in self.served for c in range(ap.au.sparse_chunk_count(len(self.words)))):
                self.idle_s = 0.0
        return out

    def _all_served(self) -> bool:
        chunks = ap.au.sparse_chunk_count(len(self.words))
        return all(c in self.served for c in range(chunks))

    def tick(self, dt_s: float) -> list[str]:
        if self.state != "PULL":
            return []
        self.idle_s += dt_s
        if self.idle_s <= ap.BOARD_IDLE_LIMIT_S:
            return []
        self.idle_s = 0.0
        if self.gets_seen == 0 and self.ready_line is not None and self.ready_sent < MAX_ATTEMPTS:
            self.ready_sent += 1
            return [self.ready_line]                       # the announcement may have been lost
        if self._all_served() and self.waits_sent < WAIT_MAX:
            self.waits_sent += 1
            return [n.build_line(T_AUDITWAIT, self.seq, self.token,
                                 n.encode_payload({"seq": self.seq, "served": len(self.served)}))]
        self._abort()
        return []


# ------------------------------------------------------------------ the hosts


@dataclass
class Ledger:
    seq: int
    attempts: list[dict] = field(default_factory=list)
    lines_kept: list[str] = field(default_factory=list)
    gets_sent: int = 0
    acks_sent: int = 0
    replays: int = 0
    accepted: bool = False
    conflict: bool = False

    def note(self, outcome: str, line: str | None = None, t: float | None = None) -> None:
        self.attempts.append({"attempt": len(self.attempts) + 1, "outcome": outcome, "t_mono": t})
        if line is not None:
            self.lines_kept.append(line.rstrip("\n"))

    def to_json(self) -> dict:
        return {"seq": self.seq, "attempts": list(self.attempts), "lines_kept": list(self.lines_kept),
                "gets_sent": self.gets_sent, "acks_sent": self.acks_sent, "replays": self.replays,
                "accepted": self.accepted, "conflict": self.conflict}


class IdentHost:
    """The IDENT handshake: the first valid IDENT is verified (`verify(identity) -> list of
    findings`); with no finding it is acknowledged and the identity established; a
    byte-identical repeat is re-acknowledged (bounded); a different IDENT, or a finding,
    ends the epoch PROTOCOL_IDENT with NO acknowledgement (the board exhausts → STOP_IDENT)."""

    def __init__(self, token: str, verify, send, clock=lambda: 0.0):
        self.token, self.verify, self.send, self.clock = token, verify, send, clock
        self.ledger = Ledger(0)
        self.payload: str | None = None
        self.identity: dict | None = None
        self.findings: list[str] = []
        self.refused = False               # verified and found wanting: no ack, the board exhausts → STOP_IDENT
        self.protocol_end: str | None = None   # channel misbehaviour only (a different second IDENT)

    @property
    def established(self) -> bool:
        return self.identity is not None and self.protocol_end is None and not self.refused

    def on_broken_line(self, line: str, outcome: str) -> bool:
        """A CRC-failed or malformed line whose head reads IDENT: in the ledger, no ack —
        the board resends on its bound (there is nothing to ask for). True if it was one."""
        t, _ = head_fields(line)
        if t != n.T_IDENT:
            return False
        self.ledger.note(outcome, line, self.clock())
        return True

    def _ack(self) -> None:
        if self.ledger.acks_sent < HOST_MAX_REPLAYS:
            self.ledger.acks_sent += 1
            self.send(n.build_line(T_IDENTACK, 0, self.token, n.encode_payload({"seq": 0})))

    def on_line(self, line: str) -> None:
        if self.protocol_end is not None:
            return
        try:
            f = n.parse_line(line)
        except n.CrcError:
            self.on_broken_line(line, "crc"); return
        except n.FrameError:
            self.on_broken_line(line, "malformed"); return
        if f["token"] != self.token or f["type"] != n.T_IDENT:
            return
        if self.refused:
            # still no ack; the board will exhaust — but only a byte-identical repeat is the
            # board's resend (review 2026-09-02): other bytes are a different IDENT, a conflict
            if f["payload"] == self.payload:
                self.ledger.note("refused-repeat", None, self.clock())
            else:
                self.ledger.note("conflict", line, self.clock()); self.ledger.conflict = True
                self.protocol_end = "PROTOCOL_IDENT: a second, different IDENT after a refusal"
            return
        if self.payload is not None:
            if f["payload"] == self.payload:
                self.ledger.note("duplicate", None, self.clock())
                self._ack()
            else:
                self.ledger.note("conflict", line, self.clock()); self.ledger.conflict = True
                self.protocol_end = "PROTOCOL_IDENT: a second, different IDENT"
            return
        try:
            ident = _payload(f)
        except Exception:  # noqa: BLE001
            self.ledger.note("malformed", line, self.clock())
            return
        findings = list(self.verify(ident) or [])
        if findings:
            # verified and found wanting: NO acknowledgement, and no epoch end from the host
            # (review 2026-09-02, item 4): the board resends, exhausts, and stops itself
            # with STOP_IDENT — its TERM ends the epoch; the findings are the HOLD
            self.findings, self.refused, self.identity, self.payload = findings, True, ident, f["payload"]
            self.ledger.note("refused", line, self.clock())
            return
        self.payload, self.identity = f["payload"], ident
        self.ledger.accepted = True
        self.ledger.note("ok", None, self.clock())
        self._ack()


class SignHost:
    """The host side of the SIGNREQ transaction over the relay. `relay_handle(line)` is
    `NotaryRelay.handle_line`: called ONCE per seq; its reply is cached and replayed for a
    byte-identical resend (the notary entry gains `replays`); `audit_seqs` decides the
    `audit_requested` field folded into SIGNOK. `expected_seq` is the relay's last + 1."""

    def __init__(self, token: str, relay, send, audit_seqs: set[int], clock=lambda: 0.0):
        self.token, self.relay, self.send, self.audit_seqs, self.clock = token, relay, send, audit_seqs, clock
        self.cache: dict[int, tuple[str, str]] = {}         # seq → (request payload, reply line)
        self.ledgers: dict[int, Ledger] = {}
        self.protocol_end: str | None = None

    @property
    def expected_seq(self) -> int:
        return self.relay.last_seq + 1

    def _ledger(self, seq: int) -> Ledger:
        return self.ledgers.setdefault(seq, Ledger(seq))

    def ledgers_json(self) -> list[dict]:
        return [self.ledgers[s].to_json() for s in sorted(self.ledgers)]

    def _get(self, seq: int) -> None:
        led = self._ledger(seq)
        if led.gets_sent < HOST_MAX_GETS:
            led.gets_sent += 1
            self.send(n.build_line(T_SIGNGET, seq, self.token, n.encode_payload({"seq": seq})))

    def on_broken_line(self, line: str, outcome: str) -> bool:
        """A CRC-failed/malformed line whose head reads SIGNREQ for the expected seq (or an
        unreadable seq): ask for it again. Returns True when it was this transaction's."""
        t, s = head_fields(line)
        if t != n.T_SIGNREQ or (s is not None and s != self.expected_seq):
            return False
        self._ledger(self.expected_seq).note(outcome, line, self.clock())
        self._get(self.expected_seq)
        return True

    def _fold_audit(self, reply_line: str, seq: int) -> str:
        f = n.parse_line(reply_line)
        if f["type"] != n.T_SIGNOK:
            return reply_line
        p = _payload(f)
        p["audit_requested"] = seq in self.audit_seqs
        return n.build_line(n.T_SIGNOK, seq, self.token, n.encode_payload(p))

    def on_signreq(self, f: dict, line: str) -> str | None:
        """A CRC-valid SIGNREQ frame (token already checked). Returns the reply line sent
        (new or replayed), or None (protocol end / nothing sent)."""
        if self.protocol_end is not None:
            return None
        seq = f["seq"]
        cached = self.cache.get(seq)
        if cached is not None:
            req_payload, reply_line = cached
            led = self._ledger(seq)
            if f["payload"] == req_payload:
                if led.replays < HOST_MAX_REPLAYS:
                    led.replays += 1
                    led.note("duplicate", None, self.clock())
                    self.send(reply_line)
                    for e in self.relay.entries:
                        if e["seq"] == seq:
                            e["replays"] = e.get("replays", 0) + 1
                    return reply_line
                led.note("duplicate-unanswered", None, self.clock())
                return None
            led.note("conflict", line, self.clock()); led.conflict = True
            self.protocol_end = f"PROTOCOL_SIGN: seq {seq} signed once, then requested again with other content"
            return None
        if seq != self.expected_seq:
            self.protocol_end = f"PROTOCOL_SEQ: SIGNREQ {seq}, expected {self.expected_seq}"
            return None
        reply = self.relay.handle_line(line)               # exactly one signature per seq
        led = self._ledger(seq)
        if reply is None:
            led.note("unanswered", line, self.clock())
            return None
        reply = self._fold_audit(reply, seq)
        self.cache[seq] = (f["payload"], reply)
        led.accepted = True
        led.note("ok", None, self.clock())
        self.send(reply)
        return reply


class TermHost:
    """TERM as a transaction: the first CRC-valid TERM is delivered once (`deliver(line)`)
    and acknowledged; a byte-identical repeat re-acknowledged (bounded); a broken
    TERM-shaped line draws TERMGET (bounded); different content is PROTOCOL_TERM."""

    def __init__(self, token: str, deliver, send, clock=lambda: 0.0):
        self.token, self.deliver, self.send, self.clock = token, deliver, send, clock
        self.ledger: Ledger | None = None
        self.payload: str | None = None
        self.seq: int | None = None
        self.protocol_end: str | None = None

    def _led(self, seq: int) -> Ledger:
        if self.ledger is None:
            self.ledger = Ledger(seq)
        return self.ledger

    def _ack(self, seq: int) -> None:
        led = self._led(seq)
        if led.acks_sent < HOST_MAX_REPLAYS:
            led.acks_sent += 1
            self.send(n.build_line(T_TERMACK, seq, self.token, n.encode_payload({"seq": seq})))

    def on_broken_line(self, line: str, outcome: str) -> bool:
        t, s = head_fields(line)
        if t != n.T_TERM:
            return False
        seq = s if s is not None else (self.seq or 0)
        led = self._led(seq)
        led.note(outcome, line, self.clock())
        if led.gets_sent < HOST_MAX_GETS:
            led.gets_sent += 1
            self.send(n.build_line(T_TERMGET, seq, self.token, n.encode_payload({"seq": seq})))
        return True

    def on_term(self, f: dict, line: str) -> bool:
        """A CRC-valid TERM. Returns True when it was delivered (first arrival)."""
        if self.protocol_end is not None:
            return False
        seq = f["seq"]
        if self.payload is not None:
            led = self._led(self.seq)
            if f["payload"] == self.payload and seq == self.seq:
                led.note("duplicate", None, self.clock()); self._ack(seq)
            else:
                led.note("conflict", line, self.clock()); led.conflict = True
                self.protocol_end = "PROTOCOL_TERM: a second, different TERM"
            return False
        self.payload, self.seq = f["payload"], seq
        led = self._led(seq)
        led.accepted = True
        led.note("ok", None, self.clock())
        self.deliver(line)
        self._ack(seq)
        return True


def closing_control_findings(summary: dict) -> list[str]:
    """v0.6 §2.6o: an application-written TERM carries the COMPLETE closing control —
    all five fields, typed (fault int, kind str, status str, nonces 16 hex). A missing
    block, a missing field or a wrong type is named (review 2026-09-02, item 2)."""
    cc = summary.get("closing_control")
    if not isinstance(cc, dict):
        return ["TERM carries no closing_control block (v0.6 §2.6o requires the complete closing control)"]
    out = []
    for k in CLOSING_CONTROL_FIELDS:
        if k not in cc:
            out.append(f"TERM closing_control lacks {k!r}")
    if "fault" in cc and not isinstance(cc["fault"], int):
        out.append("TERM closing_control.fault is not an integer")
    for k in ("kind", "status"):
        if k in cc and not isinstance(cc[k], str):
            out.append(f"TERM closing_control.{k} is not a string")
    for k in ("nonce_before", "nonce_after"):
        v = cc.get(k)
        if k in cc and not (isinstance(v, str) and len(v) == 16 and all(c in "0123456789abcdef" for c in v)):
            out.append(f"TERM closing_control.{k} is not 16 lowercase hex chars")
    return out


def closing_from_term(summary: dict) -> dict | None:
    """rel-v4: the TERM payload repeats the closing unsigned control's fields
    (`closing_control`), so a lost CLOSE is reconstructed from the re-requestable TERM.
    Returns the closing_negative record (marked `source: TERM`) only when the block is
    complete and well-typed, else None (the defect is `closing_control_findings`')."""
    if closing_control_findings(summary):
        return None
    return dict(summary["closing_control"], source="TERM")


# ------------------------------------------------------------------ heartbeats


def hb_index_of(frame: dict) -> int | None:
    i = frame.get("hb_i")
    return i if isinstance(i, int) else None


def heartbeat_findings_rel(log: dict, frames: list[dict]) -> list[str]:
    """rel-v4's heartbeat rule: for every SCORED record the indices 0..15 seen at most
    once each; a record missing two or more is a structural finding; the total missing
    over the session is bounded by `hb_missing_budget(R)` (R = SCORED records); an HB
    without an index is a protocol finding (the image is not rel-v4); duplicates are
    reported, never a finding; more than 16 distinct is impossible and a finding."""
    seen: dict[int, list[int]] = {}
    unindexed = 0
    for f in frames:
        if f.get("dir") == "rx" and f.get("type") == n.T_HB and f.get("seq") is not None:
            i = hb_index_of(f)
            if i is None:
                unindexed += 1
            else:
                seen.setdefault(f["seq"], []).append(i)
    out = []
    if unindexed:
        out.append(f"{unindexed} HB frames carry no index: not a rel-v4 image")
    scored = [r for r in log["loop_records"] if r["outcome"] == "SCORED"]
    total_missing = 0
    for r in scored:
        idx = seen.get(r["seq"], [])
        bad = [i for i in idx if not 0 <= i < HB_PER_RECORD]
        if bad:
            out.append(f"seq {r['seq']}: HB index out of range {bad}")
        distinct = {i for i in idx if 0 <= i < HB_PER_RECORD}
        missing = HB_PER_RECORD - len(distinct)
        if missing >= 2:
            out.append(f"seq {r['seq']} (SCORED): {missing} heartbeats missing (indices {sorted(set(range(HB_PER_RECORD)) - distinct)}); the bound is one per record")
        total_missing += missing
    budget = hb_missing_budget(len(scored))
    if total_missing > budget:
        out.append(f"{total_missing} heartbeats missing over {len(scored)} SCORED records > the budget floor(R/1000) = {budget}")
    return out


# ------------------------------------------------------------------ the channel


@dataclass
class Fault:
    """A scripted fault on the k-th transmission of a frame type in a direction: `drop`,
    `delete` (length bytes at offset, terminator kept), `dup`, `truncate` (the tail from
    `offset`, terminator included, never arrives — the reader's resync/quarantine case)."""
    direction: str
    mtype: str
    attempt: int = 0
    kind: str = "drop"
    offset: int = 0
    length: int = 0


class Feed:
    def __init__(self):
        self.q: list[bytes] = []

    @property
    def in_waiting(self) -> int:
        return len(self.q[0]) if self.q else 0

    def read(self, k: int) -> bytes:
        return self.q.pop(0)


class Simulation:
    """One transaction between a board twin and a host object over a faulty channel. The
    board→host bytes go through a REAL `L6LineReader` (torn lines, resync, quarantine);
    host→board lines reach the twin directly (the C twin's bounded receiver is
    `tests/test_firmware_wire_contract.py`'s business). `host_on_line(line)` feeds the
    host; `board.state == 'WAIT_ACK'`/`'PULL'` keeps the loop alive; `quarantine_on(...)`
    lets the host quarantine on its own timeouts."""

    def __init__(self, board, host_on_line, faults: list[Fault] = (), host_tick=None, board_done=None):
        self.board, self.host_on_line, self.faults = board, host_on_line, list(faults)
        self.host_tick = host_tick or (lambda: None)
        self.board_done = board_done or (lambda b: b.state not in ("WAIT_ACK", "PULL"))
        self.seen: dict[tuple, int] = {}
        self.to_board: list[str] = []
        self.host_sent: list[str] = []
        self.delivered_b2h: list[str] = []
        self.t = 0.0
        self.feed = Feed()
        self.reader = lrd.L6LineReader(self.feed, clock_mono=lambda: self.t, clock_wall=lambda: self.t)

    def send(self, line: str) -> None:
        self.host_sent.append(line)
        self.to_board.append(line)

    def _key(self, direction, line):
        try:
            return (direction, n.parse_line(line)["type"])
        except Exception:  # noqa: BLE001
            t, _ = head_fields(line)
            return (direction, t or "?")

    def _apply(self, direction: str, lines: list[str]) -> list[str | bytes]:
        out: list = []
        for line in lines:
            key = self._key(direction, line)
            k = self.seen.get(key, 0); self.seen[key] = k + 1
            hit = [f for f in self.faults if f.direction == direction and f.mtype == key[1] and f.attempt == k]
            self.t += len(line) * 10 / 115200
            if not hit:
                out.append(line); continue
            f = hit[0]
            if f.kind == "drop":
                continue
            if f.kind == "dup":
                out += [line, line]; continue
            body = line.rstrip("\n")
            if f.kind == "truncate":
                out.append(body[:f.offset].encode())         # bytes with no terminator
                continue
            out.append(body[:f.offset] + body[f.offset + f.length:] + "\n")
        return out

    def _b2h(self, lines: list[str]) -> None:
        for item in self._apply("b2h", lines):
            data = item if isinstance(item, bytes) else item.encode()
            self.feed.q.append(data)
            for ln, _tm, _tw in self.reader.poll():
                self.delivered_b2h.append(ln)
                self.host_on_line(ln)

    def run(self, max_steps: int = 2000) -> dict:
        self._b2h(self.board.start())
        steps = 0
        while not self.board_done(self.board):
            steps += 1
            if steps > max_steps:
                raise RuntimeError("the transaction did not converge")
            progressed = False
            while self.to_board:
                for line in self._apply("h2b", [self.to_board.pop(0)]):
                    progressed = True
                    self._b2h(self.board.on_host_line(line))
            if not progressed:
                dt = 0.5
                self.t += dt
                self.host_tick()
                while self.to_board:
                    for line in self._apply("h2b", [self.to_board.pop(0)]):
                        self._b2h(self.board.on_host_line(line))
                self._b2h(self.board.tick(dt))
        return {"host_sent": list(self.host_sent), "delivered_b2h": list(self.delivered_b2h),
                "fragments": list(self.reader.fragments), "seconds": self.t}
