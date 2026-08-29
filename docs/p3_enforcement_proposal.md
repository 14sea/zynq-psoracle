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

---

## Owner ruling on Option A (2026-08-29): not adopted as it stands

Option A enforces `score ⇒ actual LUT behaviour == host-supplied expected table`. The
architecture needs `score ⇒ gate-approved candidate == actual LUT behaviour`. The gap is
this bypass: a runner skips the gate, reads or guesses the current LUT behaviour, writes a
matching expected table, ARMs, and the PL's functional check passes. `configuration_valid_hw`
is hardware-latched but **not bound to the gate verdict**. Required before the next L0
submission: a non-bypassable binding between the gate-approved candidate and the hardware
expectation — by a hardware-loaded expectation derived from an unforgeable candidate/
manifest path, or an ARM payload that carries a candidate commitment the hardware can check
against the table, or a trusted, non-forgeable ARM authority carrying the gate verdict.
Option A's sweep, `functional_readout`, truth-table bit order and "wrong expectation must
not ARM" remain accepted as the L1/L3 hardware witness.

## Option A′ — Option A plus a gate-signed ARM commitment verified in the PL (for ruling)

### The binding

Make the **gate the only party that can produce a valid ARM**, and make the PL check that
before it sweeps. Concretely:

1. **A session nonce from the PL.** At setup the PL generates (or the carrier's reset
   value provides, then a free-running counter latches at first read) a 64-bit `nonce`,
   readable once per session at a pinned AXI word. It is evidence, not a secret; it exists
   so that a valid ARM cannot be replayed for a different candidate or session.
2. **The gate signs the ARM.** On a verdict of `writable`, the gate — and only the gate —
   computes `expected_tables` from the candidate's INIT bits (deterministic, certified map,
   `lut_truth_table` contract) and a tag
   `tag = MAC_K(expected_tables ‖ candidate_commit ‖ nonce)`
   where `candidate_commit` is the low 64 bits of `candidate_sha256` and `K` is a 128-bit
   key **held by the gate and baked into the carrier bitstream**, never readable from the
   PL and never available to the runner (§"key custody").
3. **The ARM payload** = `expected_tables` (12 words) ‖ `candidate_commit` (2 words) ‖
   `tag` (2 words). The runner writes it; the runner cannot produce `tag`.
4. **The PL verifies before it sweeps:** recompute `MAC_K` over the payload and its own
   `nonce`; on mismatch, refuse (`fault = F_ARM_AUTH`, no sweep, no score). On match,
   sweep the six LUTs (Option A), compare with `expected_tables`, and latch
   `configuration_valid_hw ⟺ tag_ok ∧ readout == expected ∧ ¬recovery_required ∧ fault == 0`.
   The scorer arms only on that.
5. **The PL exposes `candidate_commit` it armed for and `functional_readout`** read-only,
   so the run log's `candidate_sha256` is checked against what the hardware actually bound
   the score to — evidence again, not a match bit.

What is now enforced **in hardware**: `score ⇒ (the ARM was signed by the key-holder
for THIS candidate commitment, THIS expected table, THIS session) ∧ (the fabric's six LUTs
behave as that table)`. Since the key-holder signs only candidates its whitelist gate
passed, `score ⇒ gate-approved candidate == actual LUT behaviour`, with the sole trust
assumption being **key custody** — a boundary that is checkable (§"key custody") rather
than a process rule.

### The bypass, re-run against A′

1. runner skips the gate → 2. reads/guesses LUT behaviour → 3. writes a matching table →
4. ARM: **needs `tag`; runner has no `K` → PL refuses, `F_ARM_AUTH`, no score.** Replaying
an old valid ARM: **`nonce` differs → tag mismatch.** Replaying within the same session for
a different candidate: **`candidate_commit` is under the MAC; the PL binds the score to the
commit it verified, and the run log's candidate hash must equal it.** Colluding gate: out
of scope — the gate is the trusted party by construction (it was in the carrier too).

### Key custody — the trust boundary, stated so it can be checked

- `K` is generated by the owner, written into the carrier at build time as a constant
  (never on a readable bus), and given to the gate as a file readable **only by a separate
  OS user** that runs the gate; the runner's user cannot read it. Test: the runner, as its
  own user, cannot open the key file and cannot produce a tag the PL accepts.
- A compromised host with root defeats this. That is the same assumption the original
  carrier made about the host gate ("link 1 is the host's"), now made explicit and narrow.

### The MAC — sized for the fabric

The threat is a runner bypassing process, not a cryptanalyst. **SipHash-2-4** (64-bit ARX,
128-bit key) is a few hundred LUTs, well inside the carrier's remaining budget; keyed over
16 words it runs in a few hundred cycles. The same function is a dozen lines of Python on
the gate side, testable against published vectors. (Truncating `candidate_sha256` to 64
bits for the commitment is fine under this threat model and is stated as such.)

### Cost to the ladder if A′ is adopted

- L1: the SipHash verifier, the nonce, the 16-word ARM payload registers, `F_ARM_AUTH`;
  testbench negatives — wrong tag, replayed nonce, mismatched commit, right tag with wrong
  table — none may raise `armed`.
- L3: negative controls on the board: unsigned ARM, replayed ARM, signed ARM for candidate
  X presented after candidate Y landed — all must yield `F_ARM_AUTH` / no score, and the
  positive case must score. The enforcement point is exercised, not assumed.
- Contracts: `arm_record` gains `nonce`, `candidate_commit`, `tag`; `score_record` gains
  the PL's armed `candidate_commit`; `lut_truth_table` 1.0.0 and `arm_mac` 1.0.0 added;
  the run-log validator's rule stays as a second check.
- Key custody becomes a documented, tested precondition of every board rung from L3.

### What A′ still does not claim

It binds the **six LUTs' behaviour** to the gate's candidate. Flush frames and non-target
bits are still the PS oracle's readback (link 3) plus the gate; the hardware does not
witness them. Stated, as before.
