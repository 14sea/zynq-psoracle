"""Two-way closure: git ls-files == imported ∪ original; every imported row hashes and sizes."""

import hashlib
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/import_manifest.md"
ROW = re.compile(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \| (\d+) \| ([^|]+) \| `([^`]+)` \|$")
ORIG = re.compile(r"^\| `([^`]+)` \|$")


def section(name):
    text = MANIFEST.read_text().splitlines()
    start = next(i for i, l in enumerate(text) if l.startswith(f"## {name}"))
    end = next((i for i, l in enumerate(text[start + 1:], start + 1) if l.startswith("## ")), len(text))
    return text[start:end]


def imported():
    return [(m.group(1), m.group(2), int(m.group(3)), m.group(4).strip(), m.group(5))
            for l in section("Imported files") if (m := ROW.match(l))]


def original():
    return [m.group(1) for l in section("Files original to this repository")
            if (m := ORIG.match(l)) and m.group(1) != "path"]


def tracked():
    out = subprocess.check_output(["git", "-C", str(REPO), "ls-files"], text=True)
    return set(l for l in out.splitlines() if l)


class ImportManifest(unittest.TestCase):
    def test_rows_hash_and_size(self):
        rows = imported()
        self.assertGreaterEqual(len(rows), 25)
        for path, sha, size, origin, src in rows:
            with self.subTest(path=path):
                f = REPO / path
                self.assertTrue(f.is_file(), f"{path} missing")
                b = f.read_bytes()
                self.assertEqual(len(b), size)
                self.assertEqual(hashlib.sha256(b).hexdigest(), sha)
                self.assertIn(origin, ("zynq-psmap", "zynq-fabricmap"))

    def test_two_way_closure_over_git_ls_files(self):
        imp = {p for p, *_ in imported()}
        orig = set(original())
        self.assertEqual(imp & orig, set(), "declared as both imported and original")
        tr = tracked()
        self.assertEqual(tr - (imp | orig), set(), "tracked but undeclared")
        self.assertEqual((imp | orig) - tr, set(), "declared but not tracked")

    def test_frozen_sources_are_pinned_in_full(self):
        text = MANIFEST.read_text()
        for c in ("191ab05", "71666b02"):
            m = re.search(rf"`({c}[0-9a-f]*)`", text)
            self.assertIsNotNone(m, f"source commit starting {c} must be pinned")
            self.assertEqual(len(m.group(1)), 40, f"{c}… must be the full 40-char commit")

    def test_the_removed_authority_and_icap_modules_are_absent(self):
        for name in ("gate_board_identity.py", "board_uboot_axi.py", "board_carrier_guard.py",
                     "board_carrier_exec.py", "carrier_stream.v", "icape2_model.v"):
            hits = [p for p in tracked() if p.endswith(name)]
            self.assertEqual(hits, [], f"{name} must not be imported")

    def test_this_test_is_listed_as_original(self):
        self.assertIn("tests/test_import_manifest.py", original())


if __name__ == "__main__":
    unittest.main()
