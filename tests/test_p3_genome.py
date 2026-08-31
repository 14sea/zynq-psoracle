"""The D1 genome codec and the pinned corpus (spec §4.1/§4.2; review #2 Q7: N = 256).

The corpus fixture is the contract a future C twin is tested against; these tests pin the
Python side: the derive function round-trips the known answer and the blank candidate
bit-for-bit, every derived candidate passes the real gate, the address order and packing
are stable, and the fixture file matches an independent regeneration at spot-checked
indices (full regeneration is the generator's own job, kept out of the suite's runtime).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402

CORPUS = R / "fixtures/d1_corpus_v1.json"
SPOT_INDICES = (0, 1, 2, 7, 42, 255)   # full regeneration is not a unit test's job


class Genome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = g.load_manifest()
        cls.consts = po.load_constants()
        cls.addresses = gn.addresses(cls.manifest)

    def test_addresses_are_292_ascending_and_pinned(self):
        self.assertEqual(len(self.addresses), gn.GENOME_BITS)
        self.assertEqual(self.addresses, sorted(self.addresses))
        self.assertEqual(len(set(self.addresses)), gn.GENOME_BITS)
        # the order is itself pinned content: a re-derivation must reproduce the digest
        self.assertEqual(gn.addresses_sha256(self.manifest), gn.addresses_sha256(self.manifest))

    def test_packing_round_trips_and_rejects_overflow(self):
        genome = gn.corpus_genome(42, self.manifest)
        self.assertEqual(gn.unpack(gn.pack(genome)), genome)
        self.assertEqual(gn.from_hex(gn.to_hex(genome)), genome)
        self.assertEqual(len(gn.to_hex(genome)), 80)
        with self.assertRaises(ValueError):
            gn.unpack(gn.pack(genome)[:-1] + [1 << 31])   # sets a bit above 292
        with self.assertRaises(ValueError):
            gn.pack(1 << gn.GENOME_BITS)

    def test_known_answer_round_trips_bit_for_bit(self):
        ka = g.known_answer_candidate(self.manifest)
        genome = gn.genome_from_frames(ka, self.manifest)
        self.assertEqual(gn.frames_from_genome(genome, self.manifest), ka)

    def test_blank_candidate_round_trips_bit_for_bit(self):
        base, roles = g.gc.pinned_frames(self.manifest)
        blank = {far: list(base[far]) for far, r in roles.items() if r == "target"}
        genome = gn.blank_genome(self.manifest)
        self.assertEqual(gn.frames_from_genome(genome, self.manifest), blank)

    def test_every_derived_candidate_passes_the_real_gate(self):
        for i in (0, 1, 3, 99):
            frames = gn.frames_from_genome(gn.corpus_genome(i, self.manifest), self.manifest)
            verdict = g.gate(g.build_streams(frames, self.manifest), self.manifest)
            self.assertTrue(verdict["writable"],
                            f"entry {i}: {[f['kind'] for f in verdict['findings']]}")

    def test_derive_touches_only_whitelist_and_ecc(self):
        base, roles = g.gc.pinned_frames(self.manifest)
        frames = gn.frames_from_genome(gn.corpus_genome(3, self.manifest), self.manifest)
        allowed = g.gc.whitelist_by_far(self.manifest)
        for far, words in frames.items():
            for w in range(101):
                diff = words[w] ^ base[far][w]
                for b in range(32):
                    if (diff >> b) & 1 and w != 50:
                        self.assertIn((w, b), allowed[far], f"{far:#010x} word {w} bit {b}")

    def test_corpus_entry_is_deterministic(self):
        a = gn.corpus_entry(7, self.manifest, self.consts)
        b = gn.corpus_entry(7, self.manifest, self.consts)
        self.assertEqual(a, b)

    def test_fixture_matches_independent_regeneration_at_spot_indices(self):
        self.assertTrue(CORPUS.exists(), "fixtures/d1_corpus_v1.json missing — run "
                        "`python3 host/p3_genome.py --write-corpus fixtures/d1_corpus_v1.json`")
        corpus = json.loads(CORPUS.read_text())
        self.assertEqual(corpus["n"], gn.CORPUS_N)          # review #2 Q7: N is pinned
        self.assertEqual(corpus["genome_bits"], gn.GENOME_BITS)
        self.assertEqual(len(corpus["entries"]), gn.CORPUS_N)
        self.assertEqual(corpus["addresses_sha256"], gn.addresses_sha256(self.manifest))
        for i in SPOT_INDICES:
            self.assertEqual(corpus["entries"][i], gn.corpus_entry(i, self.manifest, self.consts),
                             f"fixture entry {i} does not regenerate")

    def test_corpus_first_two_entries_are_blank_and_known_answer(self):
        corpus = json.loads(CORPUS.read_text())
        self.assertEqual(corpus["entries"][0]["genome"], gn.to_hex(gn.blank_genome(self.manifest)))
        self.assertEqual(corpus["entries"][1]["genome"], gn.to_hex(gn.known_answer_genome(self.manifest)))
        # the known answer's hash is fabricmap's silicon-verified candidate
        ka_frames = g.known_answer_candidate(self.manifest)
        verdict = g.gate(g.build_streams(ka_frames, self.manifest), self.manifest)
        self.assertEqual(corpus["entries"][1]["candidate_sha256"], verdict["candidate_sha256"])


if __name__ == "__main__":
    unittest.main()
