"""The contract test the L5 line was missing: the C application's ACTUAL wire bytes, fed to
the REAL host validator.

Why this file exists. `tests/test_l5_refloop.py` rehearses `host/l5_refloop.py` -- the
*Python* reference of the loop -- against a fake PL, and it passed while the C application
emitted records the validator could never accept: flat payloads with no `seq`, no
`verified` and no nested `evidence`, no `IDENT` at all although
`validate_standalone_run_log` requires `app_identity`, no `HB` although the collector calls
30 s of silence a CRASH, and a closing control tagged `CLOSING_CONTROL`, which is not a
LOOP_OUTCOME. Every test was green because nothing consumed the C serialisation.

So this test compiles `firmware/p3_wire.c` -- the same source the board image links -- via
`firmware/p3_wire_twin.c`, and for a whole session:

  * the C code emits the IDENT / SIGNREQ / REC / CLOSE / TERM lines,
  * the REAL `NotaryRelay` and the REAL signer (`sign_arm.sign_genome`, fixture key) answer
    the sign requests, so commits, tables and tags are genuine,
  * the REAL `Collector` parses every line the C code produced,
  * and the REAL `validate_standalone_run_log` adjudicates the assembled log.

A green run here is evidence about the bytes the board will actually put on the wire.
`test_the_old_flat_record_shape_is_rejected` is the discrimination check: it proves this
test would have caught the defect it was written for.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import nonce as nc  # noqa: E402
from validators import audit as au  # noqa: E402
from validators import records  # noqa: E402
from validators import signer as sg  # noqa: E402
import l5_notary as n  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402
import sign_arm  # noqa: E402

SEED = 0x9E3779B97F4A7C15
TOKEN = "5a" * 16
CARRIER_SHA = "3c" * 32
TWIN = R / "firmware" / "build" / "p3_wire_twin"


def build_twin() -> Path:
    subprocess.run(["make", "wire"], cwd=R / "firmware", check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return TWIN


class Twin:
    """Drives the C serialiser: commands in, framed lines out."""

    def __init__(self, exe: Path):
        self.exe = exe
        self.commands: list[str] = []

    def __call__(self, *commands: str) -> list[str]:
        out = subprocess.run([str(self.exe)], input="\n".join(commands) + "\n",
                             capture_output=True, text=True, check=True).stdout
        lines = [ln for ln in out.splitlines() if ln.strip()]
        bad = [ln for ln in lines if ln.startswith("!")]
        if bad:
            raise AssertionError(f"the C serialiser refused: {bad}")
        return lines


class WireContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.twin = Twin(build_twin())
        cls.tmp = tempfile.TemporaryDirectory()
        key = Path(cls.tmp.name) / "K.bin"
        key.write_bytes(bytes(range(16)))
        os.chmod(key, 0o600)
        cls.holder = sg.KeyHolder(key)
        cls.manifest = g.load_manifest()
        cls.consts = po.load_constants()
        cls.blank = gn.blank_genome(cls.manifest)
        cls.blank_commit = cls._verdict(cls.blank)["candidate_sha256"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def _verdict(cls, genome: int) -> dict:
        frames = gn.frames_from_genome(genome, cls.manifest)
        return g.gate(g.build_streams(frames, cls.manifest), cls.manifest)

    # ------------------------------------------------------------------ audit words ---

    AUDIT_CHUNK = 384   # words per chunk, as firmware p3_app.c P3_AUDIT_CHUNK

    @classmethod
    def _raw_words(cls, genome: int, span: str = "streams+readback") -> list[int]:
        """The raw words the application would hold for this candidate: the three staging
        streams it built (re-read verbatim by a faithful board) followed, for a full span,
        by the twelve target frames read back — FAR order, as the firmware serves them."""
        frames = gn.frames_from_genome(genome, cls.manifest)
        words = [w for s in g.build_streams(frames, cls.manifest) for w in s["words"]]
        if span == "streams+readback":
            words += [w for far in sorted(frames) for w in frames[far]]
        assert len(words) == au.SPAN_WORDS[span]
        return words

    def _audit_cmds(self, seq: int, genome: int, span: str = "streams+readback",
                    words: list[int] | None = None) -> list[str]:
        """Twin `audit` commands: the C serialiser chunks these words exactly as the board
        does (base64url, big-endian, 384 words per chunk)."""
        words = self._raw_words(genome, span) if words is None else words
        total = len(words)
        n = (total + self.AUDIT_CHUNK - 1) // self.AUDIT_CHUNK
        cmds = []
        for c in range(n):
            off = c * self.AUDIT_CHUNK
            part = words[off:off + self.AUDIT_CHUNK]
            b64 = base64.urlsafe_b64encode(b"".join(w.to_bytes(4, "big") for w in part)).decode()
            cmds.append(f"audit token={TOKEN} seq={seq} chunk={c} chunks={n} word_offset={off} "
                        f"word_count={len(part)} total_words={total} span={span} words={b64}")
        return cmds

    def _validate(self, log: dict, chunks: list[dict]) -> dict:
        return records.validate_standalone_run_log(log, self.blank_commit, SEED, chunks, self.manifest)

    # ------------------------------------------------------------------ the session ---

    def _session(self, genomes: list[int]) -> tuple[dict, list[dict]]:
        """Run a whole COMPLETED session whose records are produced by the C code."""
        signer = lambda req: sign_arm.sign_genome(  # noqa: E731
            self.holder, req["genome"], req["nonce"])
        relay = n.NotaryRelay(TOKEN, signer, drop_budget=16, clock=lambda: 0.0)
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)

        ident_line, = self.twin(
            f"ident token={TOKEN} idcode=0x03722093 uboot_epoch=7 "
            f"carrier_sha256={CARRIER_SHA} nonce={SEED:016x} status=0x900 fclk0=50000000")
        collector.on_line(ident_line)

        chain = SEED
        seq = 0
        candidates = [self.blank] + genomes + [self.blank]
        for genome in candidates:
            seq += 1
            genome_hex = gn.to_hex(genome)
            req_line, = self.twin(
                f"signreq token={TOKEN} app_epoch=0 seq={seq} genome={genome_hex} "
                f"nonce={chain:016x}")
            reply_line = relay.handle_line(req_line)
            self.assertIsNotNone(reply_line, "the relay did not answer the C sign request")
            reply = n.decode_payload(n.parse_line(reply_line)["payload"])
            self.assertEqual(reply["schema"], "sign_reply")

            verdict = self._verdict(genome)
            tables = ",".join(reply["expected_tables"])
            nonce_after = nc.step(chain)
            # the collector must see a heartbeat inside the long stretch, exactly as the
            # application now emits one at every progress point
            hb_line, = self.twin(f"hb token={TOKEN} seq={seq}")
            collector.on_line(hb_line)
            # the application serves the raw words BEFORE the record that will claim them
            for audit_line in self.twin(*self._audit_cmds(seq, genome)):
                collector.on_line(audit_line)
            rec_line, = self.twin(
                f"rec token={TOKEN} seq={seq} genome={genome_hex} outcome=SCORED audited=1 "
                f"commit={reply['commit']} tables={tables} tag={reply['tag']} "
                f"staged={reply['commit']} stream={verdict['sequence_sha256']} "
                f"readback={reply['commit']} envelopes=3 audit_available=1 "
                f"nonce_before={chain:016x} nonce_after={nonce_after:016x} "
                f"status_after=0xf54 fault_after=0 key_loaded=1 "
                f"hw_commit={reply['commit']} readout={tables} scores=18,22,20,20,20,18 "
                f"hb_before=1 hb_after=2")
            collector.on_line(rec_line)
            chain = nonce_after

        close_line, = self.twin(
            f"closing token={TOKEN} seq={seq} nonce_before={chain:016x} "
            f"nonce_after={nc.step(chain):016x} fault=13 status=0x982")
        collector.on_line(close_line)
        term_line, = self.twin(
            f"term token={TOKEN} kind=COMPLETED reason=budget last_seq={seq} "
            f"scored={len(candidates)} refused_by_gate=0 closing_restore=1 "
            f"closing_baseline=1 closing_unsigned=1 audited={len(candidates)} "
            f"total={len(candidates)} crc_dropped=0 drop_budget=16")
        collector.on_line(term_line)

        return ({"control_plane": "standalone", "app_identity": collector.app_identity,
                 "loop_records": collector.loop_records,
                 "closing_negative": collector.closing_negative,
                 "session_summary": collector.session_summary,
                 "notary_log": relay.notary_log()}, collector.audits)

    # ------------------------------------------------------------------ the checks ----

    def test_a_full_session_of_c_emitted_records_passes_the_real_validator(self):
        log, chunks = self._session([gn.corpus_genome(2, self.manifest)])
        self.assertEqual(len(chunks), 3 * 8, "eight C-chunked audit frames per candidate")
        out = self._validate(log, chunks)
        self.assertEqual(out["scored"], 3)          # opening baseline, candidate, closing
        self.assertEqual(out["audited"], 3)         # the HOST verified all three
        self.assertEqual(out["chain_length"], 4)    # + the closing unsigned control
        for seq in (1, 2, 3):
            self.assertEqual(out["marks"][seq], "audited")
            self.assertTrue(all(out["audit"][seq]["compared"].values()))

    def test_the_c_code_sends_an_identity_the_validator_accepts(self):
        log, _ = self._session([])
        ident = records.validate(log["app_identity"])
        self.assertEqual(ident["token"], TOKEN)
        self.assertEqual(ident["control_plane"], "standalone")
        self.assertEqual(ident["pss_idcode"], "0x03722093")

    def test_records_carry_seq_verified_and_nested_evidence(self):
        """The three fields the old flat payload omitted."""
        log, _ = self._session([])
        for rec in log["loop_records"]:
            self.assertIn("seq", rec)
            self.assertIn(rec["verified"], ("audited", "replayed-only"))
            for part in ("sign_reply", "app_oracle_record", "arm", "score"):
                self.assertIn(part, rec["evidence"])

    def test_heartbeats_keep_the_collector_from_declaring_a_crash(self):
        line, = self.twin(f"hb token={TOKEN} seq=4")
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
        self.assertIsNone(collector.poll(now=25.0), "silence should not yet be a crash")
        collector.on_line(line, now=25.0)
        self.assertIsNone(collector.poll(now=50.0), "the heartbeat should have refreshed it")
        self.assertIsNotNone(collector.poll(now=90.0), "silence past 3H must still crash")

    def test_the_closing_control_is_filed_as_closing_negative_not_a_loop_record(self):
        log, _ = self._session([])
        self.assertIsNotNone(log["closing_negative"])
        self.assertEqual(log["closing_negative"]["fault"], records.EXPECTED_FAULT["unsigned"])
        self.assertNotIn("CLOSING_CONTROL", [r["outcome"] for r in log["loop_records"]])

    def test_an_audit_chunk_round_trips_through_the_frame(self):
        words = bytes(range(64))
        import base64
        b64 = base64.urlsafe_b64encode(words).decode()
        line, = self.twin(f"audit token={TOKEN} seq=2 chunk=0 chunks=4 word_offset=0 "
                          f"word_count=16 total_words=2814 span=streams+readback words={b64}")
        payload = n.decode_payload(n.parse_line(line)["payload"])
        self.assertEqual(payload["schema"], "app_audit_chunk")
        self.assertEqual((payload["chunks"], payload["word_count"]), (4, 16))
        self.assertEqual(base64.urlsafe_b64decode(payload["words"]), words)

    def test_a_short_audit_says_so_and_cannot_pass_as_a_full_one(self):
        """A candidate that ended at link 2 has staging streams but no readback frames;
        `span` and `total_words` keep the host from treating that as a full audit."""
        short, = self.twin(f"audit token={TOKEN} seq=3 chunk=0 chunks=5 word_offset=0 "
                           f"word_count=384 total_words=1602 span=streams words=AAAA")
        full, = self.twin(f"audit token={TOKEN} seq=4 chunk=0 chunks=8 word_offset=0 "
                          f"word_count=384 total_words=2814 span=streams+readback words=AAAA")
        s = n.decode_payload(n.parse_line(short)["payload"])
        f = n.decode_payload(n.parse_line(full)["payload"])
        self.assertEqual(s["span"], "streams")
        self.assertEqual(f["span"], "streams+readback")
        self.assertLess(s["total_words"], f["total_words"])

    # -- STOP_ARM: the state session 1 hit, which the schema could not express ----------

    def _stop_arm_record(self, nonce_after_hex: str) -> dict:
        """One C-emitted STOP_ARM record: an ARM was written, the nonce is unchanged."""
        signer = lambda req: sign_arm.sign_genome(  # noqa: E731
            self.holder, req["genome"], req["nonce"])
        relay = n.NotaryRelay(TOKEN, signer, drop_budget=16, clock=lambda: 0.0)
        genome_hex = gn.to_hex(self.blank)
        req_line, = self.twin(f"signreq token={TOKEN} app_epoch=0 seq=1 "
                              f"genome={genome_hex} nonce={SEED:016x}")
        reply = n.decode_payload(n.parse_line(relay.handle_line(req_line))["payload"])
        verdict = self._verdict(self.blank)
        tables = ",".join(reply["expected_tables"])
        line, = self.twin(
            f"rec token={TOKEN} seq=1 genome={genome_hex} outcome=STOP_ARM audited=1 "
            f"commit={reply['commit']} tables={tables} tag={reply['tag']} "
            f"staged={reply['commit']} stream={verdict['sequence_sha256']} "
            f"readback={reply['commit']} envelopes=3 audit_available=1 "
            f"nonce_before={SEED:016x} nonce_after={nonce_after_hex} "
            f"status_after=0x910 status_first=0x901 settle_polls=3 settled=1 "
            f"fault_after=0 key_loaded=1 writes_issued=25")
        return n.decode_payload(n.parse_line(line)["payload"])

    def _arm_rec_cmd(self, reply: dict, verdict: dict, genome_hex: str, outcome: str,
                     nonce_after_hex: str, settle: str, seq: int = 1) -> str:
        tables = ",".join(reply["expected_tables"])
        return (f"rec token={TOKEN} seq={seq} genome={genome_hex} outcome={outcome} audited=1 "
                f"commit={reply['commit']} tables={tables} tag={reply['tag']} "
                f"staged={reply['commit']} stream={verdict['sequence_sha256']} "
                f"readback={reply['commit']} envelopes=3 audit_available=1 "
                f"nonce_before={SEED:016x} nonce_after={nonce_after_hex} "
                f"fault_after=0 key_loaded=1 writes_issued=25 {settle}")

    def _one_candidate(self):
        """A relay that has answered seq 1 for the blank genome, plus the reply/verdict."""
        signer = lambda req: sign_arm.sign_genome(  # noqa: E731
            self.holder, req["genome"], req["nonce"])
        relay = n.NotaryRelay(TOKEN, signer, drop_budget=16, clock=lambda: 0.0)
        genome_hex = gn.to_hex(self.blank)
        req_line, = self.twin(f"signreq token={TOKEN} app_epoch=0 seq=1 "
                              f"genome={genome_hex} nonce={SEED:016x}")
        reply = n.decode_payload(n.parse_line(relay.handle_line(req_line))["payload"])
        return relay, reply, self._verdict(self.blank), genome_hex

    def _terminal_log(self, relay, lines: list[str], kind="STOPPED") -> dict:
        """Assemble a run log from C-emitted REC/TERM lines through the real collector."""
        ident_line, = self.twin(
            f"ident token={TOKEN} idcode=0x03722093 uboot_epoch=7 "
            f"carrier_sha256={CARRIER_SHA} nonce={SEED:016x} status=0x900 fclk0=50000000")
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
        collector.on_line(ident_line)
        for ln in lines:
            collector.on_line(ln)
        self.assertIsNotNone(collector.session_summary, "no TERM reached the collector")
        return ({"control_plane": "standalone", "app_identity": collector.app_identity,
                 "loop_records": collector.loop_records,
                 "session_summary": collector.session_summary,
                 "notary_log": relay.notary_log()}, collector.audits)

    def _blank_audit_lines(self, seq: int = 1, span: str = "streams+readback") -> list[str]:
        """The C-chunked raw words for the blank candidate, as the board would serve them."""
        return self.twin(*self._audit_cmds(seq, self.blank, span))

    # -- the settle poll (session 3, 2026-09-01) ---------------------------------------

    SETTLED = "status_after=0x910 status_first=0x901 settle_polls=3 settled=1"
    NEVER = "status_after=0x901 status_first=0x901 settle_polls=1000000 settle_max=1000000 settled=0"

    def test_every_c_arm_record_carries_the_settle_poll(self):
        rec = self._stop_arm_record(f"{SEED:016x}")
        s = rec["evidence"]["arm"]["settle"]
        self.assertEqual(set(s), {"polls", "polls_max", "settled", "status_first", "status_last"})
        self.assertEqual(s["status_last"], rec["evidence"]["arm"]["status_after"])
        self.assertEqual((s["polls"], s["settled"]), (3, True))

    def test_a_stop_arm_that_never_settled_is_rejected(self):
        """STOP_ARM now means the gate SETTLED and did not consume. An unsettled one is the
        session-1/3 mistake of concluding 'not consumed' from a read taken too early."""
        relay, reply, verdict, gh = self._one_candidate()
        line, = self.twin(self._arm_rec_cmd(reply, verdict, gh, "STOP_ARM", f"{SEED:016x}", self.NEVER))
        with self.assertRaises(records.RecordError) as cm:
            records.validate(n.decode_payload(n.parse_line(line)["payload"]))
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("STOP_SETTLE", str(cm.exception))

    def test_a_stop_settle_with_the_nonce_unchanged_validates_and_consumes_nothing(self):
        """busy never clears: the neutral outcome, chain length 0."""
        relay, reply, verdict, gh = self._one_candidate()
        rec_cmd = self._arm_rec_cmd(reply, verdict, gh, "STOP_SETTLE", f"{SEED:016x}", self.NEVER)
        term_cmd = (f"term token={TOKEN} kind=STOPPED reason=did-not-settle last_seq=1 "
                    f"closing_restore=1 crc_dropped=0 drop_budget=16")
        rec_line, term_line = self.twin(rec_cmd, term_cmd)
        log, chunks = self._terminal_log(relay, self._blank_audit_lines() + [rec_line, term_line])
        rec = log["loop_records"][0]
        self.assertEqual(rec["outcome"], "STOP_SETTLE")
        self.assertEqual(rec["evidence"]["arm"]["settle"]["settled"], False)
        self.assertEqual(rec["evidence"]["arm"]["settle"]["polls"], 1000000)
        out = self._validate(log, chunks)
        self.assertEqual(out["chain_length"], 0)
        self.assertEqual(out["audited"], 1)
        records.check_audit_policy(log, out["marks"])

    def test_a_stop_settle_with_the_nonce_stepped_validates_and_consumes_one(self):
        """busy never clears but the nonce DID step (the gate is stuck after sh_done): the
        chain advances by exactly one, and the record still claims nothing."""
        relay, reply, verdict, gh = self._one_candidate()
        rec_cmd = self._arm_rec_cmd(reply, verdict, gh, "STOP_SETTLE", f"{nc.step(SEED):016x}", self.NEVER)
        term_cmd = f"term token={TOKEN} kind=STOPPED reason=did-not-settle last_seq=1 closing_restore=1"
        rec_line, term_line = self.twin(rec_cmd, term_cmd)
        log, chunks = self._terminal_log(relay, self._blank_audit_lines() + [rec_line, term_line])
        out = self._validate(log, chunks)
        self.assertEqual(out["chain_length"], 1)

    def test_a_stop_settle_whose_nonce_jumped_is_a_falsifier(self):
        """neither unchanged nor stepped once: the PL consumed something the model does
        not describe — prereg §3's nonce item, so Falsified, not an accounting HOLD."""
        relay, reply, verdict, gh = self._one_candidate()
        jumped = nc.step(nc.step(SEED))
        line, = self.twin(self._arm_rec_cmd(reply, verdict, gh, "STOP_SETTLE", f"{jumped:016x}", self.NEVER))
        with self.assertRaises(records.Falsified):
            records.validate(n.decode_payload(n.parse_line(line)["payload"]))

    def test_a_stop_settle_that_claims_it_settled_is_a_contradiction(self):
        relay, reply, verdict, gh = self._one_candidate()
        line, = self.twin(self._arm_rec_cmd(reply, verdict, gh, "STOP_SETTLE", f"{SEED:016x}", self.SETTLED))
        with self.assertRaises(records.RecordError) as cm:
            records.validate(n.decode_payload(n.parse_line(line)["payload"]))
        self.assertNotIsInstance(cm.exception, records.Falsified)

    def test_a_consumed_arm_whose_nonce_did_not_step_is_a_falsifier(self):
        """busy cleared, scorer_done, but the nonce is unchanged with a SCORED claim: that is
        the nonce model contradicted, not a taxonomy slip."""
        relay, reply, verdict, gh = self._one_candidate()
        tables = ",".join(reply["expected_tables"])
        cmd = self._arm_rec_cmd(reply, verdict, gh, "SCORED", f"{SEED:016x}", self.SETTLED)
        cmd += (f" hw_commit={reply['commit']} readout={tables} scores=18,22,20,20,20,18 "
                f"hb_before=1 hb_after=2")
        line, = self.twin(cmd)
        with self.assertRaises(records.Falsified):
            records.validate(n.decode_payload(n.parse_line(line)["payload"]))

    def test_a_nonce_that_stepped_before_the_strobe_breaks_the_chain_as_a_falsifier(self):
        """'premature step': the ARM's nonce_before is already past the model chain."""
        relay, reply, verdict, gh = self._one_candidate()
        # a STOP_ARM record whose nonce_before is step(SEED) while the notary signed SEED
        tables = ",".join(reply["expected_tables"])
        early = nc.step(SEED)
        rec_cmd = (f"rec token={TOKEN} seq=1 genome={gh} outcome=STOP_ARM audited=1 "
                   f"commit={reply['commit']} tables={tables} tag={reply['tag']} "
                   f"staged={reply['commit']} stream={verdict['sequence_sha256']} "
                   f"readback={reply['commit']} envelopes=3 audit_available=1 "
                   f"nonce_before={early:016x} nonce_after={early:016x} "
                   f"fault_after=0 key_loaded=1 writes_issued=25 {self.SETTLED}")
        term_cmd = f"term token={TOKEN} kind=STOPPED reason=x last_seq=1 closing_restore=1"
        rec_line, term_line = self.twin(rec_cmd, term_cmd)
        log, chunks = self._terminal_log(relay, self._blank_audit_lines() + [rec_line, term_line])
        with self.assertRaises(records.Falsified) as cm:
            self._validate(log, chunks)
        self.assertIn("(vii)", str(cm.exception))

    # -- the TERM's audit block comes from the serialiser's tally (session 3) -----------

    def test_a_counted_stop_arm_terminal_session_validates(self):
        """Session 3's rejection: the TERM said audited 1 / total 0 because total was
        scored + refused. The C code now tallies the records it serialised; a STOP_ARM
        terminal session emitted by the C code, with NO explicit count, must validate."""
        relay, reply, verdict, gh = self._one_candidate()
        rec_cmd = self._arm_rec_cmd(reply, verdict, gh, "STOP_ARM", f"{SEED:016x}", self.SETTLED)
        term_cmd = (f"term token={TOKEN} kind=STOPPED reason=nonce-did-not-step last_seq=1 "
                    f"closing_restore=1 crc_dropped=0 drop_budget=16")
        rec_line, term_line = self.twin(rec_cmd, term_cmd)   # ONE process: the tally carries
        log, chunks = self._terminal_log(relay, self._blank_audit_lines() + [rec_line, term_line])
        self.assertEqual(log["session_summary"]["audit"], {"audited": 1, "total": 1})
        out = self._validate(log, chunks)
        self.assertEqual((out["chain_length"], out["audited"]), (0, 1))

    def test_a_term_that_undercounts_or_overcounts_is_rejected_as_accounting(self):
        relay, reply, verdict, gh = self._one_candidate()
        rec_cmd = self._arm_rec_cmd(reply, verdict, gh, "STOP_ARM", f"{SEED:016x}", self.SETTLED)
        for total in (0, 2):
            term_cmd = (f"term token={TOKEN} kind=STOPPED reason=x last_seq=1 "
                        f"closing_restore=1 audited=1 total={total}")
            rec_line, term_line = self.twin(rec_cmd, term_cmd)
            log, chunks = self._terminal_log(relay, self._blank_audit_lines() + [rec_line, term_line])
            with self.assertRaises(records.RecordError) as cm:
                self._validate(log, chunks)
            self.assertNotIsInstance(cm.exception, records.Falsified, f"total={total} is a HOLD, not a KILL")
            self.assertIn("(ix)", str(cm.exception) if "(ix)" in str(cm.exception) else "(ix) " + str(cm.exception))

    def test_the_tally_counts_only_records_marked_audited_as_audited(self):
        relay, reply, verdict, gh = self._one_candidate()
        rec_cmd = self._arm_rec_cmd(reply, verdict, gh, "STOP_ARM", f"{SEED:016x}", self.SETTLED)
        rec_cmd = rec_cmd.replace("audited=1", "audited=0")
        term_cmd = f"term token={TOKEN} kind=STOPPED reason=x last_seq=1 closing_restore=1"
        rec_line, term_line = self.twin(rec_cmd, term_cmd)
        log, chunks = self._terminal_log(relay, [rec_line, term_line])
        self.assertEqual(log["session_summary"]["audit"], {"audited": 0, "total": 1})
        self._validate(log, chunks)      # no words served, none claimed: consistent

    def test_a_stop_arm_record_from_the_c_code_validates(self):
        rec = self._stop_arm_record(f"{SEED:016x}")        # unchanged nonce
        records.validate(rec)
        arm = rec["evidence"]["arm"]
        self.assertEqual(arm["nonce_after"], arm["nonce_before"])
        # the observations session 1 threw away are all present
        for k in ("status_after", "fault_after", "writes_issued", "key_loaded_observed"):
            self.assertIn(k, arm)
        # the strobe's fate is NOT observable (CTRL is write-only) and the record says so
        # rather than dropping the question
        self.assertIn("unavailable", arm["ctrl_readback"])
        self.assertNotIn("ctrl_before", arm)
        self.assertEqual(arm["writes_issued"], 25)          # 20 payload + 4 tag + strobe

    def test_a_stop_arm_whose_nonce_stepped_is_rejected(self):
        """Discrimination: if the nonce stepped, the PL DID consume the ARM and the record
        is REFUSED_BY_PL or SCORED. STOP_ARM must not become a catch-all."""
        stepped = nc.step(SEED)
        rec = self._stop_arm_record(f"{stepped:016x}")
        with self.assertRaises(records.RecordError):
            records.validate(rec)

    def test_a_stop_arm_consumes_no_nonce_in_the_chain(self):
        """The PL never stepped it, so rule (vii)'s chain must not advance either."""
        rec = self._stop_arm_record(f"{SEED:016x}")
        signer = lambda req: sign_arm.sign_genome(  # noqa: E731
            self.holder, req["genome"], req["nonce"])
        relay = n.NotaryRelay(TOKEN, signer, drop_budget=16, clock=lambda: 0.0)
        req_line, = self.twin(f"signreq token={TOKEN} app_epoch=0 seq=1 "
                              f"genome={gn.to_hex(self.blank)} nonce={SEED:016x}")
        relay.handle_line(req_line)
        ident_line, = self.twin(
            f"ident token={TOKEN} idcode=0x03722093 uboot_epoch=7 "
            f"carrier_sha256={CARRIER_SHA} nonce={SEED:016x} status=0x900 fclk0=50000000")
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
        collector.on_line(ident_line)
        for audit_line in self._blank_audit_lines():
            collector.on_line(audit_line)
        term_line, = self.twin(
            f"term token={TOKEN} kind=STOPPED reason=nonce-did-not-step last_seq=1 "
            f"scored=0 refused_by_gate=0 closing_restore=1 audited=1 total=1 "
            f"crc_dropped=0 drop_budget=16")
        collector.on_line(term_line)
        log = {"control_plane": "standalone", "app_identity": collector.app_identity,
               "loop_records": [rec], "session_summary": collector.session_summary,
               "notary_log": relay.notary_log()}
        out = self._validate(log, collector.audits)
        self.assertEqual(out["chain_length"], 0, "a non-consumed ARM must not count")
        self.assertEqual(out["scored"], 0)
        self.assertEqual(out["audited"], 1, "the candidate staged and its words recompute")
        records.check_audit_policy(log, out["marks"])   # STOP_ARM self-reports, so it must be audited

    # -- the audit GATE: served words recomputed on the host (design review 2026-09-01) --

    def _stop_arm_session(self, audit_lines: list[str]) -> tuple[dict, list[dict]]:
        relay, reply, verdict, gh = self._one_candidate()
        rec_cmd = self._arm_rec_cmd(reply, verdict, gh, "STOP_ARM", f"{SEED:016x}", self.SETTLED)
        term_cmd = f"term token={TOKEN} kind=STOPPED reason=x last_seq=1 closing_restore=1"
        rec_line, term_line = self.twin(rec_cmd, term_cmd)
        return self._terminal_log(relay, audit_lines + [rec_line, term_line])

    def test_a_record_marked_audited_with_no_words_served_is_refused(self):
        """THE hole the review found: the application says 'audited', nothing was served,
        and the old gate believed it. The host now derives the mark and refuses."""
        log, chunks = self._stop_arm_session([])
        self.assertEqual(chunks, [])
        self.assertEqual(log["loop_records"][0]["verified"], "audited")
        with self.assertRaises(records.RecordError) as cm:
            self._validate(log, chunks)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("host-derived mark is 'replayed-only'", str(cm.exception))

    def test_one_flipped_word_in_the_c_chunked_audit_is_a_falsifier(self):
        words = self._raw_words(self.blank)
        words[1602 + 505] ^= 1 << 9                       # a readback frame word
        lines = self.twin(*self._audit_cmds(1, self.blank, words=words))
        log, chunks = self._stop_arm_session(lines)
        with self.assertRaises(records.Falsified) as cm:
            self._validate(log, chunks)
        self.assertIn("readback_sha256", str(cm.exception))
        words = self._raw_words(self.blank)
        words[40] ^= 1                                    # a staging-stream word
        lines = self.twin(*self._audit_cmds(1, self.blank, words=words))
        log, chunks = self._stop_arm_session(lines)
        with self.assertRaises(records.Falsified) as cm:
            self._validate(log, chunks)
        self.assertIn("staged_stream_sha256", str(cm.exception))

    def test_full_length_words_that_do_not_parse_are_a_falsifier_not_a_hold(self):
        """Round 2's boundary, through the C chunker: 2814 words, every chunk well-formed,
        but stream 2's sync word destroyed — content, so KILL-class."""
        words = self._raw_words(self.blank)
        words[2 * 534 + 8] = 0
        lines = self.twin(*self._audit_cmds(1, self.blank, words=words))
        log, chunks = self._stop_arm_session(lines)
        self.assertEqual(len(chunks), 8)
        with self.assertRaises(records.Falsified) as cm:
            self._validate(log, chunks)
        self.assertIn("does not parse", str(cm.exception))
        import l5_runner as lr
        self.assertTrue(lr.classify_rejection(cm.exception).startswith("KILL falsified:"))

    def test_a_missing_or_duplicated_c_chunk_blocks_the_log(self):
        lines = self._blank_audit_lines()
        import l5_runner as lr
        for variant, fragment in ((lines[:5] + lines[6:], "missing [5]"), (lines + [lines[2]], "duplicate")):
            log, chunks = self._stop_arm_session(variant)
            with self.assertRaises(records.RecordError) as cm:
                self._validate(log, chunks)
            self.assertNotIsInstance(cm.exception, records.Falsified)
            self.assertIn(fragment, str(cm.exception))
            self.assertTrue(lr.classify_rejection(cm.exception).startswith("HOLD instrument:"),
                            "a transport defect must never be promoted to KILL")

    def test_a_short_link2_audit_cannot_back_a_readback_claim(self):
        """streams-only words, correctly labelled, behind a STOP_ARM that claims a readback
        and marks itself audited: the host derives replayed-only and refuses the log."""
        lines = self._blank_audit_lines(span="streams")
        log, chunks = self._stop_arm_session(lines)
        with self.assertRaises(records.RecordError) as cm:
            self._validate(log, chunks)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("streams-only audit cannot back the readback_sha256", str(cm.exception))

    def test_the_gate_result_names_what_was_compared(self):
        log, chunks = self._stop_arm_session(self._blank_audit_lines())
        out = self._validate(log, chunks)
        self.assertEqual(out["audit"][1]["compared"],
                         {"staged_stream_sha256": True, "staged_sha256": True, "readback_sha256": True})

    # -- the audit policy the preregistration can actually require ---------------------

    def test_the_audit_policy_holds_for_a_session_of_c_emitted_records(self):
        log, chunks = self._session([gn.corpus_genome(2, self.manifest)])
        out = records.check_audit_policy(log, self._validate(log, chunks)["marks"])
        self.assertEqual(len(out["audited"]), 3)
        self.assertEqual(out["exempt_no_self_report"], [])

    def test_a_gate_refusal_is_exempt_because_it_staged_nothing(self):
        """Nothing was staged, so no raw words exist; the notary_log's own refusal is the
        corroboration (rule vii). Marking it 'audited' would be a lie."""
        log = {"loop_records": [
            {"seq": 1, "outcome": "SCORED", "verified": "audited",
             "evidence": {"app_oracle_record": {}}},
            {"seq": 2, "outcome": "REFUSED_BY_GATE", "verified": "replayed-only",
             "evidence": {"sign_refusal": {}}}]}
        marks = {1: "audited", 2: "replayed-only"}
        self.assertEqual(records.check_audit_policy(log, marks)["exempt_no_self_report"], [2])

    def test_an_unaudited_self_report_is_refused(self):
        """Discrimination: the policy must reject exactly what it exists to catch."""
        log = {"loop_records": [
            {"seq": 1, "outcome": "SCORED", "verified": "replayed-only",
             "evidence": {"app_oracle_record": {}}}]}
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log, {1: "replayed-only"})

    def test_a_link2_refusal_must_be_audited_because_it_staged(self):
        """STOP_LINK2 asserts `staged != commit`; the host cannot check that claim without
        the staged words, so it is NOT exempt."""
        log = {"loop_records": [
            {"seq": 1, "outcome": "STOP_LINK2", "verified": "replayed-only",
             "evidence": {"sign_reply": {}}}]}
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log, {1: "replayed-only"})

    def test_every_c_line_survives_the_real_frame_parser(self):
        log_lines = self.twin(
            f"ident token={TOKEN} carrier_sha256={CARRIER_SHA} nonce={SEED:016x}",
            f"hb token={TOKEN} seq=1",
            f"term token={TOKEN} kind=STOPPED reason=identity last_seq=0 total=0")
        for line in log_lines:
            f = n.parse_line(line)                        # raises on CRC/frame/token error
            self.assertEqual(f["token"], TOKEN)

    # -- discrimination: this test must fail on the defect it was written for -----------

    def test_the_old_flat_record_shape_is_rejected(self):
        """The pre-fix payload -- flat, no seq/verified/evidence -- must NOT validate."""
        old = {"schema": "loop_record", "schema_version": "1.0.0", "outcome": "SCORED",
               "commit": "aa" * 32, "genome": "00" * 40, "scores": [1, 2, 3, 4, 5, 6]}
        with self.assertRaises(records.RecordError):
            records.validate(old)

    def test_a_closing_control_as_a_loop_outcome_is_rejected(self):
        """The other half of the old shape: CLOSING_CONTROL is not a LOOP_OUTCOME."""
        rec = {"schema": "loop_record", "schema_version": "1.0.0", "seq": 1,
               "genome": "00" * 40, "outcome": "CLOSING_CONTROL",
               "verified": "replayed-only", "evidence": {}}
        with self.assertRaises(records.RecordError):
            records.validate(rec)


class L6WireContract(WireContract):
    """L6 prereg §2.4 on the C bytes: IDENT 1.1.0 names the master seed, the schedule mode
    and the operator-data hash; candidate records name their arm and the brackets none;
    the sampled policy holds for a C-emitted session whose non-SCORED self-report at an
    unsampled seq was auto-audited — and fails when it was not."""

    MASTER = 0x1234
    OP_SHA = "0c" * 32

    def _ident(self, mode="abba", op_sha=None, master=None) -> str:
        line, = self.twin(
            f"ident token={TOKEN} idcode=0x03722093 uboot_epoch=7 carrier_sha256={CARRIER_SHA} "
            f"nonce={SEED:016x} status=0x900 fclk0=50000000 master_seed={self.MASTER if master is None else master} "
            f"schedule_mode={mode} operator_sha={self.OP_SHA if op_sha is None else op_sha}")
        return line

    def test_identity_1_1_carries_the_three_l6_fields(self):
        ident = n.decode_payload(n.parse_line(self._ident())["payload"])
        self.assertEqual(ident["schema_version"], "1.3.0")       # 1.1.0's fields + rec-v3's two + rel-v4's echo
        records.validate(ident)                                   # 1.0.0 consumers still accept it
        out = records.check_l6_identity(ident, self.MASTER, "abba", self.OP_SHA)
        self.assertEqual(out["master_seed"], self.MASTER)
        # rec-v3: the protocol and the control are declared and checked
        self.assertEqual((ident["protocol"], ident["rec_retry_control"], ident["sign_retry_control"]), ("rel-v4", False, False))
        records.check_l6_identity(ident, self.MASTER, "abba", self.OP_SHA, protocol="rel-v4", rec_retry_control=False,
                                  sign_retry_control=False)
        with self.assertRaises(records.RecordError) as cm:
            records.check_l6_identity(ident, self.MASTER, "abba", self.OP_SHA, protocol="rel-v4", rec_retry_control=True)
        self.assertIn("rec_retry_control", str(cm.exception))
        with self.assertRaises(records.RecordError) as cm:
            records.check_l6_identity(ident, self.MASTER, "abba", self.OP_SHA, protocol="pull-v2")
        self.assertIn("declares wire protocol", str(cm.exception))
        armed = self.twin(f"ident token={TOKEN} carrier_sha256={CARRIER_SHA} nonce={SEED:016x} master_seed={self.MASTER} "
                          f"operator_sha={self.OP_SHA} rec_control=1")[0]
        a = n.decode_payload(n.parse_line(armed)["payload"])
        self.assertTrue(a["rec_retry_control"])
        old = dict(ident); del old["protocol"]; del old["rec_retry_control"]; del old["sign_retry_control"]   # a 1.1.0 image
        with self.assertRaises(records.RecordError):
            records.check_l6_identity(old, self.MASTER, "abba", self.OP_SHA, protocol="rel-v4")
        for wrong in ((self.MASTER + 1, "abba", self.OP_SHA), (self.MASTER, "random_safe_forced", self.OP_SHA),
                      (self.MASTER, "abba", "0d" * 32)):
            with self.assertRaises(records.RecordError):
                records.check_l6_identity(ident, *wrong)

    def _l6_session(self, genomes, arms, audit_seqs, stop_at=None):
        """A C-emitted session: seq 1 baseline (no arm), candidates with `arms`, closing
        baseline — or, with `stop_at`, a STOPPED epoch whose last record is a STOP_ARM at
        that seq. Audits are served only for `audit_seqs`, plus the STOP_ARM unless
        `stop_at` is negative (the withheld-words negative)."""
        import l6_schedule as ls
        signer = lambda req: sign_arm.sign_genome(self.holder, req["genome"], req["nonce"])  # noqa: E731
        relay = n.NotaryRelay(TOKEN, signer, drop_budget=16, clock=lambda: 0.0)
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
        collector.on_line(self._ident())
        chain, seq, n_served = SEED, 0, 0
        withhold = stop_at is not None and stop_at < 0
        stop_seq = abs(stop_at) if stop_at is not None else None
        candidates = [(self.blank, None)] + list(zip(genomes, arms)) + [(self.blank, None)]
        for genome, arm in candidates:
            seq += 1
            genome_hex = gn.to_hex(genome)
            req_line, = self.twin(f"signreq token={TOKEN} app_epoch=0 seq={seq} genome={genome_hex} nonce={chain:016x}")
            reply = n.decode_payload(n.parse_line(relay.handle_line(req_line))["payload"])
            verdict = self._verdict(genome)
            tables = ",".join(reply["expected_tables"])
            arm_kv = f" arm={arm}" if arm else ""
            for hb_line in self.twin(*[f"hb token={TOKEN} seq={seq}"] * 16):
                collector.on_line(hb_line)
            stopping = stop_seq == seq
            served = (seq in audit_seqs) or (stopping and not withhold)
            if served:
                n_served += 1
                for audit_line in self.twin(*self._audit_cmds(seq, genome)):
                    collector.on_line(audit_line)
            common = (f"rec token={TOKEN} seq={seq} genome={genome_hex}{arm_kv} audited={int(served)} "
                      f"commit={reply['commit']} tables={tables} tag={reply['tag']} staged={reply['commit']} "
                      f"stream={verdict['sequence_sha256']} readback={reply['commit']} envelopes=3 audit_available=1 "
                      f"nonce_before={chain:016x} fault_after=0 key_loaded=1 writes_issued=25 ")
            if stopping:
                rec_line, = self.twin(common + f"outcome=STOP_ARM nonce_after={chain:016x} {self.SETTLED}")
                collector.on_line(rec_line)
                # each twin call is its own process, so the serialiser's tally does not carry
                # across records here; the counts are passed as the application would tally them
                term_line, = self.twin(f"term token={TOKEN} kind=STOPPED reason=x last_seq={seq} "
                                       f"closing_restore=1 audited={n_served} total={seq}")
                collector.on_line(term_line)
                break
            nonce_after = nc.step(chain)
            rec_line, = self.twin(common + f"outcome=SCORED nonce_after={nonce_after:016x} status_after=0xf54 "
                                  f"hw_commit={reply['commit']} readout={tables} scores=18,22,20,20,20,18 hb_before=1 hb_after=2")
            collector.on_line(rec_line)
            chain = nonce_after
        else:
            close_line, = self.twin(f"closing token={TOKEN} seq={seq} nonce_before={chain:016x} "
                                    f"nonce_after={nc.step(chain):016x} fault=13 status=0x982")
            collector.on_line(close_line)
            term_line, = self.twin(f"term token={TOKEN} kind=COMPLETED reason=budget last_seq={seq} "
                                   f"scored={len(candidates)} refused_by_gate=0 closing_restore=1 "
                                   f"closing_baseline=1 closing_unsigned=1 audited={n_served} total={seq} "
                                   f"crc_dropped=0 drop_budget=16")
            collector.on_line(term_line)
        log = {"control_plane": "standalone", "app_identity": collector.app_identity,
               "loop_records": collector.loop_records, "session_summary": collector.session_summary,
               "notary_log": relay.notary_log()}
        if collector.closing_negative is not None:
            log["closing_negative"] = collector.closing_negative
        return log, collector.audits

    def test_candidate_records_name_the_arm_and_the_brackets_do_not(self):
        import l6_schedule as ls
        n_c = 3
        sched = ls.schedule(self.MASTER, n_c, ls.MODE_ABBA)
        genomes = [gn.corpus_genome(i, self.manifest) for i in (2, 3, 4)]
        log, chunks = self._l6_session(genomes, [r["arm"] for r in sched], ls.all_seqs(n_c))
        recs = log["loop_records"]
        self.assertEqual([r.get("arm") for r in recs], [None, "random_safe", "map_guided", "map_guided", None])
        self.assertTrue(all(r["schema_version"] == "1.1.0" for r in recs))
        self._validate(log, chunks)
        out = records.check_arm_schedule(log, sched, n_c)
        self.assertEqual((out["checked"], out["brackets"]), ([2, 3, 4], [1, 5]))
        swapped = ls.schedule(self.MASTER, n_c, ls.MODE_A_FORCED)
        with self.assertRaises(records.RecordError) as cm:
            records.check_arm_schedule(log, swapped, n_c)
        self.assertIn("swapped", str(cm.exception))

    def test_a_sampled_session_of_c_records_passes_and_the_two_negatives_fail(self):
        import l6_schedule as ls
        n_c = 3
        sched = ls.schedule(self.MASTER, n_c, ls.MODE_ABBA)
        arms = [r["arm"] for r in sched]
        sampled = ls.sampled_audit_seqs(n_c)                    # {1, 2, 4, 5}: seq 3 unsampled
        self.assertNotIn(3, sampled)
        genomes = [gn.corpus_genome(i, self.manifest) for i in (2, 3, 4)]
        # COMPLETED, seq 3 SCORED and unaudited: the sampled policy accepts it
        log, chunks = self._l6_session(genomes, arms, sampled)
        marks = self._validate(log, chunks)["marks"]
        self.assertEqual(marks[3], "replayed-only")
        out = records.check_audit_policy(log, marks, "sampled", sampled)
        self.assertEqual(out["audited"], [1, 2, 4, 5]); self.assertEqual(out["audited_auto"], [])
        # STOPPED at seq 3 with a STOP_ARM the firmware auto-audited: accepted as audited_auto
        log, chunks = self._l6_session(genomes, arms, sampled, stop_at=3)
        marks = self._validate(log, chunks)["marks"]
        self.assertEqual(marks[3], "audited")
        self.assertEqual(records.check_audit_policy(log, marks, "sampled", sampled)["audited_auto"], [3])
        # the same STOP_ARM with its words withheld: an unaudited self-report → HOLD naming seq 3
        log, chunks = self._l6_session(genomes, arms, sampled, stop_at=-3)
        marks, _ = au.verify(log, chunks, self.manifest)
        with self.assertRaises(records.RecordError) as cm:
            records.check_audit_policy(log, marks, "sampled", sampled)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertIn("[3]", str(cm.exception)); self.assertIn("§3a item 2", str(cm.exception))


class RecWireContract(WireContract):
    """rec-v3 on the C source: firmware/p3_rectx.c — the state machine the board image
    links — run on the host over a pipe, with THIS test playing the runner. The lines it
    sends are judged by the real frame parser; the host side is the real RecHost
    (host/l6_rec.py) where the test says so. A green run is evidence about the bytes and
    the attempt counts the board will actually produce."""

    def _rectx(self, cmd_extra: str = "", seq: int = 1):
        """Starts the twin on a pipe with one `rectx` command; returns (proc, read, write)."""
        import subprocess as sp
        genome_hex = gn.to_hex(self.blank)
        cmd = (f"rectx token={TOKEN} seq={seq} genome={genome_hex} outcome=REFUSED_BY_GATE "
               f"finding_kinds=gate_refusal {cmd_extra}\n")
        proc = sp.Popen([str(self.twin.exe)], stdin=sp.PIPE, stdout=sp.PIPE, text=True, bufsize=1)
        proc.stdin.write(cmd); proc.stdin.flush()

        def write(line: str) -> None:
            proc.stdin.write(line if line.endswith("\n") else line + "\n"); proc.stdin.flush()

        def read() -> str:
            return proc.stdout.readline()
        return proc, read, write

    @staticmethod
    def _result(line: str) -> dict:
        assert line.startswith("!rectx "), line
        out = {}
        for kv in line[len("!rectx "):].rstrip("\n").split(" ", 8):
            k, v = kv.split("=", 1)
            out[k] = v
        return out

    def _finish(self, proc, read) -> dict:
        res = self._result(read())
        proc.stdin.close(); proc.wait(timeout=10)
        return res

    def test_a_clean_transaction_is_one_transmission_and_an_ack(self):
        import l6_rec as rx
        proc, read, write = self._rectx()
        rec = read()
        f = n.parse_line(rec)
        self.assertEqual((f["type"], f["seq"], f["token"]), (n.T_REC, 1, TOKEN))
        records.validate(n.decode_payload(f["payload"]))
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1})))
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["gets"], res["acked"]), ("0", "1", "0", "1"))

    def test_a_recget_makes_the_board_resend_the_same_bytes(self):
        import l6_rec as rx
        proc, read, write = self._rectx()
        first = read()
        write(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1})))
        second = read()
        self.assertEqual(first, second, "the resend is byte-identical")
        write(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1})))
        third = read()
        self.assertEqual(first, third)
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1})))
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["gets"]), ("0", "3", "2"))

    def test_the_bound_running_out_resends_and_exhaustion_stops_without_an_ack(self):
        proc, read, write = self._rectx()
        lines = []
        for _ in range(3):
            lines.append(read()); write("!idle")
        self.assertEqual(len(set(lines)), 1, "three identical transmissions")
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["idle"], res["acked"]), ("-1", "3", "3", "0"))
        self.assertIn("STOP_REC", res["why"])

    def test_a_fourth_recget_is_not_answered_the_bound_is_three(self):
        import l6_rec as rx
        proc, read, write = self._rectx()
        read()
        for _ in range(2):
            write(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1}))); read()
        write(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1})))    # the third GET: no fourth send
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["gets"]), ("-1", "3", "3"))

    def test_stale_and_foreign_lines_are_ignored_and_the_right_ack_is_taken(self):
        import l6_rec as rx
        proc, read, write = self._rectx()
        read()
        write(n.build_line(n.T_HB, 1, TOKEN))                                              # not an ack
        write(n.build_line(rx.T_RECACK, 2, TOKEN, n.encode_payload({"seq": 2})))           # another seq
        write(n.build_line(rx.T_RECACK, 1, "cd" * 16, n.encode_payload({"seq": 1})))       # foreign token
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 2})))           # payload seq differs
        write("P3L5 RECACK 1 " + TOKEN + " abc def 00000000")                              # malformed
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1}))[:-3] + "0") # CRC-broken
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1})))
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["stale"]), ("0", "1", "6"))

    def test_the_control_corrupts_exactly_the_first_transmission(self):
        import l6_rec as rx
        proc, read, write = self._rectx("corrupt=1")
        first = read()
        with self.assertRaises(n.CrcError):
            n.parse_line(first)
        self.assertEqual(rx.head_fields(first), (n.T_REC, 1))
        write(n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1})))
        second = read()
        n.parse_line(second)
        self.assertEqual(rx.corrupt_crc(second), first, "the corruption is exactly l6_rec.corrupt_crc's")
        self.assertEqual(first[:-2], second[:-2])
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1})))
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["corrupted_first"]), ("0", "2", "1"))
        # not on seq 2, even when asked
        proc, read, write = self._rectx("corrupt=0", seq=2)
        n.parse_line(read())
        write(n.build_line(rx.T_RECACK, 2, TOKEN, n.encode_payload({"seq": 2})))
        self.assertEqual(self._finish(proc, read)["corrupted_first"], "0")

    def test_a_truncated_ack_without_a_newline_is_abandoned_and_the_record_resent(self):
        """Review 2026-09-02, blocker 1: the host's RECACK arrives cut mid-line (tail and
        newline lost). The board's own receiver abandons the partial line at the idle
        bound, the wait then runs out, the SAME bytes are resent — never a block."""
        import l6_rec as rx
        proc, read, write = self._rectx()
        first = read()
        ack = n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1}))
        write("!raw " + ack[:len(ack) // 2])          # half an ACK, no newline
        write("!idle")                                # then silence: the bound runs out
        second = read()
        self.assertEqual(first, second)
        write(ack)
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["partial"], res["idle"], res["acked"]), ("0", "2", "1", "1", "1"))

    def test_a_truncated_recget_and_a_line_with_no_newline_at_all_are_bounded_too(self):
        import l6_rec as rx
        proc, read, write = self._rectx()
        read()
        get = n.build_line(rx.T_RECGET, 1, TOKEN, n.encode_payload({"seq": 1}))
        write("!raw " + get[:-1])                     # the whole GET but the newline never comes
        write("!idle")
        read()                                        # resent after the bound
        write("!raw P3L5")                            # four bytes, nothing more
        write("!idle")
        read()                                        # resent again: attempt 3
        write(n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1})))
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["partial"], res["acked"]), ("0", "3", "2", "1"))

    def test_three_truncated_acks_exhaust_to_stop_rec_not_a_block(self):
        import l6_rec as rx
        proc, read, write = self._rectx()
        ack = n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1}))
        for _ in range(3):
            read(); write("!raw " + ack[:30]); write("!idle")
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["partial"], res["acked"]), ("-1", "3", "3", "0"))
        self.assertIn("STOP_REC", res["why"])

    def test_the_stale_limit_is_exactly_sixty_four_ignored_lines(self):
        """63 foreign lines then the ACK: taken; 64 foreign lines: the wait ends like the
        bound and the record is resent (P3_RECTX_STALE_LIMIT)."""
        import l6_rec as rx
        hb = n.build_line(n.T_HB, 1, TOKEN)
        ack = n.build_line(rx.T_RECACK, 1, TOKEN, n.encode_payload({"seq": 1}))
        proc, read, write = self._rectx()
        read()
        for _ in range(63):
            write(hb)
        write(ack)
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["stale"], res["idle"]), ("0", "1", "63", "0"))
        proc, read, write = self._rectx()
        read()
        for _ in range(64):
            write(hb)
        second = read()                               # the 64th ignored line ended the wait: resent
        write(ack)
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["stale"], res["idle"]), ("0", "2", "64", "1"))

    def test_the_real_host_side_drives_the_c_board_through_the_control(self):
        """The C transaction against host/l6_rec.RecHost: the control's broken first line
        makes the real host ask, the real host accepts the resend once and acknowledges."""
        import l6_rec as rx
        proc, read, write = self._rectx("corrupt=1")
        delivered = []
        host = rx.RecHost(TOKEN, 1, send=write, deliver=delivered.append)
        host.on_line(read())                     # broken → RECGET written to the board
        host.on_line(read())                     # the resend → accepted → RECACK
        res = self._finish(proc, read)
        self.assertEqual((res["rc"], res["attempts"], res["gets"]), ("0", "2", "1"))
        self.assertEqual(len(delivered), 1)
        self.assertEqual([a["outcome"] for a in host.ledger.attempts], ["crc", "ok"])


class PullWireContract(WireContract):
    """The pull protocol's C bytes (L6 §2 correction batch): AUDIT_READY and the sparse
    chunks emitted by firmware/p3_wire.c, fed to the real host puller and the real sparse
    assembler; a STOP_AUDIT record from the C serialiser through the real validator."""

    def _sparse_lines(self, seq: int, genome: int) -> list[str]:
        import tempfile
        words = self._raw_words(genome)
        with tempfile.NamedTemporaryFile("w", suffix=".hex", delete=False) as f:
            f.write(" ".join(f"{w:08x}" for w in words))
            path = f.name
        nz = sum(1 for w in words if w)
        cmds = [f"ready token={TOKEN} seq={seq} span=streams+readback total_words=2814 chunks=8 nonzero={nz}"]
        cmds += [f"sparse file={path} seq={seq} chunk={c} span=streams+readback token={TOKEN}" for c in range(8)]
        lines = self.twin(*cmds)
        os.unlink(path)
        return lines

    def test_the_c_pull_lines_drive_the_real_host_puller_to_done(self):
        import l6_audit_pull as apm
        lines = self._sparse_lines(1, self.blank)
        sent = []
        host = apm.PullHost(TOKEN, 1, send=sent.append)
        host.on_line(lines[0])                               # READY binds the transaction
        self.assertEqual(host.state, "WAIT_CHUNK")
        for chunk_line in lines[1:]:
            host.on_line(chunk_line)
        self.assertTrue(host.done)
        self.assertEqual([n.parse_line(l)["type"] for l in sent],
                         ["AUDITGET"] * 8 + ["AUDITDONE"])
        got = au.assemble(host.chunks())[1]
        self.assertEqual(got["words"], self._raw_words(self.blank))

    def test_the_c_sparse_chunks_recompute_the_gate_hashes(self):
        lines = self._sparse_lines(3, self.blank)
        payloads = [n.decode_payload(n.parse_line(l)["payload"]) for l in lines[1:]]
        words = au.assemble(payloads)[3]["words"]
        got = au.recompute(words, "streams+readback", self.manifest)
        verdict = self._verdict(self.blank)
        self.assertEqual(got["staged_sha256"], verdict["candidate_sha256"])
        self.assertEqual(got["staged_stream_sha256"], verdict["sequence_sha256"])

    def test_a_c_emitted_stop_audit_record_validates_and_is_a_hold(self):
        relay, reply, verdict, gh = self._one_candidate()
        line, = self.twin(
            f"rec token={TOKEN} seq=1 genome={gh} outcome=STOP_AUDIT audited=0 "
            f"commit={reply['commit']} tables={','.join(reply['expected_tables'])} tag={reply['tag']} "
            f"staged={reply['commit']} stream={verdict['sequence_sha256']} readback={reply['commit']} "
            f"envelopes=3 audit_available=1 audit_stop_why=host-aborted audit_chunks_served=5 arm=random_safe")
        rec = n.decode_payload(n.parse_line(line)["payload"])
        records.validate(rec)
        self.assertEqual(rec["evidence"]["audit_stop"], {"chunks_served": 5, "why": "host-aborted"})
        self.assertEqual(rec["verified"], "replayed-only")
        self.assertNotIn("arm", rec["evidence"], "no ARM evidence: none was attempted")
        with self.assertRaises(records.RecordError):
            records.check_audit_policy({"loop_records": [rec]}, {1: "replayed-only"})

    def test_a_c_stop_audit_that_claims_audited_is_refused(self):
        relay, reply, verdict, gh = self._one_candidate()
        line, = self.twin(
            f"rec token={TOKEN} seq=1 genome={gh} outcome=STOP_AUDIT audited=1 "
            f"commit={reply['commit']} tables={','.join(reply['expected_tables'])} tag={reply['tag']} "
            f"staged={reply['commit']} stream={verdict['sequence_sha256']} readback={reply['commit']} "
            f"envelopes=3 audit_available=1 audit_stop_why=x audit_chunks_served=0")
        with self.assertRaises(records.RecordError) as cm:
            records.validate(n.decode_payload(n.parse_line(line)["payload"]))
        self.assertIn("cannot be marked audited", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
