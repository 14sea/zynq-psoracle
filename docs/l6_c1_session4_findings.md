# L6 session C1 #4 (2026-09-01-09) — PASS: the first complete, fully audited C1 under prereg v0.3 / pull-v2

**Standing: PASS (runner outcome, prereg v0.3 §6). The epoch COMPLETED on the board, every
one of the 66 records was audited over the sparse pull, the validator accepted the log,
no frame was lost or dropped, and the rate report exists. `calibration.C1` is NOT pinned by
this document: the pin is the owner's adjudication (D-s3), taken on the rate report's bytes.**
Evidence `evidence/l6_17A6_2026-09-01-09-C1/`; rulings `2026-09-01-09` (whole-of-probe P3-L6
+ provisioning P3-K, both bound to prereg `8daa81f2…`, image `e19e1b12…`, manifest
`73ec76a7…`; both consumed with outcome PASS); boundary
`evidence/boundary/principal_boundary_2026-09-01-09.json` (R1–R5 PASS, 20:42, minutes before).

## 1. What the board did — everything, and nothing else

Power cycle (UART re-enumerated 20:41, `/dev/ebaz-uart → ttyUSB4`), boundary PASS, preflight
PASS, carrier `956379fa…` loaded over ymodem (`fpga loadb`, INT_STS `0x50021004` after,
`plmark 18d14a153a56a73b`), FCLK0 50.0 MHz (IO PLL 1600 MHz, div 8 × 4), CPU clock control
`0x1f000200`, dcache off, IDCODE `0x13722093`, `boardid=17A6 role=verify`, image
`e19e1b12…` (98 324 bytes at `0x02000000`, hash checked by the runner), IDENT as pinned,
watchdog ON, token `6f902db0…`.

**66 records, all `SCORED`, chain length 67:** seq 1 the opening baseline, seq 2–65 the 64
scheduled random-safe candidates (32 pair seeds, each seed twice, `arm_check` 64/64 with
brackets [1, 66]), seq 66 the closing baseline. Both baselines score exactly
`[18, 22, 20, 20, 20, 18]` with an all-zero functional readout and the same
`hw_candidate_commit` `3e24d936…`. The closing unsigned control was refused with fault 13
(status `0x00000982`, nonce advanced). `TERM COMPLETED / budget`. Zero disruptions, zero
epoch-final faults, no board-side stop of any kind.

**Frames — the inbound ledger matches the prereg's expectation exactly:** 1785 rx frames
(IDENT 1, CLOSE 1, TERM 1, SIGNREQ 66, HB 1056 = 16 per record, REC 66, AUDIT_READY 66,
AUDIT 528 = 8 per record) against `expected_frames.total = 1785`; 726 tx frames (SIGNOK 66,
AUDITREQ 66, AUDITGET 528, AUDITDONE 66). `crc_dropped 0` of the D-s4 budget 8, by type
`{}`; `bad_frames 0`; `transport_rereads []` — **no pull retry was needed**; no
AUDITABORT. The board's own session summary agrees: `crc_dropped 0` (board budget 16),
`audited 66/66`, `scored 66`, `refused_by_gate 0`, closing baseline/restore/unsigned
control all `done`.

**Audit — every record verified end to end:** 66/66 served over `streams+readback`, 2814
words each; for every record the recomputed `staged_stream_sha256`, `staged_sha256` and
`readback_sha256` equal the board's self-report (`audit_verification` compared → all
`true`). `run_log_validation: scored 66, audited 66, chain_length 67`. `run_log.json`
sha256 `3b93bdf1…`.

## 2. The rate (informational until the owner pins it)

`rate_report.json` sha256 **`786dc3ec9b4b30315f3656809a8907b7ee13f91d06aeeff1c52e203ecc2b5247`**
(written by the runner; `l6_rate.py` correctly refuses to overwrite existing evidence).
`operator_data_sha256` `0c9c82a8…` as compiled in. Over 63 steady-state periods
(interior→interior):

| quantity | C1 #4 (v0.3, pull-v2) | C1 #3 (v0.2, push; HOLD, informational) |
|---|---|---|
| evals / hour | **3909.9** | 1586 |
| period mean / CoV | 0.921 s / **0.0159** | 2.27 s / 0.019 |
| period min–max | 0.876–0.951 s | — |
| wall per candidate mean / CoV | 0.879 s / 0.0167 | — |
| audit stage mean | **0.438 s (47 % of the period)** | 1.85 s (76 %) |
| sign / stage / link2_dma / link3 / arm_settle_score | 0.114 / 0.041 / 0.020 / 0.041 / 0.205 s | — |
| settle polls | 16 every record (CoV 0) | 16 |
| opening→first, last→closing | 0.88 s, 0.90 s | — |
| failure rate | 0.0 (64 SCORED, 0 failures) | — |
| session span go→TERM | 60.6 s | — |

The pull halved the period and cut the audit share of the link from 76 % to 47 %, which is
what `docs/l6_audit_pull_design.md` modelled (≈80 % byte cut on the audit corpus). The
CoV is the smallest measured on this line.

## 3. Cross-image reproduction (found on the way, not preregistered)

C1 #3 and C1 #4 share the master seed 1278624577, so their schedules are the same 32 pair
seeds. Comparing the two run logs record by record: **all 66 genomes and all 66 functional
readouts are identical**, and both sessions' baselines score `[18, 22, 20, 20, 20, 18]`.
C1 #3 ran image `bd1454cd…` (push protocol) and C1 #4 image `e19e1b12…` (pull-v2). The
pull firmware therefore changed the transport and nothing in the operator → stage → score
path, exactly the claim the freeze batch made ("firmware unchanged" in the scoring path;
transport only). This is an observation from two sessions on one board, not a pinned
result; it is recorded because it is the first hardware evidence that the v0.3 image's
scoring behaviour equals its predecessor's.

## 4. What this session establishes

For the first time on hardware: a complete 64-candidate all-self-reporting C1 whose every
audit was served, verified and accepted — the byte loss that held C1 #1 and C1 #3 did not
occur, and the pull protocol's retry path was present but unused (0 rereads). The rate
report is a candidate for `calibration.C1`. Nothing here is a Claim B data point, and
this session was authorised for C1 only: no C2, no S, no extra diagnostics were run.

## 5. Open items for the owner — ADJUDICATED 2026-09-01 (see `docs/decisions.md`): (1) pinned `786dc3ec…`; (2) stop-loss lifted for pull-v2, history kept, future faults under frozen §7; (3) C2 next under a ruling pair bound to the post-pin manifest hash. Owner's scope note on §3: the identity holds for these 66 records only.

As written before the adjudication:

1. **Pin or refuse `calibration.C1`** = `786dc3ec…` (rate_report.json bytes). Pinning
   changes `manifests/l6_manifest.json`, whose hash the C2 ruling pair must then bind.
   This commit already changes the manifest (hardware_history + standing), so the
   committed hash after this batch is the one to read at pin time.
2. Whether the byte-loss stop-loss (met at C1 #3) is now lifted for C2/S: C1 #4 shows one
   loss-free session under pull-v2; the retry path has not been exercised on hardware.
3. C2 (`map_guided_forced`, same seed) needs its own ruling pair, a power cycle and a fresh
   boundary record; the runner takes the seed from the pin.
