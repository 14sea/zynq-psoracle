#!/usr/bin/env python3
"""P1 — the one-frame PCAP *write* plan, with its guards. Host-only; no board action.

`docs/p1_spec.md` §4 is the contract this implements. The shape of the write stream is the
one `zynq-xpart` proved on ICAPE2 (`hwicap-make-framewrite.py`: dummy×8, sync, RCRC,
IDCODE, WCFG, FAR, FDRI type-1/type-2, 202 words, DESYNC — **no GRESTORE, no GTS, no
SHUTDOWN, no START**), delivered here over PCAP in SelectMAP word order, with one change:
**no CRC-register write** (§4c). The DMA tuple is what AMD's `XDcfg_Transfer()` issues for
`XDCFG_NON_SECURE_PCAP_WRITE` and what its examples pass: `(SRC|1, 0xFFFFFFFF, N, 0)` —
the non-active endpoint's length is 0, the same rule §8a pinned for the readback command.

What the guards refuse, before any byte is sent:

* any configuration command other than RCRC, WCFG, DESYNC; any register write other than
  CMD, IDCODE, FAR, FDRI; a FAR outside the single pinned target; an FDRI count other than
  202; any word in the frame that is not the base frame's word except word 51 (within the
  certified INIT mask) and word 50 (which must equal the recomputed ECC); a pad frame that
  is not the base's next frame verbatim; a CRC-register write; a second FDRI; a stream that
  does not end in DESYNC;
* a DMA tuple other than the pinned one; an address outside the P1 allowlist; a schedule
  other than clear → verify → four registers → wait.

Read side: P1 reads with `pcap_probe_plan.build_plan()` unchanged — the P0 plan whose
guards and board result stand.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bitstream_frames as bf  # noqa: E402
import frame_ecc as fe  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402

TOOL_VERSION = "pcap_write_plan.py/0.1.0"

# ------------------------------------------------------------------ pinned target
CARRIER_BIT = REPO_ROOT / "gate_runs/claimb_round1_carrier_2026_08_13_erratum006/carrier.bit"
TARGET_FAR = 0x00400A20            # CLBLL_L_X2Y25, minor 32 — LUT0 (SLICE_X2Y25 A6LUT)
PAD_FAR = TARGET_FAR + 1           # the FDRI auto-increment writes the pad here: base verbatim
INIT_WORD = 51                     # every certified LUT0 INIT bit in this frame is in word 51
ECC_WORD = fe.ECC_WORD             # 50
# The 14 INIT positions of LUT0 that the certified local map places in this frame's word 51
# (zynq-fabricmap gate_runs/claimb_round1_carrier_2026_08_11/local_map.json, by_lut
# CLBLL_L.SLICEL_X0.ALUT): bits 15,14,13,12,11,10,9,8,7,4,3,2,1,0.
INIT_MASK = 0xFF9F
# Two known-answer patterns inside that mask, disjoint, both non-zero, Hamming 14 apart.
PATTERN_A = 0xA50F
PATTERN_B = 0x5A90
PATTERNS = {"A": PATTERN_A, "B": PATTERN_B}

# ------------------------------------------------------------------ stream words
DUMMY, SYNC, NOOP = 0xFFFFFFFF, 0xAA995566, 0x20000000
IDCODE_XC7Z010 = 0x03722093
REG_CMD, REG_FAR, REG_FDRI, REG_IDCODE, REG_CRC = 4, 1, 2, 12, 0
CMD_RCRC, CMD_WCFG, CMD_DESYNC = 7, 1, 13
ALLOWED_CMDS = {CMD_RCRC, CMD_WCFG, CMD_DESYNC}
ALLOWED_WRITE_REGS = {REG_CMD, REG_FAR, REG_FDRI, REG_IDCODE}
FORBIDDEN_CMD_NAMES = {0xB: "SHUTDOWN", 0x5: "START", 0xA: "GRESTORE", 0xC: "GCAPTURE",
                       0x3: "GHIGH", 0xF: "IPROG", 0x8: "AGHIGH", 0x0: "NULL", 0x6: "RCAP",
                       0x9: "SWITCH", 0xD + 1: "BSPI_READ"}
FRAME_WORDS = pp.FRAME_WORDS
FDRI_WORDS = 2 * FRAME_WORDS       # target + pad, as the ICAP-proven sequence did

# ------------------------------------------------------------------ DMA / buffers
WR_BUF = 0x10400000                # 1 MiB aligned, distinct from CMD_BUF / DST_BUF
PCAP = pp.PCAP_ENDPOINT
FDRI_DATA_OFFSET = 8 + 1 + 1 + 2 + 2 + 2 + 2 + 1 + 2 + 1 + 1                     # 23
STREAM_WORDS = FDRI_DATA_OFFSET + FDRI_WORDS + 2 + 4                              # 231
ALLOWED_REGIONS = (
    (pp.REG["INT_STS"], 4), (pp.REG["CTRL"], 4), (pp.REG["MCTRL"], 4),
    (pp.REG["DMA_SRC_ADDR"], 4), (pp.REG["DMA_DEST_ADDR"], 4),
    (pp.REG["DMA_SRC_LEN"], 4), (pp.REG["DMA_DEST_LEN"], 4),
    (WR_BUF, 4 * STREAM_WORDS),
)
LEGAL_WRITE_TRANSACTION = (WR_BUF | pp.DMA_HOLD_TAG, PCAP, STREAM_WORDS, 0)


def t1(write: bool, reg: int, count: int) -> int:
    return (1 << 29) | ((2 if write else 1) << 27) | (reg << 13) | count


def t2_write(count: int) -> int:
    return (2 << 29) | (2 << 27) | count


# ------------------------------------------------------------------ base frames


def base_frames(bit_path: Path = CARRIER_BIT) -> dict[int, list[int]]:
    frames = bf.parse_frames(bit_path)["frames"]
    return {TARGET_FAR: list(frames[TARGET_FAR]), PAD_FAR: list(frames[PAD_FAR])}


def target_frame(pattern: int, base: list[int]) -> list[int]:
    """The base frame with word 51's INIT field set to `pattern` and the ECC recomputed."""
    if pattern & ~INIT_MASK:
        raise ValueError(f"pattern {pattern:#06x} has bits outside the certified mask "
                         f"{INIT_MASK:#06x}")
    if pattern == 0:
        raise ValueError("a zero pattern is indistinguishable from the blank base")
    out = list(base)
    out[INIT_WORD] = (out[INIT_WORD] & ~INIT_MASK) | pattern
    return fe.update_ecc(out)


# ------------------------------------------------------------------ the stream


def write_stream(far: int, frame: list[int], pad: list[int]) -> list[int]:
    if len(frame) != FRAME_WORDS or len(pad) != FRAME_WORDS:
        raise ValueError("frame and pad must be 101 words each")
    return ([DUMMY] * 8 + [SYNC, NOOP,
            t1(True, REG_CMD, 1), CMD_RCRC, NOOP, NOOP,
            t1(True, REG_IDCODE, 1), IDCODE_XC7Z010,
            t1(True, REG_CMD, 1), CMD_WCFG, NOOP,
            t1(True, REG_FAR, 1), far,
            t1(True, REG_FDRI, 0), t2_write(FDRI_WORDS)]
            + list(frame) + list(pad)
            + [t1(True, REG_CMD, 1), CMD_DESYNC, NOOP, NOOP, NOOP, NOOP])


def validate_write_stream(words: list[int], base: dict[int, list[int]]) -> dict:
    """Literal walk of the stream. Returns what it found; raises on anything else."""
    if len(words) != STREAM_WORDS:
        raise ValueError(f"stream has {len(words)} words, pinned {STREAM_WORDS}")
    if words[:8] != [DUMMY] * 8 or words[8] != SYNC:
        raise ValueError("stream must open with eight dummies and the sync word")
    i, seen = 9, {"far": None, "fdri": 0, "cmds": [], "regs": []}
    while i < len(words):
        w = words[i]
        if w == NOOP:
            i += 1
            continue
        hdr = w >> 29
        if hdr != 1:
            raise ValueError(f"unexpected word {w:#010x} at {i}: not a type-1 header")
        op, reg, count = (w >> 27) & 3, (w >> 13) & 0x3FFF, w & 0x7FF
        if op != 2:
            raise ValueError(f"type-1 opcode {op} at {i}: only writes are permitted")
        if reg not in ALLOWED_WRITE_REGS:
            name = "CRC" if reg == REG_CRC else f"reg {reg}"
            raise ValueError(f"write to {name} at {i} is not permitted")
        seen["regs"].append(reg)
        if reg == REG_CMD:
            cmd = words[i + 1]
            if cmd not in ALLOWED_CMDS:
                raise ValueError(f"configuration command {cmd:#x} "
                                 f"({FORBIDDEN_CMD_NAMES.get(cmd, 'unknown')}) is forbidden")
            seen["cmds"].append(cmd)
            i += 2
        elif reg == REG_IDCODE:
            if words[i + 1] != IDCODE_XC7Z010:
                raise ValueError("IDCODE write is not the XC7Z010's")
            i += 2
        elif reg == REG_FAR:
            far = words[i + 1]
            if far != TARGET_FAR:
                raise ValueError(f"FAR {far:#010x} is not the pinned target {TARGET_FAR:#010x}")
            seen["far"] = far
            i += 2
        else:  # FDRI
            if count != 0 or (words[i + 1] >> 29) != 2:
                raise ValueError("FDRI must be a type-1 header of count 0 followed by type-2")
            n = words[i + 1] & 0x07FFFFFF
            if n != FDRI_WORDS:
                raise ValueError(f"FDRI count {n} != {FDRI_WORDS}")
            if seen["far"] is None:
                raise ValueError("FDRI before FAR")
            seen["fdri"] += 1
            data = words[i + 2:i + 2 + n]
            _check_frames(data[:FRAME_WORDS], data[FRAME_WORDS:], base)
            seen["frame"], seen["pad"] = data[:FRAME_WORDS], data[FRAME_WORDS:]
            i += 2 + n
    if seen["cmds"] != [CMD_RCRC, CMD_WCFG, CMD_DESYNC]:
        raise ValueError(f"command order is {seen['cmds']}, pinned [RCRC, WCFG, DESYNC]")
    if seen["fdri"] != 1:
        raise ValueError(f"{seen['fdri']} FDRI bursts; exactly one is pinned")
    if words[-6:-4] != [t1(True, REG_CMD, 1), CMD_DESYNC] or words[-4:] != [NOOP] * 4:
        raise ValueError("stream must end with DESYNC and four NOOPs")
    return seen


def _check_frames(frame: list[int], pad: list[int], base: dict[int, list[int]]) -> int:
    b = base[TARGET_FAR]
    for k, (w, bw) in enumerate(zip(frame, b)):
        if k == INIT_WORD:
            if (w & ~INIT_MASK) != (bw & ~INIT_MASK):
                raise ValueError("word 51 changes bits outside the certified INIT mask")
            if (w & INIT_MASK) not in PATTERNS.values():
                raise ValueError(f"word 51 INIT field {w & INIT_MASK:#06x} is not a pinned pattern")
        elif k == ECC_WORD:
            expect = (bw & fe.ECC_KEEP) | (fe.calculate_ecc(frame) & fe.ECC_MASK)
            if w != expect:
                raise ValueError(f"word 50 {w:#010x} is not the recomputed ECC {expect:#010x}")
        elif w != bw:
            raise ValueError(f"frame word {k} differs from the base: content-bit-only is the rule")
    if pad != base[PAD_FAR]:
        raise ValueError("pad frame is not the base's next frame verbatim")
    return frame[INIT_WORD] & INIT_MASK


# ------------------------------------------------------------------ the plan


def build_write_plan(pattern_name: str, base: dict[int, list[int]] | None = None) -> dict:
    if pattern_name not in PATTERNS:
        raise ValueError(f"pattern must be one of {sorted(PATTERNS)}")
    base = base or base_frames()
    frame = target_frame(PATTERNS[pattern_name], base[TARGET_FAR])
    stream = write_stream(TARGET_FAR, frame, base[PAD_FAR])
    validate_write_stream(stream, base)

    script: list[dict] = [
        {"step": "ctrl-before", "cmd": f"md.l {pp.REG['CTRL']:#010x} 1",
         "why": "CTRL (incl. PCAP_RATE_EN bit 25) is recorded before the write and must be "
                "unchanged after it; §5e: read, never written", "addresses": [pp.REG["CTRL"]]}]
    for i, word in enumerate(stream):
        script.append({"step": "stream-word", "cmd": f"mw.l {WR_BUF + 4 * i:#010x} {word:#010x} 1",
                       "why": f"write stream word {i}", "addresses": [WR_BUF + 4 * i]})
    script.append({"step": "clear-write", "cmd": f"mw.l {pp.REG['INT_STS']:#010x} {pp.INT_STS_CLEAR_MASK:#010x} 1",
                   "why": "INT_STS is write-to-clear; PCFG_DONE is excluded from the mask",
                   "addresses": [pp.REG["INT_STS"]]})
    script.append({"step": "clear-verify-write", "cmd": f"md.l {pp.REG['INT_STS']:#010x} 1",
                   "why": f"(INT_STS & {pp.INT_STS_CLEAR_MASK:#010x}) must read 0, or STOP",
                   "addresses": [pp.REG["INT_STS"]]})
    src, dst, sl, dl = LEGAL_WRITE_TRANSACTION
    for reg, val in (("DMA_SRC_ADDR", src), ("DMA_DEST_ADDR", dst),
                     ("DMA_SRC_LEN", sl), ("DMA_DEST_LEN", dl)):
        script.append({"step": "dma-write", "cmd": f"mw.l {pp.REG[reg]:#010x} {val:#010x} 1",
                       "why": "queues the command" if reg == "DMA_DEST_LEN" else "UG585 N3 order",
                       "addresses": [pp.REG[reg]]})
    script.append({"step": "wait-write", "cmd": f"md.l {pp.REG['INT_STS']:#010x} 1",
                   "why": f"completion is D_P_DONE {pp.INT_STS_D_P_DONE:#x}; errors {pp.INT_STS_ERROR_MASK:#010x}",
                   "addresses": [pp.REG["INT_STS"]]})
    script.append({"step": "ctrl-after", "cmd": f"md.l {pp.REG['CTRL']:#010x} 1",
                   "why": "must equal ctrl-before, or STOP (non-discriminating)",
                   "addresses": [pp.REG["CTRL"]]})
    plan = {
        "schema": "zynq-psmap/pcap_write_plan/1",
        "board_action": "NONE - this is a plan, not an execution",
        "pattern": pattern_name, "pattern_value": PATTERNS[pattern_name],
        "target_far": TARGET_FAR, "pad_far": PAD_FAR, "init_word": INIT_WORD, "init_mask": INIT_MASK,
        "stream": stream, "stream_words": len(stream),
        "frame_after": frame, "frame_after_sha256": pp_sha(frame),
        "pad_after": base[PAD_FAR],
        "dma_transaction": list(LEGAL_WRITE_TRANSACTION),
        "int_sts_error_mask": pp.INT_STS_ERROR_MASK, "int_sts_clear_mask": pp.INT_STS_CLEAR_MASK,
        "timeout_s": pp.TIMEOUT_S, "timeout_basis": "derived, not measured",
        "uboot_script": script,
    }
    check_write_plan(plan, base)
    return plan


def pp_sha(frame: list[int]) -> str:
    import hashlib, struct
    return hashlib.sha256(struct.pack(f">{len(frame)}I", *frame)).hexdigest()


def check_write_plan(plan: dict, base: dict[int, list[int]] | None = None) -> None:
    """Adjudicate the commands, never the metadata — the same rule as the read planner."""
    base = base or base_frames()
    stream_by_addr: dict[int, int] = {}
    dma: list[int] = []
    tokens: list = []
    for step in plan["uboot_script"]:
        form, start, span = pp.parse_command(step["cmd"])
        end = start + span
        if not any(b <= start and end <= b + n for b, n in ALLOWED_REGIONS):
            raise ValueError(f"{step['cmd']!r} is outside the P1 allowlist")
        parts = step["cmd"].split()
        if form == "mw.l":
            value, count = int(parts[2], 0), int(parts[3], 0)
            if WR_BUF <= start < WR_BUF + 4 * STREAM_WORDS:
                for k in range(count):
                    if start + 4 * k in stream_by_addr:
                        raise ValueError("a stream word is written twice")
                    stream_by_addr[start + 4 * k] = value
                if tokens and tokens[-1][0] == "STREAM":
                    tokens[-1] = ("STREAM", tokens[-1][1] + count)
                else:
                    tokens.append(("STREAM", count))
            elif start == pp.REG["INT_STS"]:
                if value != pp.INT_STS_CLEAR_MASK:
                    raise ValueError("INT_STS may only be written with the pinned clear mask")
                tokens.append("CLEAR")
            elif start in pp.DMA_REGISTER_ORDER:
                dma.append(value)
                tokens.append(pp.DMA_TOKEN[start])
            else:
                raise ValueError(f"unscheduled write {step['cmd']!r}")
        elif form == "md.l":
            if start == pp.REG["INT_STS"] and span == 4:
                tokens.append("READ_INT_STS")
            elif start == pp.REG["CTRL"] and span == 4:
                tokens.append("READ_CTRL")
            else:
                raise ValueError(f"unscheduled read {step['cmd']!r}")
        else:
            raise ValueError(f"{form} is not part of a write plan")
    words = [stream_by_addr.get(WR_BUF + 4 * i) for i in range(STREAM_WORDS)]
    if any(w is None for w in words):
        raise ValueError("the stream in the buffer has a gap")
    validate_write_stream(words, base)
    if tuple(dma) != LEGAL_WRITE_TRANSACTION:
        raise ValueError(f"DMA tuple {dma} is not the pinned write transaction")
    expected = ["READ_CTRL", ("STREAM", STREAM_WORDS), "CLEAR", "READ_INT_STS", "DMA_SRC_ADDR",
                "DMA_DEST_ADDR", "DMA_SRC_LEN", "DMA_DEST_LEN", "READ_INT_STS", "READ_CTRL"]
    if tokens != expected:
        raise ValueError(f"schedule {tokens} is not the pinned write schedule")
    if words != plan["stream"] or plan["frame_after"] != words[FDRI_DATA_OFFSET:FDRI_DATA_OFFSET + FRAME_WORDS]:
        raise ValueError("plan metadata disagrees with the commands")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pattern", choices=sorted(PATTERNS), default="A")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    plan = build_write_plan(a.pattern)
    if a.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"pattern {a.pattern} = {plan['pattern_value']:#06x} at FAR {TARGET_FAR:#010x} word {INIT_WORD}")
        print(f"stream words: {plan['stream_words']}   DMA: {plan['dma_transaction']}")
        print(f"frame after write sha256: {plan['frame_after_sha256']}")
        print(f"{len(plan['uboot_script'])} U-Boot steps, no board contact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
