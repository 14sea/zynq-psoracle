#!/usr/bin/env python3
"""Python reference of the two operators the two-operator image will carry (prereg §2.1,
§2.3) and of the map data compiled into it — host-only. Nothing here is firmware; the C
twin is §2's work and is checked against `fixtures/l6_operator_corpus_v1.json`, which this
module generates, in the style of `tests/test_firmware_twin.py`.

Both operators are pure functions of (pair seed, arm) — the pair seed comes from
`l6_schedule.pair_seed(master_seed, pair)` — and produce a genome: the 292-bit diff
against the pinned base, in `p3_genome`'s canonical bit order (ascending far, word, bit).

  * random-safe (arm A): `MUTATION_BITS` addresses drawn uniformly WITHOUT replacement
    from the 292 whitelisted addresses — the same universe, the same gates, no map.
  * map-guided (arm B): one target LUT drawn uniformly from the map's `index.by_lut`,
    then `MUTATION_BITS` mapped INIT positions of that LUT drawn uniformly without
    replacement — same-LUT locality, which is the one thing the map knows and the sampler
    does not (Claim B prereg §3).

The generator is the PL's xorshift64 (`validators.nonce.step`), one implementation on both
sides; uniform draws use the upper 32 bits with rejection, so a C twin reproduces them
with integer arithmetic only. The map data an image compiles in is `operator_data()`:
its sha256 (`operator_data_sha256`) is what the image's IDENT must name (§2.4) and what a
host test regenerates from the pinned `local_map.json` (§2.1).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import nonce as nc  # noqa: E402
import l6_schedule as ls  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402

MUTATION_BITS = 4          # per candidate, both arms — a draft pin (manifests/l6_manifest.json)
CORPUS_N = 256             # §2.3: N ≥ 256 (seed, index) pairs
CORPUS_MASTER_SEEDS = (0x00000001, 0x1F123BB5, 0xDEADBEEF, 0xFFFFFFFF)
OPERATOR_DATA_SCHEMA = "l6_operator_data"


class Rng:
    """xorshift64 state; `uniform(n)` is an unbiased draw in [0, n) from the upper 32 bits."""

    def __init__(self, seed32: int):
        if not 0 <= seed32 <= ls.MASK32:
            raise ValueError("seed must be 32-bit")
        x = ((seed32 << 32) | seed32) ^ ls.GOLDEN
        self.x = x if x else ls.GOLDEN
        for _ in range(ls.WARMUP_STEPS):
            self.x = nc.step(self.x)

    def next32(self) -> int:
        self.x = nc.step(self.x)
        return (self.x >> 32) & ls.MASK32

    def uniform(self, n: int) -> int:
        if n < 1 or n > 1 << 32:
            raise ValueError("uniform(n) needs 1 <= n <= 2^32")
        limit = ((1 << 32) // n) * n
        while True:
            r = self.next32()
            if r < limit:
                return r % n

    def sample(self, population: list[int], k: int) -> list[int]:
        """k distinct elements, partial Fisher–Yates over a copy — order is the draw order."""
        if k > len(population):
            raise ValueError("sample larger than population")
        pool = list(population)
        out = []
        for i in range(k):
            j = i + self.uniform(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
            out.append(pool[i])
        return out


# ------------------------------------------------------------------ the map data


def load_local_map(path: Path = po.LOCAL_MAP) -> dict:
    return json.loads(path.read_text())


def operator_data(manifest: dict, local_map: dict) -> dict:
    """The tables an image compiles in, derived from the pinned map and the phenotype
    manifest: the 292 addresses in genome bit order, and each LUT's genome bit indices in
    INIT-index order. Refuses a map whose universe is not the manifest's whitelist."""
    addrs = gn.addresses(manifest)
    index_of = {a: i for i, a in enumerate(addrs)}
    universe = []
    for e in local_map["universe"]["addresses"]:
        universe.append((int(e["far"], 16), int(e["word"]), int(e["bit"])))
    if sorted(universe) != addrs:
        raise ValueError("local_map universe != the phenotype manifest's whitelist (prereg §2.1)")
    luts = {}
    for key in sorted(local_map["index"]["by_lut"]):
        rows = sorted(local_map["index"]["by_lut"][key], key=lambda r: int(r["init_index"]))
        bits = []
        seen = set()
        for r in rows:
            far_s, word_s, bit_s = r["address_key"].split("/")
            a = (int(far_s, 16), int(word_s), int(bit_s))
            if a not in index_of:
                raise ValueError(f"{key}: {r['address_key']} is not a whitelisted address")
            if int(r["init_index"]) in seen:
                raise ValueError(f"{key}: INIT[{r['init_index']}] is mapped twice")
            seen.add(int(r["init_index"]))
            bits.append({"init_index": int(r["init_index"]), "genome_bit": index_of[a]})
        if not bits:
            raise ValueError(f"{key}: a LUT with no mapped positions")
        luts[key] = bits
    return {"schema": OPERATOR_DATA_SCHEMA, "schema_version": "1.0.0",
            "map_id": local_map["map_id"],
            "addresses": [f"{far:#010x}/{w}/{b}" for far, w, b in addrs],
            "addresses_sha256": gn.addresses_sha256(manifest),
            "luts": luts, "mutation_bits": MUTATION_BITS}


def operator_data_sha256(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ------------------------------------------------------------------ the operators


def random_safe(seed32: int, data: dict) -> int:
    rng = Rng(seed32)
    n = len(data["addresses"])
    genome = 0
    for bit in rng.sample(list(range(n)), data["mutation_bits"]):
        genome |= 1 << bit
    return genome


def map_guided(seed32: int, data: dict) -> int:
    rng = Rng(seed32)
    keys = sorted(data["luts"])
    lut = data["luts"][keys[rng.uniform(len(keys))]]
    positions = [row["genome_bit"] for row in lut]
    k = min(data["mutation_bits"], len(positions))
    genome = 0
    for bit in rng.sample(positions, k):
        genome |= 1 << bit
    return genome


OPERATORS = {ls.ARM_A: random_safe, ls.ARM_B: map_guided}


def candidate(master_seed: int, index: int, mode: str, data: dict) -> dict:
    """The genome of candidate `index` under `mode`: schedule row + genome (int and hex)."""
    row = ls.schedule(master_seed, index + 1, mode)[index]
    genome = OPERATORS[row["arm"]](row["seed"], data)
    return {**row, "genome": genome, "genome_hex": gn.to_hex(genome)}


def build_corpus(data: dict, n: int = CORPUS_N) -> dict:
    """The twin corpus: n (master_seed, index) pairs under the A,B,B,A schedule, spread over
    a few master seeds so that pair seeds, arms and both operators are all exercised."""
    entries = []
    per_seed = -(-n // len(CORPUS_MASTER_SEEDS))
    for ms in CORPUS_MASTER_SEEDS:
        for i in range(per_seed):
            if len(entries) == n:
                break
            c = candidate(ms, i, ls.MODE_ABBA, data)
            entries.append({"master_seed": ms, "index": i, "pair": c["pair"], "seed": c["seed"],
                            "arm": c["arm"], "genome": c["genome_hex"]})
    return {"schema": "l6_operator_corpus", "schema_version": "1.0.0", "n": len(entries),
            "operator_data_sha256": operator_data_sha256(data), "mutation_bits": data["mutation_bits"],
            "rule": "arm by A,B,B,A over seed pairs; pair seed = xorshift64(master_seed<<32 ^ (pair+1) ^ golden) >> 32",
            "entries": entries}


def main(argv=None) -> int:
    import argparse
    import p3_gate as g
    ap = argparse.ArgumentParser(description="write the operator data and the twin corpus")
    ap.add_argument("--corpus-out", type=Path, default=R / "fixtures/l6_operator_corpus_v1.json")
    ap.add_argument("--data-out", type=Path, default=None)
    a = ap.parse_args(argv)
    data = operator_data(g.load_manifest(), load_local_map())
    if a.data_out:
        a.data_out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    a.corpus_out.write_text(json.dumps(build_corpus(data), indent=1) + "\n")
    print(f"operator_data_sha256 {operator_data_sha256(data)}; corpus {a.corpus_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
