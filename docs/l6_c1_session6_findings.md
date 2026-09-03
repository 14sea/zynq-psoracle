# L6 session C1 #6 (2026-09-03-01) — PASS (runner outcome): the first rel-v4 epoch under prereg v0.6 COMPLETED and audited end to end, both forced retry controls exercised exactly, every transaction closed on its first transmission, no recovery anywhere

**Standing: PASS as the runner adjudicated it (prereg v0.6 §6, all items; `findings: []`).
This is the ONE rel-v4 C1 the owner's conditional stop-loss lift authorised (owner
2026-09-03, after the frozen-artifact short review PASS and the push of `d836107`). It
is a runner outcome, not yet an owner adjudication: `calibration.C1` stays null until the
owner pins `rate_report.json` (sha `08222f85799fa3d18012cdd26a5cc047527995b682bfd5679a668014ea03251c`)
by hash (D-s3); C2, S and Claim B stay closed until the owner rules on them; C1 #5 keeps
its permanent HOLD under v0.4.** Evidence `evidence/l6_17A6_2026-09-03-01-C1/`; rulings
`2026-09-03-01` (whole-of-probe P3-L6, session C1, master_seed 1278624577; provisioning
P3-K; both bound to prereg `bfd69d10…`, image `5deee74c…`, manifest `1746cdfa…`; both
consumed with outcome PASS); boundary `evidence/boundary/principal_boundary_2026-09-03-01.json`
(R1–R5 PASS, minutes before). First hardware run of the rel-v4 image `5deee74c…` and of
prereg v0.6.

## 1. What the board did — the whole epoch, correctly

Power cycle by the owner (UART re-enumerated 15:46, `/dev/ebaz-uart → ttyUSB4`, dmesg
`ch341-uart converter now attached`), boundary PASS, preflight READ (`CPU_CLK_CTRL`
`0x1f000200` — the 6:2:1 clock the image's 8 s bound is derived from), carrier
`956379fa…` loaded over ymodem, FCLK0 50.0 MHz (IO PLL 1600 MHz, div 8 × 4), IDCODE
`0x13722093`, `boardid=17A6 role=verify`, devcfg precheck all passed, provisioning rc 0,
image `5deee74c…` (98 324 bytes at `0x02000000`, hash checked by the runner), identity
page written (`random_safe_forced`, N 64, watchdog bit1, bit4 and bit5 armed). Token
`4700603f…`.

**IDENT 1.3.0: `protocol: rel-v4`, `rec_retry_control: true`, `sign_retry_control: true`**,
`master_seed 1278624577`, operator data `0c9c82a8…`; the host verified it and sent
`IDENTACK` — one transmission, one acknowledgement (ledger `ident`: attempts `["ok"]`,
`acks_sent 1`, accepted, not refused, no conflict). Epoch span (first `SIGNREQ` to last
`REC`) 68.1 s; `TERM` 68.4 s after the IDENT; the runner kept reading for the 22 s TERM
linger and closed the port (the `vhci_hcd urb->status -104` lines in dmesg are that
close, 22 s after the TERM, not a fault during the epoch).

**66 records, all `SCORED`, chain length 67:** seq 1 the opening baseline, seq 2–65 the 64
scheduled random-safe candidates (`arm_check` 64/64, brackets [1, 66]), seq 66 the closing
baseline; `baseline_findings` empty (both baselines the pinned `[18, 22, 20, 20, 20, 18]`).
Closing control refused with fault 13 (status `0x00000982`, nonce `7110b726…` →
`543b14bc…`), carried in the TERM's `closing_control` block AND in a `CLOSE` frame that
arrived — `closing_conflict: null` (the two agree). `TERM COMPLETED / budget`; the board's
own summary: `audited 66/66`, `scored 66`, `refused_by_gate 0`, `crc_dropped 0` (board
side), closing baseline/restore/unsigned control all `done`. Zero disruptions,
`epoch_final 0`, `transport_rereads []`.

**Frames:** 1785 valid inbound protocol frames, equal to `expected_frames.total` (IDENT 1,
SIGNREQ 66, HB 1056, REC 66, AUDIT_READY 66, AUDIT 528, CLOSE 1, TERM 1), plus the two
`CRC_DROP` non-frames that are the two controls (§2). Outbound 730: IDENTACK 1, SIGNOK 66,
SIGNGET 1 (the control), AUDITGET 528, AUDITDONE 66, RECACK 66, RECGET 1 (the control),
TERMACK 1 — no `AUDITREQ` frame exists under rel-v4 (`audit_requested` rides in SIGNOK).
`crc_dropped 2` of budget 8, by type `{"SIGNREQ": 1, "REC": 1}`; `bad_frames 0`;
`fragments 0`; no AUDITWAIT, no AUDIT_READY resend, no SIGNGET beyond the control, no
TERMGET, no replay.

**Audit:** 66/66 served over `streams+readback`, 2814 words each; for every record the
recomputed `staged_stream_sha256` / `staged_sha256` / `readback_sha256` equal the
self-report (`audit_verification.compared` all true); every pull `AUDIT_READY` → 8 ×
(`AUDITGET` → `AUDIT`) → `AUDITDONE` with zero retries, zero timeouts, zero duplicates
(`pulls`: 66 ledgers, `gets` 528). `run_log_validation: scored 66, audited 66,
chain_length 67`; the validator accepted.

## 2. The two forced retry controls — exercised exactly as §2.6c and §2.6k state (items 6, 12)

- **SIGNREQ control (flags.bit5):** the first `SIGNREQ 1` arrived with its CRC corrupted by
  the board and was dropped (`crc_dropped_by_type {"SIGNREQ": 1}`); the host sent
  `SIGNGET 1`; the resend 0.19 s later was accepted and signed once. Sign ledger for
  seq 1: attempts `["crc", "ok"]`, one `SIGNGET`, `replays 0`; every other seq `["ok"]`.
  `rel_control_findings` empty.
- **REC control (flags.bit4):** the first `REC 1` arrived corrupted and was dropped
  (`{"REC": 1}`); the host sent `RECGET 1`; the resend 0.23 s later was accepted and
  ACKed. REC ledger for seq 1: attempts `["crc", "ok"]`, `gets_sent 1`, `acks_sent 1`;
  every other seq `["ok"]`. `rec_closure_findings` and `rec_control_findings` empty.

Both drops are attributed as `control_drops 2` in the rate report's recovery block, not as
recoveries (D-t2); `candidates_with_recovery 0`, `recovered_seqs []`.

## 3. The rate — the three rates of D-t1 (items 3, 3a–3d), nothing pinned here

`rate_report.json` 1.2.0, derived from the three files beside it as read back from disk
(`inputs`: run_log `9cb4ebdb…`, audits `3444e389…`, timeline `130446bc…`), `binding` =
{image `5deee74c…`, prereg `bfd69d10…`, protocol rel-v4, C1, `random_safe_forced`,
1278624577}, operator contract `0c9c82a8…`:

| rate | value |
|---|---|
| inclusive (63 steady-state periods, mean 1.030 s) | 3495.7 evaluations/hour, CoV **0.0151** |
| nominal (the same 63 — no candidate recovered; `excluded_seqs []`) | 3495.7 evaluations/hour, CoV 0.0151 (≥ 60 clean: 63) |
| planning (64 candidates over the 68.14 s bracketed span) | **3381.4 evaluations/hour** — what a v0.6 S derives N from |

Per-candidate wall (SIGNREQ → REC) mean 0.967 s, CoV 0.0159. Stage breakdown (means):
sign 0.115 s, stage 0.041 s, link-2 DMA 0.021 s, link-3 readback 0.062 s, audit
(`AUDIT_READY` → `AUDITDONE`, 8 chunks) 0.482 s, ARM + settle + score 0.226 s; settle
polls 16 for every candidate. Recovery indicators all 0 (`pull_retries`, `pull_timeouts`,
`pull_crc`, `pull_malformed`, `duplicates`, `rec_retries`, `rec_gets`, `crc_drops`,
`bad_frames`, `fragments`, `sign_retries`, `ready_resends`, `done_replays`, `hb_missing`,
`ident_repeats`, `term_retries`), so every §6.3b and §6.13 bound holds with margin;
`heartbeat_findings_rel` empty (16 indexed heartbeats per record, 1056 in all).

Compared with C1 #5 (rec-v3, 3607.8 evaluations/hour inclusive over 62 clean periods
after the recovered chunk): the rel-v4 candidate period is ≈ 0.06 s longer — the SIGNREQ
transaction's acknowledgement and the `AUDITDONE` handshake sit inside it — and the
spread is the instrument's own (CoV 0.015, as C1 #4's 0.016 and C2 #1's 0.015 under
pull-v2). These numbers are informational until the owner pins them (D-s3).

## 4. What this session establishes, and what it does not

Established: the rel-v4 image runs a complete C1 epoch on 17A6 under the frozen v0.6 with
every §6 condition satisfied by machine-checked evidence; the IDENT/SIGNREQ/REC/TERM
transactions, the DONE handshake and the two controls behave on the board as their twins
did; the bound contract's premise (`CPU_CLK_CTRL 0x1f000200`) held. The 8 s board bounds,
the AUDIT_READY resend, AUDITWAIT and TERMGET paths were **not exercised** — nothing was
lost on the console in this session (no byte-loss event; the seventh L6 board session,
event count unchanged at 5) — so this session says nothing about recovery on the physical
path beyond the two deliberate controls. Not established: anything about C2's operator,
the 2 h soak, Claim B, other dies, or the physical console path's failure rate.

## 5. Open for the owner (not decided here)

1. Adjudicate C1 #6 and, if PASS, pin `rate_report.json` `08222f85…` as `calibration.C1`
   (report bytes + binding + the three input files, D-s3/D-r5/D-t2) — the manifest then
   changes and the C2 ruling pair binds the new hash.
2. The stop-loss standing for C2: the conditional lift covered this one C1 only.
3. C1 #5 is not re-judged by anything here.
