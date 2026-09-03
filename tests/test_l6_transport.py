"""The C1 #5 transport batch (owner's ruling 2026-09-02, item 4 + item 3), host-only:

  * `host/l6_reader.py` — a torn line (no terminator) followed by a frame head is
    quarantined and the new frame parsed (resync); a pull timeout quarantines the residue;
    a half line across polls, a head split across polls and a payload ending in `P3L5`
    are NOT torn; a late headless tail is console noise; nothing is silently dropped.
  * `host/l6_audit_pull.PullHost` — the chunk timeout is a monotonic deadline armed by the
    GET (not a tick accumulation); the timeout callback runs before the retry; a stale
    byte-identical reply of a verified chunk is ignored, never an attempt.
  * C1 #5's RECORDED BYTES replayed: with the new reader + pull the first resend recovers
    chunk 1 of seq 39 (attempts [timeout, ok]); glued in one read it recovers without a
    timeout; the C1 #5 reader turns the same bytes into the recorded [timeout, malformed,
    ok] — the discrimination control.
  * `ConsoleSession` wiring: fragments reach the timeline as FRAGMENT events; the pull
    ledger carries duplicates.
  * `host/l6_rate.py` — inclusive / nominal / recovery (v0.5 draft §6.3) on C1 #5 and on
    synthetic ledgers; the top-level numbers stay the inclusive ones (v0.4 unchanged).
  * `host/l6_checks.calibration_findings_v05` — every bound named when crossed; the
    runner selects it only when the manifest pins v0.5 (C1 #5 is not re-judged).
  * `host/l6_transport_soak.py` — a seeded fault-injection soak: every single fault
    recovered on the first resend, no clean candidate marked, the C1 #5 reader worse.
"""
from __future__ import annotations

import copy
import inspect
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "tests"))
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import l6_checks as lc  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_rate as lr  # noqa: E402
import l6_reader as lrd  # noqa: E402
import l6_timing as lt  # noqa: E402
import l6_transport_soak as soak  # noqa: E402

C15 = R / "evidence/l6_17A6_2026-09-02-01-C1"
RAW = (C15 / "console.log").read_bytes()
LOG = json.loads((C15 / "run_log.json").read_text())
AUDITS = json.loads((C15 / "audits.json").read_text())
FRAMES = json.loads((C15 / "timeline.json").read_text())["frames"]
TOKEN = LOG["app_identity"]["token"]
MANIFEST = json.loads((R / "manifests/l6_manifest.json").read_text())
INPUTS = {k: __import__("hashlib").sha256((C15 / f).read_bytes()).hexdigest()
          for k, f in (("run_log", "run_log.json"), ("audits", "audits.json"), ("timeline", "timeline.json"))}
DRAFT_PC = {"nominal_cov_max": 0.10, "min_clean_periods": 60, "max_recovered_candidates": 3,
            "max_pull_timeouts": 3, "max_bad_frames": 3, "max_fragments": 3}


def _line_at(i: int) -> bytes:
    return RAW[i:RAW.find(b"\n", i) + 1]


def seq39_segments() -> dict:
    """The recorded board→host bytes of seq 39's audit, cut where the session cut them."""
    tok = TOKEN.encode()
    c1 = b"P3L5 AUDIT 39 " + tok + b" eyJjaHVuayI6MSw"
    i1 = RAW.find(c1); i2 = RAW.find(c1, i1 + 10); e2 = RAW.find(b"\n", i2) + 1
    i3 = RAW.find(c1, e2); e3 = RAW.find(b"\n", i3) + 1
    ir = RAW.find(b"P3L5 AUDIT_READY 39 "); i0 = RAW.find(b"P3L5 AUDIT 39 " + tok + b" eyJjaHVuayI6MCw")
    rest, j = [], e3
    for _ in range(6):
        k = RAW.find(b"P3L5 AUDIT 39 ", j); ln = _line_at(k); rest.append(ln); j = k + len(ln)
    seg = {"ready": _line_at(ir), "chunk0": _line_at(i0), "partial": RAW[i1:i2], "copy2": RAW[i2:e2],
           "copy3": RAW[i3:e3], "rest": rest}
    assert b"\n" not in seg["partial"] and len(seg["partial"]) == 576 and len(seg["copy2"]) == 653
    return seg


SEG = seq39_segments()


class Feed:
    """A fake serial handle whose bytes are pushed by the test as the board 'sends' them."""

    def __init__(self):
        self.q: list[bytes] = []

    def push(self, data: bytes) -> None:
        self.q.append(data)

    @property
    def in_waiting(self) -> int:
        return len(self.q[0]) if self.q else 0

    def read(self, k: int) -> bytes:
        return self.q.pop(0)


class Clk:
    def __init__(self):
        self.t = 1000.0

    def mono(self):
        return self.t

    def wall(self):
        return self.t + 1e9


def reader(resync=True):
    clk, feed = Clk(), Feed()
    return lrd.L6LineReader(feed, clock_mono=clk.mono, clock_wall=clk.wall, resync=resync), feed, clk


def text(b: bytes) -> str:
    return b.decode("ascii", "replace").rstrip("\r\n")


# ------------------------------------------------------------------ the reader


class ReaderResync(unittest.TestCase):
    def test_a_torn_line_followed_by_a_frame_head_is_quarantined_and_the_new_frame_parsed(self):
        rd, feed, clk = reader()
        feed.push(SEG["partial"] + SEG["copy2"])
        lines = rd.poll()
        self.assertEqual([l for l, _, _ in lines], [text(SEG["copy2"])])
        n.parse_line(lines[0][0])                                 # the resend is a valid frame
        self.assertEqual(len(rd.fragments), 1)
        frag = rd.fragments[0]
        self.assertEqual(frag["bytes"], 576); self.assertTrue(frag["reason"].startswith("resync"))
        self.assertEqual(frag["text"].encode(), SEG["partial"], "the fragment is kept verbatim")
        self.assertEqual(bytes(rd.raw), SEG["partial"] + SEG["copy2"], "raw stays verbatim too")
        self.assertEqual(rd.take_fragments(), [frag]); self.assertEqual(rd.take_fragments(), [])

    def test_the_c1_5_reader_turns_the_same_bytes_into_one_merged_bad_line(self):
        rd, feed, clk = reader(resync=False)
        feed.push(SEG["partial"] + SEG["copy2"])
        lines = rd.poll()
        self.assertEqual(len(lines), 1); self.assertEqual(len(lines[0][0]), 1228)
        with self.assertRaises(n.FrameError):
            n.parse_line(lines[0][0])
        self.assertEqual(rd.fragments, [])

    def test_a_half_line_across_polls_is_completed_not_torn(self):
        rd, feed, clk = reader()
        feed.push(SEG["copy2"][:300]); feed.push(SEG["copy2"][300:])
        self.assertEqual(rd.poll(), [])
        clk.t += 0.05
        lines = rd.poll()
        self.assertEqual([l for l, _, _ in lines], [text(SEG["copy2"])]); self.assertEqual(rd.fragments, [])
        self.assertEqual(lines[0][1], clk.t, "stamped by the read that completed it")

    def test_a_head_split_across_polls_is_not_a_head_until_it_completes(self):
        rd, feed, clk = reader()
        feed.push(SEG["partial"] + SEG["copy2"][:7]); feed.push(SEG["copy2"][7:])
        self.assertEqual(rd.poll(), []); self.assertEqual(rd.fragments, [], "P3L5 AU is not a frame head yet")
        lines = rd.poll()
        self.assertEqual([l for l, _, _ in lines], [text(SEG["copy2"])]); self.assertEqual(len(rd.fragments), 1)

    def test_a_payload_ending_in_P3L5_is_never_split(self):
        line = n.build_line(n.T_AUDIT, 1, TOKEN, "AAAAP3L5")
        self.assertGreater(line.find("P3L5 ", 1), 0, "the marker really is inside the line")
        rd, feed, clk = reader()
        feed.push(line.encode())
        lines = rd.poll()
        self.assertEqual([l for l, _, _ in lines], [line.rstrip("\n")]); self.assertEqual(rd.fragments, [])
        self.assertEqual(n.parse_line(lines[0][0])["payload"], "AAAAP3L5")

    def test_a_fabricated_head_inside_a_line_would_need_type_seq_and_token(self):
        # the discrimination behind the previous test: only the full head resyncs
        rd, feed, clk = reader()
        feed.push(b"junk P3L5 AUDIT 3 " + b"0" * 32 + b" tail\n")
        lines = rd.poll()
        self.assertEqual(len(rd.fragments), 1); self.assertEqual(rd.fragments[0]["text"], "junk ")
        self.assertEqual([l for l, _, _ in lines], ["P3L5 AUDIT 3 " + "0" * 32 + " tail"])
        rd2, feed2, _ = reader()
        feed2.push(b"junk P3L5 AUDIT 3 " + b"0" * 31 + b" tail\n")      # 31 hex: not a head
        rd2.poll(); self.assertEqual(rd2.fragments, [])

    def test_quarantine_moves_the_residue_and_reports_it_once(self):
        rd, feed, clk = reader()
        feed.push(SEG["partial"]); self.assertEqual(rd.poll(), [])
        frag = rd.quarantine("pull timeout: seq 39 chunk 1")
        self.assertEqual((frag["bytes"], frag["reason"]), (576, "pull timeout: seq 39 chunk 1"))
        self.assertEqual(rd.buf, b""); self.assertIsNone(rd.quarantine("again"), "nothing left to quarantine")
        self.assertEqual(rd.take_fragments(), [frag])

    def test_a_late_headless_tail_after_the_quarantine_is_noise_and_before_it_completes_the_line(self):
        full = SEG["copy2"]
        rd, feed, clk = reader()
        feed.push(full[:300]); rd.poll(); rd.quarantine("pull timeout: seq 39 chunk 1")
        feed.push(full[300:])
        lines = rd.poll()
        self.assertEqual(len(lines), 1); self.assertFalse(lines[0][0].startswith("P3L5"), "a headless remnant")
        self.assertEqual(len(rd.fragments), 1, "the remnant is not a second fragment")
        rd2, feed2, _ = reader()
        feed2.push(full[:300]); rd2.poll(); feed2.push(full[300:])
        self.assertEqual([l for l, _, _ in rd2.poll()], [text(full)]); self.assertEqual(rd2.fragments, [])


# ------------------------------------------------------------------ the pull host


def pull_host(clk, sent, **kw):
    return ap.PullHost(TOKEN, 39, send=sent.append, clock=clk.mono, **kw)


class PullHostDeadline(unittest.TestCase):
    def test_the_chunk_timeout_is_a_monotonic_deadline_armed_by_the_get(self):
        clk, sent = Clk(), []
        host = pull_host(clk, sent)
        host.on_line(text(SEG["ready"]))
        self.assertEqual(host.deadline, clk.t + ap.CHUNK_TIMEOUT_S); self.assertEqual(len(sent), 1)
        clk.t += ap.CHUNK_TIMEOUT_S - 0.01; host.tick(100.0)        # dt is ignored: no timeout yet
        self.assertEqual(host.ledger.timeouts, 0); self.assertEqual(len(sent), 1)
        clk.t += 0.01; host.tick()
        self.assertEqual(host.ledger.timeouts, 1); self.assertEqual(len(sent), 2, "the retry GET")
        self.assertEqual(host.deadline, clk.t + ap.CHUNK_TIMEOUT_S, "re-armed by the retry")
        t_ok = clk.t
        host.on_line(text(SEG["chunk0"]))
        self.assertEqual(host.deadline, t_ok + ap.CHUNK_TIMEOUT_S, "the verified reply disarms it; the next GET re-arms it")
        self.assertEqual(host.chunk, 1)

    def test_the_timeout_callback_runs_before_the_retry_is_sent(self):
        clk, sent, seen = Clk(), [], []
        host = pull_host(clk, sent, on_timeout=lambda s, c: seen.append((s, c, len(sent))))
        host.on_line(text(SEG["ready"]))
        clk.t += ap.CHUNK_TIMEOUT_S; host.tick()
        self.assertEqual(seen, [(39, 0, 1)], "seen with ONE get sent: the residue is quarantined before the resend")

    def test_a_stale_byte_identical_reply_of_a_verified_chunk_is_ignored_not_an_attempt(self):
        clk, sent = Clk(), []
        host = pull_host(clk, sent)
        host.on_line(text(SEG["ready"])); host.on_line(text(SEG["chunk0"]))
        self.assertEqual(host.chunk, 1)
        before = list(host.ledger.attempts)
        host.on_line(text(SEG["chunk0"]))                           # chunk 0 again, identical
        self.assertEqual(host.ledger.attempts, before); self.assertEqual(host.chunk, 1)
        self.assertEqual(host.ledger.duplicates, [{"seq": 39, "chunk": 0, "while_waiting_for": 1}])
        self.assertEqual(len(sent), 2, "no extra GET")

    def test_a_stale_reply_with_other_content_is_still_a_failed_attempt(self):
        clk, sent = Clk(), []
        host = pull_host(clk, sent)
        host.on_line(text(SEG["ready"])); host.on_line(text(SEG["chunk0"]))
        f = n.parse_line(text(SEG["chunk0"])); p = n.decode_payload(f["payload"])
        p["nonzero"] = p.get("nonzero", 0) + 1 if "nonzero" in p else 0
        p["entries"] = list(p.get("entries", []))[:-1] if p.get("entries") else p.get("entries")
        other = n.build_line(n.T_AUDIT, 39, TOKEN, n.encode_payload(p))
        host.on_line(other)
        self.assertNotEqual(host.ledger.attempts[-1]["outcome"], "ok"); self.assertEqual(host.ledger.duplicates, [])


# ------------------------------------------------------------------ C1 #5 replayed


class C15Replay(unittest.TestCase):
    RECORDED = ["ok", "timeout", "malformed", "ok"] + ["ok"] * 6

    def _drive(self, resync: bool, glued: bool, timeout_s: float = ap.CHUNK_TIMEOUT_S):
        rd, feed, clk = reader(resync=resync)
        sent, frags = [], []

        def on_timeout(s, c):
            if resync:
                frag = rd.quarantine(f"pull timeout: seq {s} chunk {c}")
                if frag:
                    frags.append(frag)
        host = ap.PullHost(TOKEN, 39, send=sent.append, clock=clk.mono, timeout_s=timeout_s, on_timeout=on_timeout)

        def feed_and_pump(data: bytes):
            feed.push(data)
            for line, _, _ in rd.poll():
                if line.startswith(n.MAGIC):
                    host.on_line(line)
            host.tick()
        feed_and_pump(SEG["ready"]); feed_and_pump(SEG["chunk0"])
        self.assertEqual(host.chunk, 1)
        if glued:
            feed_and_pump(SEG["partial"] + SEG["copy2"])
        else:
            feed_and_pump(SEG["partial"])
            clk.t += timeout_s + 0.05; host.tick()               # the deadline passes: quarantine, retry
            feed_and_pump(SEG["copy2"])
        feed_and_pump(SEG["copy3"])
        for ln in SEG["rest"]:
            feed_and_pump(ln)
        return host, rd, sent, frags

    def test_the_recorded_ledger_of_seq_39_is_what_the_session_saw(self):
        rec = [p for p in AUDITS["pulls"] if p["seq"] == 39][0]
        self.assertEqual([a["outcome"] for a in rec["attempts"]], self.RECORDED)

    def test_with_the_new_reader_and_pull_the_first_resend_recovers_chunk_1(self):
        host, rd, sent, frags = self._drive(resync=True, glued=False)
        self.assertTrue(host.done); self.assertFalse(host.failed)
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["ok", "timeout", "ok"] + ["ok"] * 6)
        self.assertEqual([a for a in host.ledger.attempts if a["chunk"] == 1],
                         [{"seq": 39, "chunk": 1, "attempt": 0, "outcome": "timeout"},
                          {"seq": 39, "chunk": 1, "attempt": 1, "outcome": "ok"}])
        self.assertEqual(len(frags), 1); self.assertEqual(frags[0]["bytes"], 576)
        self.assertEqual(frags[0]["reason"], "pull timeout: seq 39 chunk 1")
        self.assertEqual(host.ledger.duplicates, [{"seq": 39, "chunk": 1, "while_waiting_for": 2}], "copy 3 ignored")
        self.assertEqual(len(sent), 8 + 1 + 1, "8 GETs + 1 retry GET + AUDITDONE")
        self.assertEqual(host.ledger.timeouts, 1)

    def test_glued_in_one_read_the_resend_recovers_without_any_timeout(self):
        host, rd, sent, frags = self._drive(resync=True, glued=True)
        self.assertTrue(host.done)
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["ok"] * 8)
        self.assertEqual(host.ledger.timeouts, 0); self.assertEqual(frags, [])
        self.assertEqual(len(rd.fragments), 1); self.assertTrue(rd.fragments[0]["reason"].startswith("resync"))
        self.assertEqual(len(host.ledger.duplicates), 1)

    def test_the_c1_5_reader_reproduces_the_recorded_timeout_malformed_ok(self):
        host, rd, sent, frags = self._drive(resync=False, glued=False)
        self.assertTrue(host.done, "copy 3 rescued the old path, as recorded")
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], self.RECORDED)
        self.assertEqual(rd.fragments, []); self.assertEqual(frags, [])
        self.assertEqual(host.ledger.duplicates, [])

    def test_the_replay_holds_at_the_candidate_timeout_too(self):
        host, rd, sent, frags = self._drive(resync=True, glued=False, timeout_s=0.5)
        self.assertTrue(host.done)
        self.assertEqual([a["outcome"] for a in host.ledger.attempts if a["chunk"] == 1], ["timeout", "ok"])


# ------------------------------------------------------------------ the session wiring


class SessionWiring(unittest.TestCase):
    def setUp(self):
        self.clk = Clk()
        self.feed = Feed()
        self.reader = lrd.L6LineReader(self.feed, clock_mono=self.clk.mono, clock_wall=self.clk.wall)
        self.collector = n.Collector(TOKEN, heartbeat_s=10, clock=self.clk.mono)
        self.sent = []
        self.relay = n.NotaryRelay(TOKEN, lambda req: {"refused": {"finding_kinds": ["x"]}}, drop_budget=4, clock=self.clk.mono)
        self.tl = lt.Timeline()
        self.cs = lcs.ConsoleSession(TOKEN, self.collector, self.relay, self.tl, audit_seqs=set(), crc_budget=8,
                                     send=lambda line, mtype, seq: self.sent.append((mtype, seq)),
                                     reader=self.reader, clock=self.clk.mono)
        self.board = ap.PullBoard(TOKEN, 1, "streams+readback", [0] * 2814, requested=True)

    def _pump(self, data: bytes | None = None):
        if data is not None:
            self.feed.push(data)
        for line, tm, tw in self.reader.poll():
            self.cs.on_line(line, tm, tw)
        self.cs.tick()

    def _signreq(self):
        line = n.build_line(n.T_SIGNREQ, 1, TOKEN, n.encode_payload(
            {"seq": 1, "token": TOKEN, "genome": "0" * 80, "nonce": "0" * 16, "app_epoch": 0,
             "schema": "sign_request", "schema_version": "1.0.0"}))
        self._pump(line.encode())

    def test_a_pull_timeout_quarantines_the_residue_and_the_timeline_records_the_fragment(self):
        self._signreq()
        self._pump(self.board.start()[0].encode())
        self.assertIsNotNone(self.cs.puller)
        chunk0 = self.board.serve(0).encode()
        self._pump(chunk0[:200])                                   # torn: no terminator
        self.clk.t += ap.CHUNK_TIMEOUT_S + 0.05
        self._pump()
        self.assertEqual(len(self.tl.fragments), 1)
        self.assertEqual(self.tl.fragments[0]["bytes"], 200)
        self.assertEqual([f["type"] for f in self.tl.frames if f["type"] == "FRAGMENT"], ["FRAGMENT"])
        self.assertEqual(self.cs.puller.ledger.timeouts, 1)
        self._pump(chunk0)                                         # the resend, on a clean buffer
        self.assertEqual(self.cs.puller.ledger.attempts[-1]["outcome"], "ok")
        self.assertEqual(self.tl.bad_frames, 0)
        self.assertEqual(self.tl.to_json()["fragments"][0]["reason"], "pull timeout: seq 1 chunk 0")

    def test_resync_fragments_reach_the_timeline_and_the_ledger_carries_duplicates(self):
        self._signreq()
        self._pump(self.board.start()[0].encode())
        c0 = self.board.serve(0).encode()
        self._pump(c0[:150] + c0)                                  # glued: torn copy + whole copy
        self.assertEqual(len(self.tl.fragments), 1); self.assertTrue(self.tl.fragments[0]["reason"].startswith("resync"))
        self.assertEqual(self.cs.puller.ledger.attempts[-1]["outcome"], "ok"); self.assertEqual(self.tl.bad_frames, 0)
        self._pump(c0)                                             # a stale duplicate of chunk 0
        self.assertEqual(len(self.cs.puller.ledger.duplicates), 1)
        for c in range(1, 8):
            self._pump(self.board.serve(c).encode())
        self.assertIsNone(self.cs.puller)
        self.assertEqual(self.cs.pull_ledgers[-1]["duplicates"], [{"seq": 1, "chunk": 0, "while_waiting_for": 1}])
        self.assertTrue(self.cs.pull_ledgers[-1]["done"])

    def test_the_runner_hands_the_reader_and_the_monotonic_clock_to_the_session(self):
        import l6_runner as l6
        src = inspect.getsource(l6.run_l6)
        self.assertIn("reader=reader, clock=time.monotonic", src)
        self.assertIn("console.tick()", src); self.assertNotIn("console.tick(0.02)", src)
        self.assertIn('summary["fragments"] = len(timeline.fragments)', src)
        self.assertIn('rate_report_from_evidence_dir(out_dir, plan["session"])', src, "the rate report is derived from the files on disk (D-t2)")

    def test_liveness_gaps_ignore_fragment_events(self):
        frames = [{"dir": "rx", "type": "HB", "seq": 1, "t_mono": 0.0}, {"dir": "rx", "type": "FRAGMENT", "seq": None, "t_mono": 5.0},
                  {"dir": "rx", "type": "HB", "seq": 1, "t_mono": 10.0}]
        self.assertEqual([g["gap_s"] for g in lt.liveness_gaps(frames)], [10.0])


# ------------------------------------------------------------------ the rate split


class RateSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = lr.rate_report(LOG, "C1", None, audits=AUDITS, frames=FRAMES, inputs_sha256=INPUTS)

    def test_c1_5_inclusive_nominal_and_recovery(self):
        r = self.rep
        self.assertAlmostEqual(r["inclusive"]["cov"], 0.2744, places=3); self.assertEqual(r["inclusive"]["n"], 63)
        self.assertAlmostEqual(r["nominal"]["cov"], 0.0559, places=3); self.assertEqual(r["nominal"]["n"], 62)
        self.assertEqual(r["nominal"]["excluded_seqs"], [39])
        rec = r["recovery"]
        self.assertEqual({k: rec[k] for k in ("candidates_with_recovery", "pull_timeouts", "pull_malformed", "pull_retries",
                                               "bad_frames", "fragments", "control_drops", "rec_gets", "rec_retries", "crc_drops")},
                         {"candidates_with_recovery": 1, "pull_timeouts": 1, "pull_malformed": 1, "pull_retries": 2,
                          "bad_frames": 1, "fragments": 0, "control_drops": 1, "rec_gets": 0, "rec_retries": 0, "crc_drops": 0})
        self.assertEqual(rec["rx_frames"], 1785)
        self.assertEqual(r["inputs"], INPUTS); self.assertEqual(r["run_log_sha256"], INPUTS["run_log"])
        self.assertLess(r["planning"]["evals_per_hour"], r["inclusive"]["evals_per_hour"], "planning is the conservative one")
        row = [x for x in r["per_candidate"] if x["seq"] == 39][0]
        self.assertFalse(row["clean"]); self.assertEqual(row["recovery"]["pull_timeouts"], 1)

    def test_the_top_level_numbers_are_the_inclusive_ones_v04_unchanged(self):
        r = self.rep
        self.assertEqual(r["cov"], r["inclusive"]["cov"]); self.assertEqual(r["evals_per_hour"], r["inclusive"]["evals_per_hour"])
        self.assertEqual(r["schema_version"], "1.2.0")
        for k in ("inclusive", "nominal", "recovery", "planning", "inputs", "ledgers"):
            self.assertIn(k, r["definitions"])

    def test_without_the_ledgers_nominal_is_absent_and_says_so(self):
        r = lr.rate_report(LOG, "C1", "x")
        self.assertIsNone(r["nominal"]); self.assertIn("NOT SUPPLIED", r["recovery"]["ledgers"])
        self.assertEqual(r["cov"], self.rep["cov"])

    def test_the_control_is_attributed_as_control_not_recovery(self):
        tim = {int(k): v for k, v in LOG["timing"]["records"].items()}
        rec = lr.recovery_by_seq(tim, sorted(tim), AUDITS, FRAMES)
        self.assertEqual(rec[1]["control"], 1); self.assertFalse(rec[1]["recovered"]); self.assertEqual(rec[1]["rec_gets"], 0)
        # the same ledger on seq 2 would be a recovery
        aud = copy.deepcopy(AUDITS)
        for r_ in aud["recs"]:
            if r_["seq"] == 2:
                r_["attempts"] = [{"attempt": 1, "outcome": "crc"}, {"attempt": 2, "outcome": "ok"}]; r_["gets_sent"] = 1
        rec2 = lr.recovery_by_seq(tim, sorted(tim), aud, FRAMES)
        self.assertTrue(rec2[2]["recovered"]); self.assertEqual(rec2[2]["rec_retries"], 1)

    def test_a_fragment_or_bad_frame_inside_a_window_marks_that_candidate_only(self):
        tim = {int(k): v for k, v in LOG["timing"]["records"].items()}
        t10 = tim[10]["t_signreq"] + 0.1
        frames = [{"dir": "rx", "type": "FRAGMENT", "seq": None, "t_mono": t10, "bytes": 5, "reason": "resync"}]
        rec = lr.recovery_by_seq(tim, sorted(tim), {"pulls": [], "recs": []}, frames)
        self.assertTrue(rec[10]["recovered"]); self.assertEqual(rec[10]["fragments"], 1)
        self.assertFalse(any(rec[s]["recovered"] for s in rec if s != 10))
        # through the report, on the real ledgers plus that one fragment: seq 10 joins seq 39
        r = lr.rate_report(LOG, "C1", None, audits=AUDITS, frames=FRAMES + frames, inputs_sha256=INPUTS)
        self.assertEqual(r["nominal"]["excluded_seqs"], [10, 39]); self.assertEqual(r["recovery"]["fragments"], 1)
        self.assertEqual(r["recovery"]["candidates_with_recovery"], 2)


# ------------------------------------------------------------------ the v0.5 draft findings


class V05Findings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = lr.rate_report(LOG, "C1", None, audits=AUDITS, frames=FRAMES, inputs_sha256=INPUTS)

    def test_the_draft_pass_conditions_in_the_manifest_are_these(self):
        # frozen 2026-09-03 as v0.6: the draft bounds were merged into pass_conditions with
        # exactly these values; the v0.5 draft stays on record as never frozen
        self.assertEqual({k: MANIFEST["pass_conditions"][k] for k in DRAFT_PC}, DRAFT_PC)
        self.assertNotIn("next_prereg", MANIFEST)
        self.assertEqual(MANIFEST["prereg"]["version"], "v0.6"); self.assertRegex(MANIFEST["prereg"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(MANIFEST["prereg"]["protocol"], "rel-v4")
        self.assertEqual(MANIFEST["prereg"]["never_frozen"][0]["version"], "v0.5-draft", "v0.5 never frozen (owner)")
        self.assertEqual(MANIFEST["prereg"]["supersedes"][0]["version"], "v0.4", "v0.4 superseded in history")

    def test_c1_5_is_a_hold_under_v04_and_the_runner_follows_the_manifest_not_the_draft(self):
        self.assertEqual(lc.calibration_findings(self.rep, MANIFEST["pass_conditions"]["cov_max"]),
                         ["coefficient of variation 0.274 > 0.1 (distribution published in rate_report.json)"])
        # under the DRAFT the same evidence would have no finding — stated, not applied:
        self.assertEqual(lc.calibration_findings_v05(self.rep, DRAFT_PC), [])
        import l6_runner as l6
        src = inspect.getsource(l6.run_l6)
        self.assertIn('if str(l6m["prereg"].get("version")) in V05_RULE_VERSIONS:', src)
        import l6_runner as l6r
        self.assertEqual(l6r.V05_RULE_VERSIONS, ("v0.5", "v0.6"))
        self.assertIn("lc.calibration_findings_v05(rep, pc)", src)
        self.assertIn('lc.calibration_findings(rep, pc["cov_max"])', src)

    def test_every_v05_bound_is_named_when_crossed(self):
        def mut(**changes):
            r = copy.deepcopy(self.rep)
            for k, v in changes.items():
                sect, key = k.split("__")
                r[sect][key] = v
            return lc.calibration_findings_v05(r, DRAFT_PC)
        self.assertIn("nominal coefficient of variation 0.200 > 0.1", mut(nominal__cov=0.2)[0])
        self.assertIn("clean steady-state periods 10 < 60", mut(nominal__n=10)[0])
        self.assertIn("candidates_with_recovery 4 > 3", mut(recovery__candidates_with_recovery=4)[0])
        self.assertIn("pull_timeouts 4 > 3", mut(recovery__pull_timeouts=4)[0])
        self.assertIn("bad_frames 4 > 3", mut(recovery__bad_frames=4)[0])
        self.assertIn("fragments 4 > 3", mut(recovery__fragments=4)[0])
        self.assertIn("no nominal coefficient", mut(nominal__cov=None)[0])
        r = copy.deepcopy(self.rep); del r["recovery"]["fragments"]
        self.assertIn("recovery indicator 'fragments' missing", lc.calibration_findings_v05(r, DRAFT_PC)[0])
        r = copy.deepcopy(self.rep); r["nominal"] = None
        self.assertIn("no nominal rate", lc.calibration_findings_v05(r, DRAFT_PC)[0])

    def test_a_missing_pass_condition_is_refused_by_name(self):
        pc = dict(DRAFT_PC); del pc["max_fragments"]
        self.assertEqual(lc.calibration_findings_v05(self.rep, pc), ["v0.5 pass condition 'max_fragments' is not pinned in the manifest"])


# ------------------------------------------------------------------ the soak


class Soak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.new = soak.run_soak(seed=7, candidates=120, p_fault=0.15, timeout_s=2.0)["total"]
        cls.old = soak.run_soak(seed=7, candidates=120, p_fault=0.15, timeout_s=2.0, resync=False)["total"]
        cls.fast = soak.run_soak(seed=7, candidates=120, p_fault=0.15, timeout_s=0.5)["total"]

    def test_every_single_fault_is_recovered_on_the_first_resend_and_no_clean_candidate_is_marked(self):
        t = self.new
        self.assertGreater(t["faults_injected"], 60)
        self.assertEqual(t["single_faults_recovered_on_first_resend"], t["single_faults"])
        self.assertEqual(t["pulls_failed"], t["failed_with_more_faults_than_retries_on_one_chunk"])
        self.assertGreaterEqual(t["single_faults_with_possible_late_tail_interference"], 0)
        self.assertEqual(t["clean_candidates_with_any_recovery_artifact"], 0)
        for kind in ("truncate", "interior", "drop", "glued_dup", "late_tail"):
            self.assertIn(kind, t["by_kind"], kind)
        self.assertGreater(t["fragments_by_reason"]["resync"], 0); self.assertGreater(t["fragments_by_reason"]["pull timeout"], 0)
        self.assertGreater(t["duplicates_ignored"], 0)

    def test_the_c1_5_reader_does_worse_on_the_same_seed(self):
        old, new = self.old, self.new
        self.assertGreater(old["bad_frames"], new["bad_frames"])
        self.assertEqual(old["fragments"], 0)
        tr_old, tr_new = old["by_kind"]["truncate"], new["by_kind"]["truncate"]
        self.assertLess(tr_old["recovered_first_resend"], tr_old["single"])
        self.assertEqual(tr_new["recovered_first_resend"], tr_new["single"])

    def test_the_candidate_timeout_keeps_the_invariants_and_costs_less_virtual_time(self):
        t = self.fast
        self.assertEqual(t["single_faults_recovered_on_first_resend"], t["single_faults"])
        self.assertEqual(t["clean_candidates_with_any_recovery_artifact"], 0)
        self.assertLess(t["virtual_s_total"], self.new["virtual_s_total"])


if __name__ == "__main__":
    unittest.main()
