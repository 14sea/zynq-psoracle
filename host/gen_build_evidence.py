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
EVID = os.path.join(REPO, "evidence", "l5_build")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", REPO, *args], text=True).strip()


def newest_test_report():
    d = os.path.join(REPO, "evidence", "tests")
    reps = [f for f in os.listdir(d) if f.startswith("test_report_")] if os.path.isdir(d) else []
    return "evidence/tests/" + max(reps) if reps else None


def main():
    binp = os.path.join(OUT, "p3_app.bin")
    elfp = os.path.join(OUT, "p3_app.elf")
    mapp = os.path.join(OUT, "p3_app.map")
    for p in (binp, elfp, mapp):
        if not os.path.isfile(p):
            sys.exit("missing %s -- run firmware/bsp/build.sh first" % p)

    os.makedirs(EVID, exist_ok=True)
    shutil.copyfile(mapp, os.path.join(EVID, "p3_app.map"))

    lm = json.loads(open(os.path.join(REPO, "manifests", "l5_manifest.json")).read())
    pab = lm["pinned_at_build"]

    dirty = bool(git("status", "--porcelain"))
    rep = newest_test_report()
    ev = {
        "schema": "l5_build_evidence",
        "schema_version": "1.0.0",
        "purpose": "Post-build provenance for the pinned P3 L5 application image, "
                   "regenerated after a clean rebuild (reviewer 2026-08-31).",
        "git": {"head": git("rev-parse", "HEAD"), "worktree_dirty": dirty},
        "toolchain": pab["toolchain"],
        "bsp_inputs": {
            "manifest": "manifests/l5_bsp_inputs.json",
            "manifest_sha256": sha(os.path.join(REPO, "manifests", "l5_bsp_inputs.json")),
            "count": json.loads(open(os.path.join(REPO, "manifests", "l5_bsp_inputs.json")).read())["count"],
        },
        "image": {
            "bin": "firmware/bsp/out/p3_app.bin",
            "bin_bytes": os.path.getsize(binp),
            "bin_sha256": sha(binp),
            "elf_sha256": sha(elfp),
            "reproduced_byte_identical": sha(binp) == pab["app_image_sha256"],
            "expected_bin_sha256": pab["app_image_sha256"],
        },
        "linker_map": {
            "path": "evidence/l5_build/p3_app.map",
            "sha256": sha(mapp),
        },
        "tests": {
            "report": rep,
            "note": "the fail-closed test evidence (count / skipped / boundary / "
                    "head_at_run) is this report; run host/run_tests.sh in a staged "
                    "state so it covers the new files.",
        },
    }
    with open(os.path.join(EVID, "build_evidence.json"), "w") as f:
        json.dump(ev, f, indent=2)
        f.write("\n")
    print("image reproduced byte-identical:", ev["image"]["reproduced_byte_identical"])
    print("wrote evidence/l5_build/build_evidence.json + p3_app.map")


if __name__ == "__main__":
    main()
