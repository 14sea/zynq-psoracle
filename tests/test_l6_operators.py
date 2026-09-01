"""host/l6_operators.py — the Python reference of the two operators, and the map data an
image would compile in (prereg §2.1, §2.3).

What is pinned: the derivation from the pinned local_map + phenotype manifest (its sha256
is a constant here — a changed map or a changed derivation shows up as a changed hash);
that the map's universe IS the manifest's whitelist; that random-safe stays within the
292 addresses and reaches all of them; that map-guided stays within one LUT; that both
are pure; and the twin corpus fixture (N = 256) agrees with the code that generated it."""
from __future__ import annotations

import collections
import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import bitstream_frames  # noqa: E402,F401  (zynq-psmap's copy pinned first; see test_firmware_twin)
import l6_operators as lo  # noqa: E402
import l6_schedule as ls  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402

MANIFEST = g.load_manifest()
LOCAL_MAP = lo.load_local_map()
DATA = lo.operator_data(MANIFEST, LOCAL_MAP)
PINNED_DATA_SHA = "0c9c82a812be754dbba83c02b24b4321a95af46464a201a6f3c51374f2c80d79"
CORPUS = R / "fixtures/l6_operator_corpus_v1.json"


class MapData(unittest.TestCase):
    def test_derivation_hash_is_pinned(self):
        self.assertEqual(lo.operator_data_sha256(DATA), PINNED_DATA_SHA)
        self.assertEqual(DATA["addresses_sha256"], gn.addresses_sha256(MANIFEST))
        self.assertEqual(len(DATA["addresses"]), 292)
        self.assertEqual(sorted(DATA["luts"]), sorted(LOCAL_MAP["index"]["by_lut"]))

    def test_the_manifest_draft_pins_the_same_hash(self):
        m = json.loads((R / "manifests/l6_manifest.json").read_text())
        self.assertEqual(m["operator"]["operator_data_sha256"], PINNED_DATA_SHA)
        self.assertEqual(m["operator"]["mutation_bits"], DATA["mutation_bits"])

    def test_a_map_whose_universe_is_not_the_whitelist_is_refused(self):
        import copy
        bad = copy.deepcopy(LOCAL_MAP)
        bad["universe"]["addresses"][0]["bit"] = 31
        with self.assertRaises(ValueError) as cm:
            lo.operator_data(MANIFEST, bad)
        self.assertIn("whitelist", str(cm.exception))

    def test_a_lut_row_outside_the_whitelist_is_refused(self):
        import copy
        bad = copy.deepcopy(LOCAL_MAP)
        key = sorted(bad["index"]["by_lut"])[0]
        bad["index"]["by_lut"][key][0]["address_key"] = "0x00400A20/50/0"
        with self.assertRaises(ValueError) as cm:
            lo.operator_data(MANIFEST, bad)
        self.assertIn("not a whitelisted address", str(cm.exception))


class RandomSafe(unittest.TestCase):
    def test_exactly_mutation_bits_within_the_universe(self):
        for k in range(64):
            gnm = lo.random_safe(ls.pair_seed(3, k), DATA)
            self.assertLess(gnm, 1 << 292); self.assertEqual(bin(gnm).count("1"), DATA["mutation_bits"])

    def test_reaches_every_address_roughly_uniformly(self):
        cnt = collections.Counter()
        draws = 3000
        for k in range(draws):
            gnm = lo.random_safe(ls.pair_seed(5, k), DATA)
            for b in range(292):
                if gnm >> b & 1:
                    cnt[b] += 1
        self.assertEqual(len(cnt), 292, "an address the sampler never proposes is not 'uniform over the 292'")
        expect = draws * DATA["mutation_bits"] / 292
        self.assertLess(max(cnt.values()), 2 * expect); self.assertGreater(min(cnt.values()), expect / 2)

    def test_uniform_draw_is_unbiased_by_rejection(self):
        rng = lo.Rng(1)
        self.assertEqual(rng.uniform(1), 0)
        with self.assertRaises(ValueError):
            rng.uniform(0)
        rng2 = lo.Rng(1)
        self.assertEqual([lo.Rng(1).next32() for _ in range(1)], [rng2.next32()])

    def test_pure(self):
        self.assertEqual(lo.random_safe(42, DATA), lo.random_safe(42, DATA))
        self.assertNotEqual(lo.random_safe(42, DATA), lo.random_safe(43, DATA))


class MapGuided(unittest.TestCase):
    def _lut_of(self, bit: int) -> str:
        for key, rows in DATA["luts"].items():
            if any(r["genome_bit"] == bit for r in rows):
                return key
        raise AssertionError(f"bit {bit} belongs to no LUT")

    def test_every_candidate_stays_within_one_lut(self):
        luts = collections.Counter()
        for k in range(600):
            gnm = lo.map_guided(ls.pair_seed(9, k), DATA)
            bits = [b for b in range(292) if gnm >> b & 1]
            self.assertEqual(len(bits), DATA["mutation_bits"])
            owners = {self._lut_of(b) for b in bits}
            self.assertEqual(len(owners), 1, f"candidate {k} spans LUTs {owners}")
            luts[owners.pop()] += 1
        self.assertEqual(set(luts), set(DATA["luts"]), "every LUT must be reachable")

    def test_differs_from_random_safe_on_the_same_seed(self):
        self.assertNotEqual(lo.map_guided(1234, DATA), lo.random_safe(1234, DATA))


class Corpus(unittest.TestCase):
    def test_fixture_agrees_with_the_generator_and_is_large_enough(self):
        c = json.loads(CORPUS.read_text())
        self.assertGreaterEqual(c["n"], lo.CORPUS_N)
        self.assertEqual(c["operator_data_sha256"], PINNED_DATA_SHA)
        self.assertEqual(c, lo.build_corpus(DATA, c["n"]))
        arms = collections.Counter(e["arm"] for e in c["entries"])
        self.assertEqual(arms[ls.ARM_A], arms[ls.ARM_B])

    def test_each_entry_is_reproduced_from_master_seed_and_index_alone(self):
        c = json.loads(CORPUS.read_text())
        for e in c["entries"][::7]:
            got = lo.candidate(e["master_seed"], e["index"], ls.MODE_ABBA, DATA)
            self.assertEqual((got["arm"], got["seed"], got["genome_hex"]), (e["arm"], e["seed"], e["genome"]))


if __name__ == "__main__":
    unittest.main()
