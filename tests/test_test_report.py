"""host/test_report.py is fail-closed: a report that cannot be written, registered or staged is
a non-zero exit, never a success."""
import json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "host"))
import test_report as tr  # noqa: E402

LOG = "....\nRan 4 tests in 0.010s\n\nOK (skipped=1)\n"


def temp_repo(d: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.name", "t"], check=True)
    (d / "docs").mkdir(); (d / "docs/import_manifest.md").write_text("| `host/run_tests.sh` |\n")
    (d / "host").mkdir(); (d / "host/sign_arm.py").write_text("")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "init"], check=True)
    return d


class FailClosed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.repo = temp_repo(Path(self.tmp.name))
        self.rep = {"at": "2026-01-01T000000Z", "exit_status": 0}

    def tearDown(self):
        for p in Path(self.tmp.name).rglob("*"):
            if p.is_dir(): os.chmod(p, 0o755)
        self.tmp.cleanup()

    def test_success_path_writes_registers_and_stages(self):
        path = tr.write_and_register(self.repo, Path("evidence/tests"), self.rep)
        self.assertTrue(path.exists())
        self.assertIn("`evidence/tests/test_report_2026-01-01T000000Z.json`", (self.repo / "docs/import_manifest.md").read_text())
        staged = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout
        self.assertIn("evidence/tests/test_report_2026-01-01T000000Z.json", staged); self.assertIn("docs/import_manifest.md", staged)

    def test_read_only_output_dir_is_a_failure(self):
        out = self.repo / "evidence/tests"; out.mkdir(parents=True); os.chmod(out, stat.S_IRUSR | stat.S_IXUSR)
        if os.access(out, os.W_OK): self.skipTest("running as a user that ignores directory modes (root)")
        with self.assertRaises(tr.ReportError) as cm: tr.write_and_register(self.repo, Path("evidence/tests"), self.rep)
        self.assertIn("report not written", str(cm.exception))

    def test_unwritable_manifest_is_a_failure_and_no_success_is_claimed(self):
        os.chmod(self.repo / "docs", stat.S_IRUSR | stat.S_IXUSR)
        if os.access(self.repo / "docs", os.W_OK): self.skipTest("root")
        with self.assertRaises(tr.ReportError) as cm: tr.write_and_register(self.repo, Path("evidence/tests"), self.rep)
        self.assertIn("manifest not updated", str(cm.exception))

    def test_not_a_git_repo_is_a_failure(self):
        with tempfile.TemporaryDirectory() as plain:      # NOT inside the temp git repo
            d = Path(plain); (d / "docs").mkdir(); (d / "docs/import_manifest.md").write_text("| `host/run_tests.sh` |\n")
            with self.assertRaises(tr.ReportError) as cm: tr.write_and_register(d, Path("evidence/tests"), self.rep)
            self.assertIn("git add failed", str(cm.exception))

    def test_cli_exit_3_on_failure_and_suite_status_preserved_on_success(self):
        log = Path(self.tmp.name) / "log.txt"; log.write_text(LOG)
        p = subprocess.run([sys.executable, str(REPO / "host/test_report.py"), "--exit-status", "1", "--log", str(log), "--repo", str(self.repo)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr); rep = json.loads(p.stdout.split("\nreport:")[0])
        self.assertEqual(rep["exit_status"], 1); self.assertEqual(rep["skipped"], 1); self.assertEqual(rep["ran"], 4)
        os.chmod(self.repo / "evidence/tests", stat.S_IRUSR | stat.S_IXUSR)
        if os.access(self.repo / "evidence/tests", os.W_OK): self.skipTest("root")
        p = subprocess.run([sys.executable, str(REPO / "host/test_report.py"), "--exit-status", "0", "--log", str(log), "--repo", str(self.repo)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 3); self.assertIn("fail-closed", p.stderr)

    def test_run_tests_sh_is_fail_closed_by_construction(self):
        s = (REPO / "host/run_tests.sh").read_text()
        self.assertIn('if [ "$rrc" -ne 0 ]; then', s); self.assertIn("exit 3", s); self.assertIn('exit "$trc"', s)


if __name__ == "__main__":
    unittest.main()
