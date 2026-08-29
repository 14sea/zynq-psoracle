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
| L0 host-only architecture | architecture basis ACCEPTED (§3 v0.2, `docs/l0_review_result.md`); **exit deliverables implemented at `afde303`** (import manifest with two-way closure, validators, fixtures, run-log rules, signer/principal model — 152 tests); **L0 not marked PASS: awaits the independent non-author L0 exit review** |
| L1 P3 carrier (Vivado) | **built** (continuous mandate 2026-08-29): RTL + fixture bench green; OOC +9.9 ns; implemented dummy-key build routed at +7.8 ns, isolation target 6 / flush 0, ICAPE2 = 0, 12 target FARs blank — `docs/l1_design.md`, `builds/dummy_key/`; **L1 exit review pending** (D4 residual to rule) |
| L2 = P2b counter-class non-perturbation | not authorised; first board stage; own ruling |
| L3 one gated candidate end-to-end | not authorised |
| L4 fault / restore / baseline | not authorised |
| L5 the loop | not specified (D1 first) |

## Provenance

`docs/import_manifest.md`: 19 files from `zynq-psmap` `191ab058…` and 11 from
`zynq-fabricmap` `71666b02…`, byte-for-byte, each with sha256, size, origin and source
path; two-way closure over `git ls-files` is a test. The removed authority modules and the
ICAPE2 stream engine are listed as deliberately not imported.

## Licence

Apache-2.0 for original content (`LICENSE`, `NOTICE`). Imported artifacts keep their own
terms and are not relicensed.
