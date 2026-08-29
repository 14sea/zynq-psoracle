#!/usr/bin/env python3
"""The host's side of the PL: expected truth tables, predicted scores, the AXI map.

Pure; nothing here touches a board. Every constant is read from an imported, hashed
artifact: the six evolvable LUTs' sites/targets/base INITs and the frozen vector order from
fabricmap's `carrier_constants.json` (the same file the scorer RTL is generated from), the
INIT-bit map from `local_map.json`. The LOC→map-key rule is the 7-series one: a CLBLL_L
tile holds SLICEL_X0 (even slice X) and SLICEL_X1; a CLBLM_L tile holds SLICEM_X0 (even)
and SLICEL_X1 (odd).

`expected_tables(candidate)` is what the gate signer signs and what the PL must exhibit;
`predict_scores(tables, holdout)` is the host's evidence-only prediction of the scorer's
counters (`score_record.host_prediction`); it never substitutes for the PL's own count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from validators import lut_table as lt  # noqa: E402

FM = R / "imported/fabricmap"
CONSTANTS = FM / "vivado/carrier/generated/carrier_constants.json"
LOCAL_MAP = FM / "gate_runs/claimb_round1_carrier_2026_08_13_erratum006/local_map.json"

# ---------------------------------------------------------------- the AXI window (L1 map)
AXI_BASE = 0x43C00000
CTRL, STATUS, FAULT = 0x2000, 0x2004, 0x2008
SCORES = tuple(0x2010 + 4 * i for i in range(6))
HEARTBEAT, NONCE_LO, NONCE_HI = 0x2028, 0x202C, 0x2030
PAYLOAD = tuple(0x2100 + 4 * i for i in range(20))
TAG = tuple(0x2150 + 4 * i for i in range(4))
HW_COMMIT = tuple(0x2200 + 4 * i for i in range(8))
READOUT = tuple(0x2240 + 4 * i for i in range(12))
READABLE = frozenset({STATUS, FAULT, HEARTBEAT, NONCE_LO, NONCE_HI} | set(SCORES) | set(HW_COMMIT) | set(READOUT))
WRITABLE = frozenset({CTRL} | set(PAYLOAD) | set(TAG))
ARM_STROBE, MODE_HOLDOUT = 1 << 6, 1 << 7
ST = {"gate_busy": 0, "fault": 1, "cfg_valid_hw": 2, "scorer_busy": 3, "scorer_done": 4, "scorer_armed": 5,
      "tag_ok": 6, "recovery_required": 7, "alive": 8, "sweep_done": 9, "tables_match": 10}
ST_RESERVED = 0xF8000000
F_ARM_AUTH, F_ARM_TABLE = 13, 15


def axi(off: int) -> int:
    return AXI_BASE + off


# ---------------------------------------------------------------- the LUTs
def _key(site: str, bel: str) -> str:
    x = int(site[len("SLICE_X"):site.index("Y")])
    tile_x = x // 2
    tile = "CLBLL_L" if tile_x == 1 else "CLBLM_L" if tile_x == 4 else None
    if tile is None:
        raise ValueError(f"{site}: not one of the two target columns (CLBLL_L_X2, CLBLM_L_X6)")
    slice_kind = "SLICEL" if tile == "CLBLL_L" or x % 2 else "SLICEM"
    return f"{tile}.{slice_kind}_X{x % 2}.{bel[0]}LUT"


def load_constants(path: Path = CONSTANTS) -> dict:
    c = json.loads(path.read_text())
    lm = json.loads(LOCAL_MAP.read_text())
    luts = []
    for i, l in enumerate(c["luts"]):
        key = _key(l["site"], l["bel"])
        pos = lt.mapped_positions(lm, key)
        if lt.mutable_mask(pos) != l["mutable_mask"]:
            raise ValueError(f"LUT {i} {key}: map mask {lt.mutable_mask(pos):#x} != constants {l['mutable_mask']:#x}")
        luts.append({"index": i, "site": l["site"], "bel": l["bel"], "key": key, "target": l["target"],
                     "base_init": l["base_init"], "positions": pos})
    return {"order": c["order"], "train_count": c["train_count"], "holdout_count": c["holdout_count"], "luts": luts}


def expected_tables(candidate_frames: dict[int, list[int]], consts: dict) -> list[int]:
    return [lt.truth_table(candidate_frames, l["positions"], l["base_init"]) for l in consts["luts"]]


def predict_scores(tables: list[int], consts: dict, holdout: bool = False) -> list[int]:
    """The scorer's count: over the train slice (or the holdout slice only), a LUT scores 1
    per vector whose output equals the target's — output = table bit `vector` (I0 = bit 0)."""
    n, k = consts["train_count"], consts["holdout_count"]
    vecs = consts["order"][n:n + k] if holdout else consts["order"][:n]
    return [sum(1 for v in vecs if (t >> v) & 1 == (l["target"] >> v) & 1)
            for t, l in zip(tables, consts["luts"])]


def readout_words_to_tables(words: list[int]) -> list[int]:
    """FUNCTIONAL_READOUT: table t at words 2t (hi), 2t+1 (lo)."""
    return [(words[2 * t] << 32) | words[2 * t + 1] for t in range(6)]


def commit_words_to_hex(words: list[int]) -> str:
    return "".join(f"{w:08x}" for w in words)
