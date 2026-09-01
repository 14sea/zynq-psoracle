#!/usr/bin/env python3
"""Host-paced audit pull with lossless sparse words — the wire state machine, modelled on
the host (design review 2026-09-01, item 3; second review: a REAL state machine, not a
host calling the board's serve()). PROPOSAL: no firmware here; the firmware twin of
`PullBoard` is `firmware/p3_app.c`'s pull state (this batch), checked through the C wire
twin.

Both ends build and parse the same P3L5 lines they will exchange on the console:

    board → host  AUDIT_READY {seq, span, total_words, chunks, nonzero}
    host  → board AUDITGET    {seq, chunk}                       (again on a failed attempt)
    board → host  AUDIT       app_audit_chunk 2.0.0 sparse-v1 (validators.audit)
    host  → board AUDITDONE   {seq}   |   AUDITABORT {seq, why}
    board → host  REC         `verified: audited` iff AUDITDONE was received

Binding (every mismatch is a failed attempt or a refusal, never silently accepted): the
frame token; the frame seq and the payload seq equal to the pending candidate's; the
READY's span/total_words/chunks fixed for the whole transaction and repeated in every
chunk; a reply's chunk equal to the chunk asked for.

Loss and duplication, both ways, modelled by `Channel` scripts: a READY lost → the host
never pulls, the board's bounded idle wait runs out and it aborts itself; a GET lost → the
host's chunk timeout → retry (an attempt, not a CRC drop); a DONE lost → the board aborts
after its idle wait while the host believes the audit complete — the record says
`replayed-only`, the host's mark says `audited`, and rule (ix) refuses the log (HOLD): a
lost DONE is visible, never silent; duplicates of READY/AUDIT/GET/DONE are ignored or
harmless. A malformed line DURING a pending pull is a failed attempt of that chunk (retry),
not the collector's global CRASHED — that rule stays for lines outside a pull.

Retries exhausted, or the CRC budget crossed, → the host sends AUDITABORT; the board (or
its own idle limit) ends the candidate WITHOUT an ARM: on the SCORED path the record is
`STOP_AUDIT` and the epoch stops (restore, TERM); on a non-SCORED path (the §3a
auto-audits) the record goes out with `verified: replayed-only`. The board never waits
for the host without a bound.

Selection is unchanged: the host's AUDITREQ at sign time (all-self-reporting, or the
sampled schedule) makes the board emit READY on the SCORED path; every non-SCORED
self-report emits READY unconditionally (§3a item 2).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
from validators import audit as au  # noqa: E402
from validators.records import Falsified, RecordError  # noqa: E402

MAX_RETRIES = 2                   # per chunk: at most three attempts
CHUNK_TIMEOUT_S = 2.0             # host: wait for a chunk reply
BOARD_IDLE_LIMIT_S = 10.0         # board: wait for the host's next GET/DONE before aborting
BAUD, BITS_PER_BYTE = 115200, 10
T_READY, T_GET, T_DONE, T_ABORT = "AUDIT_READY", "AUDITGET", "AUDITDONE", "AUDITABORT"
AUTO_OUTCOMES = ("STOP_LINK2", "STOP_LINK3", "REFUSED_BY_PL", "STOP_ARM", "STOP_SETTLE", "STOP_AXI")


def wire_seconds(nbytes: int) -> float:
    return nbytes * BITS_PER_BYTE / BAUD


# ------------------------------------------------------------------ the board


class PullBoard:
    """The firmware's pull state, as the C code must implement it (its twin)."""

    def __init__(self, token: str, seq: int, span: str, words: list[int], outcome: str = "SCORED",
                 requested: bool = False, corrupt: dict | None = None):
        self.token, self.seq, self.span, self.words = token, seq, span, list(words)
        self.outcome, self.requested, self.corrupt = outcome, requested, corrupt or {}
        self.state = "IDLE"
        self.audited = False
        self.aborted = False
        self.armed = False
        self.idle_s = 0.0
        self.served: dict[int, int] = {}

    @property
    def needs_audit(self) -> bool:
        """§3a: a SCORED-path candidate is audited iff the host asked at sign time; every
        non-SCORED self-report is audited unconditionally."""
        return self.requested or self.outcome in AUTO_OUTCOMES

    def start(self) -> list[str]:
        if not self.needs_audit:
            return []
        self.state = "PULL"
        self.idle_s = 0.0
        return [n.build_line(T_READY, self.seq, self.token, n.encode_payload(
            {"seq": self.seq, "span": self.span, "total_words": len(self.words),
             "chunks": au.sparse_chunk_count(len(self.words)), "nonzero": sum(1 for w in self.words if w)}))]

    def serve(self, chunk: int) -> str:
        self.served[chunk] = self.served.get(chunk, 0) + 1
        words = list(self.words)
        if chunk in self.corrupt:
            pos, w = self.corrupt[chunk]
            words[pos] = w
        return n.build_line(n.T_AUDIT, self.seq, self.token, n.encode_payload(au.build_sparse_chunk(self.seq, chunk, self.span, words)))

    def on_host_line(self, line: str) -> list[str]:
        """A line from the host while pulling → the lines the board answers with."""
        if self.state != "PULL":
            return []
        try:
            f = n.parse_line(line)
        except (n.CrcError, n.FrameError):
            return []                              # a broken host line: wait for the next
        if f["token"] != self.token or f["seq"] != self.seq:
            return []                              # not this transaction
        self.idle_s = 0.0
        p = n.decode_payload(f["payload"]) if f["payload"] != "-" else {}
        if p.get("seq") != self.seq:
            return []
        if f["type"] == T_GET:
            c = p.get("chunk")
            if isinstance(c, int) and 0 <= c < au.sparse_chunk_count(len(self.words)):
                return [self.serve(c)]
            return []
        if f["type"] == T_DONE:
            self.audited, self.state = True, "DONE"
            return []
        if f["type"] == T_ABORT:
            self._abort()
            return []
        return []

    def tick(self, dt_s: float) -> None:
        if self.state == "PULL":
            self.idle_s += dt_s
            if self.idle_s > BOARD_IDLE_LIMIT_S:
                self._abort()

    def _abort(self) -> None:
        self.audited, self.aborted, self.state = False, True, "ABORTED"

    def finish(self) -> dict:
        """After the pull: the record the board emits, and whether it may ARM. On the SCORED
        path an aborted audit is STOP_AUDIT with NO ARM; a non-SCORED path keeps its outcome
        with `replayed-only`."""
        if self.state == "PULL":
            raise RuntimeError("finish() before the pull ended")
        if self.outcome == "SCORED":
            if self.aborted or (self.needs_audit and not self.audited):
                return {"outcome": "STOP_AUDIT", "verified": "replayed-only", "arm": False, "epoch": "STOPPED", "restore": True}
            self.armed = True
            return {"outcome": "SCORED", "verified": "audited" if self.audited else "replayed-only", "arm": True, "epoch": "RUNNING"}
        return {"outcome": self.outcome, "verified": "audited" if self.audited else "replayed-only", "arm": False, "epoch": "STOPPED"}


# ------------------------------------------------------------------ the host


@dataclass
class Ledger:
    attempts: list[dict] = field(default_factory=list)
    crc_dropped: int = 0
    timeouts: int = 0
    bytes_rx: int = 0
    bytes_tx: int = 0
    lines_kept: list[str] = field(default_factory=list)

    def note(self, seq, chunk, attempt, outcome, line=None):
        self.attempts.append({"seq": seq, "chunk": chunk, "attempt": attempt, "outcome": outcome})
        if line is not None:
            self.lines_kept.append(line)              # every failed attempt kept verbatim
        if outcome == "crc":
            self.crc_dropped += 1
        elif outcome == "timeout":
            self.timeouts += 1


class PullHost:
    """The runner's pull state for one candidate. `send(line)` puts a line on the wire;
    `on_line(line)` takes every inbound line while a pull is pending; `tick(dt)` advances
    the chunk timeout. Ends with `done` (AUDITDONE sent) or `failed` (AUDITABORT sent, the
    reason in `fail_reason`); never blocks, never waits without a bound."""

    def __init__(self, token: str, seq: int, send, crc_budget: int = 10 ** 9, ledger: Ledger | None = None):
        self.token, self.seq, self.send = token, seq, send
        self.crc_budget = crc_budget
        self.ledger = ledger or Ledger()
        self.state = "WAIT_READY"
        self.binding: dict | None = None
        self.chunk = 0
        self.attempt = 0
        self.wait_s = 0.0
        self.verified: dict[int, dict] = {}
        self.done = False
        self.failed = False
        self.fail_reason = ""

    @property
    def pending(self) -> bool:
        """A pull is pending only once READY has bound it: the real runner creates the pull
        on READY, so a lost READY leaves nothing waiting on the host — the board's bounded
        idle wait is what ends that case."""
        return self.state == "WAIT_CHUNK"

    @staticmethod
    def wire_len(line: str) -> int:
        """Bytes on the wire, newline included and counted once — build_line() already ends
        in one; a received line stripped by a reader gets it added back."""
        return len(line) if line.endswith("\n") else len(line) + 1

    def _tx(self, mtype: str, payload: dict) -> None:
        line = n.build_line(mtype, self.seq, self.token, n.encode_payload(payload))
        self.ledger.bytes_tx += self.wire_len(line)
        self.send(line)

    def _get(self) -> None:
        self.wait_s = 0.0
        self._tx(T_GET, {"seq": self.seq, "chunk": self.chunk})

    def _fail(self, why: str) -> None:
        self.failed, self.fail_reason, self.state = True, why, "FAILED"
        self._tx(T_ABORT, {"seq": self.seq, "why": why})

    def _attempt_failed(self, outcome: str, line: str | None) -> None:
        self.ledger.note(self.seq, self.chunk, self.attempt, outcome, line)
        if self.ledger.crc_dropped > self.crc_budget:
            self._fail(f"PROTOCOL_CRC_BUDGET: {self.ledger.crc_dropped} > {self.crc_budget}")
            return
        if self.attempt >= MAX_RETRIES:
            self._fail(f"chunk {self.chunk}: {MAX_RETRIES + 1} attempts failed — audit incomplete (HOLD)")
            return
        self.attempt += 1
        self._get()

    def on_line(self, line: str) -> None:
        if self.state not in ("WAIT_READY", "WAIT_CHUNK"):
            return
        self.ledger.bytes_rx += self.wire_len(line)
        try:
            f = n.parse_line(line)
        except n.CrcError:
            if self.state == "WAIT_CHUNK":
                self._attempt_failed("crc", line)
            return                                    # a broken READY: the board resends nothing; we keep waiting
        except n.FrameError:
            if self.state == "WAIT_CHUNK":
                self._attempt_failed("malformed", line)   # a failed attempt, NOT the collector's CRASHED
            return
        if f["token"] != self.token or f["seq"] != self.seq:
            if self.state == "WAIT_CHUNK":
                self._attempt_failed("wrong-frame-seq-or-token", line)
            return
        p = n.decode_payload(f["payload"]) if f["payload"] != "-" else {}
        if self.state == "WAIT_READY":
            if f["type"] != T_READY:
                return
            if p.get("seq") != self.seq or p.get("span") not in au.SPAN_WORDS \
                    or p.get("total_words") != au.SPAN_WORDS.get(p.get("span")) \
                    or p.get("chunks") != au.sparse_chunk_count(p.get("total_words", 0)):
                self._fail(f"AUDIT_READY not bound to seq {self.seq} or inconsistent: {p}")
                return
            self.binding = {"span": p["span"], "total_words": p["total_words"], "chunks": p["chunks"]}
            self.state, self.chunk, self.attempt = "WAIT_CHUNK", 0, 0
            self._get()
            return
        # WAIT_CHUNK
        if f["type"] == T_READY:
            return                                    # a duplicate READY is ignored
        if f["type"] != n.T_AUDIT:
            return                                    # HB etc. are the collector's
        b = self.binding
        try:
            if p.get("seq") != self.seq:
                raise RecordError("payload seq is not this transaction's")
            if p.get("chunk") != self.chunk:
                raise RecordError(f"reply is chunk {p.get('chunk')}, asked for {self.chunk}")
            if (p.get("span"), p.get("total_words"), p.get("chunks")) != (b["span"], b["total_words"], b["chunks"]):
                raise RecordError("chunk does not repeat the READY's span/total_words/chunks")
            au.check_sparse_chunk(p)                  # shape, window, entries strictness (completeness comes at the end)
        except RecordError as exc:
            self._attempt_failed(f"mismatch: {exc}", line)
            return
        self.ledger.note(self.seq, self.chunk, self.attempt, "ok")
        self.verified[self.chunk] = p
        if self.chunk + 1 < b["chunks"]:
            self.chunk, self.attempt = self.chunk + 1, 0
            self._get()
        else:
            self.done, self.state = True, "DONE"
            self._tx(T_DONE, {"seq": self.seq})

    def tick(self, dt_s: float) -> None:
        if self.state != "WAIT_CHUNK":
            return
        self.wait_s += dt_s
        if self.wait_s > CHUNK_TIMEOUT_S:
            self._attempt_failed("timeout", None)

    def chunks(self) -> list[dict]:
        return [self.verified[c] for c in sorted(self.verified)]


# ------------------------------------------------------------------ the channel


@dataclass
class Fault:
    """A scripted fault on the k-th transmission (attempt) of a frame, by direction and
    type. `drop`: the line never arrives. `delete`: `length` bytes at `offset` vanish; an
    offset past the line's end takes the newline and the head of the NEXT line with it
    (C1 #1's shape). `dup`: the line arrives twice."""
    direction: str            # "b2h" | "h2b"
    mtype: str
    chunk: int | None = None
    attempt: int = 0
    kind: str = "delete"      # drop | delete | dup
    offset: int = 0
    length: int = 0


class Simulation:
    """Runs one candidate's pull between a PullBoard and a PullHost over a faulty channel;
    time advances by the bytes on the wire and by explicit idle ticks."""

    def __init__(self, board: PullBoard, host_kw: dict | None = None, faults: list[Fault] = ()):
        self.board = board
        self.faults = list(faults)
        self.seen: dict[tuple, int] = {}
        self.to_board: list[str] = []
        self.host_sent: list[str] = []            # every line the host put on the wire, in order

        def send(line: str) -> None:
            self.host_sent.append(line)
            self.to_board.append(line)
        self.host = PullHost(board.token, board.seq, send=send, **(host_kw or {}))
        self.t = 0.0
        self.delivered_b2h: list[str] = []

    def _key(self, direction, line):
        try:
            f = n.parse_line(line); p = n.decode_payload(f["payload"]) if f["payload"] != "-" else {}
            return (direction, f["type"], p.get("chunk"))
        except Exception:  # noqa: BLE001
            return (direction, "?", None)

    def _apply(self, direction: str, lines: list[str]) -> list[str]:
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            key = self._key(direction, line)
            k = self.seen.get(key, 0); self.seen[key] = k + 1
            hit = [f for f in self.faults if f.direction == direction and f.mtype == key[1]
                   and (f.chunk is None or f.chunk == key[2]) and f.attempt == k]
            self.t += wire_seconds(len(line) + 1)
            if not hit:
                out.append(line); i += 1; continue
            f = hit[0]
            if f.kind == "drop":
                i += 1
            elif f.kind == "dup":
                out += [line, line]; i += 1
            else:
                if f.offset + f.length <= len(line):
                    out.append(line[:f.offset] + line[f.offset + f.length:]); i += 1
                elif i + 1 < len(lines):
                    joined = line + "\n" + lines[i + 1]
                    out.append((joined[:f.offset] + joined[f.offset + f.length:]).replace("\n", ""))
                    i += 2
                else:
                    out.append(line[:f.offset]); i += 1
        return out

    def run(self, max_steps: int = 10_000) -> dict:
        for line in self._apply("b2h", self.board.start()):
            self.delivered_b2h.append(line); self.host.on_line(line)
        steps = 0
        while self.board.state == "PULL" or self.host.pending:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("the pull did not converge")
            progressed = False
            while self.to_board:
                for line in self._apply("h2b", [self.to_board.pop(0)]):
                    progressed = True
                    for reply in self._apply("b2h", self.board.on_host_line(line)):
                        self.delivered_b2h.append(reply)
                        self.host.on_line(reply)
            if not progressed:
                # nothing on the wire: both ends wait — advance time by one host timeout step
                dt = 0.5
                self.t += dt
                self.host.tick(dt)
                self.board.tick(dt)
                if not self.host.pending and self.board.state == "PULL":
                    self.board.tick(BOARD_IDLE_LIMIT_S)      # the host is done/failed: the board waits out its bound
        return {"host_done": self.host.done, "host_failed": self.host.failed, "fail_reason": self.host.fail_reason,
                "board": self.board.finish(), "ledger": self.host.ledger, "seconds": self.t}


def recompute_from_sparse(chunks: list[dict], manifest: dict, oracle: dict) -> dict:
    """Rebuild every word and recompute the three hashes; a mismatch on verified chunks is
    Falsified, exactly as validators.audit.verify does."""
    got = au.assemble(chunks)
    out = {}
    for seq, a in got.items():
        h = au.recompute(a["words"], a["span"], manifest)
        for k in ("staged_stream_sha256", "staged_sha256"):
            if h[k] != oracle[k]:
                raise Falsified(f"seq {seq}: rebuilt words recompute {k} = {h[k][:16]}…, the record claimed {oracle[k][:16]}…")
        if a["span"] == "streams+readback" and h["readback_sha256"] != oracle["readback_sha256"]:
            raise Falsified(f"seq {seq}: rebuilt readback recomputes {h['readback_sha256'][:16]}…, claimed {oracle['readback_sha256'][:16]}…")
        out[seq] = h
    return out


def compare_encodings(words: list[int], token: str, seq: int, span: str) -> dict:
    """Bytes on the wire for one candidate's audit: today's dense push vs the sparse pull
    (READY + GET×n + chunks + DONE), before any retransmission."""
    import base64
    total = len(words)
    dense = 0
    for c in range(au.sparse_chunk_count(total)):
        part = words[c * 384:(c + 1) * 384]
        b64 = base64.urlsafe_b64encode(b"".join(w.to_bytes(4, "big") for w in part)).decode()
        dense += len(n.build_line(n.T_AUDIT, seq, token, n.encode_payload(
            {"chunk": c, "chunks": 8, "schema": "app_audit_chunk", "schema_version": "1.0.0", "seq": seq, "span": span,
             "total_words": total, "word_count": len(part), "word_offset": c * 384, "words": b64})))
    sim = Simulation(PullBoard(token, seq, span, words, requested=True))
    res = sim.run()
    assert res["host_done"]
    sparse = res["ledger"].bytes_rx + res["ledger"].bytes_tx
    longest = max(len(l) for l in sim.delivered_b2h)
    return {"dense": {"bytes": dense, "seconds": wire_seconds(dense)}, "sparse": {"bytes": sparse, "seconds": wire_seconds(sparse)},
            "ratio": sparse / dense if dense else None, "longest_reply_line": longest,
            "nonzero_words": sum(1 for w in words if w), "total_words": total}


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="cost of the sparse pull over a recorded session's complete audits")
    ap.add_argument("evidence_dir", type=Path)
    a = ap.parse_args(argv)
    chunks = json.loads((a.evidence_dir / "audits.json").read_text())["chunks"]
    log = json.loads((a.evidence_dir / "run_log.json").read_text())
    token = log["app_identity"]["token"]
    by_seq: dict[int, list[dict]] = {}
    for c in chunks:
        by_seq.setdefault(c["seq"], []).append(c)
    rows = []
    for seq in sorted(by_seq):
        try:
            a = au.assemble(by_seq[seq])[seq]          # incomplete audits (C1 #3's seq 20, 62) are skipped
        except RecordError:
            continue
        rows.append(compare_encodings(a["words"], token, seq, a["span"]))
    ratios = [r["ratio"] for r in rows]; sp = [r["sparse"]["bytes"] for r in rows]; nz = [r["nonzero_words"] for r in rows]
    print(json.dumps({"complete_audits": len(rows), "ratio_min_max": [min(ratios), max(ratios)], "sparse_bytes_min_max": [min(sp), max(sp)],
                      "nonzero_min_max": [min(nz), max(nz)], "longest_reply_line": max(r["longest_reply_line"] for r in rows)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
