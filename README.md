# zynq-psoracle

**P3 of the PS line: re-establish the write-integrity interlock around a PS-side oracle.**

Draft v0.1, 2026-08-29. Host-only. Nothing in this repository touches a board, creates a
ruling, builds hardware, or modifies `zynq-psmap` / `zynq-fabricmap`.

| document | what |
|---|---|
| [`docs/p3_architecture.md`](docs/p3_architecture.md) | the question, the three parties and their authority, `configuration_valid` redefined as a host-computed predicate over PS observations, identity/epoch, the acceptance ladder L0–L5 with PASS/HOLD/KILL, line-wide kill criteria, the boundary with Claim B |
| [`docs/contracts.md`](docs/contracts.md) | versioned artifacts (`carrier_manifest`, `candidate`, `gate_verdict`, `oracle_record`, `arm_record`, `score_record`, `run_log`) and the imported psmap/fabricmap schemas, with the compatibility policy |
| [`docs/decisions.md`](docs/decisions.md) | D1 (where the loop runs — standalone recommended, decided before L5), D2 (name/remote), D3 (whether L1's build is authorised), kill criteria, boundary, the four questions the reviewer must answer |

## Why this repository exists

`zynq-fabricmap`'s Claim B programme paused because its carrier's internal readback could
not witness non-blank content, and its interlock had no channel for a host verdict
(`claimb_findings.md` §3.4–§3.5, §7). `zynq-psmap` then measured, on `17A6`, that the PS
can read configuration bit-exactly without a shutdown (S1–S3), write a certified
content-bit change and read it back with independent JTAG confirmation (P1), and do both
without disturbing the carrier's observable state (P2). P3 is the architecture that puts
those instruments where the carrier's self-check used to be — with the interlock
**re-established**, every link checked by an instrument that saw the actual bytes, and no
match bit anywhere that the host must take on trust.

## Status

| rung | state |
|---|---|
| L0 host-only architecture | architecture basis ACCEPTED (§3 v0.2, `docs/l0_review_result.md`); **exit deliverables implemented at `afde303`** (import manifest with two-way closure, validators, fixtures, run-log rules, signer/principal model — 152 tests); L0 exit: **reviewed as passed** in the whole-line gate review (2026-08-29, `docs/whole_line_gate_review_result.md`; no separate L0 exit verdict document exists) |
| L1 P3 carrier (Vivado) | **built, public (D4 option A: no key in the bitstream)**: RTL + fixture bench green incl. key-register negatives; build routed **+7.58 ns**, isolation target 6 / flush 0, ICAPE2 = 0, 12 target FARs blank, 3,107 LUTs — `builds/p3/`, `docs/l1_design.md`; **L1 preparation PASS** (re-review 2026-08-29) |
| L2 = P2b counter-class non-perturbation | **PASS on 17A6** (run #3, ruling `2026-08-30-03`, spec v1.1; `docs/l2_findings.md`): 10/10 reads + envelope write + readback bit-exact; state words equal on all 15 samples; heartbeat inside its envelope on all 31 intervals (49.86–50.09 MHz). Runs #1/#2 were host-instrument outcomes. Scoped: this carrier, these nine words, this PCAP activity — not general computational correctness |
| L3 one gated candidate end-to-end | session #1 STOP LINK3_MISMATCH → **diagnostic: FABRIC_BLANK, root cause = host instrument** (staging with the D-cache on; link 2 read the cache, the DMA read DDR; JTAG confirms the write never landed, CRC_ERROR 0) — fixed (verified `dcache off` before staging, fake reproduces it), `docs/l3_findings.md`. **Session #1 to be re-run under a new ruling.** Tooling: **ready for the board** (runbook `docs/l3_l4_runbook.md`; real-signer rehearsal on the fake passes); **host tooling written** (`host/l3_runner.py`, link-1 gate, host oracle pinned to fabricmap's silicon scores, out-of-process signer, on-board negative controls; `docs/l3_design.md`); **no ruling, not authorised** |
| L4 fault / restore / baseline | **host tooling written** (`host/l4_runner.py`, fake tests); link-1 refusal record produced host-only (`evidence/l4_gate_refused/`); on-board session needs P3-L4 + P3-K rulings — `docs/l3_l4_runbook.md` |
| L5 the loop | not specified (D1 first) |

## Gate review

`docs/whole_line_gate_review.md` — the package; **result 2026-08-29: HOLD**
(`docs/whole_line_gate_review_result.md`) — blocker D4 (the signer and the runner are one
OS user; the keyed bitstream is key material). Proposal: `docs/d4_principal_boundary.md`
(recommended: runtime key provisioned by a separate signer user over JTAG; bitstream becomes
public). **Owner chose A (2026-08-29); implemented host-only** — runtime write-once key register,
`F_ARM_NOKEY`, JTAG provisioning tool (prepare-only without a `provisioning P3-K` ruling),
runner provisioning step + `key_loaded_observed`, pre-positive controls, public build.
Re-review 2026-08-29 (later): **D4 PASS, L1 host/build/principal preparation PASS**
(`docs/whole_line_gate_review_result.md`). Principal `p3signer`/`p3jtag` established on
the host and verified as the runner (R1–R5, `evidence/boundary/`). Sudoers wildcard →
fixed key paths (owner re-applies with sudo before the board). **Next: the owner's
`whole-of-probe P3-L2` ruling. No ruling yet, no board contact.**

## Provenance

`docs/import_manifest.md`: 19 files from `zynq-psmap` `191ab058…` and 11 from
`zynq-fabricmap` `71666b02…`, byte-for-byte, each with sha256, size, origin and source
path; two-way closure over `git ls-files` is a test. The removed authority modules and the
ICAPE2 stream engine are listed as deliberately not imported.

## Licence

Apache-2.0 for original content (`LICENSE`, `NOTICE`). Imported artifacts keep their own
terms and are not relicensed.
