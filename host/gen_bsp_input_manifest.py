#!/usr/bin/env python3
"""Generate manifests/l5_bsp_inputs.json: the exact Xilinx embeddedsw files the
standalone build (firmware/bsp/build.sh) compiles into the P3 application image.

The application image hash (pinned_at_build.app_image_sha256) is the product of
three input sets: the pinned xPack toolchain (pinned by tarball sha256), the
repo-tracked firmware/BSP glue (pinned by git), and the third-party Xilinx
embeddedsw sources that build.sh reads out of a local 2025.2 install. Only the
third set was previously unpinned, so the image was reproducible only relative to
"this host's embeddedsw tree". This tool pins that set exactly.

It does NOT guess the file list. For every translation unit build.sh compiles it
asks the pinned compiler for the full preprocessor dependency set (`-M`), takes
the union, keeps the files that live under the embeddedsw root, and records each
one's path (relative to the embeddedsw root), size and sha256. That is the exact,
verified set of embeddedsw inputs -- sources and every header they pull in -- so a
changed BSP header can no longer silently change the image without changing this
manifest.

Host-only. Requires the pinned toolchain in toolchain/ and the 2025.2 embeddedsw
tree; touches no board. Re-running on the same inputs is deterministic.
"""
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TC = os.path.join(REPO, "toolchain", "xpack-arm-none-eabi-gcc-14.2.1-1.1")
CC = os.path.join(TC, "bin", "arm-none-eabi-gcc")
EMB = "/home/test/Xilinx/2025.2/data/embeddedsw"
SA = EMB + "/lib/bsp/standalone_v9_4/src"
WD = EMB + "/XilinxProcessorIPLib/drivers/scuwdt_v2_6/src"
BSP = os.path.join(REPO, "firmware", "bsp")

ARCH = "-mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard".split()
INC = [
    "-I" + BSP + "/include",
    "-I" + SA + "/common",
    "-I" + SA + "/arm/common",
    "-I" + SA + "/arm/common/gcc",
    "-I" + SA + "/arm/cortexa9",
    "-I" + SA + "/arm/cortexa9/gcc",
    "-I" + WD,
]

# Every translation unit build.sh compiles (asm + C + WDT + glue + app), by
# absolute path. Kept in lockstep with build.sh -- test_bsp_inputs_manifest.py
# asserts build.sh names exactly these sources.
SA_ASM = [
    "arm/cortexa9/gcc/boot.S", "arm/cortexa9/gcc/cpu_init.S",
    "arm/cortexa9/gcc/translation_table.S", "arm/cortexa9/gcc/xil-crt0.S",
    "arm/cortexa9/gcc/asm_vectors.S",
]
SA_C = [
    "arm/cortexa9/xil_cache.c", "arm/cortexa9/xil_mmu.c",
    "arm/cortexa9/xil_misc_psreset_api.c", "arm/cortexa9/xl2cc_counter.c",
    "arm/cortexa9/xtime_l.c", "arm/common/vectors.c", "arm/common/xil_exception.c",
    "common/xil_assert.c", "common/xil_printf.c", "common/print.c",
    "common/xil_mem.c", "common/xil_sutil.c", "common/xil_util.c",
    "common/outbyte.c", "common/inbyte.c",
    "arm/common/gcc/sbrk.c", "arm/common/gcc/_sbrk.c", "arm/common/gcc/write.c",
    "arm/common/gcc/read.c", "arm/common/gcc/close.c", "arm/common/gcc/fstat.c",
    "arm/common/gcc/isatty.c", "arm/common/gcc/lseek.c", "arm/common/gcc/_exit.c",
    "arm/common/gcc/_open.c", "arm/common/gcc/open.c", "arm/common/gcc/unlink.c",
    "arm/common/gcc/getpid.c", "arm/common/gcc/kill.c", "arm/common/gcc/errno.c",
    "arm/common/gcc/abort.c",
]
WD_C = ["xscuwdt.c", "xscuwdt_g.c", "xscuwdt_sinit.c"]
APP = [
    os.path.join(REPO, "firmware", "p3_app.c"),
    os.path.join(REPO, "firmware", "p3_derive.c"),
    os.path.join(REPO, "firmware", "p3_search.c"),
    os.path.join(REPO, "firmware", "p3_wire.c"),
    os.path.join(BSP, "src", "console.c"),
]

TU = [os.path.join(SA, s) for s in (SA_ASM + SA_C)] + \
     [os.path.join(WD, s) for s in WD_C] + APP


def deps_of(tu):
    """Full preprocessor dependency set of one translation unit, absolute paths."""
    out = subprocess.check_output(
        [CC, *ARCH, "-std=gnu11", *INC, "-DUSE_AMP=0", "-M", "-MG", tu],
        stderr=subprocess.DEVNULL, text=True,
    )
    body = out.split(":", 1)[1] if ":" in out else out
    toks = body.replace("\\\n", " ").split()
    return [os.path.realpath(t) for t in toks if t not in ("\\",)]


def main(line="l5"):
    embreal = os.path.realpath(EMB)
    inputs = set()
    for tu in TU:
        for d in deps_of(tu):
            if d.startswith(embreal + os.sep):
                inputs.add(d)

    files = []
    for p in sorted(inputs):
        data = open(p, "rb").read()
        rel = os.path.relpath(p, embreal)
        files.append({
            "path": rel,                       # relative to embeddedsw root
            "version_dir": rel.split(os.sep)[2] if rel.startswith("lib/") else rel.split(os.sep)[2],
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    manifest = {
        "schema": "%s_bsp_inputs" % line,
        "schema_version": "1.0.0",
        # Deliberately names the image by REFERENCE, never by value. An earlier version
        # embedded the hash here; the image was rebuilt twice and this manifest went on
        # describing an input set as feeding a withdrawn image, which a review caught.
        # There is one source of truth for that hash and it is l5_manifest.json.
        "purpose": (
            "The exact Xilinx embeddedsw source and header files that "
            "firmware/bsp/build.sh compiles into the P3 application image whose hash is "
            "pinned at manifests/" + line + "_manifest.json pinned_at_build.app_image_sha256. "
            "Generated by host/gen_bsp_input_manifest.py from the pinned toolchain's own "
            "preprocessor dependency output (gcc -M); not a hand-written list."
        ),
        "embeddedsw_root": EMB,
        "embeddedsw_note": (
            "These files are referenced in place from a local Xilinx 2025.2 "
            "install; they are deliberately NOT vendored into the repo (see "
            "tests/test_import_manifest.py 'Deliberately NOT imported'). This "
            "manifest makes the image reproducible against an *identified* "
            "embeddedsw tree: given these exact files (checked by sha256) plus "
            "the pinned xPack toolchain, build.sh reproduces the pinned image "
            "byte-for-byte."
        ),
        "packages": {
            "standalone": "standalone_v9_4",
            "scuwdt": "scuwdt_v2_6",
        },
        "count": len(files),
        "files": files,
    }
    out_path = os.path.join(REPO, "manifests", "%s_bsp_inputs.json" % line)
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print("wrote %s (%d embeddedsw input files)" % (out_path, len(files)))


if __name__ == "__main__":
    if not os.path.isdir(EMB):
        sys.exit("embeddedsw tree not found at %s (host-only generator)" % EMB)
    line = sys.argv[1] if len(sys.argv) > 1 else "l5"
    if line not in ("l5", "l6"):
        sys.exit("usage: gen_bsp_input_manifest.py [l5|l6]")
    main(line)
