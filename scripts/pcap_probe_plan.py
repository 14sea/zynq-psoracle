#!/usr/bin/env python3
"""Host-only planner for the PCAP readback probe.  It does NOT touch a board.

What it produces is a *plan*: the readback command words, the devcfg DMA register
programming, and the U-Boot command script that would carry them out.  Nothing here opens
a serial port, and there is no code path that does.  The probe stages S1-S3 are not
authorised; this exists so the sequence `docs/s0_derived_sequence.md` pins can be checked
by machine rather than by reading.

Two properties, both from that document:

* `--dma-order` defaults to the **pinned** reading.  S0 §8a is resolved -- a readback is
  two unidirectional DMA commands, which is what AMD's own `XDcfg_PcapReadback()` issues --
  and the bidirectional reading is retained only as the named alternative for a NEW run.
  While §8a was open there was deliberately no default; that was right then and is wrong
  now.
* every address is checked against a fixed allowlist, and any `FDRI` write is refused
  before a plan is produced at all.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# ---------------------------------------------------------------- devcfg (UG585, §1)

DEVCFG_BASE = 0xF8007000
REG = {
    "CTRL":          DEVCFG_BASE + 0x000,
    "INT_STS":       DEVCFG_BASE + 0x00C,
    "STATUS":        DEVCFG_BASE + 0x014,
    "DMA_SRC_ADDR":  DEVCFG_BASE + 0x018,
    "DMA_DEST_ADDR": DEVCFG_BASE + 0x01C,
    "DMA_SRC_LEN":   DEVCFG_BASE + 0x020,
    "DMA_DEST_LEN":  DEVCFG_BASE + 0x024,
    "MCTRL":         DEVCFG_BASE + 0x080,
}
# MCTRL[4] PCAP_LPBK (XDCFG_MCTRL_PCAP_LPBK_MASK = 0x10).  With loopback enabled the data
# path is not PL frame readback.  The sources do not establish the exact outcome for this
# probe's unequal command/read lengths.  AMD's readback path clears the bit every time;
# §5e forbids adjusting, so this probe READS it and refuses to proceed.  The reset value is
# 0 and that does NOT substitute for the live read: it is writable mode state, and anything
# earlier in the boot may have set it.
MCTRL_PCAP_LPBK = 0x00000010
# UG585: "programmed in the exact sequence as described"; DEST_LEN queues the command.
DMA_WRITE_ORDER = ("DMA_SRC_ADDR", "DMA_DEST_ADDR", "DMA_SRC_LEN", "DMA_DEST_LEN")

DMA_REGISTER_ORDER = tuple(DEVCFG_BASE + o for o in (0x018, 0x01C, 0x020, 0x024))

PCAP_ENDPOINT = 0xFFFFFFFF          # UG585: "Destination Address: 0xFFFF_FFFF"
DMA_HOLD_TAG = 0x1                  # SRC/DST[1:0] = 2'b01 -> hold DONE until PCAP done
DMA_ALIGN = 64                      # UG585: all DMA transactions 64-byte aligned

CTRL_MASK = 0x0C000000              # PCAP_PR (27) | PCAP_MODE (26)
CTRL_REQUIRED = 0x0C000000
CTRL_HISTORICAL_17A6 = 0x4E00E07F   # recorded, never required

INT_STS_PCFG_DONE = 1 << 2          # readback forbidden until this asserts
INT_STS_D_P_DONE = 1 << 12          # completion: DMA *and* PCAP
INT_STS_DMA_DONE = 1 << 13          # NOT sufficient on its own
INT_STS_ERROR_MASK = (
    (1 << 23) | (1 << 22) | (1 << 21) | (1 << 20)   # AXI WTO/WERR/RTO/RERR
    | (1 << 18)                                     # RX_FIFO_OV
    | (1 << 15) | (1 << 14)                         # DMA_CMD_ERR / DMA_Q_OV
    | (1 << 11)                                     # P2D_LEN_ERR
    | (1 << 6)                                      # PCFG_HMAC_ERR
)
# INT_STS bits are write-to-clear.  A residual D_P_DONE from an earlier transfer reads
# exactly like a completion of this one, so every read clears first and verifies the
# clear landed.  PCFG_DONE is deliberately NOT cleared: it is the evidence that the PL
# holds the carrier, and UG585 forbids a readback without it.
INT_STS_CLEAR_MASK = INT_STS_ERROR_MASK | INT_STS_D_P_DONE | INT_STS_DMA_DONE
assert not INT_STS_CLEAR_MASK & INT_STS_PCFG_DONE

# UG470 step 14.  START (step 12) is NOT issued because SHUTDOWN was not, and spec §5c
# forbids startup transitions outright.
CMD_DESYNC = 0x0000000D
CMD_SHUTDOWN = 0x0000000B
CMD_RCRC = 0x00000007

# ---------------------------------------------------------------- buffers (S0 §6)

CMD_BUF = 0x10200000
DST_BUF = 0x10300000
FRAME_WORDS = 101
READBACK_WORDS = 2 * FRAME_WORDS    # dummy frame + target frame
TIMEOUT_S = 1.0                     # derived, not measured

ADDRESS_ALLOWLIST = frozenset(REG.values()) | {CMD_BUF, DST_BUF}
# The command buffer is written one word at a time, so the allowlist is over *regions*:
# a bare set of base addresses cannot express "CMD_BUF + 4*i".

# ---------------------------------------------------------------- packet headers

TYPE1, TYPE2 = 0b001, 0b010
OP_READ, OP_WRITE = 0b01, 0b10
R_FAR, R_FDRO, R_CMD = 1, 3, 4
CMD_RCFG = 0x00000004
NOOP = 0x20000000
DUMMY = 0xFFFFFFFF
SYNC = 0xAA995566
FLUSH_NOOPS = 32

# A configuration write is what this probe must never emit.
FORBIDDEN_REGISTERS = {2: "FDRI"}

# Sized to the buffers themselves, not rounded up.  A region wider than the buffer is
# slack an overrun can hide in: with DST_BUF given 256 words for a 202-word buffer, a
# write starting at the last real word and running two words past the end still landed
# inside the "allowed" region.
CMD_STREAM_WORDS = 11 + FLUSH_NOOPS          # the readback stream; cleanup is shorter
ALLOWED_REGIONS: tuple[tuple[int, int], ...] = tuple(
    [(a, 4) for a in sorted(REG.values())]
    + [(CMD_BUF, 4 * CMD_STREAM_WORDS), (DST_BUF, 4 * READBACK_WORDS)])


def type1(op: int, register: int, count: int) -> int:
    if register in FORBIDDEN_REGISTERS and op == OP_WRITE:
        raise ValueError(
            f"refusing to build a write to {FORBIDDEN_REGISTERS[register]}: "
            "the probe writes zero configuration frames")
    if not 0 <= count < (1 << 11):
        raise ValueError(f"type-1 count out of range: {count}")
    return (TYPE1 << 29) | (op << 27) | (register << 13) | count


def type2(op: int, count: int) -> int:
    if not 0 <= count < (1 << 27):
        raise ValueError(f"type-2 count out of range: {count}")
    return (TYPE2 << 29) | (op << 27) | count


def cleanup_commands() -> list[int]:
    """UG470 steps 11 and 14, minus every step that depends on SHUTDOWN.

    The vendor procedure ends NOOP, START, RCRC, DESYNC, NOOPs.  START is a startup
    transition, forbidden by spec §5c and meaningless without the SHUTDOWN this probe
    does not issue; RCRC recomputes a CRC over a device that was never shut down.  What
    remains, and what the engine does need, is to be left desynchronised.
    """
    return [NOOP, type1(OP_WRITE, R_CMD, 1), CMD_DESYNC] + [NOOP] * 2


def readback_commands(far: int, words: int = READBACK_WORDS) -> list[int]:
    """UG470 Table 6-2 order, in SelectMAP order.  No br8: that is an ICAPE2 pin property.

    RCFG precedes FAR.  An earlier version emitted FAR first, copying the order measured
    on the HWICAP path, while the documents around it claimed the sequence was discharged
    against UG470 -- which orders it the other way.  The vendor order governs; the
    divergence is recorded in s0_derived_sequence.md §3c rather than quietly resolved.
    """
    if not 0 <= far <= 0xFFFFFFFF:
        raise ValueError(f"FAR out of range: {far:#x}")
    return [
        DUMMY, SYNC, NOOP, NOOP,
        type1(OP_WRITE, R_CMD, 1), CMD_RCFG,     # UG470 step 6: RCFG first,
        NOOP,                                    #   then one NOOP,
        type1(OP_WRITE, R_FAR, 1), far,          # UG470 step 7: then the FAR
        type1(OP_READ, R_FDRO, 0),               # step 8
        type2(OP_READ, words),
    ] + [NOOP] * FLUSH_NOOPS


# ---------------------------------------------------------------- DMA plan

def _tagged(addr: int) -> int:
    if addr % DMA_ALIGN:
        raise ValueError(f"{addr:#010x} is not {DMA_ALIGN}-byte aligned (UG585 N2)")
    return addr | DMA_HOLD_TAG


def dma_commands(order: str, cmd_words: int, read_words: int) -> list[dict]:
    """S0 §8a is resolved; `order` selects the pinned reading or the named alternative."""
    if order == "two-unidirectional":
        return [
            {"name": "command", "DMA_SRC_ADDR": _tagged(CMD_BUF),
             "DMA_DEST_ADDR": PCAP_ENDPOINT,
             "DMA_SRC_LEN": cmd_words, "DMA_DEST_LEN": 0},
            {"name": "readback", "DMA_SRC_ADDR": PCAP_ENDPOINT,
             "DMA_DEST_ADDR": _tagged(DST_BUF),
             "DMA_SRC_LEN": 0, "DMA_DEST_LEN": read_words},
        ]
    if order == "one-bidirectional":
        return [
            {"name": "command+readback", "DMA_SRC_ADDR": _tagged(CMD_BUF),
             "DMA_DEST_ADDR": _tagged(DST_BUF),
             "DMA_SRC_LEN": cmd_words, "DMA_DEST_LEN": read_words},
        ]
    raise ValueError(f"unknown --dma-order {order!r}")


# A CLOSED grammar.  Three command forms are permitted and everything else is refused.
#
# Two earlier versions leaked.  The first read only the metadata beside each command.  The
# second parsed the command but took the start address alone and treated an unrecognised
# command as touching nothing, so `mw.l 0x103003fc 0xdeadbeef 2` overran the buffer and
# `mw.b 0x43c00000 0xff 1` was off the allowlist entirely -- both passed.  An allowlist
# whose parser fails open is not an allowlist, so an unparseable command is now an error.
_GRAMMAR = (
    ("dcache-off", re.compile(r"^dcache off$")),
    ("md.l", re.compile(r"^md\.l (0x[0-9a-f]+) (0x[0-9a-f]+|\d+)$")),
    ("mw.l", re.compile(r"^mw\.l (0x[0-9a-f]+) (?:0x[0-9a-f]+|\d+) (0x[0-9a-f]+|\d+)$")),
)


def parse_command(cmd: str) -> tuple[str, int, int]:
    """(form, start, span_bytes).  Raises on anything the grammar does not cover."""
    s = cmd.strip()
    for name, rx in _GRAMMAR:
        m = rx.match(s)
        if not m:
            continue
        if name == "dcache-off":
            return name, 0, 0
        start = int(m.group(1), 16)
        count = int(m.group(2), 0)
        if count < 1:
            raise ValueError(f"word count must be >= 1: {cmd!r}")
        return name, start, 4 * count
    raise ValueError(f"command not in the permitted grammar: {cmd!r}")


# ------------------------------------------------------------ transaction policy
#
# Field-by-field legality is not enough, and review made that concrete three times.
# Knowing each value is individually permitted says nothing about whether the values
# COMBINE into a legal operation: source and destination can be swapped so a readback
# overwrites the command buffer, a length legal on its own can overrun the buffer it is
# paired with, and a word sequence can pass a packet-by-packet walk while being
# structurally nothing.  These checks adjudicate whole transactions and exact streams,
# and the per-value sets are gone rather than extended.

READ_ONLY_REGISTERS = {REG["CTRL"], REG["STATUS"], REG["MCTRL"]}
CLEANUP_WORDS = 5

# S0 §8a, resolved 2026-08-28: UG585 contradicts itself, and AMD's own readback API issues
# two unidirectional transfers.  The other reading is retained as the alternative a NEW run
# may adopt after ANY stop -- not only after a particular error bit.
PINNED_DMA_ORDER = "two-unidirectional"
ALTERNATIVE_DMA_ORDER = "one-bidirectional"
# Named for what they ARE, not for what they would prove.  An earlier version called these
# "*_PINNED_WRONG" and reported them as the observation that would reveal a wrong pin;
# UG585's INT_STS table assigns each bit a general meaning and establishes no such causal
# mapping.  They are generic error stops a wrong pin MIGHT surface as, among others.
CANDIDATE_DIAGNOSIS_BITS = {"DMA_CMD_ERR": 1 << 15, "P2D_LEN_ERR": 1 << 11}

# Every DMA transaction this probe may issue, as a complete tuple in the normative write
# order (SRC_ADDR, DEST_ADDR, SRC_LEN, DEST_LEN).  Nothing else is a legal transaction.
# The length of the NON-ACTIVE endpoint is 0, not a mirror of the active one.  That is
# what AMD's own driver does -- XDcfg_PcapReadback() issues (Source, INVALID, SrcLen, 0)
# then (INVALID, Dest, 0, DestLen) -- and an earlier version of this file mirrored the
# lengths by generalising from UG585's *configuration* example, which is a write and does
# not transfer to readback.  The result refused the vendor's own tuples and permitted
# tuples no vendor implementation issues.
LEGAL_DMA_TRANSACTIONS = {
    "command":       (CMD_BUF | DMA_HOLD_TAG, PCAP_ENDPOINT, CMD_STREAM_WORDS, 0),
    "readback":      (PCAP_ENDPOINT, DST_BUF | DMA_HOLD_TAG, 0, READBACK_WORDS),
    "cleanup":       (CMD_BUF | DMA_HOLD_TAG, PCAP_ENDPOINT, CLEANUP_WORDS, 0),
    # The §8a alternative remains constructible, but is not adopted by the vendor
    # readback API.  That supports the pinned transaction shape; it does not establish
    # that the silicon must reject this alternative tuple.
    "bidirectional": (CMD_BUF | DMA_HOLD_TAG, DST_BUF | DMA_HOLD_TAG,
                      CMD_STREAM_WORDS, READBACK_WORDS),
}


def _check_register_write(addr: int, value: int) -> None:
    """Policies that are genuinely per-register.  DMA registers are judged as a tuple."""
    if addr in READ_ONLY_REGISTERS:
        raise ValueError(
            f"write of {value:#010x} to {addr:#010x}: this register is read-only here "
            f"(§5e: CTRL is checked, not adjusted)")
    if addr == REG["INT_STS"] and value != INT_STS_CLEAR_MASK:
        raise ValueError(
            f"INT_STS may only be written with the exact clear mask "
            f"{INT_STS_CLEAR_MASK:#010x}, not {value:#010x}")


def dma_transactions(plan: dict) -> list[tuple[int, int, int, int]]:
    """Rebuild each DMA command from its four register writes, in the normative order.

    The DMA_DEST_LEN write is what queues a command, so it closes a tuple.  A register
    written out of order, or a tuple left open at the end, means there is no transaction
    to adjudicate -- which is itself an error rather than something to skip.
    """
    txs: list[tuple[int, int, int, int]] = []
    pending: list[int] = []
    for step in plan["uboot_script"]:
        form, start, _ = parse_command(step["cmd"])
        if form != "mw.l" or start not in DMA_REGISTER_ORDER:
            continue
        want = DMA_WRITE_ORDER[len(pending)]
        if start != REG[want]:
            raise ValueError(
                f"DMA registers written out of order: expected {want} "
                f"({REG[want]:#010x}), got {start:#010x}")
        pending.append(int(step["cmd"].split()[2], 0))
        if len(pending) == 4:
            txs.append(tuple(pending))
            pending = []
    if pending:
        raise ValueError("an incomplete DMA command was left unqueued")
    return txs


def check_dma_transactions(plan: dict) -> None:
    legal = set(LEGAL_DMA_TRANSACTIONS.values())
    for tx in dma_transactions(plan):
        if tx not in legal:
            raise ValueError(
                "not a permitted DMA transaction: "
                f"src={tx[0]:#010x} dst={tx[1]:#010x} src_len={tx[2]} dst_len={tx[3]}")


# --- the exact streams -------------------------------------------------------------
#
# Literals and explicit positions, not calls to this module's own packet builders: a
# stream validated against the generator that produced it proves only self-consistency.
# The literals are UG470 Table 6-2's.

W_DUMMY, W_SYNC, W_NOOP = 0xFFFFFFFF, 0xAA995566, 0x20000000
W_CMD_WRITE1, W_FAR_WRITE1 = 0x30008001, 0x30002001
W_FDRO_READ0, W_TYPE2_READ_202 = 0x28006000, 0x480000CA
W_RCFG, W_DESYNC = 0x00000004, 0x0000000D


def validate_readback_stream(words: list[int], target_far: int) -> None:
    if len(words) != 43:
        raise ValueError(f"readback stream is {len(words)} words, not 43")
    for i, want, what in ((0, W_DUMMY, "dummy"), (1, W_SYNC, "sync"),
                          (2, W_NOOP, "NOOP"), (3, W_NOOP, "NOOP"),
                          (4, W_CMD_WRITE1, "Type-1 write 1 word to CMD"),
                          (5, W_RCFG, "RCFG"),
                          (6, W_NOOP, "UG470 step 6's trailing NOOP"),
                          (7, W_FAR_WRITE1, "Type-1 write 1 word to FAR"),
                          (8, target_far, "the target FAR"),
                          (9, W_FDRO_READ0, "Type-1 read 0 words from FDRO"),
                          (10, W_TYPE2_READ_202, "Type-2 read 202 words")):
        if words[i] != want:
            raise ValueError(
                f"readback word {i} is {words[i]:#010x}, expected {want:#010x} ({what})")
    for i in range(11, 43):
        if words[i] != W_NOOP:
            raise ValueError(f"flush word {i} is {words[i]:#010x}, expected a NOOP")


def validate_cleanup_stream(words: list[int]) -> None:
    if len(words) != CLEANUP_WORDS:
        raise ValueError(f"cleanup stream is {len(words)} words, not {CLEANUP_WORDS}")
    for i, want in ((0, W_NOOP), (1, W_CMD_WRITE1), (2, W_DESYNC),
                    (3, W_NOOP), (4, W_NOOP)):
        if words[i] != want:
            raise ValueError(
                f"cleanup word {i} is {words[i]:#010x}, expected {want:#010x}")


def command_buffer_phases(plan: dict) -> list[list[int]]:
    """Reconstruct each configuration stream, expanding `mw.l`'s repeat count.

    Ignoring the count let a single `mw.l CMD_BUF 0x20000000 43` fill the buffer with 43
    NOOPs while the reconstruction saw one word and passed.  Each phase must also begin
    at the buffer base and be contiguous: a gap means words the checker never saw would
    still reach the engine.  The buffer is reused between phases, so a write to an
    already-written offset starts a new one.
    """
    phases: list[dict[int, int]] = []
    current: dict[int, int] = {}
    for step in plan["uboot_script"]:
        form, start, _ = parse_command(step["cmd"])
        if form != "mw.l" or not (CMD_BUF <= start < CMD_BUF + 4 * CMD_STREAM_WORDS):
            continue
        parts = step["cmd"].split()
        value, count = int(parts[2], 0), int(parts[3], 0)
        for k in range(count):
            addr = start + 4 * k
            if addr in current:
                phases.append(current)
                current = {}
            current[addr] = value
    if current:
        phases.append(current)

    out = []
    for phase in phases:
        addrs = sorted(phase)
        if addrs[0] != CMD_BUF:
            raise ValueError(
                f"a command stream starts at {addrs[0]:#010x}, not at the buffer base")
        if addrs != [CMD_BUF + 4 * i for i in range(len(addrs))]:
            raise ValueError("a command stream has a gap; unchecked words would be sent")
        out.append([phase[a] for a in addrs])
    return out


# --- the schedule ------------------------------------------------------------------
#
# Validating each transaction and each stream in isolation still says nothing about the
# order they run in.  Review assembled four whole plans out of individually legal parts:
# two cleanup tuples in place of the real one; an extra legal cleanup appended; the
# cleanup stream written into the command buffer BEFORE the main DMA, so the transfer
# that fires sends the wrong stream; and a legal INT_STS clear slipped between the
# DMA_DEST_LEN trigger and the wait, which erases the very completion being waited for.
#
# So the whole schedule is derived from the commands -- never from `step` names, which a
# plan is free to lie about -- and compared against one exact expected sequence.

DMA_TOKEN = {REG["DMA_SRC_ADDR"]: "DMA_SRC_ADDR", REG["DMA_DEST_ADDR"]: "DMA_DEST_ADDR",
             REG["DMA_SRC_LEN"]: "DMA_SRC_LEN", REG["DMA_DEST_LEN"]: "DMA_DEST_LEN"}


def schedule_tokens(plan: dict) -> list:
    """One token per command, parsed from the command text alone.

    Consecutive command-buffer writes collapse into ("CMD_STREAM", words) counting the
    words actually written, so a bulk `mw.l ... 43` cannot masquerade as one word.
    """
    tokens: list = []
    for step in plan["uboot_script"]:
        form, start, _ = parse_command(step["cmd"])
        parts = step["cmd"].split()
        if form == "dcache-off":
            tok = "CACHE"
        elif form == "md.l":
            count = int(parts[2], 0)
            if start == REG["CTRL"] and count == 1:
                tok = "READ_CTRL"
            elif start == REG["MCTRL"] and count == 1:
                tok = "READ_MCTRL"
            elif start == REG["INT_STS"] and count == 1:
                tok = "READ_INT_STS"
            elif start == DST_BUF and count == READBACK_WORDS:
                tok = "READ_DST"
            else:
                raise ValueError(f"unscheduled read: {step['cmd']!r}")
        else:
            value, count = int(parts[2], 0), int(parts[3], 0)
            if start == REG["INT_STS"]:
                tok = "CLEAR"
            elif start in DMA_TOKEN:
                tok = DMA_TOKEN[start]
            elif start == DST_BUF and count == READBACK_WORDS:
                # The value is part of the token.  Abstracting a destination write to
                # "FILL_DST" discarded the one thing §6c depends on: a prefill of zero
                # makes "the DMA never wrote" and "the engine returned zeros" the same
                # bytes, and a prefill that disagrees with the recorded sentinel makes the
                # verdict table adjudicate against a pattern that was never written.
                tok = ("FILL_DST", value, count)
            elif CMD_BUF <= start < CMD_BUF + 4 * CMD_STREAM_WORDS:
                if tokens and isinstance(tokens[-1], tuple):
                    tokens[-1] = ("CMD_STREAM", tokens[-1][1] + count)
                    continue
                tok = ("CMD_STREAM", count)
            else:
                raise ValueError(f"unscheduled write: {step['cmd']!r}")
        tokens.append(tok)
    return tokens


def _dma_block(words: int) -> list:
    """The invariant shape around one transfer: clear, verify, four registers, wait.

    The four register writes must be contiguous, and nothing may sit between the
    DMA_DEST_LEN trigger and the wait -- that gap is where a clear would erase the
    completion.
    """
    return ["CLEAR", "READ_INT_STS", "DMA_SRC_ADDR", "DMA_DEST_ADDR",
            "DMA_SRC_LEN", "DMA_DEST_LEN", "READ_INT_STS"]


def expected_schedule(order: str, sentinel: int) -> list:
    check_sentinel(sentinel)
    prologue = ["CACHE", "READ_CTRL", "READ_MCTRL", "READ_INT_STS",
                ("FILL_DST", sentinel, READBACK_WORDS), "READ_DST",
                ("CMD_STREAM", CMD_STREAM_WORDS)]
    transfers = _dma_block(0) * 2 if order == "two-unidirectional" else _dma_block(0)
    return (prologue + transfers + ["READ_DST", ("CMD_STREAM", CLEANUP_WORDS)]
            + _dma_block(0) + ["READ_INT_STS"])


EXPECTED_TRANSACTIONS = {
    "two-unidirectional": ["command", "readback", "cleanup"],
    "one-bidirectional": ["bidirectional", "cleanup"],
}


def _show(token) -> str:
    """Render a token with its operands in hex; a decimal sentinel is unreadable."""
    if isinstance(token, tuple):
        return "(" + ", ".join(
            x if isinstance(x, str) else f"{x:#x}" for x in token) + ")"
    return repr(token)


def check_schedule(plan: dict) -> None:
    order = plan["dma_order"]
    got, want = schedule_tokens(plan), expected_schedule(order, plan["sentinel"])
    if got != want:
        for i, (a, b) in enumerate(zip(got, want)):
            if a != b:
                raise ValueError(
                    f"schedule diverges at position {i}: "
                    f"got {_show(a)}, expected {_show(b)}")
        raise ValueError(
            f"schedule has {len(got)} steps, expected {len(want)}")

    by_tuple = {v: k for k, v in LEGAL_DMA_TRANSACTIONS.items()}
    names = [by_tuple[tx] for tx in dma_transactions(plan)]
    if names != EXPECTED_TRANSACTIONS[order]:
        raise ValueError(
            f"transaction sequence is {names}, expected {EXPECTED_TRANSACTIONS[order]}")


def check_sentinel(sentinel: int) -> None:
    """`mw.l` is a 32-bit write.

    Refusing only zero left `0x100000000` accepted, and that value truncates to zero on
    the board -- the prefill would silently become the one pattern §6c exists to exclude.
    """
    if not 1 <= sentinel <= 0xFFFFFFFF:
        raise ValueError(
            f"sentinel {sentinel:#x} must be a non-zero 32-bit value "
            f"(1 .. 0xFFFFFFFF); mw.l writes 32 bits and would truncate it")


def check_value_policy(plan: dict) -> None:
    for step in plan["uboot_script"]:
        form, start, _ = parse_command(step["cmd"])
        if form != "mw.l":
            continue
        if start in REG.values() and start not in DMA_REGISTER_ORDER:
            _check_register_write(start, int(step["cmd"].split()[2], 0))
    check_dma_transactions(plan)
    phases = command_buffer_phases(plan)
    if len(phases) != 2:
        raise ValueError(
            f"expected exactly two command-buffer streams, got {len(phases)}")
    validate_readback_stream(phases[0], plan["target_far"])
    validate_cleanup_stream(phases[1])
    check_schedule(plan)


def addresses_in(cmd: str) -> list[int]:
    """The start address, or [] for a command that touches no address."""
    _, start, span = parse_command(cmd)
    return [start] if span else []


def _dma_steps(cmd: dict) -> list[dict]:
    """Clear, verify the clear, program, wait -- for EVERY DMA command without exception.

    An earlier version cleared once, before the first command.  Under
    `two-unidirectional` the D_P_DONE left by the first transfer then satisfied the second
    transfer's wait immediately, so the readback would have been read out before it
    happened; the cleanup command had neither a clear nor a wait, so DESYNC was never
    known to have been delivered.  The clear is per-command because the hazard is
    per-command.
    """
    name = cmd["name"]
    steps = [
        {"step": f"clear-{name}",
         "cmd": f"mw.l {REG['INT_STS']:#010x} {INT_STS_CLEAR_MASK:#010x} 1",
         "why": "INT_STS is write-to-clear; a residual D_P_DONE reads as a completion",
         "addresses": [REG["INT_STS"]]},
        {"step": f"clear-verify-{name}", "cmd": f"md.l {REG['INT_STS']:#010x} 1",
         "why": f"(INT_STS & {INT_STS_CLEAR_MASK:#010x}) must read 0, or STOP",
         "addresses": [REG["INT_STS"]]},
    ]
    for reg in DMA_WRITE_ORDER:
        steps.append({"step": f"dma-{name}",
                      "cmd": f"mw.l {REG[reg]:#010x} {cmd[reg]:#010x} 1",
                      "why": ("queues the command" if reg == "DMA_DEST_LEN"
                              else "UG585 N3: this order is normative"),
                      "addresses": [REG[reg]]})
    steps.append({"step": f"wait-{name}", "cmd": f"md.l {REG['INT_STS']:#010x} 1",
                  "why": (f"completion is D_P_DONE {INT_STS_D_P_DONE:#x}, not DMA_DONE "
                          f"{INT_STS_DMA_DONE:#x}; errors {INT_STS_ERROR_MASK:#010x}"),
                  "addresses": [REG["INT_STS"]]})
    return steps


def check_allowlist(plan: dict) -> None:
    """Adjudicate the commands, never the metadata beside them.

    The whole span a command touches must lie inside one allowed region -- not merely its
    first word -- and the metadata beside it must then agree with what was parsed.
    """
    for step in plan["uboot_script"]:
        _, start, span = parse_command(step["cmd"])
        if span:
            end = start + span
            if not any(base <= start and end <= base + size
                       for base, size in ALLOWED_REGIONS):
                raise ValueError(
                    f"[{start:#010x},{end:#010x}) in {step['cmd']!r} is not contained "
                    f"in any allowed region")
        claimed = list(step.get("addresses", ()))
        real = [start] if span else []
        if sorted(real) != sorted(claimed):
            raise ValueError(
                f"metadata {[f'{a:#010x}' for a in claimed]} disagrees with the command "
                f"{step['cmd']!r} which touches {[f'{a:#010x}' for a in real]}")


def build_plan(far: int, order: str, sentinel: int) -> dict:
    check_sentinel(sentinel)
    cmds = readback_commands(far)
    dma = dma_commands(order, len(cmds), READBACK_WORDS)

    script: list[dict] = [
        {"step": "cache", "cmd": "dcache off",
         "why": "the DMA writes DDR behind the D-cache; md would return the prefill",
         "addresses": []},
        {"step": "ctrl-gate", "cmd": f"md.l {REG['CTRL']:#010x} 1",
         "why": f"masked-bit gate: (CTRL & {CTRL_MASK:#010x}) == {CTRL_REQUIRED:#010x}",
         "addresses": [REG["CTRL"]]},
        {"step": "loopback-gate", "cmd": f"md.l {REG['MCTRL']:#010x} 1",
         "why": f"(MCTRL & {MCTRL_PCAP_LPBK:#x}) must be 0, or STOP before any DMA: "
                f"loopback selects a different data path whose exact outcome is not pinned",
         "addresses": [REG["MCTRL"]]},
        {"step": "pcfg-done", "cmd": f"md.l {REG['INT_STS']:#010x} 1",
         "why": f"UG585 N1: readback forbidden until INT_STS[2] ({INT_STS_PCFG_DONE:#x})",
         "addresses": [REG["INT_STS"]]},
        {"step": "sentinel-fill",
         "cmd": f"mw.l {DST_BUF:#010x} {sentinel:#010x} {READBACK_WORDS:#x}",
         "why": "written and verified before anything that could let the DMA write it",
         "addresses": [DST_BUF]},
        {"step": "sentinel-verify", "cmd": f"md.l {DST_BUF:#010x} {READBACK_WORDS:#x}",
         "why": "spec §7.5: not confirmed present -> the read is not attempted",
         "addresses": [DST_BUF]},
    ]
    for i, word in enumerate(cmds):
        script.append({"step": "cmd-word",
                       "cmd": f"mw.l {CMD_BUF + 4 * i:#010x} {word:#010x} 1",
                       "why": f"command word {i}",
                       "addresses": [CMD_BUF + 4 * i]})
    for cmd in dma:
        script.extend(_dma_steps(cmd))
    script.append({"step": "readout", "cmd": f"md.l {DST_BUF:#010x} {READBACK_WORDS:#x}",
                   "why": "202 words; only [101:202] is adjudicated",
                   "addresses": [DST_BUF]})
    # configuration-engine cleanup (spec §5d.5): leave the engine desynchronised.
    clean = cleanup_commands()
    for i, word in enumerate(clean):
        script.append({"step": "cleanup-word",
                       "cmd": f"mw.l {CMD_BUF + 4 * i:#010x} {word:#010x} 1",
                       "why": f"cleanup word {i} (UG470 step 14, DESYNC)",
                       "addresses": [CMD_BUF + 4 * i]})
    script.extend(_dma_steps({
        "name": "cleanup", "DMA_SRC_ADDR": _tagged(CMD_BUF),
        "DMA_DEST_ADDR": PCAP_ENDPOINT,
        "DMA_SRC_LEN": len(clean), "DMA_DEST_LEN": 0}))
    script.append({"step": "status-final", "cmd": f"md.l {REG['INT_STS']:#010x} 1",
                   "why": "recorded verbatim in the stage record",
                   "addresses": [REG["INT_STS"]]})

    plan = {
        "schema": "zynq-psmap/pcap_probe_plan/1",
        "board_action": "NONE - this is a plan, not an execution",
        "target_far": far,
        "dma_order": order,
        "unresolved": ["S0 8b: 2'b01 tag with a PCAP endpoint"],
        "pinned_dma_order": PINNED_DMA_ORDER,
        "alternative_dma_order": ALTERNATIVE_DMA_ORDER,
        "candidate_diagnoses": {n: f"INT_STS[{b.bit_length() - 1}] {n}"
                                for n, b in CANDIDATE_DIAGNOSIS_BITS.items()},
        "candidate_diagnoses_note": (
            "generic error stops; not exclusive, not necessary, and no claim that a wrong "
            "pin cannot fail silently"),
        "command_words": cmds,
        "command_word_count": len(cmds),
        "readback_words": READBACK_WORDS,
        "adjudicated_slice": [FRAME_WORDS, 2 * FRAME_WORDS],
        "sentinel": sentinel,
        "timeout_s": TIMEOUT_S,
        "timeout_basis": "derived from UG585 throughput, not measured",
        "ctrl_mask": CTRL_MASK,
        "ctrl_required": CTRL_REQUIRED,
        "int_sts_error_mask": INT_STS_ERROR_MASK,
        "int_sts_clear_mask": INT_STS_CLEAR_MASK,
        "cleanup_words": clean,
        "dma_commands": dma,
        "uboot_script": script,
    }
    check_allowlist(plan)
    check_value_policy(plan)
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--far", default="0x00000b99",
                    help="target frame address (default: the pinned positive control)")
    ap.add_argument("--dma-order", default=PINNED_DMA_ORDER,
                    choices=("two-unidirectional", "one-bidirectional"),
                    help="S0 §8a is resolved: the default is the pinned reading. "
                         "'one-bidirectional' is the retained alternative that a NEW run "
                         "may adopt after any stop - never a retry inside a run")
    ap.add_argument("--sentinel", default="0xA5A5A5A5")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    plan = build_plan(int(a.far, 0), a.dma_order, int(a.sentinel, 0))
    if a.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"target FAR {plan['target_far']:#010x}   dma order: {plan['dma_order']}")
        print(f"command words: {plan['command_word_count']}   "
              f"readback words: {plan['readback_words']}   "
              f"adjudicated: words[{FRAME_WORDS}:{2 * FRAME_WORDS}]")
        print("UNRESOLVED: " + "; ".join(plan["unresolved"]))
        print(f"\n{len(plan['uboot_script'])} U-Boot steps, no board contact:")
        for s in plan["uboot_script"][:5]:
            print(f"  {s['cmd']:52s} # {s['why']}")
        print("  ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
