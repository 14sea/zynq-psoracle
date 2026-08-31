#!/usr/bin/env python3
"""The T1 notary channel, protocol layer only (D1 spec §5): framing, relay, collector.

Transport is injected — nothing here opens a serial port; the board wiring is L5-design
work. What is pinned here and tested host-side:

- **Framing** (§5b): `P3L5 <type> <seq> <token> <payload> <crc32>\n`, printable ASCII, the
  **full 128-bit token** (32 hex chars — review #1 blocker 2) in every line, CRC32 over the
  body. A CRC-failed line is dropped and counted; exceeding the pinned drop budget is a
  `PROTOCOL` end, never a silent degradation.
- **Relay** (runner principal): parses `SIGNREQ` lines, asks the signer (a callable — in
  production `sudo -n -u p3signer host/sign_arm.py` with op `sign_genome`), answers
  `SIGNOK`/`SIGNREF`, and writes the `notary_log` — the host's independent record that rule
  (vii) cross-checks. It cannot forge a tag; it enforces seq monotonicity and the token.
  A gate refusal is answered and the session continues; only channel misbehaviour ends it.
- **Collector**: consumes the application's framed records, applies the §3c collector-side
  epoch rules (a foreign token, a seq gap, silence past 3 heartbeat intervals, a console
  banner → `CRASHED` unless a terminal line arrived first) and assembles the standalone
  run-log inputs for `validators.records.validate_standalone_run_log`.

Payloads are compact JSON, base64url — framed lines stay single-line printable ASCII.
"""

from __future__ import annotations

import base64
import json
import time
import zlib

MAGIC = "P3L5"
TOKEN_HEX = 32
# application → host
T_IDENT, T_SIGNREQ, T_HB, T_REC, T_AUDIT, T_TERM = "IDENT", "SIGNREQ", "HB", "REC", "AUDIT", "TERM"
# the closing unsigned ARM: not a loop_record ("CLOSING_CONTROL" is not a LOOP_OUTCOME), so
# it travels as its own type and the collector files it under the log's closing_negative key
T_CLOSE = "CLOSE"
# host → application
T_SIGNOK, T_SIGNREF, T_AUDITREQ = "SIGNOK", "SIGNREF", "AUDITREQ"
APP_TYPES = (T_IDENT, T_SIGNREQ, T_HB, T_REC, T_AUDIT, T_TERM, T_CLOSE)


class FrameError(ValueError):
    """A malformed frame (not a CRC failure): a PROTOCOL matter."""


class CrcError(ValueError):
    """A CRC-failed line: dropped and counted against the budget."""


class ProtocolEnd(Exception):
    """The channel misbehaved (§3c PROTOCOL): the epoch is over. Never raised for a refusal."""


def encode_payload(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).decode()


def decode_payload(text: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(text.encode()))


def build_line(mtype: str, seq: int, token: str, payload: str = "-") -> str:
    body = f"{MAGIC} {mtype} {seq} {token} {payload}"
    return f"{body} {zlib.crc32(body.encode()) & 0xFFFFFFFF:08x}\n"


def parse_line(line: str) -> dict:
    line = line.rstrip("\n")
    parts = line.split(" ")
    if len(parts) != 6 or parts[0] != MAGIC:
        raise FrameError(f"not a {MAGIC} frame: {line[:40]!r}")
    body = " ".join(parts[:5])
    if f"{zlib.crc32(body.encode()) & 0xFFFFFFFF:08x}" != parts[5]:
        raise CrcError("crc mismatch")
    mtype, seq_s, token, payload = parts[1], parts[2], parts[3], parts[4]
    if len(token) != TOKEN_HEX or any(c not in "0123456789abcdef" for c in token):
        raise FrameError("token is not the full 128-bit session token (32 hex chars)")
    if not seq_s.isdigit():
        raise FrameError(f"seq {seq_s!r} is not a number")
    return {"type": mtype, "seq": int(seq_s), "token": token, "payload": payload}


class NotaryRelay:
    """The runner-principal relay: SIGNREQ in, SIGNOK/SIGNREF out, notary_log kept.

    `signer` is a callable(dict sign_request) → either
      {"commit", "expected_tables", "tag", ...}  (a signed candidate) or
      {"refused": {"finding_kinds": [...]}}       (the gate said no — session continues).
    """

    def __init__(self, token: str, signer, drop_budget: int, clock=time.time):
        if len(token) != TOKEN_HEX:
            raise ValueError("the relay needs the full 128-bit session token")
        self.token, self.signer, self.drop_budget, self.clock = token, signer, drop_budget, clock
        self.crc_dropped = 0
        self.last_seq = 0
        self.entries: list[dict] = []
        self.ended: str | None = None

    def _end(self, reason: str) -> None:
        self.ended = reason
        raise ProtocolEnd(reason)

    def handle_line(self, line: str) -> str | None:
        """One inbound line → the reply line for SIGNREQ, None otherwise. Raises ProtocolEnd."""
        if self.ended:
            raise ProtocolEnd(self.ended)
        try:
            f = parse_line(line)
        except CrcError:
            self.crc_dropped += 1
            if self.crc_dropped > self.drop_budget:
                self._end(f"PROTOCOL_CRC_BUDGET: {self.crc_dropped} > {self.drop_budget}")
            return None
        except FrameError as exc:
            self._end(f"PROTOCOL_FRAME: {exc}")
        if f["token"] != self.token:
            self._end("PROTOCOL_TOKEN: a frame with a foreign token")
        if f["type"] != T_SIGNREQ:
            return None                      # records and heartbeats are the collector's
        if f["seq"] != self.last_seq + 1:
            self._end(f"PROTOCOL_SEQ: got {f['seq']}, expected {self.last_seq + 1}")
        req = decode_payload(f["payload"])
        req.setdefault("schema", "sign_request"); req.setdefault("schema_version", "1.0.0")
        if req.get("token") != self.token or req.get("seq") != f["seq"]:
            self._end("PROTOCOL_SEQ: the payload disagrees with its frame")
        answer = self.signer(req)
        self.last_seq = f["seq"]
        if "refused" in answer:
            ans = {"schema": "sign_refusal", "schema_version": "1.0.0", "seq": f["seq"],
                   "finding_kinds": answer["refused"]["finding_kinds"]}
            reply_type = T_SIGNREF
        else:
            ans = {"schema": "sign_reply", "schema_version": "1.0.0", "seq": f["seq"],
                   "commit": answer["commit"], "expected_tables": answer["expected_tables"],
                   "tag": answer["tag"]}
            reply_type = T_SIGNOK
        self.entries.append({"seq": f["seq"], "at": self.clock(), "request": req, "answer": ans})
        return build_line(reply_type, f["seq"], self.token, encode_payload(ans))

    def notary_log(self) -> dict:
        return {"schema": "notary_log", "schema_version": "1.0.0",
                "token": self.token, "entries": list(self.entries)}


class Collector:
    """§3c collector side. Feed it every inbound line (`on_line`) plus console noise
    (`on_banner`) and poll (`poll`); once ended, `epoch_end` says how and why."""

    def __init__(self, token: str, heartbeat_s: float, clock=time.time):
        self.token, self.heartbeat_s, self.clock = token, heartbeat_s, clock
        self.app_identity: dict | None = None
        self.loop_records: list[dict] = []
        self.session_summary: dict | None = None
        self.closing_negative: dict | None = None
        self.audits: list[dict] = []
        self.last_heard = clock()
        self.last_rec_seq = 0
        self.epoch_end: dict | None = None

    def _crash(self, reason: str) -> None:
        if self.epoch_end is None:
            self.epoch_end = {"kind": "CRASHED", "reason": reason, "last_seq": self.last_rec_seq}

    def on_banner(self) -> None:
        """A U-Boot banner or prompt on the console: the application is gone."""
        self._crash("console banner")

    def poll(self, now: float | None = None) -> dict | None:
        now = self.clock() if now is None else now
        if self.epoch_end is None and now - self.last_heard > 3 * self.heartbeat_s:
            self._crash(f"silence > {3 * self.heartbeat_s:.0f}s")
        return self.epoch_end

    def on_line(self, line: str, now: float | None = None) -> None:
        if self.epoch_end is not None:
            return                            # after the end, nothing more is evidence
        now = self.clock() if now is None else now
        try:
            f = parse_line(line)
        except CrcError:
            return                            # the relay counts these against the budget
        except FrameError:
            self._crash("unparseable frame")
            return
        if f["token"] != self.token:
            self._crash("foreign token")
            return
        self.last_heard = now
        if f["type"] == T_IDENT:
            self.app_identity = decode_payload(f["payload"])
        elif f["type"] == T_REC:
            rec = decode_payload(f["payload"])
            if rec.get("seq") != self.last_rec_seq + 1:
                self._crash(f"record seq gap: {rec.get('seq')} after {self.last_rec_seq}")
                return
            self.last_rec_seq = rec["seq"]
            self.loop_records.append(rec)
        elif f["type"] == T_AUDIT:
            self.audits.append(decode_payload(f["payload"]))
        elif f["type"] == T_CLOSE:
            self.closing_negative = decode_payload(f["payload"])
        elif f["type"] == T_TERM:
            self.session_summary = decode_payload(f["payload"])
            self.epoch_end = self.session_summary.get("epoch_end")
        # T_HB and host-direction types only refresh last_heard

    def crashed_summary(self, counts: dict | None = None, audit: dict | None = None,
                        crc_dropped: int = 0, drop_budget: int = 0) -> dict:
        """The collector-written session_summary for a CRASHED end (§6a)."""
        if self.epoch_end is None or self.epoch_end["kind"] != "CRASHED":
            raise ValueError("crashed_summary is only for a CRASHED end")
        return {"schema": "session_summary", "schema_version": "1.0.0", "token": self.token,
                "epoch_end": dict(self.epoch_end),
                "counts": counts or {"scored": sum(1 for r in self.loop_records if r.get("outcome") == "SCORED"),
                                     "refused_by_gate": sum(1 for r in self.loop_records if r.get("outcome") == "REFUSED_BY_GATE")},
                "closing": {"restore": "not_reached", "baseline": "not_reached", "unsigned_control": "not_reached"},
                "audit": audit or {"audited": 0, "total": len(self.loop_records)},
                "crc_dropped": crc_dropped, "drop_budget": drop_budget, "written_by": "collector"}
