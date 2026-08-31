"""The C twin against the Python reference — review #2's Q7 condition, discharged.

`firmware/p3_derive.c` is the half of the standalone application that can be proven on the
host: the derive function, the stream builder and parser, both hash domains, the pinned
readback command stream, base64url, the nonce model and the identity page. This suite
compiles it with the host compiler and drives it over the WHOLE pinned corpus (N = 256) and
the auxiliary fixtures, comparing bit for bit. A stale `p3_data.h` is a failure too: the
data the C side sees is generated from the same manifest the Python side reads.

Skipped only if no host C compiler exists — and the skip says so, never silently.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
# `scripts/` and `imported/fabricmap/scripts/` both carry a `bitstream_frames.py` and a
# `frame_ecc.py`; the import manifest keeps them separate because they are different
# revisions in principle, and each finds `data/prjxray/tilegrid.json` RELATIVE TO ITSELF —
# only the zynq-psmap copy has that data beneath it. Whichever is imported first wins
# `sys.modules` for the whole run, and importing `p3_gate` puts the fabricmap copy at the
# front of the path. This module sorts before `test_l3_runner`, which is what used to fix
# the order, so it pins the psmap copy explicitly before anything can pull the other one.
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy: pinned first, deliberately)
import pcap_probe_plan as pp  # noqa: E402
from validators import nonce as nc  # noqa: E402
import l5_notary as n  # noqa: E402
import l5_refloop as rf  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402

FW = R / "firmware"
TWIN = FW / "build/p3_twin"
CORPUS = json.loads((R / "fixtures/d1_corpus_v1.json").read_text())
HAVE_CC = shutil.which(os.environ.get("CC", "cc")) is not None


def run_twin(mode: str, lines: list[str]) -> list[str]:
    p = subprocess.run([str(TWIN), mode], input="\n".join(lines) + "\n",
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise AssertionError(f"p3_twin {mode} exited {p.returncode}: {p.stderr}")
    return p.stdout.strip().split("\n")


@unittest.skipUnless(HAVE_CC, "no host C compiler: the C twin cannot be checked here")
class Twin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build = subprocess.run(["make", "twin"], cwd=FW, capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"the twin did not build:\n{build.stdout}\n{build.stderr}")
        cls.manifest = g.load_manifest()

    def test_generated_data_header_is_current(self):
        p = subprocess.run([sys.executable, str(R / "host/gen_firmware_data.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"firmware/p3_data.h is stale: {p.stderr}")

    def test_whole_corpus_reproduces_both_hashes(self):
        """N = 256, every entry, both hash domains — the Q7 exit gate."""
        entries = CORPUS["entries"]
        self.assertEqual(len(entries), 256)
        out = run_twin("derive", [e["genome"] for e in entries])
        self.assertEqual(len(out), len(entries))
        for e, line in zip(entries, out):
            got = line.split()
            self.assertEqual(len(got), 2, f"entry {e['index']}: {line}")
            self.assertEqual(got[0], e["candidate_sha256"], f"entry {e['index']} candidate")
            self.assertEqual(got[1], e["sequence_sha256"], f"entry {e['index']} sequence")

    def test_whole_corpus_round_trips_through_the_stream_parser(self):
        """Build → parse → the four target frames and the flush frame come back identical."""
        out = run_twin("parse", [e["genome"] for e in CORPUS["entries"]])
        self.assertEqual(set(out), {"ok"})

    def test_a_bit_flip_changes_the_candidate_hash(self):
        """Discrimination: the comparison above would pass on a constant too."""
        base = CORPUS["entries"][0]["genome"]
        flipped = f"{int(base, 16) ^ 1:0{len(base)}x}"
        out = run_twin("derive", [base, flipped])
        self.assertNotEqual(out[0].split()[0], out[1].split()[0])

    def test_malformed_genomes_are_refused(self):
        out = run_twin("derive", ["00" * 39, "zz" * 40, "f" * 80])
        self.assertEqual(out[0], "bad-genome")          # too short
        self.assertEqual(out[1], "bad-genome")          # not hex
        self.assertEqual(out[2], "bad-genome")          # bits above 292 set

    def test_readback_command_stream_equals_psmap(self):
        fars = [f"{f:08x}" for f in sorted(g.gc.pinned_frames(self.manifest)[1])]
        out = run_twin("rbcmd", fars)
        for far, line in zip(fars, out):
            self.assertEqual([int(x, 16) for x in line.split()],
                             pp.readback_commands(int(far, 16)), f"FAR {far}")

    def test_cleanup_stream_equals_psmap(self):
        out = run_twin("cleanup", ["-"])
        self.assertEqual([int(x, 16) for x in out[0].split()], pp.cleanup_commands())

    def test_frame_ecc_equals_the_imported_port(self):
        import frame_ecc as fe
        base, roles = g.gc.pinned_frames(self.manifest)
        fars = sorted(base)[:4]
        lines = [" ".join(f"{w:08x}" for w in base[f]) for f in fars]
        out = run_twin("ecc", lines)
        for far, line in zip(fars, out):
            self.assertEqual(int(line, 16), fe.update_ecc(base[far])[0x32], f"FAR {far:#x}")

    def test_nonce_model_matches(self):
        seeds = [0x9E3779B97F4A7C15, 1, 0xFFFFFFFFFFFFFFFF, 0x123456789ABCDEF0]
        out = run_twin("nonce", [f"{s:016x}" for s in seeds])
        for s, line in zip(seeds, out):
            self.assertEqual(int(line, 16), nc.step(s))

    def test_crc32_matches_the_framing(self):
        bodies = ["P3L5 HB 1 " + "ab" * 16 + " -", "P3L5 SIGNREQ 42 " + "5a" * 16 + " eyJhIjoxfQ=="]
        out = run_twin("crc32", bodies)
        import zlib
        for body, line in zip(bodies, out):
            self.assertEqual(int(line, 16), zlib.crc32(body.encode()) & 0xFFFFFFFF)

    def test_base64url_round_trips_against_the_notary(self):
        payloads = [{"seq": i, "schema": "sign_reply", "commit": "ab" * 32} for i in range(4)]
        want = [n.encode_payload(p) for p in payloads]
        raw = [json.dumps(p, sort_keys=True, separators=(",", ":")).encode().hex() for p in payloads]
        self.assertEqual(run_twin("b64", raw), want)
        self.assertEqual([bytes.fromhex(h) for h in run_twin("b64d", want)],
                         [base64.urlsafe_b64decode(w) for w in want])

    def test_base64url_decode_refuses_malformed_input(self):
        self.assertEqual(run_twin("b64d", ["abc", "ab=c", "!!!!"]), ["bad-b64"] * 3)

    def test_identity_page_parses_as_the_python_builds_it(self):
        token = "5a" * 16
        carrier = "9a" * 32
        page = rf.build_identity_page(token, 3, 0x12345678, carrier,
                                      0x9E3779B97F4A7C15, 0x900, 7, 11, 3)
        line = " ".join(f"{w:08x}" for w in page)
        got = run_twin("page", [line])[0].split()
        parsed = rf.parse_identity_page(page)
        self.assertEqual(got[0], parsed["token"])
        self.assertEqual(int(got[1]), parsed["uboot_epoch"])
        self.assertEqual(got[3], parsed["carrier_sha256"])
        self.assertEqual(int(got[4], 16), parsed["nonce_seen"])
        self.assertEqual(int(got[6]), parsed["seed"])
        self.assertEqual(int(got[7]), parsed["budget"])

    def test_identity_page_with_a_broken_checksum_is_refused(self):
        page = rf.build_identity_page("5a" * 16, 0, 0, "9a" * 32, 1, 0x900, 0, 0, 0)
        page[-1] ^= 1
        out = run_twin("page", [" ".join(f"{w:08x}" for w in page)])
        self.assertEqual(out[0], "page-refused")


if __name__ == "__main__":
    unittest.main()
