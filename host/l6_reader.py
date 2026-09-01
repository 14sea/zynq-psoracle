#!/usr/bin/env python3
"""The L6 console reader: non-blocking, per-read timestamps (C1 #1 finding 2).

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
"""
from __future__ import annotations

import re
import time

UBOOT_PROMPT = re.compile(rb"(zynq-uboot>|U-Boot \d)")


class L6LineReader:
    def __init__(self, ser, clock_mono=time.monotonic, clock_wall=time.time):
        self.ser = ser
        self.mono, self.wall = clock_mono, clock_wall
        self.buf = b""
        self.raw = bytearray()
        self.reads = 0

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
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            out.append((line.decode("ascii", "replace").rstrip("\r"), t_mono, t_wall))
        return out

    def saw_uboot_banner(self) -> bool:
        return bool(UBOOT_PROMPT.search(self.raw[-4096:]))
