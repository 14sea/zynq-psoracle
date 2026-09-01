#!/usr/bin/env python3
"""L6 schedule arithmetic — pure functions, no board, no I/O.

Everything the L6 preregistration (`docs/l6_soak_prereg.md`) says must be derived BEFORE a
session rather than typed by hand or read off what arrived:

  * the arm schedule (§2.2): `arm(index)` under Claim B's A,B,B,A pairing rule, and the
    per-pair seed each candidate's operator is fed — one master seed, one rule, one twin;
  * the sampled audit schedule (§3a item 1): every 16th seq, plus the first and the last
    candidate and both baselines;
  * the expected protocol frame count and the CRC drop budget (D-s4), from N, the audit
    schedule and the fixed brackets — never from the count actually received;
  * N for the soak (D-s3): ⌊0.9 × min(rate_A, rate_B) × T⌋, and the session timeout the
    runner records.

Seq ↔ index. A COMPLETED session emits records seq 1 (opening baseline, blank genome),
seq 2 … N+1 (the N candidates, index 0 … N−1) and seq N+2 (closing baseline). The two
baselines are brackets, not candidates: they have no arm and no operator seed.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from validators import nonce as nc  # noqa: E402

ARM_A, ARM_B = "random_safe", "map_guided"
ARMS = (ARM_A, ARM_B)
MODE_ABBA, MODE_A_FORCED, MODE_B_FORCED = "abba", "random_safe_forced", "map_guided_forced"
MODES = (MODE_ABBA, MODE_A_FORCED, MODE_B_FORCED)
# identity-page flags: bit0 holdout, bit1 watchdog (D-s1), bits 2..3 the schedule mode
FLAG_HOLDOUT, FLAG_WATCHDOG = 1 << 0, 1 << 1
MODE_FLAG_SHIFT, MODE_FLAG_MASK = 2, 0b11 << 2
MODE_FLAG = {MODE_ABBA: 0, MODE_A_FORCED: 1, MODE_B_FORCED: 2}

AUDIT_EVERY = 16
# D-s4 brackets (fixed): per session, per record, per audited record
FRAMES_PER_SESSION = {"IDENT": 1, "CLOSE": 1, "TERM": 1}
FRAMES_PER_RECORD = {"SIGNREQ": 1, "HB": 16, "REC": 1}
FRAMES_PER_AUDITED = {"AUDIT": 8}
# the pull protocol (docs/l6_audit_pull_design.md): inbound frames per audited record are
# one AUDIT_READY plus the chunks; the host's AUDITGET/AUDITDONE are outbound and not budgeted
PROTOCOLS = {"push-v1": {"per_audited": {"AUDIT": 8}},
             "pull-v2": {"per_audited": {"AUDIT_READY": 1, "AUDIT": 8}}}
CRC_PER_MILLE = 4                      # budget = ceil(4 × expected / 1000)
SOAK_FRACTION = 0.9                    # D-s3: N = ⌊0.9 × min(rate) × T⌋
TIMEOUT_MARGIN, TIMEOUT_FIXED_S = 1.25, 600.0
GOLDEN = 0x9E3779B97F4A7C15
MASK32 = 0xFFFFFFFF
MASK64 = 0xFFFFFFFFFFFFFFFF
WARMUP_STEPS = 4
PAIR_SEED_RULE = ("pair_seed(master_seed, pair) = upper 32 bits of the xorshift64 state after 4 steps "
                  "from x0 = ((master_seed<<32) | master_seed) ^ (((pair+1) * golden) mod 2^64), "
                  "with x0 = golden if that is 0; golden = 0x9E3779B97F4A7C15; "
                  "step: x ^= x<<13; x ^= x>>7; x ^= x<<17 (mod 2^64)")


def flags_for(mode: str, watchdog: bool, holdout: bool = False) -> int:
    if mode not in MODES:
        raise ValueError(f"schedule mode {mode!r} is not one of {MODES}")
    return ((FLAG_HOLDOUT if holdout else 0) | (FLAG_WATCHDOG if watchdog else 0)
            | MODE_FLAG[mode] << MODE_FLAG_SHIFT)


def mode_from_flags(flags: int) -> str:
    code = (flags & MODE_FLAG_MASK) >> MODE_FLAG_SHIFT
    for mode, c in MODE_FLAG.items():
        if c == code:
            return mode
    raise ValueError(f"flags {flags:#x}: schedule-mode code {code} is not assigned")


# ------------------------------------------------------------------ the arm schedule


def arm_abba(index: int) -> str:
    """Claim B's pairing rule. Candidates come in seed pairs (index 2k, 2k+1 share seed k);
    successive pairs alternate their order: pair 0 = A,B; pair 1 = B,A; pair 2 = A,B; …
    Written out: A,B,B,A,A,B,B,A,… — so neither arm systematically runs second."""
    if index < 0:
        raise ValueError("index must be >= 0")
    pair, second = index // 2, index % 2
    first_is_a = pair % 2 == 0
    return ARM_A if (first_is_a ^ bool(second)) else ARM_B


def pair_seed(master_seed: int, pair: int) -> int:
    """The 32-bit operator seed of pair k. Exactly PAIR_SEED_RULE: x0 = ((master_seed<<32)
    | master_seed) ^ (((k+1) × golden) mod 2^64), x0 = golden if that is 0, then
    WARMUP_STEPS = 4 xorshift64 steps (the PL's nonce generator, `validators.nonce.step`,
    one implementation), and the upper 32 bits of the result. The seed sits in both halves
    and the state is warmed up because a single step leaves the upper 32 bits independent
    of the lowest bits, so pairs differing only there would share a seed."""
    if not 0 <= master_seed <= MASK32:
        raise ValueError("master_seed must be a 32-bit value (it travels in the identity page)")
    if pair < 0:
        raise ValueError("pair must be >= 0")
    x = ((master_seed << 32) | master_seed) ^ ((pair + 1) * GOLDEN & MASK64)
    if x == 0:
        x = GOLDEN
    for _ in range(WARMUP_STEPS):   # one step does not diffuse the low bits into the high half
        x = nc.step(x)
    return (x >> 32) & MASK32


def schedule(master_seed: int, n: int, mode: str) -> list[dict]:
    """One row per candidate: index, seq, pair, seed, arm. `mode` forces one arm for the
    calibration sessions (C1: A, C2: B) or interleaves them for the soak (S)."""
    if mode not in MODES:
        raise ValueError(f"schedule mode {mode!r} is not one of {MODES}")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("n must be a positive integer")
    rows = []
    for i in range(n):
        arm = {MODE_ABBA: arm_abba(i), MODE_A_FORCED: ARM_A, MODE_B_FORCED: ARM_B}[mode]
        rows.append({"index": i, "seq": i + 2, "pair": i // 2,
                     "seed": pair_seed(master_seed, i // 2), "arm": arm})
    return rows


def baseline_seqs(n: int) -> tuple[int, int]:
    return 1, n + 2


def arm_for_seq(sched: list[dict], seq: int) -> str | None:
    """The scheduled arm of a seq, or None for a bracket (seq 1 / seq N+2)."""
    for row in sched:
        if row["seq"] == seq:
            return row["arm"]
    return None


# ------------------------------------------------------------------ the audit schedule


def sampled_audit_seqs(n: int, every: int = AUDIT_EVERY) -> set[int]:
    """§3a item 1: SCORED candidates audited by AUDITREQ = every `every`-th seq, plus the
    first and the last candidate (seq 2, seq N+1) and both baselines (seq 1, seq N+2)."""
    if n < 1 or every < 1:
        raise ValueError("n and every must be >= 1")
    first, last = baseline_seqs(n)
    out = {first, last, 2, n + 1}
    out |= {s for s in range(first, last + 1) if s % every == 0}
    return out


def all_seqs(n: int) -> set[int]:
    return set(range(1, n + 3))


# ------------------------------------------------------------------ D-s4


def expected_frames(n: int, audited_seqs: set[int], protocol: str = "push-v1") -> dict:
    """The frame count a COMPLETED session of N candidates emits, by the fixed brackets.
    `audited_seqs` is the set of seqs the host WILL request an audit for (the sampled
    schedule, or every seq for all-self-reporting) — the §3a item-2 auto-audits of
    non-SCORED self-reports are not knowable in advance and are deliberately not counted."""
    records = n + 2
    audited = len({s for s in audited_seqs if 1 <= s <= records})
    by_type = dict(FRAMES_PER_SESSION)
    for t, per in FRAMES_PER_RECORD.items():
        by_type[t] = per * records
    if protocol not in PROTOCOLS:
        raise ValueError(f"protocol {protocol!r} is not one of {sorted(PROTOCOLS)}")
    for t, per in PROTOCOLS[protocol]["per_audited"].items():
        by_type[t] = per * audited
    return {"n": n, "records": records, "audited_records": audited, "protocol": protocol,
            "by_type": by_type, "total": sum(by_type.values())}


def crc_budget(expected_total: int) -> int:
    """D-s4's closed formula. Independent of it, a missing AUDIT/REC/TERM is a structural
    HOLD (`host/l6_checks.py`); the budget bounds CRC drops only."""
    if expected_total < 1:
        raise ValueError("expected_total must be >= 1")
    return math.ceil(CRC_PER_MILLE * expected_total / 1000)


# ------------------------------------------------------------------ D-s3


def soak_n(rate_a_per_h: float, rate_b_per_h: float, duration_s: float) -> int:
    """N = ⌊0.9 × min(rate_A, rate_B) × T⌋ with T in hours."""
    for r in (rate_a_per_h, rate_b_per_h):
        if not (r > 0):
            raise ValueError("calibration rates must be positive")
    if not (duration_s > 0):
        raise ValueError("duration must be positive")
    return math.floor(SOAK_FRACTION * min(rate_a_per_h, rate_b_per_h) * duration_s / 3600.0)


def session_timeout_s(n: int, rate_a_per_h: float, rate_b_per_h: float) -> float:
    """The runner's own bound (prereg §4.6): (N + 2 brackets) at the slower measured rate,
    times a margin, plus a fixed allowance for the preamble and closing steps. Recorded
    with its inputs; it is a bound on the session, not a prediction of it."""
    slow = min(rate_a_per_h, rate_b_per_h)
    if not (slow > 0):
        raise ValueError("calibration rates must be positive")
    return math.ceil(TIMEOUT_MARGIN * (n + 2) * 3600.0 / slow + TIMEOUT_FIXED_S)
