#!/usr/bin/env python3
"""Host-paced audit pull with lossless sparse words — the next protocol version, as a
pure host model (design review 2026-09-01, item 3). PROPOSAL: nothing here is firmware,
nothing runs on a board, no preregistration is changed.

The problem it answers. Three contiguous byte deletions in 2.3 MB of console traffic, all
inside the ~3 KB audit lines the application streams back-to-back after link 3, and 96 %
of the audited words are zero. Under the current push protocol one lost chunk is a HOLD:
there is no way to ask again, and every zero word costs link time in which the loss can
happen.

The protocol (wire names are proposals; the framing is the existing P3L5 line):

    board:  AUDIT_READY {seq, span, total_words, chunks, nonzero}    after link 3 (or link 2)
    host:   AUDITGET   {seq, chunk}                                  for chunk = 0 .. chunks-1
    board:  AUDIT      {seq, chunk, chunks, span, total_words, encoding: "sparse-v1", entries}
            ... repeated for each AUDITGET; the board serves a chunk as often as asked
    host:   AUDITDONE  {seq}                                         when every chunk verified
    board:  REC        (the record; `verified: audited` iff AUDITDONE was received)

  * a chunk is a fixed window of `WINDOW` word positions of the full span; its `entries`
    are (position, word) pairs for the NON-ZERO words in that window, positions strictly
    ascending and unique, packed as uint16 + uint32 big-endian and base64url'd; an
    unlisted position is zero by definition — lossless, and the host rebuilds ALL
    `total_words` words and recomputes the three hashes exactly as today
    (`validators.audit.recompute`);
  * a chunk whose line fails CRC, is malformed, or does not arrive within `CHUNK_TIMEOUT`
    is asked for again, at most `MAX_RETRIES` more times; every failed attempt is kept
    verbatim in the ledger and counted against the D-s4 CRC budget (a timeout counts as
    an attempt, not as a CRC drop);
  * retries exhausted on any chunk → the candidate's audit is incomplete → HOLD, as now;
  * a chunk that verifies (CRC, shape, ordering) but whose rebuilt words do not recompute
    the record's hashes → `Falsified`, as now: the encoding weakens nothing.

Cost model: bytes and seconds at 115 200 baud, 10 bits per byte, per candidate, including
every retransmitted attempt — so a rate report under this protocol carries its own
retransmission cost.
"""
from __future__ import annotations

import base64
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
from validators import audit as au  # noqa: E402
from validators.records import Falsified, RecordError  # noqa: E402

WINDOW = 384                      # word positions per chunk (the same 8 chunks per full span as today)
MAX_RETRIES = 2                   # per chunk: at most three attempts
CHUNK_TIMEOUT_S = 2.0
BAUD, BITS_PER_BYTE = 115200, 10
T_AUDIT_READY, T_AUDITGET, T_AUDITDONE = "AUDIT_READY", "AUDITGET", "AUDITDONE"
ENCODING = "sparse-v1"


# ------------------------------------------------------------------ the encoding


def encode_entries(words: list[int], window_start: int, window_end: int) -> str:
    """The non-zero words of one window as packed (uint16 position, uint32 word) pairs,
    ascending positions, base64url. Positions are absolute within the span."""
    out = bytearray()
    for pos in range(window_start, min(window_end, len(words))):
        w = words[pos]
        if w:
            out += struct.pack(">HI", pos, w & 0xFFFFFFFF)
    return base64.urlsafe_b64encode(bytes(out)).decode()


def decode_entries(b64: str, window_start: int, window_end: int) -> list[tuple[int, int]]:
    """Strict: base64url alphabet, whole 6-byte pairs, positions inside the window,
    strictly ascending and unique. Anything else is a RecordError (shape), never silently
    accepted — an accepted chunk must mean exactly one set of words."""
    body = b64.rstrip("=")
    bad = set(body) - au._B64
    if bad:
        raise RecordError(f"sparse entries: characters outside base64url: {sorted(bad)}")
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except Exception as exc:  # noqa: BLE001
        raise RecordError(f"sparse entries do not decode: {exc}") from None
    if len(raw) % 6:
        raise RecordError(f"sparse entries: {len(raw)} bytes are not whole (uint16, uint32) pairs")
    entries = [struct.unpack(">HI", raw[i:i + 6]) for i in range(0, len(raw), 6)]
    last = -1
    for pos, word in entries:
        if not window_start <= pos < window_end:
            raise RecordError(f"sparse entries: position {pos} outside the chunk window [{window_start}, {window_end})")
        if pos <= last:
            raise RecordError(f"sparse entries: position {pos} not strictly ascending after {last} (duplicate or disorder)")
        if word == 0:
            raise RecordError(f"sparse entries: position {pos} lists a zero word (unlisted means zero)")
        last = pos
    return entries


def chunk_count(total_words: int) -> int:
    return (total_words + WINDOW - 1) // WINDOW


def build_chunk_payload(seq: int, chunk: int, span: str, words: list[int]) -> dict:
    total = au.SPAN_WORDS[span]
    if len(words) != total:
        raise ValueError(f"{len(words)} words for span {span!r}")
    chunks = chunk_count(total)
    if not 0 <= chunk < chunks:
        raise ValueError("chunk out of range")
    lo, hi = chunk * WINDOW, min((chunk + 1) * WINDOW, total)
    return {"schema": "app_audit_chunk", "schema_version": "2.0.0", "encoding": ENCODING, "seq": seq,
            "chunk": chunk, "chunks": chunks, "span": span, "total_words": total,
            "window": [lo, hi], "entries": encode_entries(words, lo, hi)}


def assemble_sparse(chunks: list[dict]) -> dict[int, dict]:
    """{seq: {"span", "words", "chunks"}} from verified sparse chunks: every chunk 0..n-1
    exactly once (a duplicate that is byte-identical is a retry's echo and is fine),
    windows consistent, entries strict; unlisted positions are zero."""
    by_seq: dict[int, dict[int, dict]] = {}
    for c in chunks:
        for k in ("schema", "schema_version", "encoding", "seq", "chunk", "chunks", "span", "total_words", "window", "entries"):
            if k not in c:
                raise RecordError(f"sparse chunk missing {k!r}")
        if c["schema"] != "app_audit_chunk" or c["schema_version"] != "2.0.0" or c["encoding"] != ENCODING:
            raise RecordError("not a sparse-v1 app_audit_chunk 2.0.0")
        if c["span"] not in au.SPAN_WORDS or c["total_words"] != au.SPAN_WORDS[c["span"]]:
            raise RecordError(f"span/total_words {c['span']!r}/{c['total_words']} not pinned")
        if c["chunks"] != chunk_count(c["total_words"]):
            raise RecordError("chunks disagrees with total_words / WINDOW")
        lo, hi = c["chunk"] * WINDOW, min((c["chunk"] + 1) * WINDOW, c["total_words"])
        if list(c["window"]) != [lo, hi]:
            raise RecordError(f"chunk {c['chunk']} window {c['window']} is not [{lo}, {hi}]")
        prev = by_seq.setdefault(c["seq"], {}).get(c["chunk"])
        if prev is not None and prev != c:
            raise RecordError(f"seq {c['seq']} chunk {c['chunk']} served twice with different content")
        by_seq[c["seq"]][c["chunk"]] = c
    out = {}
    for seq, got in sorted(by_seq.items()):
        any_c = next(iter(got.values()))
        want = set(range(any_c["chunks"]))
        if set(got) != want:
            raise RecordError(f"seq {seq}: chunks present {sorted(got)}, need {sorted(want)}: missing {sorted(want - set(got))}")
        words = [0] * any_c["total_words"]
        for ch in sorted(got):
            lo, hi = got[ch]["window"]
            for pos, w in decode_entries(got[ch]["entries"], lo, hi):
                words[pos] = w
        out[seq] = {"span": any_c["span"], "words": words, "chunks": any_c["chunks"]}
    return out


# ------------------------------------------------------------------ the model


@dataclass
class Deletion:
    """Delete `length` bytes at `offset` of the k-th transmission of chunk `chunk`
    (attempt 0 = the first). `offset` past the line's end deletes across the boundary into
    whatever the board sends next — C1 #1's shape."""
    chunk: int
    attempt: int
    offset: int
    length: int


@dataclass
class Ledger:
    attempts: list[dict] = field(default_factory=list)
    crc_dropped: int = 0
    timeouts: int = 0
    bytes_sent: int = 0
    lines_kept: list[str] = field(default_factory=list)

    def note(self, seq, chunk, attempt, outcome, nbytes, line=None):
        self.attempts.append({"seq": seq, "chunk": chunk, "attempt": attempt, "outcome": outcome, "bytes": nbytes})
        self.bytes_sent += nbytes
        if line is not None:
            self.lines_kept.append(line)            # every failed attempt kept verbatim
        if outcome == "crc":
            self.crc_dropped += 1
        elif outcome == "timeout":
            self.timeouts += 1


class ModelBoard:
    """Serves one candidate's words under the pull protocol; `corrupt` makes a chunk's
    content wrong while its framing stays valid (the Falsified case)."""

    def __init__(self, token: str, seq: int, span: str, words: list[int], corrupt: dict | None = None):
        self.token, self.seq, self.span, self.words = token, seq, span, list(words)
        self.corrupt = corrupt or {}
        self.served: dict[int, int] = {}

    def ready_line(self) -> str:
        nz = sum(1 for w in self.words if w)
        return n.build_line(T_AUDIT_READY, self.seq, self.token, n.encode_payload(
            {"seq": self.seq, "span": self.span, "total_words": len(self.words),
             "chunks": chunk_count(len(self.words)), "nonzero": nz}))

    def serve(self, chunk: int) -> str:
        self.served[chunk] = self.served.get(chunk, 0) + 1
        words = list(self.words)
        if chunk in self.corrupt:
            pos, w = self.corrupt[chunk]
            words[pos] = w
        return n.build_line(n.T_AUDIT, self.seq, self.token, n.encode_payload(build_chunk_payload(self.seq, chunk, self.span, words)))


class ModelHost:
    """Pulls every chunk with retries, keeps the ledger, and returns the verified sparse
    chunks — or raises RecordError (retries exhausted: HOLD) — then the caller recomputes."""

    def __init__(self, token: str, deletions: list[Deletion] = (), crc_budget: int = 10 ** 9,
                 timeouts: set[tuple[int, int]] = frozenset()):
        self.token, self.deletions, self.crc_budget, self.timeouts = token, list(deletions), crc_budget, set(timeouts)
        self.ledger = Ledger()

    def _channel(self, chunk: int, attempt: int, line: str, next_line: str | None) -> tuple[str, str | None]:
        """Applies this attempt's deletions to the bytes as the host would receive them."""
        stream = line
        merged_next = None
        for d in self.deletions:
            if d.chunk == chunk and d.attempt == attempt:
                if d.offset + d.length <= len(line):
                    stream = stream[:d.offset] + stream[d.offset + d.length:]
                elif next_line is not None:
                    # a loss spanning the line boundary: the newline goes and the two lines merge
                    joined = line + next_line
                    stream = joined[:d.offset] + joined[d.offset + d.length:]
                    merged_next = ""           # the next line is consumed into this one
        return stream, merged_next

    def pull(self, board: ModelBoard) -> list[dict]:
        ready = n.parse_line(board.ready_line())
        info = n.decode_payload(ready["payload"])
        verified: dict[int, dict] = {}
        for chunk in range(info["chunks"]):
            for attempt in range(MAX_RETRIES + 1):
                if (chunk, attempt) in self.timeouts:
                    self.ledger.note(board.seq, chunk, attempt, "timeout", 0)
                    continue
                line = board.serve(chunk)
                next_line = board.serve(chunk + 1) if chunk + 1 < info["chunks"] else None
                if next_line is not None:
                    board.served[chunk + 1] -= 1        # only peeked for the boundary model
                received, _ = self._channel(chunk, attempt, line, next_line)
                for rx in received.split("\n"):
                    if not rx:
                        continue
                    try:
                        f = n.parse_line(rx)
                        payload = n.decode_payload(f["payload"])
                        if f["type"] != n.T_AUDIT or payload.get("chunk") != chunk:
                            raise n.FrameError("not the chunk asked for")
                        lo, hi = payload["window"]
                        decode_entries(payload["entries"], lo, hi)      # shape/order strictness
                    except n.CrcError:
                        self.ledger.note(board.seq, chunk, attempt, "crc", len(rx) + 1, rx)
                        if self.ledger.crc_dropped > self.crc_budget:
                            raise RecordError(f"PROTOCOL_CRC_BUDGET: {self.ledger.crc_dropped} > {self.crc_budget}")
                        break
                    except (n.FrameError, RecordError, KeyError, ValueError) as exc:
                        self.ledger.note(board.seq, chunk, attempt, f"malformed: {exc}", len(rx) + 1, rx)
                        self.ledger.crc_dropped += 0    # a malformed line is NOT a CRC drop
                        break
                    else:
                        self.ledger.note(board.seq, chunk, attempt, "ok", len(rx) + 1)
                        verified[chunk] = payload
                        break
                if chunk in verified:
                    break
            else:
                raise RecordError(f"seq {board.seq} chunk {chunk}: {MAX_RETRIES + 1} attempts failed — audit incomplete (HOLD)")
        return [verified[c] for c in sorted(verified)]


def recompute_from_sparse(chunks: list[dict], manifest: dict, oracle: dict) -> dict:
    """Rebuild every word and recompute the three hashes; compare with the record's claim.
    A mismatch on verified chunks is Falsified, exactly as validators.audit.verify does."""
    got = assemble_sparse(chunks)
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


# ------------------------------------------------------------------ the cost model


def cost(bytes_on_wire: int) -> dict:
    return {"bytes": bytes_on_wire, "seconds": bytes_on_wire * BITS_PER_BYTE / BAUD}


def compare_encodings(words: list[int], token: str, seq: int, span: str) -> dict:
    """Bytes on the wire for one candidate's audit: today's dense push vs the sparse pull
    (READY + GET/DONE overhead + chunk lines), before any retransmission."""
    dense = 0
    total = len(words)
    for c in range(chunk_count(total)):
        part = words[c * 384:(c + 1) * 384]
        b64 = base64.urlsafe_b64encode(b"".join(w.to_bytes(4, "big") for w in part)).decode()
        dense += len(n.build_line(n.T_AUDIT, seq, token, n.encode_payload(
            {"chunk": c, "chunks": 8, "schema": "app_audit_chunk", "schema_version": "1.0.0", "seq": seq, "span": span,
             "total_words": total, "word_count": len(part), "word_offset": c * 384, "words": b64})))
    board = ModelBoard(token, seq, span, words)
    sparse = len(board.ready_line()) + sum(len(board.serve(c)) for c in range(chunk_count(total)))
    sparse += chunk_count(total) * len(n.build_line(T_AUDITGET, seq, token, n.encode_payload({"seq": seq, "chunk": 0})))
    sparse += len(n.build_line(T_AUDITDONE, seq, token, n.encode_payload({"seq": seq})))
    return {"dense": cost(dense), "sparse": cost(sparse), "ratio": sparse / dense if dense else None,
            "nonzero_words": sum(1 for w in words if w), "total_words": total}


def main(argv=None) -> int:
    ap = __import__("argparse").ArgumentParser(description="cost of the sparse pull on a recorded session")
    ap.add_argument("evidence_dir", type=Path)
    a = ap.parse_args(argv)
    chunks = json.loads((a.evidence_dir / "audits.json").read_text())["chunks"]
    log = json.loads((a.evidence_dir / "run_log.json").read_text())
    token = log["app_identity"]["token"]
    served = au.assemble([c for c in chunks if c["seq"] == 1])
    words = served[1]["words"]
    print(json.dumps(compare_encodings(words, token, 1, served[1]["span"]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
