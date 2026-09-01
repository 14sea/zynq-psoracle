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

    # ------------------------------------------------------------------ the session ---

    def _session(self, genomes: list[int]) -> dict:
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

        return {"control_plane": "standalone", "app_identity": collector.app_identity,
                "loop_records": collector.loop_records,
                "closing_negative": collector.closing_negative,
                "session_summary": collector.session_summary,
                "notary_log": relay.notary_log()}

    # ------------------------------------------------------------------ the checks ----

    def test_a_full_session_of_c_emitted_records_passes_the_real_validator(self):
        log = self._session([gn.corpus_genome(2, self.manifest)])
        out = records.validate_standalone_run_log(log, self.blank_commit, SEED)
        self.assertEqual(out["scored"], 3)          # opening baseline, candidate, closing
        self.assertEqual(out["audited"], 3)         # session 1 audits every candidate
        self.assertEqual(out["chain_length"], 4)    # + the closing unsigned control

    def test_the_c_code_sends_an_identity_the_validator_accepts(self):
        log = self._session([])
        ident = records.validate(log["app_identity"])
        self.assertEqual(ident["token"], TOKEN)
        self.assertEqual(ident["control_plane"], "standalone")
        self.assertEqual(ident["pss_idcode"], "0x03722093")

    def test_records_carry_seq_verified_and_nested_evidence(self):
        """The three fields the old flat payload omitted."""
        log = self._session([])
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
        log = self._session([])
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
            f"status_after=0x900 fault_after=0 key_loaded=1 "
            f"ctrl_before=0x0 ctrl_after=0x0 writes_issued=25")
        return n.decode_payload(n.parse_line(line)["payload"])

    def test_a_stop_arm_record_from_the_c_code_validates(self):
        rec = self._stop_arm_record(f"{SEED:016x}")        # unchanged nonce
        records.validate(rec)
        arm = rec["evidence"]["arm"]
        self.assertEqual(arm["nonce_after"], arm["nonce_before"])
        # the observations session 1 threw away are all present
        for k in ("status_after", "fault_after", "ctrl_before", "ctrl_after",
                  "writes_issued", "key_loaded_observed"):
            self.assertIn(k, arm)
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
        term_line, = self.twin(
            f"term token={TOKEN} kind=STOPPED reason=nonce-did-not-step last_seq=1 "
            f"scored=0 refused_by_gate=0 closing_restore=1 audited=1 total=1 "
            f"crc_dropped=0 drop_budget=16")
        collector.on_line(term_line)
        log = {"control_plane": "standalone", "app_identity": collector.app_identity,
               "loop_records": [rec], "session_summary": collector.session_summary,
               "notary_log": relay.notary_log()}
        out = records.validate_standalone_run_log(log, self.blank_commit, SEED)
        self.assertEqual(out["chain_length"], 0, "a non-consumed ARM must not count")
        self.assertEqual(out["scored"], 0)
        self.assertEqual(out["audited"], 1, "the candidate staged, so it is still audited")
        records.check_audit_policy(log)      # STOP_ARM self-reports, so it must be audited

    # -- the audit policy the preregistration can actually require ---------------------

    def test_the_audit_policy_holds_for_a_session_of_c_emitted_records(self):
        log = self._session([gn.corpus_genome(2, self.manifest)])
        out = records.check_audit_policy(log)
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
        self.assertEqual(records.check_audit_policy(log)["exempt_no_self_report"], [2])

    def test_an_unaudited_self_report_is_refused(self):
        """Discrimination: the policy must reject exactly what it exists to catch."""
        log = {"loop_records": [
            {"seq": 1, "outcome": "SCORED", "verified": "replayed-only",
             "evidence": {"app_oracle_record": {}}}]}
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log)

    def test_a_link2_refusal_must_be_audited_because_it_staged(self):
        """STOP_LINK2 asserts `staged != commit`; the host cannot check that claim without
        the staged words, so it is NOT exempt."""
        log = {"loop_records": [
            {"seq": 1, "outcome": "STOP_LINK2", "verified": "replayed-only",
             "evidence": {"sign_reply": {}}}]}
        with self.assertRaises(records.RecordError):
            records.check_audit_policy(log)

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


if __name__ == "__main__":
    unittest.main()
