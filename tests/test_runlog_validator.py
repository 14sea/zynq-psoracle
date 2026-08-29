"""run_log rules (i)–(v): the five negatives, each tested one at a time, plus the positive."""

import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from validators.records import RecordError, canonical_sha256, validate_run_log  # noqa: E402

C = "aa" * 32
TABLES = [f"{0x517A5CEA46B05DE4:016x}", "0" * 16, "1" * 16, "2" * 16, "3" * 16, "4" * 16]


def chain(epoch=0):
    gate = {"schema": "gate_verdict", "schema_version": "1.0.0", "candidate_sha256": C, "writable": True,
            "findings": [], "gate_tool": {"name": "gate_candidate.py"}, "manifest_sha256": "bb" * 32, "epoch": epoch}
    oracle = {"schema": "oracle_record", "schema_version": "1.0.0",
              "session": {"boardid": "17A6", "epoch": epoch, "plmark": "x"},
              "candidate_sha256": C, "staged_sha256": C, "staged_stream_sha256": "cc" * 32,
              "write": {"dma": [0x10400001, 0xFFFFFFFF, 231, 0], "error_bits": []},
              "readback_sha256": C, "configuration_valid_hw_expected": True}
    arm = {"schema": "arm_record", "schema_version": "1.0.0",
           "oracle_record_sha256": canonical_sha256(oracle), "gate_verdict_sha256": canonical_sha256(gate),
           "epoch": epoch, "nonce": "0123456789abcdef", "candidate_commit": C, "expected_tables": TABLES,
           "tag": "dd" * 16, "signer": {"principal": "gate-signer"}, "axi_before": {"status": "0x80", "fault": "0x0"}}
    score = {"schema": "score_record", "schema_version": "1.0.0", "arm_record_sha256": canonical_sha256(arm),
             "configuration_valid_hw": True, "hw_candidate_commit": C, "functional_readout": TABLES,
             "scores": [1, 2, 3, 4, 5, 6], "host_prediction": [1, 2, 3, 4, 5, 6]}
    return {"schema": "run_log", "schema_version": "1.0.0", "ruling_sha256": "ee" * 32,
            "records": [gate, oracle, arm, score], "epoch_final": epoch}


def relink(log):
    """After mutating a record, re-point the hashes so only the intended rule breaks."""
    gate, oracle, arm, score = log["records"]
    arm["oracle_record_sha256"] = canonical_sha256(oracle)
    arm["gate_verdict_sha256"] = canonical_sha256(gate)
    score["arm_record_sha256"] = canonical_sha256(arm)
    return log


class RunLog(unittest.TestCase):
    def test_positive_chain_validates(self):
        v = validate_run_log(chain())
        self.assertEqual(len(v), 1)

    def _expect(self, log, rule):
        with self.assertRaises(RecordError) as cm:
            validate_run_log(relink(log))
        self.assertTrue(str(cm.exception).startswith(rule), str(cm.exception))

    def test_i_epoch_mismatch(self):
        log = chain(); log["records"][2]["epoch"] = 1
        self._expect(log, "(i)")

    def test_ii_commit_mismatch(self):
        log = chain(); log["records"][3]["hw_candidate_commit"] = "ff" * 32
        self._expect(log, "(ii)")

    def test_iii_readout_mismatch(self):
        log = chain(); log["records"][3]["functional_readout"] = ["9" * 16] + TABLES[1:]
        self._expect(log, "(iii)")

    def test_iv_oracle_hash_mismatch(self):
        log = chain(); log["records"][1]["readback_sha256"] = "ff" * 32
        self._expect(log, "(iv)")
        log = chain(); log["records"][1]["staged_sha256"] = "ff" * 32
        self._expect(log, "(iv)")

    def test_v_hw_latch_false(self):
        log = chain(); log["records"][3]["configuration_valid_hw"] = False
        self._expect(log, "(v)")

    def test_dangling_reference_is_rejected(self):
        log = chain(); log["records"][3]["arm_record_sha256"] = "00" * 32
        with self.assertRaises(RecordError) as cm:
            validate_run_log(log)
        self.assertIn("(chain)", str(cm.exception))

    def test_oracle_domains_must_differ(self):
        log = chain(); log["records"][1]["staged_stream_sha256"] = C
        with self.assertRaises(RecordError):
            validate_run_log(relink(log))

    def test_arm_must_be_signed_by_the_gate_signer_principal(self):
        log = chain(); log["records"][2]["signer"] = {"principal": "runner"}
        with self.assertRaises(RecordError):
            validate_run_log(relink(log))


if __name__ == "__main__":
    unittest.main()
