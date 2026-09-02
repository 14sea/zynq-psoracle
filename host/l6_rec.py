#!/usr/bin/env python3
"""The REC transaction (rec-v3): a loop record is not accepted until the host has said so,
and the board does not propose the next candidate until then (owner's batch 2026-09-01,
after S #1: `REC 465` lost ~536 console bytes, was CRC-dropped, and the collector ended the
epoch on the seq gap — the one frame type the pull protocol could not re-request).

Both ends build and parse the same P3L5 lines they will exchange on the console:

    board → host  REC     <seq> <token> <loop_record b64>        (attempt 1)
    host  → board RECACK  {seq}      the record arrived whole and was accepted (or is a
                                     byte-identical duplicate of the accepted one)
    host  → board RECGET  {seq}      a REC-shaped line for this seq arrived broken: resend
    board → host  REC     …          the SAME bytes again (attempt k ≤ REC_MAX_ATTEMPTS)

Closure. Token, frame seq and payload seq bind every line; the board answers only a
RECACK/RECGET whose seq is the record it is waiting on; the host acknowledges only the
current candidate's record — the one whose sign exchange the relay answered and whose
record has not yet been accepted (`pending`). A REC for any other seq is channel
misbehaviour: the board advanced without an acknowledgement → PROTOCOL end.

Idempotence. The board resends the exact bytes it built once (the serialiser's tally
counts the record once). A duplicate REC of the accepted record is re-acknowledged and
never appended again; a REC that shares the accepted seq but differs in content is a
PROTOCOL end, never a second accepted record and never a "newer" one.

Bounded retry, every way a frame can be lost: REC lost or CRC-broken → the host sends
RECGET on a broken REC-shaped line, and in any case the board's own bounded wait runs out
and it resends; RECACK lost → the board resends, the host re-acknowledges; RECGET lost →
the board's wait runs out and it resends. After REC_MAX_ATTEMPTS without an
acknowledgement the board STOPS (`STOP_REC`, restore, TERM) — a record the host never
confirmed is never treated as delivered and no further candidate is proposed.

One ledger. Every attempt — the original broken line included — goes into the session's
inbound ledger (the Timeline, CRC authority for every type) and into the per-seq REC
ledger with the raw line kept verbatim; failed attempts count against D-s4's budget.
Content is not the transport's business: a CRC-valid record that is wrong (a nonce that
does not step, a readback that is not the commit) is accepted ONCE and judged by the
validator — a retry never replaces it and can never wash out a falsifier.

The preregistered control (forced REC-retry). With the identity page's flags.bit4 set,
the board deliberately corrupts the CRC of the FIRST transmission of the opening
baseline's record (seq 1, attempt 1) — one hex digit of the CRC field — so every session
proves the real wire retry in its first seconds: the host must RECGET, the board must
resend byte-identical, the ledger must show exactly `crc` then `ok` for seq 1. A session
armed with the control whose ledger does not show that is a HOLD (the control was not
exercised); the deliberate drop counts against the budget like any other.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402

PROTOCOL = "rec-v3"
T_RECACK, T_RECGET = "RECACK", "RECGET"
HOST_TYPES = (T_RECACK, T_RECGET)
REC_MAX_ATTEMPTS = 3              # board: the first transmission + two retries
REC_HOST_MAX_GETS = 2             # host: RECGETs per seq; the board's bound is the authority beyond that
BOARD_ACK_LIMIT_S = 10.0          # board: wait for RECACK/RECGET before resending (a COUNT of polls in C)
FLAG_REC_CONTROL = 1 << 4         # identity page: the forced REC-retry control


def corrupt_crc(line: str) -> str:
    """The control's corruption, exactly as the firmware applies it: the LAST hex digit of
    the CRC field flipped ('0' → '1', anything else → '0'). The line keeps its shape and its
    type/seq fields, so the host reads it as a REC for this seq and asks for it again."""
    body, nl = (line[:-1], "\n") if line.endswith("\n") else (line, "")
    last = body[-1]
    return body[:-1] + ("1" if last == "0" else "0") + nl


def head_fields(line: str) -> tuple[str | None, int | None]:
    """(type, seq) as far as a broken line's head can be read — for a CRC-failed or
    malformed line; None where unreadable. Never trusted for acceptance, only for asking."""
    parts = line.rstrip("\n").split(" ")
    if len(parts) < 3 or parts[0] != n.MAGIC:
        return None, None
    t = parts[1] if parts[1] in n.APP_TYPES else None
    s = int(parts[2]) if parts[2].isdigit() else None
    return t, s


# ------------------------------------------------------------------ the board


class RecBoard:
    """The firmware's REC transaction (firmware/p3_rectx.c is its C twin, host-compiled
    and driven by tests/test_firmware_wire_contract.py::RecWireContract)."""

    def __init__(self, token: str, seq: int, rec_line: str, corrupt_first: bool = False):
        self.token, self.seq = token, seq
        self.line = rec_line if rec_line.endswith("\n") else rec_line + "\n"
        self.corrupt_first = corrupt_first
        self.attempts = 0
        self.state = "IDLE"            # IDLE → WAIT_ACK → DONE | EXHAUSTED
        self.idle_s = 0.0
        self.acked = False
        self.why = ""

    def start(self) -> list[str]:
        return self._send()

    def _send(self) -> list[str]:
        if self.attempts >= REC_MAX_ATTEMPTS:
            self.state, self.why = "EXHAUSTED", f"STOP_REC: the record was not acknowledged after {REC_MAX_ATTEMPTS} attempts"
            return []
        self.attempts += 1
        self.state, self.idle_s = "WAIT_ACK", 0.0
        line = self.line
        if self.corrupt_first and self.attempts == 1:
            line = corrupt_crc(line)
        return [line]

    def on_host_line(self, line: str) -> list[str]:
        if self.state != "WAIT_ACK":
            return []
        try:
            f = n.parse_line(line)
        except (n.CrcError, n.FrameError):
            return []                              # a broken host line: keep waiting, within the bound
        if f["token"] != self.token or f["seq"] != self.seq:
            return []                              # not this transaction (a stale line is ignored)
        try:
            p = n.decode_payload(f["payload"]) if f["payload"] != "-" else {}
        except Exception:  # noqa: BLE001
            return []
        if p.get("seq") != self.seq:
            return []
        if f["type"] == T_RECACK:
            self.acked, self.state = True, "DONE"
            return []
        if f["type"] == T_RECGET:
            return self._send()
        return []

    def tick(self, dt_s: float) -> list[str]:
        if self.state != "WAIT_ACK":
            return []
        self.idle_s += dt_s
        if self.idle_s > BOARD_ACK_LIMIT_S:
            return self._send()
        return []

    def finish(self) -> dict:
        if self.state == "WAIT_ACK":
            raise RuntimeError("finish() before the transaction ended")
        return {"acked": self.acked, "attempts": self.attempts, "next_candidate": self.acked,
                "epoch": "RUNNING" if self.acked else "STOPPED", "why": self.why}


# ------------------------------------------------------------------ the host


@dataclass
class RecLedger:
    """One seq's transaction as the host saw it; `attempts` in arrival order, every failed
    or duplicate line kept verbatim."""
    seq: int
    attempts: list[dict] = field(default_factory=list)
    lines_kept: list[str] = field(default_factory=list)
    gets_sent: int = 0
    acks_sent: int = 0
    accepted: bool = False
    conflict: bool = False

    def note(self, outcome: str, line: str | None = None, t: float | None = None) -> None:
        self.attempts.append({"attempt": len(self.attempts) + 1, "outcome": outcome, "t_mono": t})
        if line is not None:
            self.lines_kept.append(line.rstrip("\n"))

    def to_json(self) -> dict:
        return {"seq": self.seq, "attempts": list(self.attempts), "lines_kept": list(self.lines_kept),
                "gets_sent": self.gets_sent, "acks_sent": self.acks_sent, "accepted": self.accepted,
                "conflict": self.conflict}


class RecHost:
    """The host side for ONE candidate: `pending` is its seq. `on_line` takes every inbound
    line while pending; the outcome is `accepted` (RECACK sent, record delivered to
    `deliver`) or `protocol` (the channel misbehaved: reason in `why`). The real runner's
    ConsoleSession (host/l6_console.py) implements exactly this against the Collector."""

    def __init__(self, token: str, seq: int, send, deliver, clock=lambda: 0.0):
        self.token, self.seq, self.send, self.deliver, self.clock = token, seq, send, deliver, clock
        self.ledger = RecLedger(seq)
        self.payload: str | None = None
        self.accepted = False
        self.protocol_end: str | None = None

    def _tx(self, mtype: str) -> None:
        self.send(n.build_line(mtype, self.seq, self.token, n.encode_payload({"seq": self.seq})))

    def _get(self) -> None:
        if self.ledger.gets_sent < REC_HOST_MAX_GETS:
            self.ledger.gets_sent += 1
            self._tx(T_RECGET)

    def _ack(self) -> None:
        if self.ledger.acks_sent < REC_MAX_ATTEMPTS:      # one per arrival, bounded by the board's attempts
            self.ledger.acks_sent += 1
            self._tx(T_RECACK)

    def on_line(self, line: str) -> None:
        if self.protocol_end is not None:
            return
        try:
            f = n.parse_line(line)
        except n.CrcError:
            t, s = head_fields(line)
            if t == n.T_REC and (s is None or s == self.seq):
                self.ledger.note("crc", line, self.clock())
                self._get()
            return
        except n.FrameError:
            t, s = head_fields(line)
            if t == n.T_REC and (s is None or s == self.seq):
                self.ledger.note("malformed", line, self.clock())
                self._get()
            return
        if f["token"] != self.token or f["type"] != n.T_REC:
            return
        if f["seq"] != self.seq:
            self.protocol_end = (f"PROTOCOL_REC: REC seq {f['seq']} while seq {self.seq} is the current candidate — "
                                 f"the board advanced without an acknowledgement")
            return
        try:
            rec = n.decode_payload(f["payload"])
        except Exception:  # noqa: BLE001 — a CRC-valid line whose payload does not decode: ask again
            self.ledger.note("malformed", line, self.clock())
            self._get()
            return
        if self.accepted:
            if f["payload"] == self.payload:
                self.ledger.note("duplicate", line, self.clock())
                self._ack()                                # the ACK was lost: say it again, append nothing
            else:
                self.ledger.note("conflict", line, self.clock())
                self.ledger.conflict = True
                self.protocol_end = f"PROTOCOL_REC: seq {self.seq} arrived twice with different content"
            return
        if rec.get("seq") != self.seq:
            self.ledger.note("malformed", line, self.clock())
            self._get()
            return
        self.payload, self.accepted = f["payload"], True
        self.ledger.accepted = True
        self.ledger.note("ok", None, self.clock())
        self.deliver(rec)                                  # accepted ONCE; content is the validator's
        self._ack()


# ------------------------------------------------------------------ the channel


@dataclass
class Fault:
    """A scripted fault on the k-th transmission of a frame type in a direction. `drop`:
    the line never arrives; `delete`: `length` bytes at `offset` vanish (S #1's shape:
    an interior run of a REC line); `dup`: the line arrives twice."""
    direction: str            # "b2h" | "h2b"
    mtype: str
    attempt: int = 0
    kind: str = "delete"
    offset: int = 0
    length: int = 0


class Simulation:
    """One candidate's REC transaction between a RecBoard and a RecHost over a faulty
    channel; time advances by explicit idle ticks when nothing is on the wire."""

    def __init__(self, board: RecBoard, faults: list[Fault] = (), token: str | None = None):
        self.board = board
        self.faults = list(faults)
        self.seen: dict[tuple, int] = {}
        self.to_board: list[str] = []
        self.host_sent: list[str] = []
        self.delivered: list[dict] = []
        self.delivered_b2h: list[str] = []
        self.t = 0.0

        def send(line: str) -> None:
            self.host_sent.append(line)
            self.to_board.append(line)
        self.host = RecHost(token or board.token, board.seq, send=send, deliver=self.delivered.append,
                            clock=lambda: self.t)

    def _key(self, direction, line):
        try:
            f = n.parse_line(line)
            return (direction, f["type"])
        except Exception:  # noqa: BLE001
            t, _ = head_fields(line)
            return (direction, t or "?")

    def _apply(self, direction: str, lines: list[str]) -> list[str]:
        out = []
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
            out.append(body[:f.offset] + body[f.offset + f.length:] + "\n")
        return out

    def run(self, max_steps: int = 1000) -> dict:
        for line in self._apply("b2h", self.board.start()):
            self.delivered_b2h.append(line); self.host.on_line(line)
        steps = 0
        while self.board.state == "WAIT_ACK" and self.host.protocol_end is None:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("the transaction did not converge")
            progressed = False
            while self.to_board:
                for line in self._apply("h2b", [self.to_board.pop(0)]):
                    progressed = True
                    for reply in self._apply("b2h", self.board.on_host_line(line)):
                        self.delivered_b2h.append(reply); self.host.on_line(reply)
            if not progressed:
                dt = 0.5
                self.t += dt
                for reply in self._apply("b2h", self.board.tick(dt)):
                    self.delivered_b2h.append(reply); self.host.on_line(reply)
        if self.board.state == "WAIT_ACK":
            # the host declared a protocol end: the board waits out its bound and exhausts
            while self.board.state == "WAIT_ACK":
                self.board.tick(BOARD_ACK_LIMIT_S + 1)
        return {"board": self.board.finish(), "host_accepted": self.host.accepted,
                "protocol_end": self.host.protocol_end, "ledger": self.host.ledger,
                "records": list(self.delivered), "seconds": self.t}
