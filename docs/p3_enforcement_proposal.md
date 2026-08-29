# Proposal: a trusted enforcement point for `configuration_valid` — for ruling, not adopted

Status: proposal, 2026-08-29, written after the L0 REJECT (`l0_review_result.md`). Nothing
here is in force. The owner rules whether §3 is redrafted along one of these lines.

## The requirement, restated

ARM/score must be **physically ineffective** while the interlock predicate is false, and the
party that enforces it must not be the runner. The host may still own link 1 (permission —
the carrier design §3b already said the PL does not re-implement the content gate); what
must move into hardware is: **"the fabric holds what the host claims it handed over"** as a
precondition of scoring, enforced by the PL from an observation the PL itself makes.

## Option A — functional truth-table witness in the PL (recommended)

The only thing the PL can observe about its own configuration without ICAPE2 is the
**behaviour** of the evolvable LUTs. The scorer already drives the six target LUTs' inputs
with a vector source and captures their outputs. Extend it:

1. On ARM, the host writes not a bit but **the expected 64-bit truth table of each target
   LUT** (six words × 2, or a 32-bit hash the PL recomputes over the tables — see Q3's
   principle: prefer the full tables, they are 384 bits, twelve AXI writes).
2. The PL then **sweeps all 64 input vectors** of each LUT and captures the outputs — a
   `functional_readout` — and compares it, in hardware, with what the host wrote.
3. `configuration_valid_hw` ⟺ `functional_readout == expected` ∧ `¬recovery_required` ∧
   `fault == 0`, computed and latched by the PL. **The scorer arms only on
   `configuration_valid_hw`.** A host that sends a wrong expectation gets no score; a host
   that sends the *right* expectation for a candidate that never landed gets no score
   either, because the fabric's behaviour will not match.
4. The PL exposes the `functional_readout` words read-only, so the host records what the
   fabric actually did (evidence, not a match bit: the host compares them itself too).

What this enforces in hardware: **score ⟹ the six LUTs' effective content == the content
the host claimed at ARM.** What stays with the host: that the claimed content is the
gate-accepted candidate (link 1) and that flush frames / non-LUT bits equal the base (the
PS oracle's PCAP readback, link 3, plus the gate). What is *not* witnessed by hardware:
routing and non-target bits — they are outside the whitelist, refused by the gate, and
witnessed by the PS oracle's readback; a routing corruption that reaches the LUT inputs
would surface as a truth-table mismatch, one that does not would not.

Precedent on this die: `zynq-xpart` T2.2/T2.3 read a target LUT's output functionally
(`lut_probe` @ `0xF4000000`) to confirm ICAP writes, deterministically over three flips;
`zynq-fabricmap`'s scorer already drives these LUTs' inputs. The addition is a 64-vector
sweep and a comparator per LUT, plus twelve AXI-writable expectation words.

Costs: ~384 bits of expectation registers + 384 bits of capture + 6 comparators, small
against the carrier's 800-LUT budget (`carrier_stream.v` comments); the exhaustive sweep
is 64 cycles per LUT. The truth-table domain must be pinned in a contract
(`lut_truth_table` 1.0.0: bit order relative to INIT[63:0], which input is A1…A6, the
uncertified positions' base values included).

## Option B — PS as a trusted control plane (bare-metal app owns ARM)

Move the predicate into a standalone PS application (D1 = standalone) and make it the only
AXI master that can reach the ARM register — e.g. the PL accepts ARM only when accompanied
by a nonce the PL handed the app at session start over a channel U-Boot scripting cannot
replay. This makes the *enforcer* the PS app rather than the PL. Weaker than A: the PL
still cannot check the configuration itself, and "the app is trusted" is an assumption
about software on the same PS the runner drives; it also forces D1 now. Not recommended
as the primary mechanism; possibly useful in L5 as a second layer.

## Option C — keep the original carrier's ICAPE2 readback compare and fix it

The fabricmap leg paused because that compare never returned non-blank content and the
diagnosis was inseparable (`claimb_findings.md` §3.3). Reopening it is a different
programme with its own stop-loss already triggered. Not proposed.

## What changes in the ladder if A is adopted

- L1 adds the sweep/compare logic and the expectation registers to the carrier; the OOC
  gate covers it; a testbench proves `armed` cannot rise with a mismatched expectation.
- L3's PASS gains a hardware conjunct: `configuration_valid_hw` observed 1 (read over the
  pinned AXI words) before the score, and a negative control — ARM with a deliberately
  wrong expectation must produce **no score** (the enforcement point exercised, not
  assumed).
- `contracts.md`: `arm_record` carries the expectation words; `score_record` carries the
  `functional_readout` and `configuration_valid_hw`; the run-log validator's rule becomes
  a *second* check, not the only one.

## The question for the owner

Redraft §3 along Option A (PL-enforced functional witness), or another mechanism the
reviewer names? Until ruled, L0 stays KILL and §3 stays as reviewed.
