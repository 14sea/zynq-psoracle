#!/usr/bin/env python3
"""The L6 console reader: non-blocking, per-read timestamps (C1 #1 finding 2); torn-line
resynchronisation and fragment quarantine (C1 #5 finding, owner's ruling 2026-09-02).

Why this exists. `host/l5_runner.LineReader` reads through zynq-psmap's
`SerialTransport.drain()`, which loops `read(4096)` on a port opened with `timeout = 0.1`
and returns only once the board has been silent for 100 ms. Inside a candidate the
application never pauses that long, so the whole candidate (26 frames) came back from one
`drain()` and the runner stamped every line with one time: 625 frames, 25 stamps, and a
six-stage breakdown that was void on hardware (`docs/l6_c1_session1_findings.md` §3).

This reader uses the SAME open serial handle (the transport's own `_serial`, same epoch —
nothing is reopened, imported `board_session.py` is not modified) but reads only what is
already waiting (`read(in_waiting)`), so a poll returns in microseconds and the runner's
~20 ms loop is the resolution. A line's stamp is the time of the OS read that completed
it; lines completed by the same read honestly share a stamp. Raw bytes are kept verbatim
(`raw`), a partial line survives across polls (`buf`), and a U-Boot banner in the raw
stream is still the crash signal. `drain()` is never called.

Torn lines (C1 #5, `docs/l6_c1_session5_findings.md` §3). The first reply of `AUDIT 39`
chunk 1 reached the host short and WITHOUT its line end; the reader of that session kept
the 576 unterminated bytes in `buf` for ever, so when the board resent the chunk the
resend was appended to the residue and the whole 1228-byte line was rejected as
malformed — one recovery cost a timeout AND a wasted resend. Two rules close that:

  * **resynchronisation on a frame head.** A `P3L5 <TYPE> <seq> <token32> ` head that
    appears inside the buffer with NO line end before it can only mean the bytes before
    it are a line that lost its terminator: those bytes are moved to `fragments`
    (quarantined, verbatim, stamped, reason `resync`) and the new frame is parsed from
    its own head. The full head is required — a base64 payload can end in `P3L5`, but it
    is followed by a space and an 8-hex CRC, never by `<TYPE> <seq> <token32> ` — so a
    valid line is never split (test: a payload ending in `P3L5`). A head split across two
    polls is simply not a head yet; nothing is emitted until it completes.
  * **quarantine on demand.** `quarantine(reason)` moves whatever unterminated bytes are
    waiting into `fragments` (the pull calls it on a chunk timeout, so a resend never
    glues to the residue even if it arrives without a recognisable head).

A fragment is never silently dropped: it stays in `raw`, in `fragments` (bytes, head,
stamps, reason) and, through the session, in the timeline as a `FRAGMENT` event. A
fragment is never reassembled into protocol input — the resend is the authority. A
half line that is merely split across polls (no head inside it, no quarantine asked) is
completed by the later read exactly as before.
"""
from __future__ import annotations

import re
import time

UBOOT_PROMPT = re.compile(rb"(zynq-uboot>|U-Boot \d)")
# a frame head: magic, a type, a seq, the 32-hex token, each followed by one space. The
# search starts at offset 1: a head at offset 0 is the line being read, not a resync.
FRAME_HEAD = re.compile(rb"P3L5 [A-Z_]+ \d+ [0-9a-f]{32} ")
FRAGMENT_HEAD_CHARS = 96


class L6LineReader:
    def __init__(self, ser, clock_mono=time.monotonic, clock_wall=time.time, resync: bool = True):
        self.ser = ser
        self.mono, self.wall = clock_mono, clock_wall
        self.resync = resync
        self.buf = b""
        self.raw = bytearray()
        self.reads = 0
        self.fragments: list[dict] = []          # every quarantined fragment, verbatim, in order
        self._pending_fragments: list[dict] = []  # not yet taken by the session (take_fragments)

    # ------------------------------------------------------------------ fragments
    def _quarantine(self, frag: bytes, reason: str, t_mono: float, t_wall: float) -> dict:
        rec = {"t_mono": t_mono, "t_wall": t_wall, "bytes": len(frag), "reason": reason,
               "head": frag[:FRAGMENT_HEAD_CHARS].decode("ascii", "replace"),
               "text": frag.decode("ascii", "replace")}
        self.fragments.append(rec)
        self._pending_fragments.append(rec)
        return rec

    def quarantine(self, reason: str) -> dict | None:
        """Move the unterminated bytes waiting in the buffer (if any) to `fragments`. Called
        by the pull on a chunk timeout so the board's resend starts from a clean buffer.
        Returns the fragment record, or None when the buffer was empty."""
        if not self.buf:
            return None
        frag, self.buf = self.buf, b""
        return self._quarantine(frag, reason, self.mono(), self.wall())

    def take_fragments(self) -> list[dict]:
        """The fragments quarantined since the last call (for the session's timeline)."""
        out, self._pending_fragments = self._pending_fragments, []
        return out

    # ------------------------------------------------------------------ lines
    def poll(self) -> list[tuple[str, float, float]]:
        """Every line completed by the bytes waiting NOW, each with (t_mono, t_wall) of this
        read. Returns [] without blocking when nothing is waiting."""
        n = self.ser.in_waiting
        if not n:
            return []
        chunk = self.ser.read(n)
        if not chunk:
            return []
        t_mono, t_wall = self.mono(), self.wall()
        self.reads += 1
        self.raw += chunk
        self.buf += chunk
        out = []
        while True:
            nl = self.buf.find(b"\n")
            if self.resync:
                m = FRAME_HEAD.search(self.buf, 1)
                if m is not None and (nl == -1 or m.start() < nl):
                    # a frame head with no line end before it: the bytes before it are a
                    # torn line — quarantined, and the new frame starts at its own head
                    frag, self.buf = self.buf[:m.start()], self.buf[m.start():]
                    self._quarantine(frag, "resync: a frame head arrived with no line end before it", t_mono, t_wall)
                    continue
            if nl == -1:
                break
            line, self.buf = self.buf[:nl], self.buf[nl + 1:]
            out.append((line.decode("ascii", "replace").rstrip("\r"), t_mono, t_wall))
        return out

    def saw_uboot_banner(self) -> bool:
        return bool(UBOOT_PROMPT.search(self.raw[-4096:]))
