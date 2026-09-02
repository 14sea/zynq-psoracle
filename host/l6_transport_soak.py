#!/usr/bin/env python3
"""Host-only replay / fault-injection soak of the console transport — the L6 reader
(`host/l6_reader.py`) and the pull host (`host/l6_audit_pull.PullHost`) driven byte by
byte over a scripted channel (owner's ruling 2026-09-02 after C1 #5, item 4: "a pure host
replay / fault-injection soak, then review").

    l6_transport_soak.py [--seed S] [--candidates N] [--p-fault P] [--timeout-s T]
                         [--no-resync] [--out evidence/l6_transport_soak/<name>.json]

What is simulated. For every candidate a real `PullBoard` (the firmware's pull twin)
serves real sparse chunks built from C1 #5's recorded audit words (evidence, read-only);
the board's lines are turned into BYTES and delivered to the reader through a channel
that (a) splits every delivery into random poll-sized reads — including splits inside the
`P3L5 <TYPE> <seq> <token> ` head — and (b) with probability `p_fault` per board→host
line applies ONE fault:

    truncate      the tail of the line, its terminator included, never arrives (C1 #5's
                  first reply of AUDIT 39 chunk 1: 576 of 652 bytes, no line end)
    interior      a contiguous run of bytes vanishes, the terminator stays (C1 #3, S #1)
    drop          the whole line never arrives
    dup           the line arrives twice, whole
    glued_dup     a truncated copy immediately followed by a whole copy in the same read —
                  the shape of C1 #5's merged 1228-byte line (the old reader's BAD_FRAME)
    late_tail     the tail arrives late: before the host's timeout (a slow half line) or
                  after it (a headless remnant after the quarantine)

Time is virtual (bytes on the wire at 115200 8N1 plus the scripted delays); the host's
chunk deadline is the monotonic one the runner uses. The session's rules are applied as
the runner applies them: only `P3L5` lines reach the pull host; a headless remnant is
console noise; the reader's resync fragments and the pull timeout's quarantine are
recorded. `--no-resync` runs the reader as it was in C1 #5 (no resync, no quarantine) as
the discrimination control.

What is claimed, and only this. Per candidate: whether the pull completed, every chunk's
attempts, timeouts, fragments (by reason), stale duplicates ignored, bad frames, headless
remnants; per injected fault: whether the chunk it hit was verified by the FIRST
transmission after it ("recovered on the first resend") — a chunk hit by a second fault
before that transmission is a double fault and is reported apart, never as a failure of
the mechanism. The soak measures the host mechanism over a modelled channel; it
measures nothing about the CH340/usbipd path itself.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_reader as lrd  # noqa: E402
from validators import audit as au  # noqa: E402

TOOL_VERSION = "l6_transport_soak.py/0.1.0"
DEFAULT_WORDS = R / "evidence/l6_17A6_2026-09-02-01-C1/audits.json"
FAULT_KINDS = ("truncate", "interior", "drop", "dup", "glued_dup", "late_tail")
HEAD_LEN = len("P3L5 AUDIT 39 ") + 32 + 1


class Channel:
    """The fake serial handle: reads are the scheduled byte pieces whose time has come."""

    def __init__(self):
        self.pending: list[tuple[float, bytes]] = []    # (arrival time, bytes), kept sorted
        self.ready: list[bytes] = []

    def schedule(self, t: float, data: bytes) -> None:
        self.pending.append((t, data))
        self.pending.sort(key=lambda x: x[0])

    def next_time(self) -> float | None:
        return self.pending[0][0] if self.pending else None

    def release(self, now: float) -> None:
        while self.pending and self.pending[0][0] <= now:
            self.ready.append(self.pending.pop(0)[1])

    @property
    def in_waiting(self) -> int:
        return len(self.ready[0]) if self.ready else 0

    def read(self, k: int) -> bytes:
        return self.ready.pop(0)


def load_words(path: Path = DEFAULT_WORDS) -> dict[int, dict]:
    chunks = json.loads(path.read_text())["chunks"]
    return au.assemble(chunks)


def _split_pieces(rng: random.Random, data: bytes, t0: float, p_head_split: float = 0.3) -> list[tuple[float, bytes]]:
    """Random poll-sized pieces; with probability p_head_split one boundary falls inside
    the frame head. Each piece arrives when its last byte has crossed the wire."""
    cuts = set()
    k = rng.randint(0, 3)
    for _ in range(k):
        cuts.add(rng.randint(1, max(1, len(data) - 1)))
    if rng.random() < p_head_split and len(data) > HEAD_LEN:
        cuts.add(rng.randint(1, HEAD_LEN))
    cuts = sorted(c for c in cuts if 0 < c < len(data))
    out, prev = [], 0
    for c in cuts + [len(data)]:
        piece = data[prev:c]
        out.append((t0 + ap.wire_seconds(c), piece))
        prev = c
    return out


class CandidateSoak:
    def __init__(self, rng: random.Random, token: str, seq: int, span: str, words: list[int],
                 p_fault: float, timeout_s: float, resync: bool):
        self.rng, self.p_fault, self.timeout_s, self.resync = rng, p_fault, timeout_s, resync
        self.board = ap.PullBoard(token, seq, span, words, requested=True)
        self.chan = Channel()
        self.clock = {"t": 0.0}
        self.reader = lrd.L6LineReader(self.chan, clock_mono=lambda: self.clock["t"], clock_wall=lambda: self.clock["t"],
                                       resync=resync)
        self.to_board: list[str] = []
        self.quarantines: list[dict] = []

        def on_timeout(s, c):
            if not resync:
                return                                   # the C1 #5 reader: nothing was quarantined
            frag = self.reader.quarantine(f"pull timeout: seq {s} chunk {c}")
            if frag:
                self.quarantines.append(frag)
        self.host = ap.PullHost(token, seq, send=self.to_board.append, clock=lambda: self.clock["t"],
                                timeout_s=timeout_s, on_timeout=on_timeout)
        self.faults: list[dict] = []
        self.headless_lines = 0
        self.bad_frames = 0
        self.wire_t = 0.0                                # the board's TX clock (serialised)
        self.tx_index: dict[int, int] = {}               # chunk → transmissions so far

    def _deliver(self, line: str, chunk: int | None) -> None:
        data = (line if line.endswith("\n") else line + "\n").encode()
        data = data.replace(b"\n", b"\r\n")
        start = max(self.wire_t, self.clock["t"])
        fault = None
        if chunk is not None and self.rng.random() < self.p_fault:
            fault = self.rng.choice(FAULT_KINDS)
        k = self.tx_index.get(chunk, 0) if chunk is not None else 0
        if chunk is not None:
            self.tx_index[chunk] = k + 1
        rec = {"chunk": chunk, "transmission": k, "kind": fault}
        if fault == "drop":
            self.wire_t = start + ap.wire_seconds(len(data))
        elif fault == "truncate":
            keep = self.rng.randint(16, len(data) - 3)
            for t, piece in _split_pieces(self.rng, data[:keep], start):
                self.chan.schedule(t, piece)
            self.wire_t = start + ap.wire_seconds(len(data))
            rec["bytes_missing"] = len(data) - keep
        elif fault == "interior":
            off = self.rng.randint(1, len(data) - 12)
            m = self.rng.randint(1, min(200, len(data) - 3 - off))
            cut = data[:off] + data[off + m:]
            for t, piece in _split_pieces(self.rng, cut, start):
                self.chan.schedule(t, piece)
            self.wire_t = start + ap.wire_seconds(len(data))
            rec["bytes_missing"] = m
        elif fault == "dup":
            for t, piece in _split_pieces(self.rng, data + data, start):
                self.chan.schedule(t, piece)
            self.wire_t = start + ap.wire_seconds(2 * len(data))
        elif fault == "glued_dup":
            keep = self.rng.randint(16, len(data) - 3)
            glued = data[:keep] + data
            for t, piece in _split_pieces(self.rng, glued, start):
                self.chan.schedule(t, piece)
            self.wire_t = start + ap.wire_seconds(len(glued))
            rec["bytes_missing"] = len(data) - keep
        elif fault == "late_tail":
            keep = self.rng.randint(16, len(data) - 3)
            late = self.rng.choice([self.timeout_s * 0.5, self.timeout_s * 1.5])
            for t, piece in _split_pieces(self.rng, data[:keep], start):
                self.chan.schedule(t, piece)
            self.chan.schedule(start + ap.wire_seconds(keep) + late, data[keep:])
            self.wire_t = start + ap.wire_seconds(len(data))
            rec["tail_delay_s"] = late; rec["after_timeout"] = late > self.timeout_s
        else:
            for t, piece in _split_pieces(self.rng, data, start):
                self.chan.schedule(t, piece)
            self.wire_t = start + ap.wire_seconds(len(data))
        if fault:
            self.faults.append(rec)

    def _pump_host_lines(self) -> None:
        while self.to_board:
            line = self.to_board.pop(0)
            for reply in self.board.on_host_line(line):
                f = n.parse_line(reply)
                p = n.decode_payload(f["payload"])
                self._deliver(reply, p.get("chunk"))

    def _feed(self) -> None:
        for line, _tm, _tw in self.reader.poll():
            if not line.startswith(n.MAGIC):
                self.headless_lines += 1
                continue
            try:
                n.parse_line(line)
            except n.FrameError:
                self.bad_frames += 1
            except n.CrcError:
                pass
            self.host.on_line(line)
        self.host.tick()

    def run(self, max_virtual_s: float = 600.0) -> dict:
        for line in self.board.start():
            self._deliver(line, None)
        steps = 0
        while not (self.host.done or self.host.failed):
            steps += 1
            if self.clock["t"] > max_virtual_s or steps > 100_000:
                raise RuntimeError("the candidate did not converge")
            self._pump_host_lines()
            nxt = self.chan.next_time()
            dl = self.host.deadline if self.host.state == "WAIT_CHUNK" else None
            targets = [x for x in (nxt, dl) if x is not None]
            if not targets:
                if self.board.state == "PULL":
                    self.board.tick(ap.BOARD_IDLE_LIMIT_S + 1)
                break
            self.clock["t"] = max(self.clock["t"], min(targets))
            self.chan.release(self.clock["t"])
            self._feed()
            self._pump_host_lines()
        # the first-resend claim, per fault that hit a chunk transmission
        for rec in self.faults:
            c, k = rec["chunk"], rec["transmission"]
            if c is None or rec["kind"] in ("dup",):
                rec["first_resend_recovered"] = None      # a whole duplicate needs no resend
                continue
            later = [r2 for r2 in self.faults if r2["chunk"] == c and r2["transmission"] == k + 1]
            att = [a for a in self.host.ledger.attempts if a["chunk"] == c]
            ok_at = [a["attempt"] for a in att if a["outcome"] == "ok"]
            rec["double_fault"] = bool(later)
            # a fault on the LAST permitted transmission (attempt MAX_RETRIES) has no resend
            # to recover on: the pull is exhausted by the retry bound, which is the D-s4 /
            # §6 rule, not this mechanism — reported apart as `no_resend_allowed`
            rec["no_resend_allowed"] = k + 1 > ap.MAX_RETRIES
            # a late tail of ANOTHER chunk that arrives after its timeout is a headless
            # remnant that can land inside this chunk's next transmission (a poll boundary
            # apart) and merge with it — cross-chunk interference, a second fault in effect;
            # reported apart, never counted as a first-resend failure of the mechanism
            rec["late_tail_interference_possible"] = any(
                r2["kind"] == "late_tail" and r2.get("after_timeout") and r2["chunk"] != c for r2 in self.faults)
            if later or rec["no_resend_allowed"]:
                rec["first_resend_recovered"] = None
            else:
                rec["first_resend_recovered"] = bool(ok_at) and min(ok_at) <= k + 1
        return {"seq": self.board.seq, "done": self.host.done, "failed": self.host.failed, "why": self.host.fail_reason,
                "attempts": self.host.ledger.attempts, "timeouts": self.host.ledger.timeouts,
                "duplicates_ignored": len(self.host.ledger.duplicates), "bad_frames": self.bad_frames,
                "headless_lines": self.headless_lines, "fragments": [f["reason"].split(":")[0] for f in self.reader.fragments],
                "faults": self.faults, "virtual_s": self.clock["t"]}


def run_soak(seed: int, candidates: int, p_fault: float, timeout_s: float, resync: bool = True,
             words_path: Path = DEFAULT_WORDS) -> dict:
    rng = random.Random(seed)
    words = load_words(words_path)
    seqs = sorted(words)
    token = "5c" * 16
    per = []
    for i in range(candidates):
        s = seqs[i % len(seqs)]
        c = CandidateSoak(rng, token, s, words[s]["span"], words[s]["words"], p_fault, timeout_s, resync)
        per.append(c.run())
    faults = [f for p in per for f in p["faults"]]
    judged = [f for f in faults if f.get("first_resend_recovered") is not None and not f.get("double_fault")]
    interfered = [f for f in judged if f.get("late_tail_interference_possible")]
    single = [f for f in judged if not f.get("late_tail_interference_possible")]
    by_kind: dict[str, dict] = {}
    for f in faults:
        d = by_kind.setdefault(f["kind"], {"injected": 0, "single": 0, "recovered_first_resend": 0, "double": 0,
                                            "no_resend_allowed": 0, "late_tail_interference_possible": 0,
                                            "recovered_first_resend_despite_interference": 0})
        d["injected"] += 1
        if f.get("no_resend_allowed"):
            d["no_resend_allowed"] += 1
        elif f.get("double_fault"):
            d["double"] += 1
        elif f.get("late_tail_interference_possible"):
            d["late_tail_interference_possible"] += 1
            d["recovered_first_resend_despite_interference"] += int(bool(f["first_resend_recovered"]))
        elif f.get("first_resend_recovered") is not None:
            d["single"] += 1
            d["recovered_first_resend"] += int(f["first_resend_recovered"])
    max_faults_one_chunk = 0
    for p in per:
        cnt: dict[int, int] = {}
        for f in p["faults"]:
            if f["chunk"] is not None:
                cnt[f["chunk"]] = cnt.get(f["chunk"], 0) + 1
        max_faults_one_chunk = max(max_faults_one_chunk, max(cnt.values(), default=0))
    failed = [p for p in per if p["failed"]]
    exhaustible = [p for p in per if any(sum(1 for f in p["faults"] if f["chunk"] == c and f["kind"] != "dup") > ap.MAX_RETRIES
                                         for c in range(9))]
    total = {"tool": TOOL_VERSION, "seed": seed, "candidates": candidates, "p_fault": p_fault, "timeout_s": timeout_s,
             "resync": resync, "words": str(words_path.relative_to(R)),
             "faults_injected": len(faults), "single_faults": len(single),
             "faults_on_the_last_permitted_transmission": sum(1 for f in faults if f.get("no_resend_allowed")),
             "single_faults_with_possible_late_tail_interference": len(interfered),
             "of_which_recovered_on_first_resend": sum(1 for f in interfered if f["first_resend_recovered"]),
             "single_faults_recovered_on_first_resend": sum(1 for f in single if f["first_resend_recovered"]),
             "by_kind": by_kind, "pulls_done": sum(1 for p in per if p["done"]), "pulls_failed": len(failed),
             "failed_with_more_faults_than_retries_on_one_chunk": sum(1 for p in failed if p in exhaustible),
             "timeouts": sum(p["timeouts"] for p in per), "duplicates_ignored": sum(p["duplicates_ignored"] for p in per),
             "bad_frames": sum(p["bad_frames"] for p in per), "headless_lines": sum(p["headless_lines"] for p in per),
             "fragments": sum(len(p["fragments"]) for p in per),
             "fragments_by_reason": {k: sum(p["fragments"].count(k) for p in per) for k in ("resync", "pull timeout")},
             "clean_candidates": sum(1 for p in per if not p["faults"]),
             "clean_candidates_with_any_recovery_artifact": sum(
                 1 for p in per if not p["faults"] and (p["timeouts"] or p["fragments"] or p["bad_frames"]
                                                         or any(a["outcome"] != "ok" for a in p["attempts"]))),
             "virtual_s_total": sum(p["virtual_s"] for p in per),
             "max_faults_on_one_chunk": max_faults_one_chunk}
    return {"schema": "l6_transport_soak", "schema_version": "1.0.0", "total": total, "candidates_detail": per}


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--seed", type=int, default=1278624577)
    a.add_argument("--candidates", type=int, default=2000)
    a.add_argument("--p-fault", type=float, default=0.05)
    a.add_argument("--timeout-s", type=float, default=ap.CHUNK_TIMEOUT_S)
    a.add_argument("--no-resync", action="store_true", help="the C1 #5 reader (discrimination control)")
    a.add_argument("--out", type=Path, default=None)
    a.add_argument("--no-detail", action="store_true", help="write the totals only")
    args = a.parse_args(argv)
    t0 = time.time()
    rep = run_soak(args.seed, args.candidates, args.p_fault, args.timeout_s, resync=not args.no_resync)
    rep["total"]["host_seconds"] = round(time.time() - t0, 1)
    if args.no_detail:
        rep.pop("candidates_detail")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep["total"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
