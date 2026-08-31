"""The signer's genome operation (D1 §4.3): derive + own gate + tables + tag.

In-process against a fixture key, plus one real subprocess invocation of
`host/sign_arm.py` (no sudo — the fixture key is this user's; the D4 principal boundary
is exercised by its own tests and on the board)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import signer as sg  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402
import sign_arm  # noqa: E402

NONCE = "9e3779b97f4a7c15"


def private_key(tmp: Path, k: bytes = bytes(range(16))) -> Path:
    p = tmp / "K.bin"
    p.write_bytes(k)
    os.chmod(p, 0o600)
    return p


class SignGenome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.holder = sg.KeyHolder(private_key(Path(cls.tmp.name)))
        cls.manifest = g.load_manifest()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_known_answer_genome_signs_to_the_gate_hash_and_tables(self):
        ka_hex = gn.to_hex(gn.known_answer_genome(self.manifest))
        out = sign_arm.sign_genome(self.holder, ka_hex, NONCE)
        frames = g.known_answer_candidate(self.manifest)
        verdict = g.gate(g.build_streams(frames, self.manifest), self.manifest)
        self.assertEqual(out["commit"], verdict["candidate_sha256"])
        self.assertEqual(out["sequence_sha256"], verdict["sequence_sha256"])
        tables = po.expected_tables(frames, po.load_constants())
        self.assertEqual(out["expected_tables"], [f"{t:016x}" for t in tables])
        nonce_bytes = int(NONCE, 16).to_bytes(8, "little")   # records: int hex; MAC: LE bytes
        payload = sg.ArmPayload(bytes.fromhex(out["commit"]), tuple(tables),
                                nonce_bytes, bytes.fromhex(out["tag"]))
        self.assertTrue(sg.verify_arm(self.holder, payload, nonce_bytes))
        self.assertEqual(payload.words(), out["words"])

    def test_blank_genome_signs(self):
        out = sign_arm.sign_genome(self.holder, gn.to_hex(gn.blank_genome(self.manifest)), NONCE)
        self.assertIn("tag", out)

    def test_malformed_genome_is_an_error_not_a_refusal(self):
        with self.assertRaises(ValueError):
            sign_arm.sign_genome(self.holder, "zz" * 40, NONCE)
        with self.assertRaises(ValueError):
            sign_arm.sign_genome(self.holder, "00" * 39, NONCE)

    def test_unwritable_genome_returns_refusal_data_without_signing(self):
        bad = {"schema": "gate_verdict", "schema_version": "1.0.0", "candidate_sha256": "00" * 32,
               "sequence_sha256": "11" * 32, "writable": False,
               "findings": [{"kind": "whitelist"}, {"kind": "ecc"}],
               "gate_tool": {}, "manifest_sha256": "22" * 32}
        with mock.patch.object(g, "gate", return_value=bad):
            out = sign_arm.sign_genome(self.holder, gn.to_hex(0), NONCE)
        self.assertEqual(out, {"refused": {"finding_kinds": ["ecc", "whitelist"]}})

    def test_subprocess_cli_signs_the_known_answer(self):
        key = private_key(Path(self.tmp.name))
        req = {"op": "sign_genome",
               "genome": gn.to_hex(gn.known_answer_genome(self.manifest)), "nonce": NONCE}
        p = subprocess.run([sys.executable, str(R / "host/sign_arm.py"), str(key)],
                           input=json.dumps(req), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["key_id"], self.holder.key_id)
        self.assertEqual(len(out["words"]), 24)


if __name__ == "__main__":
    unittest.main()
