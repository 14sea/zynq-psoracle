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
| L0 host-only architecture | **not passed** — v0.1 REJECTED (`docs/l0_review_result.md`: §3 was a bypass); Option A ruled insufficient; **Option A′ conditionally accepted as the basis, and §3 is now rewritten as v0.2** (PL MAC gate over a gate-signed ARM: full-hash commitment, one-shot nonce, functional sweep; key custody D4). **v0.2 not reviewed** — needs an independent non-author L0 review, then validators/fixtures/manifest |
| L1 P3 carrier (Vivado) | not authorised |
| L2 = P2b counter-class non-perturbation | not authorised; first board stage; own ruling |
| L3 one gated candidate end-to-end | not authorised |
| L4 fault / restore / baseline | not authorised |
| L5 the loop | not specified (D1 first) |

## Provenance

No files have been imported yet. When they are, `docs/import_manifest.md` will list each
byte-for-byte with its sha256 and source commit, in `zynq-psmap`'s form.

## Licence

Apache-2.0 for original content (`LICENSE`, `NOTICE`). Imported artifacts keep their own
terms and are not relicensed.
