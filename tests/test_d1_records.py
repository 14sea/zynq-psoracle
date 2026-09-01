"""The standalone-plane record validators and rules (vii)–(ix) (D1 spec §7, contracts.md).

A happy COMPLETED session is built programmatically (blank baseline → one scored candidate
→ one gate refusal → closing baseline → closing unsigned control, nonce chain from the
seed), then each rule is violated one at a time and must be rejected with a message naming
it. Every negative asserts on the rule tag, not just on "it raised".
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from validators import nonce as nc  # noqa: E402
from validators import records  # noqa: E402

SEED = 0x9E3779B97F4A7C15
TOKEN = "ab" * 16
BLANK = "0b" * 32
CAND = "0c" * 32
G_BLANK = "00" * 40
G_CAND = "11" * 40
TABLES = [f"{i:016x}" for i in (5, 6, 7, 8, 9, 10)]


def reply(seq, commit):
    return {"schema": "sign_reply", "schema_version": "1.0.0", "seq": seq, "commit": commit,
            "expected_tables": list(TABLES), "tag": "cd" * 16}


def request(seq, genome, nonce):
    return {"schema": "sign_request", "schema_version": "1.0.0", "token": TOKEN,
            "app_epoch": 0, "seq": seq, "genome": genome, "nonce": nonce}


def oracle(seq, commit, readback=None):
    return {"schema": "app_oracle_record", "schema_version": "1.0.0", "seq": seq,
            "staged_sha256": commit, "staged_stream_sha256": "5e" * 32,
            "readback_sha256": readback or commit, "write": {"envelopes": 3},
            "audit_available": True}


def scored(seq, genome, commit, nonce, verified="replayed-only"):
    return {"schema": "loop_record", "schema_version": "1.0.0", "seq": seq, "genome": genome,
            "outcome": "SCORED", "verified": verified,
            "evidence": {"sign_reply": reply(seq, commit), "app_oracle_record": oracle(seq, commit),
                         "arm": {"nonce_before": f"{nonce:016x}", "nonce_after": f"{nc.step(nonce):016x}",
                                 "status_after": "0x00000f54", "fault_after": 0, "key_loaded_observed": True,
                                 "settle": {"polls": 2, "polls_max": 10000, "settled": True,
                                            "status_first": "0x00000901", "status_last": "0x00000f54"}},
                         "score": {"hw_candidate_commit": commit,
                                   "functional_readout": list(TABLES), "scores": [1] * 6,
                                   "heartbeat": {"before": 1, "after": 2}}}}


def refused(seq, genome):
    return {"schema": "loop_record", "schema_version": "1.0.0", "seq": seq, "genome": genome,
            "outcome": "REFUSED_BY_GATE", "verified": "replayed-only",
            "evidence": {"sign_refusal": {"schema": "sign_refusal", "schema_version": "1.0.0",
                                          "seq": seq, "finding_kinds": ["whitelist"]}}}


def make_log():
    n0 = SEED
    n1 = nc.step(n0)
    n2 = nc.step(n1)
    recs = [scored(1, G_BLANK, BLANK, n0), scored(2, G_CAND, CAND, n1),
            refused(3, G_CAND), scored(4, G_BLANK, BLANK, n2)]
    entries = []
    for r in recs:
        seq = r["seq"]
        if r["outcome"] == "REFUSED_BY_GATE":
            ans = r["evidence"]["sign_refusal"]
            non = f"{0:016x}"
        else:
            ans = r["evidence"]["sign_reply"]
            non = r["evidence"]["arm"]["nonce_before"]
        entries.append({"seq": seq, "at": seq * 1.0, "request": request(seq, r["genome"], non),
                        "answer": copy.deepcopy(ans)})   # the notary's copy is independent evidence
    n3 = nc.step(n2)
    return {
        "app_identity": {"schema": "app_identity", "schema_version": "1.0.0",
                         "control_plane": "standalone", "pss_idcode": "0x03722093",
                         "token": TOKEN, "uboot_epoch": 0, "carrier_sha256": "9a" * 32,
                         "nonce_at_start": f"{SEED:016x}", "status_at_start": "0x00000900",
                         "fclk0_hz_decoded": 50000000, "app_epoch": 0, "findings": []},
        "notary_log": {"schema": "notary_log", "schema_version": "1.0.0", "token": TOKEN,
                       "entries": entries},
        "loop_records": recs,
        "closing_negative": {"nonce_before": f"{n3:016x}", "nonce_after": f"{nc.step(n3):016x}",
                             "fault": 13, "status": "0x00000982"},
        "session_summary": {"schema": "session_summary", "schema_version": "1.0.0",
                            "token": TOKEN,
                            "epoch_end": {"kind": "COMPLETED", "reason": "budget", "last_seq": 4},
                            "counts": {"scored": 3, "refused_by_gate": 1},
                            "closing": {"restore": "done", "baseline": "done", "unsigned_control": "done"},
                            "audit": {"audited": 0, "total": 4},
                            "crc_dropped": 0, "drop_budget": 8, "written_by": "app"}}


class HappyPath(unittest.TestCase):
    def test_completed_session_validates(self):
        out = records.validate_standalone_run_log(make_log(), BLANK, SEED)
        self.assertEqual(out, {"scored": 3, "audited": 0, "chain_length": 4})

    def test_stopped_session_without_closing_arm_validates(self):
        log = make_log()
        log["loop_records"] = log["loop_records"][:2]
        log["notary_log"]["entries"] = log["notary_log"]["entries"][:2]
        del log["closing_negative"]
        s = log["session_summary"]
        s["epoch_end"] = {"kind": "STOPPED", "reason": "LINK3_MISMATCH", "last_seq": 2}
        s["closing"] = {"restore": "done", "baseline": "not_reached", "unsigned_control": "not_reached"}
        s["audit"] = {"audited": 0, "total": 2}
        out = records.validate_standalone_run_log(log, BLANK, SEED)
        self.assertEqual(out["chain_length"], 2)


class RuleNegatives(unittest.TestCase):
    def check(self, mutate, fragment):
        log = make_log()
        mutate(log)
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(log, BLANK, SEED)
        self.assertIn(fragment, str(cm.exception))

    def test_vii_missing_notary_entry(self):
        self.check(lambda l: l["notary_log"]["entries"].pop(1), "(vii)")

    def test_vii_commit_mismatch_with_notary(self):
        def m(l):
            l["notary_log"]["entries"][1]["answer"]["commit"] = "ee" * 32
        self.check(m, "(vii)")

    def test_vii_signed_nonce_is_not_the_consumed_nonce(self):
        def m(l):
            l["notary_log"]["entries"][1]["request"]["nonce"] = f"{0xdead:016x}"
        self.check(m, "(vii)")

    def test_vii_nonce_chain_break(self):
        def m(l):
            l["loop_records"][1]["evidence"]["arm"]["nonce_before"] = f"{0xbeef:016x}"
        self.check(m, "nonce")

    def test_viii_completed_without_closing_control(self):
        self.check(lambda l: l.pop("closing_negative"), "(viii)")

    def test_viii_closing_control_wrong_fault(self):
        def m(l):
            l["closing_negative"]["fault"] = 12
        self.check(m, "(viii)")

    def test_viii_last_scored_is_not_the_baseline(self):
        def m(l):
            l["loop_records"][3] = scored(4, G_CAND, CAND, nc.step(nc.step(SEED)))
            l["notary_log"]["entries"][3]["answer"] = l["loop_records"][3]["evidence"]["sign_reply"]
            l["notary_log"]["entries"][3]["request"]["nonce"] = l["loop_records"][3]["evidence"]["arm"]["nonce_before"]
        self.check(m, "(viii)")

    def test_viii_stop_with_closing_arm_is_refused(self):
        def m(l):
            l["session_summary"]["epoch_end"]["kind"] = "STOPPED"
            l["session_summary"]["closing"]["baseline"] = "not_reached"
            l["session_summary"]["closing"]["unsigned_control"] = "not_reached"
        self.check(m, "(viii)")   # closing_negative still present under a stop

    def test_ix_audit_count_disagrees(self):
        def m(l):
            l["session_summary"]["audit"]["audited"] = 2
        self.check(m, "(ix)")

    def test_token_must_agree_across_records(self):
        def m(l):
            l["session_summary"]["token"] = "cd" * 16
        self.check(m, "token")


class RecordNegatives(unittest.TestCase):
    def test_scored_readout_must_equal_signed_tables(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["evidence"]["score"]["functional_readout"] = ["0" * 16] * 6
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("(iii)", str(cm.exception))

    def test_scored_commit_chain(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["evidence"]["score"]["hw_candidate_commit"] = "ee" * 32
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("(ii)", str(cm.exception))

    def test_scored_without_key_loaded_is_refused(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["evidence"]["arm"]["key_loaded_observed"] = False
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("(v)", str(cm.exception))

    def test_nonce_must_step_by_the_model(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["evidence"]["arm"]["nonce_after"] = r["evidence"]["arm"]["nonce_before"]
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("step", str(cm.exception))

    def test_stop_link3_with_matching_readback_is_a_contradiction(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["outcome"] = "STOP_LINK3"
        del r["evidence"]["arm"]; del r["evidence"]["score"]
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("contradiction", str(cm.exception))

    def test_refused_by_gate_must_not_carry_a_score(self):
        r = refused(3, G_CAND)
        r["evidence"]["score"] = {"scores": [1] * 6}
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("must not contain", str(cm.exception))

    def test_link2_binding_staged_must_equal_commit(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["evidence"]["app_oracle_record"]["staged_sha256"] = "ee" * 32
        r["evidence"]["app_oracle_record"]["readback_sha256"] = "ee" * 32
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("link 2", str(cm.exception))

    def test_verified_mark_is_mandatory(self):
        r = scored(1, G_BLANK, BLANK, SEED)
        r["verified"] = "trusted"
        with self.assertRaises(records.RecordError) as cm:
            records.validate(r)
        self.assertIn("(rule ix)", str(cm.exception))

    def test_session_summary_completed_needs_all_closing_steps(self):
        s = make_log()["session_summary"]
        s["closing"]["restore"] = "not_reached"
        with self.assertRaises(records.RecordError) as cm:
            records.validate(s)
        self.assertIn("(viii)", str(cm.exception))

    def test_session_summary_crashed_is_collector_written(self):
        s = make_log()["session_summary"]
        s["epoch_end"]["kind"] = "CRASHED"
        s["closing"] = {k: "not_reached" for k in records.CLOSING_STEPS}
        with self.assertRaises(records.RecordError) as cm:
            records.validate(s)
        self.assertIn("collector", str(cm.exception))

    def test_drop_budget_exceeded_must_be_protocol(self):
        s = make_log()["session_summary"]
        s["crc_dropped"] = 99
        with self.assertRaises(records.RecordError) as cm:
            records.validate(s)
        self.assertIn("drop budget", str(cm.exception))

    def test_truncated_token_is_rejected(self):
        i = make_log()["app_identity"]
        i["token"] = "ab" * 4
        with self.assertRaises(records.RecordError) as cm:
            records.validate(i)
        self.assertIn("128-bit", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
