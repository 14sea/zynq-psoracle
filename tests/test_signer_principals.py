"""`arm_mac` signer and the principal model (`p3_architecture` §3c), with fixtures only.

Two principals are modelled by two key paths: one private (mode 0400, readable by this
test process — standing in for gate-signer) and one the runner side never receives.
No real OS users are created (owner's limit). The properties checked are the ones the
architecture relies on: only a KeyHolder can sign; the runner API has no way to obtain or
rebuild K; a tag from another key, a replayed nonce, a changed commit or a changed table
all fail verification; a world-readable key file is refused.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from validators import signer as sg  # noqa: E402

COMMIT = bytes(range(32))
TABLES = (0x517A5CEA46B05DE4, 1, 2, 3, 4, 5)
NONCE = bytes.fromhex("0123456789abcdef")


def private_key(tmp: Path, k: bytes = bytes(range(16, 32))) -> Path:
    p = tmp / "K"; p.write_bytes(k); os.chmod(p, 0o400); return p


class Principals(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.holder = sg.KeyHolder(private_key(self.tmp))
        self.verdict = {"writable": True, "candidate_sha256": COMMIT.hex()}

    def test_gate_signs_and_pl_model_verifies(self):
        p = sg.sign_arm(self.holder, self.verdict, COMMIT, TABLES, NONCE)
        self.assertTrue(sg.verify_arm(self.holder, p, NONCE))
        self.assertEqual(len(p.words()), 24)

    def test_only_a_keyholder_can_sign(self):
        with self.assertRaises(sg.SignerRefusal):
            sg.sign_arm("not a holder", self.verdict, COMMIT, TABLES, NONCE)
        with self.assertRaises(sg.SignerRefusal):
            sg.sign_arm(None, self.verdict, COMMIT, TABLES, NONCE)

    def test_runner_api_exposes_no_key(self):
        """The runner side gets ArmPayload; nothing on it or in the module returns K."""
        p = sg.sign_arm(self.holder, self.verdict, COMMIT, TABLES, NONCE)
        self.assertFalse(hasattr(p, "key"))
        self.assertNotIn("_k", dir(p))
        self.assertEqual(sg.KeyHolder.__slots__, ("_k", "key_id"))
        self.assertNotIn(self.holder._k.hex(), repr(self.holder))
        self.assertNotIn(self.holder._k.hex(), self.holder.key_id)

    def test_unwritable_verdict_is_never_signed(self):
        with self.assertRaises(sg.SignerRefusal):
            sg.sign_arm(self.holder, {"writable": False, "candidate_sha256": COMMIT.hex()}, COMMIT, TABLES, NONCE)

    def test_commit_must_be_the_verdicts_hash_and_full_length(self):
        with self.assertRaises(sg.SignerRefusal):
            sg.sign_arm(self.holder, self.verdict, bytes(32), TABLES, NONCE)     # a different candidate
        with self.assertRaises(sg.SignerRefusal):
            sg.arm_message(COMMIT[:8], TABLES, NONCE)                           # truncated commitment

    def test_negatives_the_pl_must_refuse(self):
        p = sg.sign_arm(self.holder, self.verdict, COMMIT, TABLES, NONCE)
        other = sg.KeyHolder(private_key(self.tmp / "o" if (self.tmp / "o").mkdir() is None else self.tmp, bytes(16)))
        self.assertFalse(sg.verify_arm(other, p, NONCE), "tag from another key")
        self.assertFalse(sg.verify_arm(self.holder, p, bytes(8)), "replayed nonce")
        wrong_commit = sg.ArmPayload(bytes(32), p.expected_tables, p.nonce, p.tag)
        self.assertFalse(sg.verify_arm(self.holder, wrong_commit, NONCE), "changed commit")
        wrong_table = sg.ArmPayload(p.candidate_commit, (0,) + p.expected_tables[1:], p.nonce, p.tag)
        self.assertFalse(sg.verify_arm(self.holder, wrong_table, NONCE), "changed table")
        unsigned = sg.ArmPayload(p.candidate_commit, p.expected_tables, p.nonce, bytes(16))
        self.assertFalse(sg.verify_arm(self.holder, unsigned, NONCE), "unsigned")

    def test_world_readable_or_absent_key_is_refused(self):
        p = self.tmp / "loose"; p.write_bytes(bytes(16)); os.chmod(p, 0o644)
        with self.assertRaises(sg.SignerRefusal):
            sg.KeyHolder(p)
        with self.assertRaises(sg.SignerRefusal):
            sg.KeyHolder(self.tmp / "missing")
        short = self.tmp / "short"; short.write_bytes(b"1234"); os.chmod(short, 0o400)
        with self.assertRaises(sg.SignerRefusal):
            sg.KeyHolder(short)


if __name__ == "__main__":
    unittest.main()
