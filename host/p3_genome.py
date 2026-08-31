#!/usr/bin/env python3
"""The D1 genome: 292 whitelisted content bits → canonical frames, both directions.

`docs/d1_standalone_spec.md` §4.1/§4.2: a genome is the **absolute values** of the
manifest's 292 whitelisted `(far, word, bit)` addresses, in **canonical order = ascending
`(far, word, bit)`**, packed little-endian into ten 32-bit words (bits 292..319 zero).
Frames are *derived* from a genome by one deterministic function — base target frames,
whitelisted bits set to the genome's values, word 50's ECC recomputed with the imported
rule — and the signer and the application must implement it identically. The pinned
conformance corpus (`fixtures/d1_corpus_v1.json`, **N = 256**, review #2's Q7 condition)
is what a future C twin is tested against: entry 0 = the blank candidate, entry 1 = the
known answer, entries 2..255 from deterministic per-index seeds.

Pure host-side; nothing here touches a board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import p3_gate as g  # noqa: E402  (sets up the imported-script paths)
import p3_oracle as po  # noqa: E402
import frame_ecc as fe  # noqa: E402  (the imported prjxray ECC port, same file the gate uses)
import run_log as rl  # noqa: E402

GENOME_BITS = 292
GENOME_WORDS = 10
CORPUS_N = 256                       # review #2 Q7: pinned, not an unbound quantifier
CORPUS_SEED_LABEL = "d1-corpus-v1"   # per-index seeds derive from this label


def addresses(manifest: dict) -> list[tuple[int, int, int]]:
    """The canonical address order: ascending (far, word, bit) over the whitelist."""
    out = [(far, w, b) for far, entries in g.gc.whitelist_by_far(manifest).items()
           for (w, b) in entries]
    out.sort()
    if len(out) != GENOME_BITS:
        raise ValueError(f"whitelist has {len(out)} addresses, expected {GENOME_BITS}")
    return out


def addresses_sha256(manifest: dict) -> str:
    """Pins the order itself: sha256 over 'far:word:bit' lines in canonical order."""
    body = "".join(f"{far:#010x}:{w}:{b}\n" for far, w, b in addresses(manifest))
    return hashlib.sha256(body.encode()).hexdigest()


# ------------------------------------------------------------------- packing / text form


def pack(genome: int) -> list[int]:
    if not 0 <= genome < 1 << GENOME_BITS:
        raise ValueError(f"genome is not a {GENOME_BITS}-bit value")
    return [(genome >> (32 * j)) & 0xFFFFFFFF for j in range(GENOME_WORDS)]


def unpack(words: list[int]) -> int:
    if len(words) != GENOME_WORDS or any(not 0 <= w < 1 << 32 for w in words):
        raise ValueError(f"a packed genome is exactly {GENOME_WORDS} 32-bit words")
    genome = sum(w << (32 * j) for j, w in enumerate(words))
    if genome >> GENOME_BITS:
        raise ValueError("bits 292..319 of a packed genome must be zero")
    return genome


def to_hex(genome: int) -> str:
    """Canonical text form: the ten packed words, word 0 first, 8 hex chars each."""
    return "".join(f"{w:08x}" for w in pack(genome))


def from_hex(text: str) -> int:
    if len(text) != 8 * GENOME_WORDS:
        raise ValueError(f"a genome hex string is exactly {8 * GENOME_WORDS} chars")
    return unpack([int(text[8 * j:8 * j + 8], 16) for j in range(GENOME_WORDS)])


# ------------------------------------------------------------------- frames ⇄ genome


def frames_from_genome(genome: int, manifest: dict) -> dict[int, list[int]]:
    """The single derive function both sides must implement identically (spec §4.2)."""
    base, roles = g.gc.pinned_frames(manifest)
    frames = {far: list(base[far]) for far, r in roles.items() if r == "target"}
    for i, (far, w, b) in enumerate(addresses(manifest)):
        if (genome >> i) & 1:
            frames[far][w] |= 1 << b
        else:
            frames[far][w] &= ~(1 << b) & 0xFFFFFFFF
    return {far: fe.update_ecc(words) for far, words in frames.items()}


def genome_from_frames(frames: dict[int, list[int]], manifest: dict) -> int:
    genome = 0
    for i, (far, w, b) in enumerate(addresses(manifest)):
        if (frames[far][w] >> b) & 1:
            genome |= 1 << i
    return genome


def blank_genome(manifest: dict) -> int:
    base, roles = g.gc.pinned_frames(manifest)
    return genome_from_frames({far: base[far] for far, r in roles.items() if r == "target"},
                              manifest)


def known_answer_genome(manifest: dict) -> int:
    return genome_from_frames(g.known_answer_candidate(manifest), manifest)


# ------------------------------------------------------------------- the pinned corpus


def corpus_genome(index: int, manifest: dict) -> int:
    """Entry `index` of the corpus, derivable independently of the fixture file."""
    if not 0 <= index < CORPUS_N:
        raise ValueError(f"corpus index {index} outside 0..{CORPUS_N - 1}")
    if index == 0:
        return blank_genome(manifest)
    if index == 1:
        return known_answer_genome(manifest)
    return random.Random(f"{CORPUS_SEED_LABEL}/{index}").getrandbits(GENOME_BITS)


def corpus_entry(index: int, manifest: dict, consts: dict) -> dict:
    """genome → derive → gate (must be writable) → the hashes and tables a C twin must match."""
    genome = corpus_genome(index, manifest)
    frames = frames_from_genome(genome, manifest)
    streams = g.build_streams(frames, manifest)
    verdict = g.gate(streams, manifest)
    if not verdict["writable"]:
        kinds = [f["kind"] for f in verdict["findings"]]
        raise ValueError(f"corpus entry {index}: derived frames are not writable ({kinds}) — "
                         "the derive function violates the whitelist; this is a defect, not data")
    return {"index": index, "genome": to_hex(genome),
            "candidate_sha256": verdict["candidate_sha256"],
            "sequence_sha256": verdict["sequence_sha256"],
            "expected_tables": [f"{t:016x}" for t in po.expected_tables(frames, consts)]}


def build_corpus(manifest: dict, consts: dict, n: int = CORPUS_N) -> dict:
    return {"schema": "d1_corpus", "schema_version": "1.0.0",
            "seed_label": CORPUS_SEED_LABEL, "n": n,
            "genome_bits": GENOME_BITS, "genome_words": GENOME_WORDS,
            "address_order": "ascending (far, word, bit)",
            "addresses_sha256": addresses_sha256(manifest),
            "manifest_sha256": hashlib.sha256(g.MANIFEST.read_bytes()).hexdigest(),
            "entries": [corpus_entry(i, manifest, consts) for i in range(n)]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write-corpus", type=Path, help="write the pinned corpus JSON here")
    ap.add_argument("--n", type=int, default=CORPUS_N)
    args = ap.parse_args(argv)
    manifest = g.load_manifest()
    if args.write_corpus:
        corpus = build_corpus(manifest, po.load_constants(), args.n)
        args.write_corpus.write_text(json.dumps(corpus, indent=1) + "\n")
        print(f"{args.write_corpus}: n={corpus['n']} addresses={corpus['addresses_sha256'][:12]}…")
        return 0
    ka = known_answer_genome(manifest)
    print(f"addresses_sha256 {addresses_sha256(manifest)}")
    print(f"blank  {to_hex(blank_genome(manifest))}")
    print(f"known  {to_hex(ka)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
