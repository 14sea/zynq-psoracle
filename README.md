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

**Canonical status table: [`docs/status.md`](docs/status.md)** — L0, D4, L1, L2, L3 (scoped), L4 all
**PASS** on EBAZ4203 `17A6` as of 2026-08-31, and the **L0–L4 overall review is PASS (scoped)**;
L5's D1 specification is drafted (`docs/d1_standalone_spec.md`, not reviewed). The per-rung rows below are a summary; where they and
`docs/status.md` disagree, `docs/status.md` wins.

| rung | state |
|---|---|
| L0 host-only architecture | **PASS** — §3 v0.3 (PL-enforced, gate-signed ARM; runtime-provisioned key); `docs/l0_review_result.md` |
| D4 key custody | **PASS** — real signer OS user + JTAG-provisioned write-once key; `evidence/boundary/` |
| L1 P3 carrier | **PASS** (preparation) — public build `builds/p3/`, +7.58 ns, isolation 6/0, ICAPE2 0; `docs/l1_design.md` |
| L2 = P2b | **PASS** on 17A6 (run #3) — `docs/l2_findings.md`; heartbeat pinned [49.5, 50.5] MHz |
| L3 one gated candidate | **PASS (scoped)** on 17A6 — five sessions, `docs/l3_findings.md` |
| L4 fault / restore / baseline | **PASS** on 17A6 — `docs/l4_findings.md` |
| L5 the loop | D1 specification drafted, not reviewed (`docs/d1_standalone_spec.md`) |

Tests: `host/run_tests.sh` (records exit status + environment into `evidence/tests/`); see
`docs/status.md` for the sandbox/sudo caveat.

## Gate reviews (historical records)

`docs/whole_line_gate_review.md` (package, 2026-08-29) and `docs/whole_line_gate_review_result.md`
(HOLD → D4 option A → PASS). Their status statements are historical; `docs/status.md` is current.

## Provenance

`docs/import_manifest.md`: 19 files from `zynq-psmap` `191ab058…` and 11 from
`zynq-fabricmap` `71666b02…`, byte-for-byte, each with sha256, size, origin and source
path; two-way closure over `git ls-files` is a test. The removed authority modules and the
ICAPE2 stream engine are listed as deliberately not imported.

## Licence

Apache-2.0 for original content (`LICENSE`, `NOTICE`). Imported artifacts keep their own
terms and are not relicensed.
