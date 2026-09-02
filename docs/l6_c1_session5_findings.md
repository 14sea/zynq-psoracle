# L6 session C1 #5 (2026-09-02-01) — HOLD (instrument, prereg v0.4 §6 item 3): the first rec-v3 epoch COMPLETED and audited end to end, the forced REC-retry control exercised exactly, but one audit chunk lost bytes, the pull retried it, and the 2.1 s retry put the coefficient of variation at 0.274 > 0.10

**Standing: HOLD (CoV 0.274 over the 63 steady-state periods; the bound is 0.10). Every
other PASS condition of §6 holds: `TERM COMPLETED`, 66 SCORED records (1 + 64 + 1), both
baselines exactly `[18, 22, 20, 20, 20, 18]`, the closing unsigned control refused with
fault 13, 66/66 audits pulled and verified, REC closure clean, the IDENT declaring
`rec-v3` with the control echoed, the seq 1 control ledger exactly `["crc", "ok"]`, 1785
protocol frames exactly as expected, zero disruptions, the validator accepting. Nothing
is pinned: `rate_report.json` (sha `3253157c…`) is published as §6 item 3 requires and is
not a calibration. Per the owner's authorisation (one C1 epoch, any non-PASS archived and
NOT re-run) this session is archived as it stands.** Evidence
`evidence/l6_17A6_2026-09-02-01-C1/`; rulings `2026-09-02-01` (whole-of-probe P3-L6,
session C1, master_seed 1278624577; provisioning P3-K; both bound to prereg `12799ef9…`,
image `403f4ab5…`, manifest `f12b6958…`; both consumed with outcome HOLD); boundary
`evidence/boundary/principal_boundary_2026-09-02-01.json` (R1–R5 PASS, 18:04, minutes
before). First hardware run of the rec-v3 image `403f4ab5…` and of prereg v0.4.

## 1. What the board did — the whole epoch, correctly

Power cycle (UART re-enumerated 18:04:26, `/dev/ebaz-uart → ttyUSB4`, dmesg `ch341-uart
converter now attached`), boundary PASS, preflight READ, carrier `956379fa…` loaded over
ymodem, FCLK0 50.0 MHz (IO PLL 1600 MHz, div 8 × 4), CPU clock control `0x1f000200`,
IDCODE `0x13722093`, `boardid=17A6 role=verify`, image `403f4ab5…` (98 324 bytes at
`0x02000000`, hash checked by the runner). **IDENT 1.2.0: `protocol: rec-v3`,
`rec_retry_control: true`**, `schedule_mode random_safe_forced`, `master_seed
1278624577`, operator data `0c9c82a8…`, token `b108aac4…`. `go` at 18:09:14; TERM 65.9 s
later.

**66 records, all `SCORED`, chain length 67:** seq 1 the opening baseline, seq 2–65 the 64
scheduled random-safe candidates (`arm_check` 64/64, brackets [1, 66]), seq 66 the closing
baseline. Both baselines score `[18, 22, 20, 20, 20, 18]` with `hw_candidate_commit`
`3e24d936…`. Closing control refused with fault 13 (status `0x00000982`, nonce advanced).
`TERM COMPLETED / budget`; the board's own summary: `audited 66/66`, `scored 66`,
`refused_by_gate 0`, `crc_dropped 0` (board side — the control's corrupted line is the
host's drop, not the board's), closing baseline/restore/unsigned control all `done`.
Zero disruptions, `epoch_final 0`.

**Frames:** 1785 valid inbound protocol frames, equal to `expected_frames.total` (IDENT 1,
SIGNREQ 66, HB 1056, REC 66, AUDIT_READY 66, AUDIT 528, CLOSE 1, TERM 1), plus the two
non-frames the ledger records separately: one `CRC_DROP` (the control, type REC) and one
`BAD_FRAME` (§3). Outbound 795: SIGNOK 66, AUDITREQ 66, AUDITGET 530 (528 + the two
re-requests of §3), AUDITDONE 66, RECACK 66, RECGET 1 (the control). `crc_dropped 1` of
budget 8, by type `{"REC": 1}`; `bad_frames 1`; `transport_rereads []` (the md.l
re-read counter of §2b — no register read was repeated); no AUDITABORT.

**Audit:** 66/66 served over `streams+readback`, 2814 words each; for every record the
recomputed `staged_stream_sha256` / `staged_sha256` / `readback_sha256` equal the
self-report (`audit_verification.compared` all true). `run_log_validation: scored 66,
audited 66, chain_length 67`; the validator accepted.

## 2. The forced REC-retry control — exercised exactly as §2.6c states (PASS items 6, 7, 8)

At go + 1.02 s the first `REC 1` arrived with its CRC deliberately corrupted by the board
(`flags.bit4` armed by the runner) and was dropped (`crc_dropped_by_type {"REC": 1}`,
the session's only CRC drop); the host sent `RECGET 1`; the resend at go + 1.22 s was
accepted and ACKed. Ledger for seq 1: attempts `["crc", "ok"]`, `gets_sent 1`,
`acks_sent 1`, accepted, no conflict. Every other seq: attempts `["ok"]`, `gets_sent 0`,
`acks_sent 1`, accepted. `rec_closure_findings` and `rec_control_findings` are empty —
the summary's `findings` holds the CoV line only.

## 3. The fault — AUDIT 39 chunk 1: bytes lost, the pull re-requested it twice, 2.1 s spent

Candidate seq 39 (`random_safe`, scores `[18, 22, 20, 19, 21, 18]`, audited and
verified). `AUDIT_READY 39` at go + 36.86 s; chunk 0 arrived clean 62 ms later. Then:

1. `AUDITGET 39 chunk 1` — the reply reached the host as **576 bytes with no line
   terminator** (a valid chunk-1 line is 652 bytes). Its base64 body (533 chars) shares
   only its first 529 chars with the valid body (596 chars): bytes were lost *inside* the
   line as well as at its end. The host's chunk timeout (≈2.09 s, `console.tick`) expired
   with the line still open — ledger attempt 0 `timeout`.
2. `AUDITGET 39 chunk 1` again — the board resent; the receiver, still holding the
   unterminated 576 bytes, delivered the two as one 1228-byte line (`… InN0cmVhbP3L5
   AUDIT 39 …`), which failed framing — `BAD_FRAME` (`bad_frames 1`; **not** a CRC drop,
   `crc_dropped 0` for this pull). Ledger attempt 1 `malformed`.
3. `AUDITGET 39 chunk 1` a third time — a clean 652-byte line, CRC `39652dde`, attempt 2
   `ok`. Chunks 2–7 then arrived at the usual 40–80 ms spacing; `AUDITDONE` at
   go + 39.40 s. Pull ledger: `done true`, `failed false`, `timeouts 1`.

Cost: the audit stage of seq 39 is 2.539 s against a median of 0.457 s (the other 63
candidates lie in 0.391–0.502 s); its period is 3.095 s against a median of 0.965 s
(the other 62 steady-state periods lie in 0.854–1.055 s). With that one period the
sample CoV is **0.274** (`cov_wall 0.287`); without it, 0.056 — stated for the
distribution's sake only, §6 item 3 includes retries in the audit stage by design and the
bound is over all steady-state periods.

The wire path is unchanged (CH340 → usbipd → WSL `vhci_hcd`, no flow control). dmesg
around the fault (clock aligned on the ch341 attach at 18:04:26): an FTDI ghost node
`ttyUSB0` disconnected at 18:08:49 (before `go`, a different device), and the `vhci_hcd`
unlink lines at 18:10:22 are the runner closing the port at session end. **Nothing at
18:09:52.** Same family as C1 #1, C1 #3 and S #1: a contiguous run of console bytes
missing inside a ~600-byte burst; the fifth event of the series, the first under
rec-v3, and the first the pull recovered from within a completed epoch.

## 4. What this session establishes, and what it does not

- The rec-v3 image `403f4ab5…` ran a full C1 epoch on 17A6: the REC transaction, the
  forced control, the closure check and the sparse pull all behaved as the prereg and the
  twin describe. No image defect was observed.
- The pull-v2 retry recovered a byte loss inside an audit line — C1 #3's failure mode —
  and the epoch completed. The cost of one recovery (one chunk timeout + two re-requests
  ≈ 2.1 s) is larger than the CoV bound tolerates in a 64-candidate session.
- The rate is informational: 3607.8 evals/h over 63 periods (C1 #4 under pull-v2:
  3909.9, CoV 0.016; C2 #1: 3633.0, CoV 0.015). Not a calibration; `calibration.C1` stays
  null.
- Not a Claim B data point. The stop-loss count is the owner's: under §7 as frozen, S #1
  (REC line lost) and C1 #5 (AUDIT line lost, recovered, CoV) are consecutive sessions
  lost to console byte loss; whether that is "the same instrument cause" is not decided
  here.

## 5. Open items for the owner (not decided here)

1. Classification under §7: whether C1 #5 counts with S #1 as two consecutive losses to
   the same cause (→ stop, fix, host-side proof before a third ruling), or as a distinct
   outcome (a recovered transport event that fails a statistical bound).
2. Whether §6 item 3's bound should stay as frozen (retries inside the period, CoV over
   all steady-state periods) — under which any single ~2 s recovery fails a 64-candidate
   C1/C2 — or whether a v0.5 should state how a recovered retry enters the rate (e.g. a
   CoV over the periods without a retry alongside the full one, both published, with the
   retry count bounded). Any such change is host-only, reviewed, and re-frozen before a
   new ruling.
3. The chunk timeout (≈2.09 s observed): the loss was detectable within ~100 ms of the
   burst's end (chunks arrive 40–80 ms apart); a shorter bounded wait would shrink the
   cost of a recovery without changing what is recovered. Same review path as item 2.
4. Loss statistics: `host/l6_loss_stats.py` now covers seven sessions
   (`docs/l6_console_loss_summary.md`): five loss events over 5,566,850 bytes, 0.90 per MB,
   still exposure only; the seq 1 control drop is recorded apart, not as a loss.
