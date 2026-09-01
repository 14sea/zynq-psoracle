# L6 session C2 #1 (2026-09-01-10) — PASS: the map-guided calibration, complete and fully audited

**Standing: PASS (runner outcome, prereg v0.3 §6). The epoch COMPLETED on the board, all 66
records were audited over the sparse pull, the validator accepted the log, no frame was
lost or dropped, and the rate report exists. `calibration.C2` is NOT pinned by this
document: the pin is the owner's adjudication (D-s3) on the rate report's bytes.**
Evidence `evidence/l6_17A6_2026-09-01-10-C2/`; rulings `2026-09-01-10` (whole-of-probe P3-L6
+ provisioning P3-K, bound to prereg `8daa81f2…`, image `e19e1b12…`, manifest `d84a770a…`
— the post-C1-pin hash; both consumed with outcome PASS); boundary
`evidence/boundary/principal_boundary_2026-09-01-10.json` (R1–R5 PASS, 21:01).

## 1. What the board did

Power cycle (UART re-enumerated 21:00:54, after C1 #4's 20:41), boundary PASS, preflight
PASS, carrier `956379fa…` over ymodem, FCLK0 50.0 MHz, image `e19e1b12…` (hash checked by
the runner), IDENT as pinned, watchdog ON, token `68a40e39…`. Session `C2`, mode
`map_guided_forced`, master seed 1278624577 (shared with C1 by the pin), 32 pair seeds each
twice, arm `map_guided` × 64.

**66 records, all `SCORED`, chain length 67:** seq 1 opening baseline, seq 2–65 the 64
scheduled map-guided candidates (`arm_check` 64/64, brackets [1, 66]), seq 66 closing
baseline. Both baselines score exactly `[18, 22, 20, 20, 20, 18]` — the same as C1 #3 and
C1 #4. Closing unsigned control refused with fault 13 (status `0x00000982`, nonce
advanced). `TERM COMPLETED / budget`. Zero disruptions, `epoch_final 0`.

**Frames:** 1785 rx frames exactly as preregistered (IDENT 1, CLOSE 1, TERM 1, SIGNREQ 66,
HB 1056, REC 66, AUDIT_READY 66, AUDIT 528), 726 tx. `crc_dropped 0` of budget 8,
`bad_frames 0`, `transport_rereads []`, no AUDITABORT. Board-side summary: scored 66,
refused_by_gate 0, audited 66/66, closing baseline/restore/unsigned control all done.

**Audit:** 66/66 served over `streams+readback`; for every record the recomputed
stream/staged/readback hashes equal the board's self-report (all `compared` true).
`run_log_validation: scored 66, audited 66, chain_length 67`. `run_log.json` sha `b7f14bca…`.

## 2. The rate (informational until the owner pins it)

`rate_report.json` sha256 **`a13e301f2f2ee2bbc12751fb883b4e189f0e27122e6899d5aa3c53f514568959`**.
`operator_data_sha256` `0c9c82a8…` (same contract as C1). Over 63 steady-state periods:

| quantity | C2 #1 (map_guided) | C1 #4 (random_safe, pinned `786dc3ec…`) |
|---|---|---|
| evals / hour | **3633.0** | 3909.9 |
| period mean / CoV | 0.991 s / **0.0150** | 0.921 s / 0.0159 |
| period min–max | 0.954–1.025 s | 0.876–0.951 s |
| wall per candidate mean / CoV | 0.970 s / 0.0152 | 0.879 s / 0.0167 |
| sign / stage / link2_dma / link3 | 0.118 / 0.041 / 0.021 / 0.060 s | 0.114 / 0.041 / 0.020 / 0.041 s |
| audit / arm_settle_score | 0.482 / 0.226 s | 0.438 / 0.205 s |
| settle polls | 16 every record (CoV 0) | 16 |
| opening→first, last→closing | 0.98 s, 0.99 s | 0.88 s, 0.90 s |
| failure rate | 0.0 (64 SCORED) | 0.0 |
| session span go→TERM | 65.4 s | 60.6 s |

The map-guided operator is ~7 % slower per candidate than random-safe (link3 and audit
stages carry most of the difference); both CoVs are ≈0.015. Under D-s3, the soak's N is
⌊0.9 × min(rate_C1, rate_C2) × 7200 s⌋ — with these two reports that is
⌊0.9 × 3633.0 / 3600 × 7200⌋ = **6539** candidates, which the S runner derives from the
pinned reports' bytes, never from this text.

## 3. Relation to C1 #4 (same seed, different operator)

Record by record against C1 #4: the two baselines (seq 1, 66) have identical genome and
readout; **all 64 candidates differ in genome and readout**, as they must — the pair seeds
are the same and the operator is not. Candidate score sums span 115–121 (C1 #4: 114–121);
20 distinct score vectors. Nothing here compares operator quality — that is Claim B's
question and not this line's.

## 4. What this session establishes, and what is left to the owner — ADJUDICATED 2026-09-01: `calibration.C2` pinned `a13e301f…` (see `docs/decisions.md`); the owner-verified S derivation is N 6539 / sampled audits 412 / 121 449 inbound frames / CRC budget 486 / timeout 8702 s; S ruling pair pending, bound to the post-pin hash.

As written before the adjudication:

Both calibration sessions of prereg v0.3 are now complete, fully audited and loss-free on
17A6 under pull-v2 (C1 #4 and C2 #1: 0 drops, 0 rereads each). Left to the owner: pin or
refuse `calibration.C2` = `a13e301f…`; if pinned, the manifest changes again and the S
ruling pair (`abba`, seed 1278628687, `--duration-s 7200`, `--calibration-c1/-c2` naming the
two pinned reports) binds the post-pin hash. Not done here, by the ruling's scope: no S,
no Claim B data, no extra diagnostics.
