#!/usr/bin/env python3
"""Derive `carrier_manifest` 1.0.0 (docs/contracts.md) from a built P3 bitstream.

Everything in the manifest is read from the artifacts — the bitstream's frame table, the
build record, the register map the RTL implements — not typed. The key never appears; only
any key id: the key is provisioned at runtime (D4 option A) and its id is per session. The heartbeat envelope is
`null` until the L2 no-read baseline measures it (`p3_architecture.md` §6 L2).

usage: gen_carrier_manifest.py <p3.bit> <p3_build.json> <out.json> [--key-id HEX] [--nonce-seed HEX]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts"))
sys.path.insert(0, str(R))
import bitstream_frames as bf  # noqa: E402
import diag_pcap_target_select as ds  # noqa: E402
from validators.records import validate  # noqa: E402

TARGET_FARS = [0x00400A20, 0x00400A21, 0x00400A22, 0x00400A23,
               0x00400C1A, 0x00400C1B, 0x00400C1C, 0x00400C1D,
               0x00400C20, 0x00400C21, 0x00400C22, 0x00400C23]
AXI = {
    "base": 0x43C00000,
    "stable_state": [0x2004, 0x2008, 0x2010, 0x2014, 0x2018, 0x201C, 0x2020, 0x2024],
    "heartbeat": {"offset": 0x2028, "width_bits": 32,
                  "advances_per_s_min": None, "advances_per_s_max": None,
                  "note": "bounds are pinned from the L2 no-read baseline before the L2 ruling"},
    "nonce": {"lo": 0x202C, "hi": 0x2030, "steps_after_every_arm_attempt": True,
              "generator": "xorshift64 (validators/nonce.py)"},
    "arm_payload": {"first": 0x2100, "words": 20, "tag_first": 0x2150, "tag_words": 4,
                    "strobe": {"offset": 0x2000, "bit": 6}, "write_only": True},
    "hw_candidate_commit": {"first": 0x2200, "words": 8},
    "functional_readout": {"first": 0x2240, "words": 12},
    "status_reserved_mask": 0xF8000000,
    "status_alive_bit": 8,
    "fault_codes": {"13": "F_ARM_AUTH", "15": "F_ARM_TABLE"},
    "undecoded": "SLVERR on read and write",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bit", type=Path); ap.add_argument("build_json", type=Path); ap.add_argument("out", type=Path)
    ap.add_argument("--nonce-seed", default=None)
    ap.add_argument("--heartbeat-bounds", nargs=2, type=float, metavar=("MIN_HZ", "MAX_HZ"), default=None,
                    help="owner-ruled L2 envelope (ticks/s); null until L2 PASS")
    a = ap.parse_args()
    data = a.bit.read_bytes()
    build = json.loads(a.build_json.read_text())
    sha = hashlib.sha256(data).hexdigest()
    if build.get("bitstream_sha256") != sha:
        sys.exit(f"build record sha {build.get('bitstream_sha256')} != bitstream {sha}")
    frames = bf.parse_frames(a.bit)["frames"]
    digest, count = ds.frame_table_digest(frames)
    blank = {f"{far:#010x}": sum(1 for w in frames[far] if w) for far in TARGET_FARS}
    if any(blank.values()):
        sys.exit(f"target frames are not blank in this base: {blank}")
    target, min_h, dist = ds.select_target(frames, ds.MIN_NONZERO)
    reverse = ds.reverse_index(frames)
    axi = json.loads(json.dumps(AXI))
    if a.heartbeat_bounds:
        lo, hi = a.heartbeat_bounds
        axi["heartbeat"].update(advances_per_s_min=lo, advances_per_s_max=hi,
                                note="pinned by the owner from L2 evidence (docs/l2_findings.md run #3, 2026-08-30-03); "
                                     "the L2 heartbeat contract of this carrier/clock path, not a computational-correctness guarantee")
    m = {
        "schema": "carrier_manifest", "schema_version": "1.0.0",
        "bitstream_sha256": sha, "bitstream_bytes": len(data),
        "frame_table_sha256": digest, "frame_count": count,
        "part": build["part"], "top": build["top"], "vivado": build["vivado"],
        "wns_ns": build["wns_ns"], "cell_isolation": build["cell_isolation"],
        "board_roles": {"17A6": "verify"},
        "axi": axi,
        "target_columns": ["CLBLL_L_X2", "CLBLM_L_X6"],
        "target_fars": [f"{f:#010x}" for f in TARGET_FARS],
        "target_frames_nonzero_words": blank,
        "positive_control": {"far": f"{target:#010x}", "frame_sha256": ds.frame_sha256(frames[target]),
                             "min_hamming_to_neighbours": min_h, "hamming": dist,
                             "globally_unique": len(reverse[ds.frame_sha256(frames[target])]) == 1},
        "blank_far_group_size": len(reverse.get(ds.frame_sha256([0] * 101), [])),
        "no_icap": True,
        "nonce_seed": a.nonce_seed or build.get("nonce_seed"),
        "mac": {"algorithm": "siphash-2-4-128",
                "key": "runtime-provisioned into a write-once, write-only register (0x2160-0x216C + CTRL bit 8) "
                       "over the DAP mem-AP by the gate-signer principal; not in this bitstream",
                "key_loaded_status_bit": 11, "fault_nokey": 12,
                "key_id_note": "key_id = sha256(K) is recorded per session in arm_record.signer.key_id (docs/decisions.md D4 option A)"},
        "lut_truth_table": {"bit_order": "INIT[i] = bit i; sweep vector[0] = I0 (LOCK_PINS I0:A1..I5:A6)"},
    }
    validate(m)
    a.out.write_text(json.dumps(m, indent=2) + "\n")
    print(f"manifest -> {a.out}  bitstream {sha[:16]}…  frames {count}  positive control {target:#010x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
