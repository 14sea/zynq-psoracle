# L6 session C2 #2 (2026-09-03-02) — PASS (runner outcome): the map-guided rel-v4 epoch under prereg v0.6 COMPLETED and audited end to end; two AUDIT chunks arrived CRC-broken on the console and the pull re-requested each once — the first real (non-control) recovery of the rel-v4 line on the board, inside the bounds

**Standing: PASS as the runner adjudicated it (prereg v0.6 §6, all items; `findings: []`).
This is the ONE rel-v4 C2 the owner's stop-loss operational exception authorised (owner
2026-09-03, after the C1 pin commit `23477a7` was pushed). It is a runner outcome, not an
owner adjudication: `calibration.C2` stays null until the owner independently reviews
this session and pins `rate_report.json` (sha
`959790d0e17401936ddd9636f79b9f79e9d45f4fc106de1482f2c8aa969db191`) by hash (D-s3); S and
Claim B stay closed until the owner rules; C1 #5 keeps its permanent HOLD under v0.4.**
Evidence `evidence/l6_17A6_2026-09-03-02-C2/`; rulings `2026-09-03-02` (whole-of-probe
P3-L6, session C2, master_seed 1278624577; provisioning P3-K; both bound to prereg
`bfd69d10…`, image `5deee74c…`, manifest `154a7525…`; both consumed with outcome PASS);
boundary `evidence/boundary/principal_boundary_2026-09-03-02.json` (R1–R5 PASS, minutes
before). Second hardware run of the rel-v4 image `5deee74c…` under prereg v0.6; first
map-guided epoch under rel-v4.

## 1. What the board did — the whole epoch, correctly

Power cycle by the owner (UART re-enumerated 17:47, `/dev/ebaz-uart → ttyUSB4`), boundary
PASS, preflight READ (`CPU_CLK_CTRL 0x1f000200`), carrier `956379fa…` loaded, FCLK0 50.0
MHz, IDCODE `0x13722093`, `boardid=17A6 role=verify`, devcfg precheck all passed,
provisioning rc 0, image `5deee74c…` (98 324 bytes at `0x02000000`, hash checked),
identity page written (`map_guided_forced`, N 64, watchdog bit1, bit4 and bit5 armed).
Token `440d9be1…`.

**IDENT 1.3.0: `protocol: rel-v4`, `rec_retry_control: true`, `sign_retry_control: true`**,
`schedule_mode map_guided_forced`, `master_seed 1278624577` (the same seed as C1, so the
same 32 seed pairs walked by the other operator), operator data `0c9c82a8…`; verified and
`IDENTACK`ed once (ledger `ident`: attempts `["ok"]`, accepted). Epoch span (first
`SIGNREQ` to last `REC`) 68.4 s; `TERM` 68.6 s after the IDENT, acknowledged once; the
22 s TERM linger, then the port closed (the `vhci_hcd urb->status -104` lines in dmesg
are that close, 22 s after the TERM).

**66 records, all `SCORED`, chain length 67:** seq 1 the opening baseline, seq 2–65 the 64
scheduled map-guided candidates (`arm_check` 64/64, brackets [1, 66], every record's arm
`map_guided`), seq 66 the closing baseline; both baselines `[18, 22, 20, 20, 20, 18]`.
Closing control refused with fault 13 (status `0x00000982`, nonce `7110b726…` →
`543b14bc…` — the same nonces as C1 #6, the chain being a function of the seed and the
carrier's NONCE_SEED), carried by the TERM's `closing_control` and by a `CLOSE` frame that
agree (`closing_conflict: null`). `TERM COMPLETED / budget`; the board's summary:
`audited 66/66`, `scored 66`, `refused_by_gate 0`, `crc_dropped 0` (board side), closing
baseline/restore/unsigned control all `done`. Zero disruptions, `epoch_final 0`,
`transport_rereads []`.

**Frames:** 1785 valid inbound protocol frames = `expected_frames.total` (IDENT 1, SIGNREQ
66, HB 1056, REC 66, AUDIT_READY 66, AUDIT 528, CLOSE 1, TERM 1), plus **four `CRC_DROP`
non-frames**: the two controls (§2) and the two broken AUDIT chunks (§3). Outbound 732:
IDENTACK 1, SIGNOK 66, SIGNGET 1 (the control), AUDITGET **530** (528 + the two
re-requests), AUDITDONE 66, RECACK 66, RECGET 1 (the control), TERMACK 1. `crc_dropped
4` of budget 8, by type `{"SIGNREQ": 1, "REC": 1, "AUDIT": 2}`; `bad_frames 0`;
`fragments 0`; no AUDITWAIT, no AUDIT_READY resend, no TERMGET, no replay, no timeout.

**Audit:** 66/66 served over `streams+readback`, 2814 words each; every recomputed
`staged_stream_sha256` / `staged_sha256` / `readback_sha256` equals the self-report;
`run_log_validation: scored 66, audited 66, chain_length 67`; the validator accepted.

## 2. The two forced retry controls — exact (items 6, 12)

Sign ledger seq 1: attempts `["crc", "ok"]`, one `SIGNGET`, `replays 0`; REC ledger seq 1:
`["crc", "ok"]`, `gets_sent 1`, `acks_sent 1`; every other seq `["ok"]` in both ledgers.
`rec_control_findings`, `rel_control_findings`, `rec_closure_findings`,
`rel_closure_findings` all empty; the two drops attributed as `control_drops 2`.

## 3. The two real recoveries — AUDIT chunks CRC-broken on the console, re-requested once each (items 3a–3b, 13)

| seq (arm) | chunk | what arrived | host action | recovered after | period |
|---|---|---|---|---|---|
| 35 (map_guided) | 7 of 8 (the last) | a complete AUDIT-shaped line whose CRC did not verify (`CRC_DROP`, `frame_type AUDIT`, go + 36.2 s) | `AUDITGET 35 chunk 7` again, immediately (no timeout — the line was complete) | 42 ms: the resend verified, `AUDITDONE 35` 1 ms later | 1.063 s (mean 1.033 s) |
| 50 (map_guided) | 5 of 8 | the same shape (go + 51.7 s) | `AUDITGET 50 chunk 5` again, immediately | 42 ms; chunks 6, 7 and `AUDITDONE` followed normally | 1.098 s |

Pull ledgers: `[ok ×7, crc, ok]` for 35 and `[ok ×5, crc, ok, ok, ok]` for 50;
`crc_dropped 1` each, `timeouts 0`, `duplicates []`, `waits_seen 0`. Both candidates
SCORED and audited (their three hashes recompute equal). In the rate report they are the
two `recovered_seqs` (`pull_retries 2`, `pull_crc 2`, `crc_drops 2` — the non-control
drops); the nominal set excludes their two periods.

These are the sixth and seventh console corruption events of the L6 line (after C1 #1,
C1 #3 ×2, S #1, C1 #5), the first two under rel-v4 and the first two recovered **without
a timeout**: the bytes were wrong, not missing, so the line terminated normally, the CRC
refused it, and the re-request cost one round trip (≈ 42 ms, the normal chunk cadence)
instead of the 2.0 s chunk deadline that C1 #5's truncated chunk needed. The 8 s board
bounds, AUDIT_READY resend, AUDITWAIT and TERMGET paths were again not exercised.

## 4. The rate — the three rates of D-t1, nothing pinned here

`rate_report.json` 1.2.0 (`inputs`: run_log `2bc4b4a6…`, audits `2f44d835…`, timeline
`9941cebb…`; `binding` = {image `5deee74c…`, prereg `bfd69d10…`, rel-v4, C2,
`map_guided_forced`, 1278624577}; operator contract `0c9c82a8…`):

| rate | value |
|---|---|
| inclusive (63 steady-state periods, mean 1.035 s) | 3479.6 evaluations/hour, CoV 0.0193 |
| nominal (61 clean periods; `excluded_seqs [35, 50]`) | 3484.7 evaluations/hour, CoV **0.0175** (≥ 60 clean: 61) |
| planning (64 candidates over the 68.41 s span) | **3367.8 evaluations/hour** — what S derives N from, with C1's 3381.4 |

Per-candidate wall mean 0.969 s, CoV 0.0205. Stage means: sign 0.116 s, stage 0.041 s,
link-2 DMA 0.021 s, link-3 0.062 s, audit 0.486 s (0.504 s and 0.553 s for the two
recovered), ARM + settle + score 0.226 s; settle polls 16 throughout. Recovery indicators:
`candidates_with_recovery 2` ≤ 3, `pull_timeouts 0`, `bad_frames 0`, `fragments 0`,
`sign_retries` / `ready_resends` / `ident_repeats` / `term_retries` / `done_replays` /
`hb_missing` all 0; `heartbeat_findings_rel` empty (1056 indexed heartbeats). C1 #6 and
C2 #2 differ by 0.4 % in planning rate — the map-guided operator's compute time is not
visible at this resolution; the min of the two planning rates would size a 2 h S at
N = ⌊0.9 × 3367.8 × 2⌋ = 6062 candidates (derived by the runner, not typed here).

## 5. What this session establishes, and what it does not

Established: the rel-v4 image runs a complete map-guided C2 on 17A6 under the frozen v0.6
with every §6 condition machine-checked; the pull's CRC re-request works on the physical
console path for real corruption events (two, both recovered on the first resend, each
inside its candidate's period); the two controls and every transaction behave as in C1 #6.
Not established: anything about the timeout / READY-resend / AUDITWAIT / TERMGET paths
(untriggered); the 2 h soak; Claim B; other dies; the console's failure rate beyond
"2 corrupted lines in 1789 inbound lines of this session".

## 6. Open for the owner (not decided here)

1. Independent review of C2 #2 and, if PASS, the `calibration.C2` pin (`959790d0…`; report
   bytes + binding + the three input files) — the manifest then changes.
2. Whether the S session is opened (the stop-loss exception covered this one C2 only); S
   would derive N, audits, frames, budget and timeout from the two pinned planning rates.
3. C1 #5 is not re-judged by anything here.
