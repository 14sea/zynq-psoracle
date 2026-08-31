#!/usr/bin/env python3
"""Write the test-run evidence report FAIL-CLOSED (reviewer 2026-08-31).

    test_report.py --exit-status N --log <unittest output> [--repo DIR] [--out-dir evidence/tests]

Succeeds (exit 0) only if ALL of: the report was written atomically, it was registered in
docs/import_manifest.md, and `git add` staged both. Any failure → a message on stderr and
exit 3; nothing is reported as success that did not land. The `head_at_run` field is the
HEAD when the suite ran — a report can never contain the commit that will include it, so
`worktree_dirty` says whether the tree differed from that HEAD.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


class ReportError(Exception):
    pass


def sudo_probe(repo: Path) -> tuple[str, bool]:
    try:
        p = subprocess.run(["sudo", "-n", "-u", "p3signer", sys.executable, str(repo / "host/sign_arm.py"),
                            "/var/lib/p3signer/keys/K.bin"], input='{"op": "probe"}', capture_output=True, text=True, timeout=60)
        out = (p.stdout if p.returncode == 0 else p.stderr).strip()[:300]
        return out, p.returncode == 0 and out.startswith("{")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"probe error: {exc}", False


def build(repo: Path, exit_status: int, log_text: str) -> dict:
    ran = re.search(r"^Ran (\d+)", log_text, re.M)
    result = [l for l in log_text.splitlines() if l.startswith(("OK", "FAILED"))]
    skipped = re.search(r"skipped=(\d+)", log_text)
    failures = re.search(r"failures=(\d+)", log_text); errors = re.search(r"errors=(\d+)", log_text)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
    probe, available = sudo_probe(repo)
    return {"schema": "test_report", "schema_version": "1.0.0",
            "at": time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime()),
            "exit_status": int(exit_status), "ran": int(ran.group(1)) if ran else None,
            "result_line": result[-1] if result else None,
            "skipped": int(skipped.group(1)) if skipped else 0,
            "failures": int(failures.group(1)) if failures else 0, "errors": int(errors.group(1)) if errors else 0,
            "host": os.uname().nodename, "user": os.environ.get("USER") or str(os.getuid()),
            "head_at_run": head.stdout.strip() if head.returncode == 0 else None,
            "worktree_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
            "note": "head_at_run is the HEAD when the suite ran; the commit that includes this report is necessarily later",
            "sudo_signer_probe": probe, "boundary_available": available,
            "no_new_privs": "no new privileges" in probe}


def write_and_register(repo: Path, out_dir: Path, rep: dict) -> Path:
    out_dir = repo / out_dir
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"test_report_{rep['at']}.json"
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(rep, indent=2) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        raise ReportError(f"report not written: {exc}") from None
    rel = path.relative_to(repo).as_posix()
    manifest = repo / "docs/import_manifest.md"
    try:
        s = manifest.read_text()
        if f"`{rel}`" not in s:
            anchor = "| `host/run_tests.sh` |\n"
            if anchor not in s:
                raise ReportError("import manifest lacks the run_tests.sh anchor row")
            s = s.replace(anchor, anchor + f"| `{rel}` |\n", 1)
            tmp = manifest.with_suffix(".md.part"); tmp.write_text(s); os.replace(tmp, manifest)
    except OSError as exc:
        raise ReportError(f"manifest not updated: {exc}") from None
    g = subprocess.run(["git", "add", "--", str(path), str(manifest)], cwd=repo, capture_output=True, text=True)
    if g.returncode != 0:
        raise ReportError(f"git add failed: {g.stderr.strip()}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit-status", type=int, required=True); ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--out-dir", type=Path, default=Path("evidence/tests"))
    a = ap.parse_args()
    try:
        rep = build(a.repo, a.exit_status, a.log.read_text())
        path = write_and_register(a.repo, a.out_dir, rep)
    except (ReportError, OSError) as exc:
        print(f"TEST REPORT FAILED (fail-closed): {exc}", file=sys.stderr); return 3
    print(json.dumps({k: rep[k] for k in ("at", "exit_status", "ran", "result_line", "skipped", "head_at_run", "worktree_dirty", "boundary_available", "no_new_privs")}, indent=1))
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
