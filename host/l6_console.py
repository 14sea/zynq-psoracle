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
"""
from __future__ import annotations

import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_timing as lt  # noqa: E402


class ConsoleSession:
    def __init__(self, token: str, collector: n.Collector, relay: n.NotaryRelay, timeline: lt.Timeline,
                 audit_seqs: set[int], crc_budget: int, send):
        self.token, self.collector, self.relay, self.timeline = token, collector, relay, timeline
        self.audit_seqs, self.crc_budget, self.send = audit_seqs, crc_budget, send
        self.audit_sent_for: set[int] = set()

    @property
    def crc_dropped(self) -> int:
        """The one number: every CRC-failed inbound frame, counted once, all types."""
        return self.timeline.crc_dropped

    @property
    def ended(self) -> bool:
        return self.collector.epoch_end is not None

    def on_line(self, line: str, t_mono: float, t_wall: float) -> None:
        if self.ended:
            return                                  # after the end nothing is evidence
        self.timeline.observe(line, t_mono, t_wall)   # the ledger: frames, CRC drops, bad frames
        if not line.startswith(n.MAGIC):
            return                                  # console noise
        try:
            f = n.parse_line(line)
        except n.CrcError:
            # counted by the ledger above; the budget is enforced here for EVERY type
            if self.timeline.crc_dropped > self.crc_budget:
                self.collector.epoch_end = {"kind": "PROTOCOL", "last_seq": self.collector.last_rec_seq,
                                            "reason": f"PROTOCOL_CRC_BUDGET: {self.timeline.crc_dropped} > {self.crc_budget}"}
            return
        except n.FrameError:
            self.collector.on_line(line)            # its rule: a malformed frame is CRASHED
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
