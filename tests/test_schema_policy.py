"""`docs/contracts.md` policy: reject foreign MAJOR; accept additive MINOR, ignore unknown fields."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validators.records import RecordError, validate  # noqa: E402
from validators.schema import SchemaError, check_envelope  # noqa: E402

GOOD = {"schema": "gate_verdict", "schema_version": "1.0.0", "candidate_sha256": "ab" * 32,
        "writable": True, "findings": [], "gate_tool": {"name": "gate_candidate.py"},
        "manifest_sha256": "cd" * 32}


class Policy(unittest.TestCase):
    def test_same_major_accepted(self):
        self.assertTrue(validate(dict(GOOD))["writable"])

    def test_foreign_major_rejected(self):
        with self.assertRaises(RecordError) as cm:
            validate({**GOOD, "schema_version": "2.0.0"})
        self.assertIn("MAJOR", str(cm.exception))

    def test_additive_minor_accepted_and_unknown_field_ignored(self):
        known = validate({**GOOD, "schema_version": "1.3.0", "new_optional": 42})
        self.assertNotIn("new_optional", known)

    def test_lower_minor_accepted(self):
        validate({**GOOD, "schema_version": "1.0.0"})
        known = check_envelope({**GOOD, "schema_version": "1.0.0"}, "gate_verdict", "1.2.0",
                               ("candidate_sha256", "writable", "findings", "gate_tool", "manifest_sha256"))
        self.assertIn("writable", known)

    def test_missing_required_field_rejected(self):
        bad = dict(GOOD); del bad["findings"]
        with self.assertRaises(RecordError):
            validate(bad)

    def test_wrong_schema_name_rejected(self):
        with self.assertRaises(RecordError):
            validate({**GOOD, "schema": "score_record"})

    def test_bad_version_string_rejected(self):
        with self.assertRaises(SchemaError):
            check_envelope({**GOOD, "schema_version": "1.0"}, "gate_verdict", "1.0.0", ())

    def test_writable_with_findings_is_a_contradiction(self):
        with self.assertRaises(RecordError):
            validate({**GOOD, "findings": [{"kind": "whitelist"}]})

    def test_findings_are_bucketed_by_kind(self):
        with self.assertRaises(RecordError):
            validate({**GOOD, "writable": False, "findings": [{"message": "pair missing"}]})


if __name__ == "__main__":
    unittest.main()
