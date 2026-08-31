"""manifests/l5_bsp_inputs.json pins the third-party Xilinx embeddedsw files that
firmware/bsp/build.sh compiles into the application image.

Before this manifest the pinned app_image_sha256 was reproducible only against
"whatever embeddedsw tree this host happens to have". The manifest names each of
those inputs by path/size/sha256 so the image is reproducible against an
*identified* input set. These tests keep the manifest honest:

  * structural checks (always, fail-closed): the manifest is well formed, and every
    source build.sh names appears in it -- so the build cannot pull a source the
    manifest omits without this test noticing;
  * a drift guard: the generator's source lists equal build.sh's source lists;
  * a reproduction check (skipped only when the embeddedsw tree is absent, e.g. a
    reviewer sandbox): every file the manifest lists still hashes to the recorded
    sha256 and size on this host -- the manifest is truthful about the real inputs.

Header completeness comes from the generator's `gcc -M` closure
(host/gen_bsp_input_manifest.py), which is itself in the repo and reviewable; it
is not re-run here (38 compiler invocations is too slow for a unit test).
"""
import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "host"))

MANIFEST = REPO / "manifests" / "l5_bsp_inputs.json"
BUILD_SH = REPO / "firmware" / "bsp" / "build.sh"


def _shell_list(var, text):
    """Extract a `VAR="a b c \\ d"` list from build.sh as basenames of sources."""
    m = re.search(var + r'="(.*?)"', text, re.DOTALL)
    assert m, "%s not found in build.sh" % var
    return [os.path.basename(t) for t in m.group(1).split() if t != "\\"]


class Manifest(unittest.TestCase):
    def setUp(self):
        self.m = json.loads(MANIFEST.read_text())
        self.by_base = {}
        for f in self.m["files"]:
            self.by_base.setdefault(os.path.basename(f["path"]), []).append(f)

    def test_shape(self):
        self.assertEqual(self.m["schema"], "l5_bsp_inputs")
        self.assertEqual(self.m["count"], len(self.m["files"]))
        self.assertGreater(self.m["count"], 0)
        for f in self.m["files"]:
            self.assertFalse(f["path"].startswith("/"), f["path"])
            self.assertNotIn("..", f["path"].split("/"), f["path"])
            self.assertEqual(len(f["sha256"]), 64)
            self.assertGreater(f["bytes"], 0)
        self.assertEqual(
            set(self.m["packages"].values()), {"standalone_v9_4", "scuwdt_v2_6"})

    def test_every_source_build_sh_compiles_is_pinned(self):
        text = BUILD_SH.read_text()
        sources = (
            _shell_list("ASM_SRCS", text) + _shell_list("C_SRCS", text)
            + _shell_list("SYS_SRCS", text) + _shell_list("WDT_SRCS", text))
        for s in sources:
            self.assertIn(s, self.by_base,
                          "%s is compiled by build.sh but not pinned in the manifest" % s)

    def test_generator_lists_match_build_sh(self):
        """The generator cannot drift from build.sh's source set."""
        import gen_bsp_input_manifest as g
        text = BUILD_SH.read_text()
        gen = {os.path.basename(s) for s in (g.SA_ASM + g.SA_C + g.WD_C)}
        sh = set(
            _shell_list("ASM_SRCS", text) + _shell_list("C_SRCS", text)
            + _shell_list("SYS_SRCS", text) + _shell_list("WDT_SRCS", text))
        self.assertEqual(gen, sh)

    def test_recorded_hashes_match_the_tree_on_this_host(self):
        root = self.m["embeddedsw_root"]
        if not os.path.isdir(root):
            self.skipTest("embeddedsw tree not present (%s) -- reproduction "
                          "check needs the 2025.2 install; structure was still "
                          "checked" % root)
        for f in self.m["files"]:
            p = os.path.join(root, f["path"])
            data = open(p, "rb").read()
            self.assertEqual(len(data), f["bytes"], f["path"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), f["sha256"], f["path"])


if __name__ == "__main__":
    unittest.main()
