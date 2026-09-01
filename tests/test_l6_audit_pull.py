"""host/l6_audit_pull.py — the host-paced sparse audit pull as a WIRE state machine
(design review 2026-09-01, second round). Both ends build and parse real P3L5 lines; the
channel injects scripted drops, deletions and duplicates in both directions.

Real words: C1 #3's 64 complete audits (evidence/l6_17A6_2026-09-01-08-C1, read-only) and
a streams-only span cut from them. Every scenario the review asked for is a test: binding
of token / frame seq / payload seq / READY's span-total-chunks / the requested chunk;
READY, GET and DONE lost or duplicated; a malformed line during a pull is a retry, not a
crash; retries exhausted → AUDITABORT → STOP_AUDIT with no ARM and a stop; the board
never waits without a bound; sampled selection and the §3a auto-audit; C1 #1/#3-shaped
deletions recovered by one retry; valid CRC with wrong content Falsified; costs."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l5_notary as n  # noqa: E402
import l6_audit_pull as ap  # noqa: E402
import p3_gate as g  # noqa: E402
from validators import audit as au  # noqa: E402
from validators.records import Falsified, RecordError  # noqa: E402

C13 = R / "evidence/l6_17A6_2026-09-01-08-C1"
LOG = json.loads((C13 / "run_log.json").read_text())
TOKEN = LOG["app_identity"]["token"]
ALL = au.assemble(json.loads((C13 / "audits.json").read_text())["chunks"] and
                  [c for c in json.loads((C13 / "audits.json").read_text())["chunks"] if c["seq"] not in (20, 62)])
WORDS = ALL[1]["words"]
ORACLE = LOG["loop_records"][0]["evidence"]["app_oracle_record"]
MANIFEST = g.load_manifest()
FULL, STREAMS = "streams+readback", "streams"


def run(faults=(), outcome="SCORED", requested=True, words=WORDS, span=FULL, host_kw=None, corrupt=None):
    board = ap.PullBoard(TOKEN, 1, span, words, outcome=outcome, requested=requested, corrupt=corrupt)
    sim = ap.Simulation(board, host_kw=host_kw, faults=list(faults))
    return sim, sim.run()


def reply_len(chunk):
    return len(ap.PullBoard(TOKEN, 1, FULL, WORDS).serve(chunk))


class CleanPull(unittest.TestCase):
    def test_a_clean_pull_verifies_every_chunk_and_recomputes_the_record(self):
        sim, res = run()
        self.assertTrue(res["host_done"]); self.assertFalse(res["host_failed"])
        self.assertEqual(res["board"], {"outcome": "SCORED", "verified": "audited", "arm": True, "epoch": "RUNNING"})
        types = [n.parse_line(l)["type"] for l in sim.delivered_b2h]
        self.assertEqual(types, [ap.T_READY] + [n.T_AUDIT] * 8)
        h = ap.recompute_from_sparse(sim.host.chunks(), MANIFEST, ORACLE)[1]
        self.assertEqual((h["staged_sha256"], h["readback_sha256"]), (ORACLE["staged_sha256"], ORACLE["readback_sha256"]))

    def test_the_streams_span_works_the_same_way(self):
        sim, res = run(words=WORDS[:au.STREAM_SPAN], span=STREAMS, outcome="STOP_LINK2", requested=False)
        self.assertTrue(res["host_done"])
        self.assertEqual(res["board"]["outcome"], "STOP_LINK2"); self.assertEqual(res["board"]["verified"], "audited")
        self.assertEqual(sim.host.binding, {"span": STREAMS, "total_words": 1602, "chunks": 5})

    def test_corpus_every_complete_c1_3_audit_is_lossless_and_bounded(self):
        """All 64 complete audits of C1 #3 (and the streams span cut from each): lossless,
        the record's hashes recomputed, the sparse wire 19–21 % of the dense one, no reply
        line longer than 1 KB."""
        ratios, longest = [], 0
        for seq, a in sorted(ALL.items()):
            oracle = next(r for r in LOG["loop_records"] if r["seq"] == seq)["evidence"]["app_oracle_record"]
            sim, res = run(words=a["words"])
            self.assertTrue(res["host_done"], seq)
            ap.recompute_from_sparse(sim.host.chunks(), MANIFEST, oracle)
            c = ap.compare_encodings(a["words"], TOKEN, seq, FULL)
            ratios.append(c["ratio"]); longest = max(longest, c["longest_reply_line"])
            s_words = a["words"][:au.STREAM_SPAN]
            got = au.assemble([au.build_sparse_chunk(seq, k, STREAMS, s_words) for k in range(5)])[seq]["words"]
            self.assertEqual(got, s_words, seq)
        self.assertEqual(len(ratios), 64)
        self.assertGreater(min(ratios), 0.15); self.assertLess(max(ratios), 0.25)
        self.assertLess(longest, 1024)


class Binding(unittest.TestCase):
    def test_a_ready_that_is_not_bound_to_this_candidate_fails_the_pull(self):
        for bad in ({"seq": 2}, {"span": "streams", "total_words": 2814}, {"chunks": 7}, {"total_words": 1602}):
            board = ap.PullBoard(TOKEN, 1, FULL, WORDS, requested=True)
            ready = n.decode_payload(n.parse_line(board.start()[0])["payload"]); ready.update(bad)
            sent = []
            host = ap.PullHost(TOKEN, 1, send=sent.append)
            host.on_line(n.build_line(ap.T_READY, 1, TOKEN, n.encode_payload(ready)))
            self.assertTrue(host.failed, bad); self.assertIn("not bound", host.fail_reason)
            self.assertEqual(n.parse_line(sent[-1])["type"], ap.T_ABORT)

    def test_a_reply_with_the_wrong_token_frame_seq_payload_seq_or_chunk_is_a_failed_attempt(self):
        board = ap.PullBoard(TOKEN, 1, FULL, WORDS, requested=True)
        good = board.serve(0)
        f = n.parse_line(good); p = n.decode_payload(f["payload"])
        variants = {
            "token": n.build_line(n.T_AUDIT, 1, "cd" * 16, f["payload"]),
            "frame seq": n.build_line(n.T_AUDIT, 2, TOKEN, f["payload"]),
            "payload seq": n.build_line(n.T_AUDIT, 1, TOKEN, n.encode_payload({**p, "seq": 2})),
            "chunk": board.serve(1),
            "span": n.build_line(n.T_AUDIT, 1, TOKEN, n.encode_payload({**p, "span": STREAMS, "total_words": 1602, "chunks": 5})),
        }
        for what, line in variants.items():
            sent = []
            host = ap.PullHost(TOKEN, 1, send=sent.append)
            host.on_line(board.start()[0])
            self.assertEqual(host.state, "WAIT_CHUNK")
            host.on_line(line)
            att = host.ledger.attempts[-1]
            self.assertNotEqual(att["outcome"], "ok", what); self.assertEqual(host.chunk, 0, what)
            self.assertEqual(host.attempt, 1, f"{what}: one retry issued")
            self.assertEqual(len(host.ledger.lines_kept), 1, what)
            host.on_line(good)                                     # the right reply is then accepted
            self.assertEqual(host.chunk, 1, what)

    def test_a_chunk_that_changes_the_transactions_binding_is_refused_at_assembly_too(self):
        chunks = [au.build_sparse_chunk(1, c, FULL, WORDS) for c in range(8)]
        alien = au.build_sparse_chunk(1, 2, STREAMS, WORDS[:au.STREAM_SPAN])
        with self.assertRaises(RecordError) as cm:
            au.assemble(chunks[:2] + [alien] + chunks[3:])
        self.assertIn("one transaction, one binding", str(cm.exception))


class LossAndDuplication(unittest.TestCase):
    def test_c1_3s_in_line_deletions_are_recovered_by_one_retry(self):
        for lost in (309, 229):
            L = reply_len(3)
            sim, res = run([ap.Fault("b2h", n.T_AUDIT, 3, 0, "delete", L // 3, min(lost, L // 2))])
            self.assertTrue(res["host_done"])
            att = [a["outcome"] for a in res["ledger"].attempts if a["chunk"] == 3]
            self.assertEqual(att, ["crc", "ok"]); self.assertEqual(res["ledger"].crc_dropped, 1)
            self.assertEqual(len(res["ledger"].lines_kept), 1)
            ap.recompute_from_sparse(sim.host.chunks(), MANIFEST, ORACLE)

    def test_c1_1s_boundary_deletion_merging_two_replies_is_recovered(self):
        """A deletion running off the end of chunk 4's reply takes the newline: the host sees
        one merged line — malformed — and asks for chunk 4 again; chunk 5 is asked for in
        its turn as always."""
        L = reply_len(4)
        sim, res = run([ap.Fault("b2h", n.T_AUDIT, 4, 0, "delete", L - 20, 39)])
        self.assertTrue(res["host_done"])
        att = [a["outcome"] for a in res["ledger"].attempts if a["chunk"] == 4]
        self.assertNotEqual(att[0], "ok"); self.assertEqual(att[-1], "ok")
        ap.recompute_from_sparse(sim.host.chunks(), MANIFEST, ORACLE)

    def test_ready_lost_the_board_bounds_its_wait_and_stops_without_an_arm(self):
        sim, res = run([ap.Fault("b2h", ap.T_READY, None, 0, "drop")])
        self.assertFalse(res["host_done"]); self.assertFalse(res["host_failed"])   # the host never had a pull
        self.assertEqual(res["board"], {"outcome": "STOP_AUDIT", "verified": "replayed-only", "arm": False, "epoch": "STOPPED", "restore": True})
        self.assertEqual(sim.board.state, "ABORTED")

    def test_get_lost_is_a_host_timeout_and_a_retry_not_a_crc_drop(self):
        sim, res = run([ap.Fault("h2b", ap.T_GET, 2, 0, "drop")])
        self.assertTrue(res["host_done"])
        self.assertEqual((res["ledger"].timeouts, res["ledger"].crc_dropped), (1, 0))
        self.assertEqual([a["outcome"] for a in res["ledger"].attempts if a["chunk"] == 2], ["timeout", "ok"])

    def test_done_lost_is_visible_the_board_records_replayed_only_and_rule_ix_refuses(self):
        """The full run log with the board's STOP_AUDIT record and the host's verified
        chunks goes through the REAL validate_standalone_run_log: the host-derived mark is
        `audited`, the record says `replayed-only`, and rule (ix) refuses — a lost DONE is
        never silent."""
        import copy
        from validators import records
        sim, res = run([ap.Fault("h2b", ap.T_DONE, None, 0, "drop")])
        self.assertTrue(res["host_done"])                             # the host believes it complete …
        self.assertEqual(res["board"]["outcome"], "STOP_AUDIT")       # … the board waited out its bound, no ARM
        self.assertEqual(res["board"]["verified"], "replayed-only")
        rec = copy.deepcopy(LOG["loop_records"][0])
        rec["outcome"], rec["verified"] = "STOP_AUDIT", "replayed-only"
        for k in ("arm", "score"):
            del rec["evidence"][k]
        rec["evidence"]["audit_stop"] = {"why": "the host went quiet during the audit pull", "chunks_served": 8}
        log = {"control_plane": "standalone", "app_identity": LOG["app_identity"],
               "loop_records": [rec],
               "notary_log": {"schema": "notary_log", "schema_version": "1.0.0", "token": TOKEN,
                              "entries": [LOG["notary_log"]["entries"][0]]},
               "session_summary": {"schema": "session_summary", "schema_version": "1.0.0", "token": TOKEN,
                                   "epoch_end": {"kind": "STOPPED", "reason": "the audit pull did not complete: no ARM was attempted", "last_seq": 1},
                                   "counts": {"scored": 0, "refused_by_gate": 0},
                                   "closing": {"restore": "done", "baseline": "not_reached", "unsigned_control": "not_reached"},
                                   "audit": {"audited": 0, "total": 1}, "crc_dropped": 0, "drop_budget": 16,
                                   "written_by": "app"}}
        import p3_gate as g2
        import p3_genome as gn
        phen = MANIFEST
        blank = g2.gate(g2.build_streams(gn.frames_from_genome(gn.blank_genome(phen), phen), phen), phen)["candidate_sha256"]
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(log, blank, 0x9E3779B97F4A7C15, sim.host.chunks(), phen)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("(ix)", str(cm.exception)); self.assertIn("replayed-only", str(cm.exception))

    def test_duplicates_are_harmless(self):
        sim, res = run([ap.Fault("b2h", ap.T_READY, None, 0, "dup"), ap.Fault("b2h", n.T_AUDIT, 5, 0, "dup"),
                        ap.Fault("h2b", ap.T_GET, 1, 0, "dup"), ap.Fault("h2b", ap.T_DONE, None, 0, "dup")])
        self.assertTrue(res["host_done"]); self.assertEqual(res["board"]["outcome"], "SCORED")
        self.assertEqual(sim.board.served.get(1), 2, "a duplicated GET is simply served twice")

    def test_a_malformed_line_during_a_pull_is_a_retry_not_a_crash(self):
        board = ap.PullBoard(TOKEN, 1, FULL, WORDS, requested=True)
        sent = []
        host = ap.PullHost(TOKEN, 1, send=sent.append)
        host.on_line(board.start()[0])
        host.on_line("P3L5 AUDIT 1 " + TOKEN + " abc def 00000000")      # seven fields
        self.assertEqual(host.ledger.attempts[-1]["outcome"], "malformed")
        self.assertEqual(host.state, "WAIT_CHUNK"); self.assertEqual(host.attempt, 1)
        self.assertEqual(host.ledger.crc_dropped, 0)


class Exhaustion(unittest.TestCase):
    def test_three_failed_attempts_abort_the_pull_and_the_board_stops_without_an_arm(self):
        sim, res = run([ap.Fault("b2h", n.T_AUDIT, 3, a, "delete", 100, 50) for a in range(ap.MAX_RETRIES + 1)])
        self.assertTrue(res["host_failed"]); self.assertIn("HOLD", res["fail_reason"])
        self.assertEqual(res["board"], {"outcome": "STOP_AUDIT", "verified": "replayed-only", "arm": False, "epoch": "STOPPED", "restore": True})
        self.assertFalse(sim.board.armed)
        self.assertEqual(n.parse_line(sim.host_sent[-1])["type"], ap.T_ABORT, "the host's last line is the abort")
        self.assertEqual(len(res["ledger"].lines_kept), 3, "all three failed attempts kept verbatim")
        self.assertEqual(res["ledger"].crc_dropped, 3)

    def test_every_failed_attempt_counts_against_the_budget_and_the_budget_aborts(self):
        faults = [ap.Fault("b2h", n.T_AUDIT, c, 0, "delete", 100, 50) for c in range(3)]
        sim, res = run(faults)
        self.assertTrue(res["host_done"]); self.assertEqual(res["ledger"].crc_dropped, 3)
        sim, res = run(faults, host_kw={"crc_budget": 2})
        self.assertTrue(res["host_failed"]); self.assertIn("PROTOCOL_CRC_BUDGET: 3 > 2", res["fail_reason"])
        self.assertEqual(res["board"]["outcome"], "STOP_AUDIT")

    def test_an_auto_audited_non_scored_path_keeps_its_outcome_and_marks_replayed_only_on_abort(self):
        sim, res = run([ap.Fault("b2h", n.T_AUDIT, 0, a, "delete", 100, 50) for a in range(3)], outcome="STOP_ARM", requested=False)
        self.assertEqual(res["board"], {"outcome": "STOP_ARM", "verified": "replayed-only", "arm": False, "epoch": "STOPPED"})

    def test_the_board_never_waits_unboundedly(self):
        board = ap.PullBoard(TOKEN, 1, FULL, WORDS, requested=True)
        board.start()
        board.tick(ap.BOARD_IDLE_LIMIT_S + 0.1)
        self.assertEqual(board.state, "ABORTED"); self.assertEqual(board.finish()["outcome"], "STOP_AUDIT")


class Selection(unittest.TestCase):
    def test_an_unrequested_scored_candidate_is_not_pulled_and_arms(self):
        sim, res = run(requested=False)
        self.assertEqual(sim.delivered_b2h, [])
        self.assertEqual(res["board"], {"outcome": "SCORED", "verified": "replayed-only", "arm": True, "epoch": "RUNNING"})

    def test_every_non_scored_self_report_is_pulled_without_a_request(self):
        for out in ap.AUTO_OUTCOMES:
            sim, res = run(requested=False, outcome=out)
            self.assertTrue(res["host_done"], out); self.assertEqual(res["board"]["verified"], "audited", out)
            self.assertFalse(res["board"]["arm"])


class Content(unittest.TestCase):
    def test_valid_crc_with_wrong_content_is_falsified_on_recompute(self):
        sim, res = run(corrupt={5: (5 * au.SPARSE_WINDOW + 7, 0xDEADBEEF)})
        self.assertTrue(res["host_done"], "the chunk verifies on the wire …")
        with self.assertRaises(Falsified):
            ap.recompute_from_sparse(sim.host.chunks(), MANIFEST, ORACLE)   # … and is a KILL on content

    def test_retransmission_cost_is_in_the_ledger(self):
        _, clean = run()
        _, lossy = run([ap.Fault("b2h", n.T_AUDIT, 3, 0, "delete", 100, 50)])
        self.assertGreater(lossy["ledger"].bytes_rx, clean["ledger"].bytes_rx)
        self.assertGreater(lossy["ledger"].bytes_tx, clean["ledger"].bytes_tx)   # one more GET
        self.assertGreater(lossy["seconds"], clean["seconds"])


if __name__ == "__main__":
    unittest.main()
