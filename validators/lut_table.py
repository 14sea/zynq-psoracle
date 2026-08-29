"""`lut_truth_table` 1.0.0 — a target LUT's 64-bit truth table from candidate frames.

The certified map (`zynq-fabricmap` `local_map.json`, `index.by_lut[<lut_key>]`) places each
mapped `INIT[i]` at an `address_key` `"<FAR>/<word>/<bit>"`. Positions the map does not
certify keep the base LUT's value (`base_init` = the LUT's actual INIT before the candidate,
the known-answer artifact's `selection.actual_init`), because that is what the fabric will
exhibit. Polarity is direct (frame bit 1 ⇒ INIT bit 1), as the fixture confirms against
`target_init` on all 49 certified positions. Bit order: INIT[i] is bit i of the 64-bit table (LSB = INIT[0]); which physical
input is A1..A6 is the LUT's own convention and is not reordered here — the fabric's sweep
must use the same convention (pinned in `carrier_manifest` at L1).
"""

from __future__ import annotations


def mapped_positions(local_map: dict, lut_key: str) -> dict[int, tuple[int, int, int]]:
    out: dict[int, tuple[int, int, int]] = {}
    for rec in local_map["index"]["by_lut"][lut_key]:
        idx = int(rec["init_index"])
        far_s, word_s, bit_s = rec["address_key"].split("/")
        if idx in out:
            raise ValueError(f"INIT[{idx}] is mapped twice")
        out[idx] = (int(far_s, 16), int(word_s), int(bit_s))
    return out


def truth_table(frames: dict[int, list[int]], positions: dict[int, tuple[int, int, int]],
                base_init: int) -> int:
    table = base_init & 0xFFFFFFFFFFFFFFFF
    for idx, (far, word, bit) in positions.items():
        if far not in frames:
            raise ValueError(f"INIT[{idx}] maps to FAR {far:#010x}, which the candidate does not carry")
        v = (frames[far][word] >> bit) & 1
        table = (table & ~(1 << idx)) | (v << idx)
    return table


def mutable_mask(positions: dict[int, tuple[int, int, int]]) -> int:
    return sum(1 << i for i in positions)
