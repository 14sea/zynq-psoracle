#!/usr/bin/env python3
"""Host-only session soak of the rel-v4 line over a modelled channel — the S #2 fault class
(contiguous byte deletion that crosses frame boundaries: HB tail + REC head) injected
into WHOLE sessions of the board twins driven against the real host stack (reader,
ConsoleSession, Collector, NotaryRelay, Timeline), with the v0.7 candidate gates run over
the artefacts the session leaves.

    l6_session_soak.py [--seed S] [--candidates N] [--p-fault P] [--policy ledger|crash]
                       [--out evidence/l6_session_soak/<name>.json]

The board is the composition of the twins the firmware batch already proved against the
C twins: IdentBoard → per seq SignBoard (SIGNREQ ↔ SIGNOK/SIGNGET) → 16 indexed HB →
ReadyBoard (the sampled pull) when the SIGNOK asked → RecBoard (REC ↔ RECACK/RECGET, the
same bytes resent on the bound, ≤ 3) → TermBoard. Both seq-1 controls are armed (bit4,
bit5). Time is virtual: bytes on the wire at 115200 8N1 plus the twins' bounds.

The channel, board→host, applies at most one fault per line with probability p_fault:
    delete_run   a contiguous run of L bytes (50..900) vanishes starting inside the line
                 and, when L exceeds what is left of it, continuing into the FOLLOWING
                 lines — S #2's shape (HB #12's tail + HB #13–#15 + REC's head + body),
                 S #1's (an interior run of a REC), C1 #3's (inside an audit burst).
                 The run is a burst ON THE WIRE: its remainder expires when the board
                 stops transmitting for CARRY_MAX_GAP_S, so it can never eat a line the
                 board sends seconds later on a transaction's bound (without that bound
                 one scripted run swallowed three AUDIT_READY resends 50 s apart — a
                 model artefact, not a transport fault)
    truncate     the tail of the line, terminator included, never arrives (C1 #5)
    crc          one body byte flipped: a complete line with a bad CRC (C2 #2's two)
    dup          the line arrives twice
    drop         the line never arrives
Host→board lines are dropped with probability p_h2b (an ACK lost: the board resends).

What is claimed, and only this: under the v0.7 candidate console policy ("ledger") a
session survives every fault the transactions cover and ends on the board's TERM with
every record accepted once, and the v0.7 gates (REC closure, rel-v4 closure, the two
controls, the record-budget heartbeat rule, the bad-frame bound) say what they say about
the artefacts; under the v0.6 policy ("crash") the same bytes end the epoch at the first
malformed non-transaction line — the discrimination control. Per fault: the line types
it hit, the seq, and whether that seq's record was accepted afterwards. The soak measures
the HOST mechanism over a modelled channel; it measures nothing about CH340/usbipd.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_checks as lc  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_reader as lrd  # noqa: E402
import l6_rec as rx  # noqa: E402
import l6_rel as rel  # noqa: E402
import l6_timing as lt  # noqa: E402
import l6_transport_soak as tsoak  # noqa: E402

TOOL_VERSION = "l6_session_soak.py/0.1.0"
TOKEN = "6b" * 16
FAULT_KINDS = ("delete_run", "truncate", "crc", "dup", "drop")
FAULT_WEIGHTS = (0.5, 0.15, 0.2, 0.05, 0.1)
# a deletion run is a burst on the wire: after this much transmit-idle its remainder is over
CARRY_MAX_GAP_S = 0.05
SIGN_ANSWER = {"commit": "a" * 64, "expected_tables": ["0" * 16] * 6, "tag": "b" * 32}
WORDS = [0] * 2814
for _i in (5, 700, 1400, 2813):
    WORDS[_i] = 0x1234_5678 ^ _i
BASELINE = [18, 22, 20, 20, 20, 18]


def wire_s(nbytes: int) -> float:
    return nbytes * 10 / 115200


# ------------------------------------------------------------------ the board


class Board:
    """The rel-v4 application over one session: the twins composed."""

    def __init__(self, token: str, n_candidates: int, audit_seqs: set[int], controls: bool = True):
        self.token, self.n, self.audit_seqs, self.controls = token, n_candidates, audit_seqs, controls
        self.records_total = n_candidates + 2
        self.seq = 0
        self.phase = "IDENT"
        self.tx = None                      # the current transaction twin
        self.pull: rel.ReadyBoard | None = None
        self.records: list[dict] = []
        self.stopped: str | None = None
        self.done = False
        self.stats = {"sign_attempts": 0, "rec_attempts": 0, "ready_sent": 0, "waits_sent": 0, "term_attempts": 0}
        self.ident_line = n.build_line(n.T_IDENT, 0, token, n.encode_payload(
            {"schema": "app_identity", "schema_version": "1.3.0", "control_plane": "standalone", "token": token,
             "protocol": "rel-v4", "master_seed": 7, "schedule_mode": "abba", "operator_data_sha256": "0" * 64,
             "rec_retry_control": controls, "sign_retry_control": controls, "pss_idcode": "0x13722093",
             "uboot_epoch": 0, "carrier_sha256": "1" * 64, "nonce_at_start": "2" * 16, "findings": [],
             "app_epoch": 0, "status_at_start": "0x0"}))

    # -- lines the board emits
    def start(self) -> list[str]:
        self.tx = rel.IdentBoard(self.token, self.ident_line)
        return self.tx.start()

    def _signreq(self, seq: int) -> str:
        return n.build_line(n.T_SIGNREQ, seq, self.token, n.encode_payload(
            {"seq": seq, "token": self.token, "genome": "0" * 80, "nonce": f"{seq:016x}", "app_epoch": 0,
             "schema": "sign_request", "schema_version": "1.0.0"}))

    def _record(self, seq: int, audited: bool) -> dict:
        arm = None if seq in (1, self.records_total) else ("random_safe" if (seq // 2) % 2 == 0 else "map_guided")
        rec = {"schema": "loop_record", "schema_version": "1.1.0", "seq": seq, "outcome": "SCORED",
               "verified": "audited" if audited else "replayed-only", "genome": "0" * 80,
               "evidence": {"score": {"scores": list(BASELINE) if arm is None else [17, 21, 20, 20, 19, 18]},
                            "arm": {"settle": {"polls": 16}}}}
        if arm is not None:
            rec["arm"] = arm
        return rec

    def _begin_sign(self) -> list[str]:
        self.seq += 1
        self.phase = "SIGN"
        line = self._signreq(self.seq)
        self.tx = rel.SignBoard(self.token, self.seq, line)
        out = self.tx.start()
        self.stats["sign_attempts"] += 1
        if self.controls and self.seq == 1:
            out = [rx.corrupt_crc(out[0])]          # the forced SIGNREQ-retry control (bit5)
        return out

    def _after_sign(self) -> list[str]:
        hb = [rel.hb_line(self.token, self.seq, i) for i in range(rel.HB_PER_RECORD)]
        if self.tx.reply_type == n.T_SIGNOK and self.tx.audit_requested:
            self.phase = "PULL"
            self.pull = rel.ReadyBoard(self.token, self.seq, "streams+readback", WORDS, requested=True)
            out = self.pull.start()
            self.stats["ready_sent"] += 1
            return hb + out
        return hb + self._begin_rec(audited=False)

    def _begin_rec(self, audited: bool) -> list[str]:
        self.phase = "REC"
        rec = self._record(self.seq, audited)
        self.records.append(rec)
        line = n.build_line(n.T_REC, self.seq, self.token, n.encode_payload(rec))
        self.tx = rx.RecBoard(self.token, self.seq, line, corrupt_first=self.controls and self.seq == 1)
        self.stats["rec_attempts"] += 1
        return self.tx.start()

    def _term(self, kind: str, reason: str) -> list[str]:
        self.phase = "TERM"
        p = {"schema": "session_summary", "schema_version": "1.0.0", "token": self.token,
             "epoch_end": {"kind": kind, "last_seq": self.seq if kind != "COMPLETED" else self.records_total, "reason": reason},
             "counts": {"scored": len(self.records), "refused_by_gate": 0},
             "closing": {"restore": "done", "baseline": "done", "unsigned_control": "done"} if kind == "COMPLETED"
             else {"restore": "done", "baseline": "not_reached", "unsigned_control": "not_reached"},
             "audit": {"audited": sum(1 for r in self.records if r["verified"] == "audited"), "total": len(self.records)},
             "crc_dropped": 0, "drop_budget": 0, "written_by": "app"}
        if kind == "COMPLETED":
            p["closing_control"] = {"fault": 13, "kind": "unsigned", "status": "0x00000982",
                                    "nonce_before": "3" * 16, "nonce_after": "4" * 16}
        self.tx = rel.TermBoard(self.token, self.records_total + 1, n.build_line(n.T_TERM, self.records_total + 1, self.token, n.encode_payload(p)))
        self.stats["term_attempts"] += 1
        close = [n.build_line(n.T_CLOSE, self.records_total + 1, self.token, n.encode_payload(p["closing_control"]))] if kind == "COMPLETED" else []
        return close + self.tx.start()

    def _advance(self) -> list[str]:
        """The current transaction ended: what comes next."""
        tx = self.tx
        if self.phase == "IDENT":
            if not tx.acked:
                self.stopped = "STOP_IDENT"; return self._term("STOPPED", "STOP_IDENT")
            return self._begin_sign()
        if self.phase == "SIGN":
            if not tx.acked:
                self.stopped = "STOP_SIGN"; return self._term("STOPPED", "STOP_SIGN")
            return self._after_sign()
        if self.phase == "REC":
            if not tx.acked:
                self.stopped = "STOP_REC"; return self._term("STOPPED", "STOP_REC")
            if self.seq >= self.records_total:
                return self._term("COMPLETED", "budget")
            return self._begin_sign()
        if self.phase == "TERM":
            self.done = True
            return []
        return []

    def on_host_line(self, line: str) -> list[str]:
        out: list[str] = []
        if self.phase == "PULL" and self.pull is not None:
            served = self.pull.on_host_line(line)
            out += served
            if self.pull.state != "PULL":
                audited = self.pull.audited
                self.pull = None
                out += self._begin_rec(audited)
            return out
        if self.tx is None or self.done:
            return out
        replies = self.tx.on_host_line(line)
        if replies:
            if self.phase == "SIGN":
                self.stats["sign_attempts"] += 1
            elif self.phase == "REC":
                self.stats["rec_attempts"] += 1
            elif self.phase == "TERM":
                self.stats["term_attempts"] += 1
        out += replies
        if self.tx.state in ("DONE", "EXHAUSTED"):
            out += self._advance()
        return out

    def tick(self, dt: float) -> list[str]:
        out: list[str] = []
        if self.done:
            return out
        if self.phase == "PULL" and self.pull is not None:
            lines = self.pull.tick(dt)
            for l in lines:
                t, _ = rx.head_fields(l)
                if t == ap.T_READY:
                    self.stats["ready_sent"] += 1
                elif t == rel.T_AUDITWAIT:
                    self.stats["waits_sent"] += 1
            out += lines
            if self.pull.state != "PULL":
                audited = self.pull.audited
                self.pull = None
                out += self._begin_rec(audited)
            return out
        if self.tx is None:
            return out
        lines = self.tx.tick(dt)
        if lines:
            if self.phase == "SIGN":
                self.stats["sign_attempts"] += 1
            elif self.phase == "REC":
                self.stats["rec_attempts"] += 1
            elif self.phase == "TERM":
                self.stats["term_attempts"] += 1
        out += lines
        if self.tx.state in ("DONE", "EXHAUSTED"):
            out += self._advance()
        return out


# ------------------------------------------------------------------ the faulty channel


class FaultyWire:
    """Board→host bytes with at most one fault per line; a deletion run may carry into
    the following lines. Records every fault with the frame types and seqs it touched."""

    def __init__(self, rng: random.Random, p_fault: float, faults: list[dict], scripted: list[dict] | None = None):
        self.rng, self.p_fault, self.faults = rng, p_fault, faults
        self.carry = 0                       # bytes of a deletion run still to eat from the next lines
        self.carry_fault: dict | None = None
        self.carry_until: float = 0.0        # the burst ends when the wire goes idle this long
        # scripted faults: {"type": "HB", "seq": 10, "hb_i": 12, "kind": "delete_run", "offset": 60, "length": 850}
        # — applied to the FIRST line matching type/seq(/hb_i), then spent
        self.scripted = list(scripted or [])

    @staticmethod
    def _hb_i(line: str) -> int | None:
        try:
            f = n.parse_line(line)
            return n.decode_payload(f["payload"]).get("i") if f["type"] == n.T_HB else None
        except Exception:  # noqa: BLE001
            return None

    def _scripted_for(self, line: str, typ, seq) -> dict | None:
        for i, s in enumerate(self.scripted):
            if s["type"] == typ and s["seq"] == seq and ("hb_i" not in s or s["hb_i"] == self._hb_i(line)):
                return self.scripted.pop(i)
        return None

    @staticmethod
    def _head(line: str) -> tuple[str | None, int | None]:
        return rx.head_fields(line)

    def apply(self, line: str, t: float) -> bytes:
        data = line.encode()
        typ, seq = self._head(line)
        if self.carry and t > self.carry_until:
            self.carry, self.carry_fault = 0, None       # the burst ended: the wire went idle
        if self.carry:
            self.carry_until = t + CARRY_MAX_GAP_S
            k = min(self.carry, len(data))
            self.carry_fault["hit"].append({"type": typ, "seq": seq, "bytes": k, "whole": k == len(data)})
            data = data[k:]
            self.carry -= k
            if self.carry == 0:
                self.carry_fault = None
            return data
        script = self._scripted_for(line, typ, seq)
        if script is None and self.rng.random() >= self.p_fault:
            return data
        kind = script["kind"] if script else self.rng.choices(FAULT_KINDS, FAULT_WEIGHTS)[0]
        fault = {"t": t, "kind": kind, "hit": [{"type": typ, "seq": seq}], "seq": seq, "scripted": script is not None}
        self.faults.append(fault)
        if kind == "drop":
            return b""
        if kind == "dup":
            return data + data
        if kind == "crc":
            i = self.rng.randint(5, max(5, len(data) - 12))
            b = bytearray(data); b[i] = ord("A") if b[i] != ord("A") else ord("B")
            return bytes(b)
        if kind == "truncate":
            cut = self.rng.randint(1, max(1, len(data) - 2))
            fault["hit"][0]["bytes"] = len(data) - cut
            return data[:cut]
        # delete_run
        length = script["length"] if script else self.rng.randint(50, 900)
        off = script["offset"] if script else self.rng.randint(1, max(1, len(data) - 1))
        off = min(off, len(data) - 1)
        eaten = min(length, len(data) - off)
        fault["hit"][0].update({"bytes": eaten, "offset": off, "length": length})
        rest = length - eaten
        if rest > 0:
            self.carry, self.carry_fault, self.carry_until = rest, fault, t + CARRY_MAX_GAP_S
        return data[:off] + data[off + eaten:]


# ------------------------------------------------------------------ the session


class SessionSoak:
    def __init__(self, seed: int, candidates: int, p_fault: float, p_h2b: float, policy: str,
                 controls: bool = True, scripted: list[dict] | None = None):
        self.rng = random.Random(seed)
        self.seed, self.candidates, self.p_fault, self.p_h2b, self.policy = seed, candidates, p_fault, p_h2b, policy
        self.now = 1000.0
        clock = lambda: self.now  # noqa: E731
        n_records = candidates + 2
        import l6_schedule as ls
        self.audit_seqs = ls.sampled_audit_seqs(candidates)
        expected = ls.expected_frames(candidates, self.audit_seqs, "rel-v4")
        self.crc_budget = ls.crc_budget(expected["total"])
        self.collector = n.Collector(TOKEN, heartbeat_s=10, clock=clock)
        self.relay = n.NotaryRelay(TOKEN, lambda req: dict(SIGN_ANSWER), drop_budget=self.crc_budget, clock=clock)
        self.timeline = lt.Timeline()
        self.channel = tsoak.Channel()
        self.reader = lrd.L6LineReader(self.channel, clock_mono=clock, clock_wall=clock)
        self.to_board: list[tuple[float, str]] = []
        self.host_sent: list[str] = []
        self.faults: list[dict] = []
        self.wire = FaultyWire(self.rng, p_fault, self.faults, scripted=scripted)
        self.wire_free_at = self.now
        self.board = Board(TOKEN, candidates, self.audit_seqs, controls=controls)
        self.h2b_dropped = 0

        def send(line: str, mtype: str, seq: int) -> None:
            self.host_sent.append(line)
            self.timeline.note_sent(mtype, seq, self.now, self.now)
            if self.rng.random() < self.p_h2b:
                self.h2b_dropped += 1
                return
            self.to_board.append((self.now + wire_s(len(line)), line))
            self.to_board.sort(key=lambda x: x[0])

        self.cs = lcs.ConsoleSession(TOKEN, self.collector, self.relay, self.timeline, self.audit_seqs, self.crc_budget,
                                     send=send, reader=self.reader, clock=clock, protocol="rel-v4",
                                     identity_check=lambda ident: [], bad_frame_policy=policy,
                                     bad_frame_budget=self.crc_budget if policy == lcs.BAD_FRAME_LEDGER else None)
        self.n_records = n_records

    def _emit(self, lines: list[str]) -> None:
        for line in lines:
            data = self.wire.apply(line, self.now)
            if not data:
                continue
            t0 = max(self.now, self.wire_free_at)
            for t, piece in tsoak._split_pieces(self.rng, data, t0):
                self.channel.schedule(t, piece)
            self.wire_free_at = t0 + wire_s(len(data))

    def _host_poll(self) -> None:
        self.channel.release(self.now)
        while self.channel.ready:
            for line, tm, tw in self.reader.poll():
                self.cs.on_line(line, tm, tw)
        self.cs.tick()
        self.collector.poll()

    def _host_open(self) -> bool:
        return self.collector.epoch_end is None or self.cs.lingering(self.now)

    def run(self, max_virtual_s: float = 8.0 * 3600) -> dict:
        self._emit(self.board.start())
        t_end = self.now + max_virtual_s
        last_progress = self.now
        while self.now < t_end:
            if self.board.done and not self.channel.pending and not self.channel.ready and not self.to_board:
                break
            if not self._host_open() and self.board.done:
                break
            nxt = [t for t in (self.channel.next_time(), self.to_board[0][0] if self.to_board else None) if t is not None]
            if nxt:
                step = min(nxt) - self.now
                if step > 0.5:
                    step = 0.5
                self.now += max(step, 0.0)
                self._host_poll()
                while self.to_board and self.to_board[0][0] <= self.now:
                    _, line = self.to_board.pop(0)
                    self._emit(self.board.on_host_line(line))
                self._emit(self.board.tick(max(step, 0.0)))
            else:
                self.now += 0.5
                self._host_poll()
                self._emit(self.board.tick(0.5))
            if self.board.done and self.collector.epoch_end is not None and not self.cs.lingering(self.now):
                break
        return self.report()

    def report(self) -> dict:
        log = {"loop_records": self.collector.loop_records, "app_identity": self.collector.app_identity,
               "session_summary": self.collector.session_summary or {"written_by": "collector",
                                                                     "epoch_end": self.collector.epoch_end or {"kind": "OPEN"}}}
        rel_ledgers = self.cs.rel_ledgers_json()
        pulls = self.cs.pull_ledgers
        gates = {}
        if self.collector.session_summary is not None:
            gates["structural_v07"] = lc.structural_findings(log, self.collector.audits, self.audit_seqs, self.timeline.frames,
                                                            protocol="rel-v4", hb_rule="v07")
            gates["structural_v06"] = lc.structural_findings(log, self.collector.audits, self.audit_seqs, self.timeline.frames,
                                                            protocol="rel-v4", hb_rule="v06")
            gates["rec_closure"] = lc.rec_closure_findings(log, self.cs.rec_ledgers_json())
            gates["rec_control"] = lc.rec_control_findings(self.cs.rec_ledgers_json(), self.board.controls)
            gates["rel_closure"] = lc.rel_closure_findings(log, rel_ledgers, pulls)
            gates["rel_control"] = lc.rel_control_findings(rel_ledgers.get("signs") or [], self.board.controls)
            gates["baseline"] = lc.baseline_findings(log)
        accepted = {r["seq"] for r in self.collector.loop_records}
        for f in self.faults:
            f["accepted_after"] = f["seq"] in accepted if f.get("seq") else None
        hb_missing = 0
        seen: dict[int, set] = {}
        for fr in self.timeline.frames:
            if fr.get("dir") == "rx" and fr.get("type") == n.T_HB and fr.get("hb_i") is not None:
                seen.setdefault(fr["seq"], set()).add(fr["hb_i"])
        records_missing = [s for s in accepted if len(seen.get(s, set())) < 16]
        return {"tool": TOOL_VERSION, "seed": self.seed, "candidates": self.candidates, "records": self.n_records,
                "p_fault": self.p_fault, "p_h2b": self.p_h2b, "policy": self.policy, "crc_budget": self.crc_budget,
                "epoch_end": self.collector.epoch_end, "board_done": self.board.done, "board_stopped": self.board.stopped,
                "records_accepted": len(accepted), "virtual_s": self.now - 1000.0,
                "bad_frames": self.timeline.bad_frames, "crc_dropped": self.timeline.crc_dropped,
                "crc_dropped_by_type": dict(self.timeline.crc_dropped_by_type), "fragments": len(self.timeline.fragments),
                "faults": len(self.faults), "faults_by_kind": {k: sum(1 for f in self.faults if f["kind"] == k) for k in FAULT_KINDS},
                "faults_crossing_lines": sum(1 for f in self.faults if len(f["hit"]) > 1),
                "faults_into_rec": sum(1 for f in self.faults if any(h["type"] == n.T_REC for h in f["hit"])),
                "faults_unrecovered": [f for f in self.faults if f.get("accepted_after") is False],
                "h2b_dropped": self.h2b_dropped, "board_stats": self.board.stats,
                "rec_gets_sent": sum(l.gets_sent for l in self.cs.rec_ledgers.values()),
                "rec_attempt_histogram": {str(k): v for k, v in sorted(
                    __import__("collections").Counter(len(l.attempts) for l in self.cs.rec_ledgers.values()).items())},
                "records_missing_heartbeats": sorted(records_missing), "gates": gates,
                "fault_log": self.faults}


def run_matrix(seeds, candidates, p_fault, p_h2b, policies=(lcs.BAD_FRAME_LEDGER, lcs.BAD_FRAME_CRASH)) -> dict:
    runs = []
    for seed in seeds:
        for policy in policies:
            r = SessionSoak(seed, candidates, p_fault, p_h2b, policy).run()
            r.pop("fault_log", None)
            runs.append(r)
    return {"tool": TOOL_VERSION, "runs": runs}


def main(argv=None) -> int:
    import argparse
    ap_ = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap_.add_argument("--seed", type=int, default=1)
    ap_.add_argument("--seeds", type=int, default=1, help="run seeds seed..seed+seeds-1")
    ap_.add_argument("--candidates", type=int, default=200)
    ap_.add_argument("--p-fault", type=float, default=0.02)
    ap_.add_argument("--p-h2b", type=float, default=0.005)
    ap_.add_argument("--out", type=Path, default=None)
    a = ap_.parse_args(argv)
    out = run_matrix(range(a.seed, a.seed + a.seeds), a.candidates, a.p_fault, a.p_h2b)
    for r in out["runs"]:
        print(f"seed {r['seed']} {r['policy']:6s} end {r['epoch_end']} records {r['records_accepted']}/{r['records']} "
              f"faults {r['faults']} crossing {r['faults_crossing_lines']} into_rec {r['faults_into_rec']} "
              f"bad {r['bad_frames']} crc {r['crc_dropped']} frag {r['fragments']} unrecovered {len(r['faults_unrecovered'])} "
              f"gates_v07 {sum(len(v) for k, v in r['gates'].items() if k != 'structural_v06')}")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
