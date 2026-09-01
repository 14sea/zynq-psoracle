#!/usr/bin/env python3
"""Bundle the L5 post-build evidence into evidence/l5_build/.

Reviewer 2026-08-31 asked that build.sh be re-run in a clean/staged state and the
build's provenance be captured in one place: toolchain sha, the embeddedsw BSP
input manifest, the linker map, the image sha, and the test standing. This tool
runs after a fresh `firmware/bsp/build.sh` and writes:

  * evidence/l5_build/p3_app.map        -- a tracked copy of the linker map
  * evidence/l5_build/build_evidence.json -- the hashes + git state, tying together
    the toolchain, the BSP input manifest, the map and the image.

The test standing (count / skipped / boundary) lives in its own fail-closed
artifact under evidence/tests/ (host/run_tests.sh -> host/test_report.py); this
record points at the newest such report rather than duplicating it.

Host-only. Deterministic given the same out/ products.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "firmware", "bsp", "out")
LINES = {"l5": {"image": "p3_app", "manifest": "l5_manifest.json", "bsp": "l5_bsp_inputs.json",
                "evidence": "l5_build", "schema": "l5_build_evidence"},
         "l6": {"image": "p3_app_l6", "manifest": "l6_manifest.json", "bsp": "l6_bsp_inputs.json",
                "evidence": "l6_build", "schema": "l6_build_evidence"},
         "l6next": {"image": "p3_app_l6", "manifest": "l6_manifest.json", "bsp": "l6_bsp_inputs.json",
                    "evidence": "l6_next_build", "schema": "l6_next_build_evidence", "pin_key": "next_image"}}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", REPO, *args], text=True).strip()


def green_test_report(path=None):
    """The test report the evidence cites: the given one, or the newest. REFUSES a report
    that is not green (exit_status != 0, or failures/errors in its result line) — the
    first L6 build evidence cited the newest file, which was an older green run from
    before the sources changed, and would just as readily have cited a red one
    (compatibility review 2026-09-01, blocker 2)."""
    d = os.path.join(REPO, "evidence", "tests")
    if path is None:
        reps = [f for f in os.listdir(d) if f.startswith("test_report_")] if os.path.isdir(d) else []
        if not reps:
            sys.exit("no test report in evidence/tests/")
        path = os.path.join(d, max(reps))
    rep = json.loads(open(path).read())
    line = rep.get("result_line", "")
    if rep.get("exit_status") != 0 or "FAILED" in line or "error" in line.lower():
        sys.exit("refusing to cite a non-green test report %s: exit_status=%r result=%r"
                 % (os.path.relpath(path, REPO), rep.get("exit_status"), line))
    return os.path.relpath(path, REPO), rep


def main(line="l5", report=None):
    L = LINES[line]
    EVID = os.path.join(REPO, "evidence", L["evidence"])
    binp = os.path.join(OUT, L["image"] + ".bin")
    elfp = os.path.join(OUT, L["image"] + ".elf")
    mapp = os.path.join(OUT, L["image"] + ".map")
    for p in (binp, elfp, mapp):
        if not os.path.isfile(p):
            sys.exit("missing %s -- run IMAGE=%s firmware/bsp/build.sh first" % (p, L["image"]))

    os.makedirs(EVID, exist_ok=True)
    shutil.copyfile(mapp, os.path.join(EVID, L["image"] + ".map"))

    lm = json.loads(open(os.path.join(REPO, "manifests", L["manifest"])).read())
    pab = lm[L.get("pin_key", "pinned_at_build")]
    if "toolchain" not in pab:
        pab = dict(pab, toolchain=lm["pinned_at_build"]["toolchain"])

    dirty = bool(git("status", "--porcelain"))
    if report == "pending":
        # the chicken-and-egg step: the suite that will become report A cannot be green
        # while this file still describes the previous image, so the image fields are
        # written first with NO report cited; the next call cites A explicitly
        rep, rep_body = None, {}
    else:
        rep, rep_body = green_test_report(report)
    ev = {
        "schema": L["schema"],
        "schema_version": "1.0.0",
        "purpose": "Post-build provenance for the pinned P3 %s application image, "
                   "regenerated after a clean rebuild (reviewer 2026-08-31)." % line.upper(),
        "git": {"head": git("rev-parse", "HEAD"), "worktree_dirty": dirty},
        "toolchain": pab["toolchain"],
        "bsp_inputs": {
            "manifest": "manifests/" + L["bsp"],
            "manifest_sha256": sha(os.path.join(REPO, "manifests", L["bsp"])),
            "count": json.loads(open(os.path.join(REPO, "manifests", L["bsp"])).read())["count"],
        },
        "image": {
            "bin": "firmware/bsp/out/%s.bin" % L["image"],
            "bin_bytes": os.path.getsize(binp),
            "bin_sha256": sha(binp),
            "elf_sha256": sha(elfp),
            "reproduced_byte_identical": sha(binp) == pab["app_image_sha256"],
            "expected_bin_sha256": pab["app_image_sha256"],
        },
        "linker_map": {
            "path": "evidence/%s/%s.map" % (L["evidence"], L["image"]),
            "sha256": sha(mapp),
        },
        "tests": {
            "report": rep,
            "report_sha256": sha(os.path.join(REPO, rep)) if rep else None,
            "status": "cited and verified green by the generator" if rep else
                      "PENDING: written before the post-build suite ran; must be regenerated with --report",
            "ran": rep_body.get("ran"), "skipped": rep_body.get("skipped"),
            "head_at_run": rep_body.get("head_at_run"), "result_line": rep_body.get("result_line"),
            "note": "the fail-closed test evidence (count / skipped / boundary / "
                    "head_at_run) is this report, cited explicitly and verified green "
                    "by the generator; run host/run_tests.sh in a staged state so it "
                    "covers the new files.",
        },
    }
    with open(os.path.join(EVID, "build_evidence.json"), "w") as f:
        json.dump(ev, f, indent=2)
        f.write("\n")
    print("image reproduced byte-identical:", ev["image"]["reproduced_byte_identical"])
    print("wrote evidence/%s/build_evidence.json + %s.map" % (L["evidence"], L["image"]))


if __name__ == "__main__":
    line = sys.argv[1] if len(sys.argv) > 1 else "l5"
    if line not in LINES:
        sys.exit("usage: gen_build_evidence.py [l5|l6] [--report evidence/tests/test_report_X.json]")
    report = None
    if len(sys.argv) > 3 and sys.argv[2] == "--report":
        report = sys.argv[3] if sys.argv[3] == "pending" else os.path.join(REPO, sys.argv[3])
    main(line, report)
