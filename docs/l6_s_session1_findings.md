# L6 session S #1 (2026-09-01-11) — HOLD: one REC line lost bytes 231 s into the soak; the collector ended the epoch; a second, host-side defect in the crash path

**Standing: HOLD (transport, prereg §6 — `CRASHED` before 1 h). The board did not stop:
464 SCORED records in 231 s, every one of the 31 sampled audits pulled and verified, 0
rereads. At record 465 the REC line arrived with ~536 contiguous bytes missing, failed CRC,
was dropped (1 of budget 486), and the collector — seeing seq 466 after 464 — ended the
epoch as `CRASHED: record seq gap`. Prereg §6 item 4 makes a missing `REC` fatal
regardless of the CRC budget, so this is the correct outcome for the protocol as frozen.
Not a Claim B data point; nothing is pinned; per the owner's ruling this S is archived and
NOT re-run.** Evidence `evidence/l6_17A6_2026-09-01-11-S/`; rulings `2026-09-01-11` (both
bound to manifest `bb63b31d…`, both consumed with outcome HOLD); boundary
`principal_boundary_2026-09-01-11.json` (PASS, 21:13).

## 1. What the board did — 231 s of a correct soak

Power cycle (UART re-enumerated 21:13:19), boundary PASS, preflight READ, carrier and image
loaded (image hash checked), IDENT as pinned, token `da08f206…`. The runner derived the S
parameters from the two pinned calibration reports and they equal the owner's independent
derivation exactly: `abba`, seed 1278628687, N 6539, records 6541, sampled audits 412,
expected inbound frames 121 449, CRC budget 486 (`ceil(4 × 121449 / 1000)`), session
timeout 8702 s, flags 2. `go` at 21:17:48.

From `go` to the fault: **464 SCORED records (seq 1–464), no gap, 7456 HB (16 per record
through seq 466), 466 SIGNREQ, 465 REC received, 31 `AUDIT_READY` + 248 `AUDIT` chunks
(the sampled schedule: seq 1, 2, 16, 32, … 464 — all 31 due by then) — every audit pulled
in one attempt, `transport_rereads []`, no abort.** `loop_records.verified`: 31 `audited`,
433 `replayed-only`. Zero disruptions, `epoch_final 0`, `refused_by_gate 0`. The pace was
≈2.0 records/s (464 in 231 s), i.e. ≈7200 evals/h of interleaved A/B — above both
calibrations, as the soak's sampled audit (1 in 16) predicts.

## 2. The fault — REC 465 lost ~536 bytes; the collector ended the epoch

`console.log` line 8652 is `P3L5 REC 465 …`: 1775 bytes where its neighbours (REC 464,
REC 466) are 2307 and 2315 — one contiguous interior run of ≈536 bytes missing; the line's
tail (`…"seq":465,"verified":"replayed-only"}` + CRC token) is intact. CRC failed → dropped
(`timeline.crc_dropped_by_type {"REC": 1}`, the only drop of the session, budget 486). The
board went on: SIGNREQ 466, 16 HB, REC 466 (complete), SIGNREQ 467 all arrived. The
collector, on REC 466 after REC 464, wrote `epoch_end CRASHED: record seq gap: 466 after
464` (session_summary `written_by: collector`, closing `not_reached`) and the runner
stopped the session at 21:21:40 — 231.5 s after `go`, 1.78 MB received.

Timing on the host clock: REC 464 at go+230.571, SIGNREQ 465 at +230.592, its 16 HB by
+230.824, **REC 465 at +231.0 (dropped)**, SIGNREQ 466 at +231.051, REC 466 at +231.508.
Nothing unusual precedes the loss: the HB cadence of records 464–466 is identical to every
earlier record.

**This is the C1 #1 / C1 #3 fault family** (a contiguous run of console bytes missing
inside a burst) landing, for the first time, on a `REC` line rather than an audit chunk.
The pull protocol recovers lost audit chunks (and did, in design; here none were lost) but
has no re-request for `REC`, so a lost REC is a lost record and §6 item 4 ends the session.
Loss-event tally for the line so far: C1 #1 (~38 B, audit), C1 #3 (308 B + 228 B, audit),
S #1 (~536 B, REC); C1 #4 and C2 #1 were loss-free over ~2.3 MB each; this one hit at
1.78 MB.

Host USB record: `dmesg` shows no USB/tty event at the fault time. The one event in the
window — the ghost `ttyUSB0` FTDI disconnect — maps to ≈21:17:24 (dmesg clock corrected by
the 21:13:19 ch341 attach), 24 s **before** `go`, during the app-image ymodem, which
completed. So the cause is not named as a host USB event; it is the same unexplained
console byte loss.

## 3. Second finding — host-side: the crash-path summary says 0 audited

The validator's rejection reason is not the seq gap but `(ix) summary says 0 audited, the
host verified 31`. The collector-synthesised `session_summary` on the CRASHED path carries
`audit.audited 0` while the run log holds 31 verified audits. This is a host instrument
defect in the crash path only (a COMPLETED session's summary is written by the app and
was correct in C1 #4 / C2 #1); it does not change the outcome (the seq gap is fatal on
its own) but it mislabels the rejection and must be fixed before the next S so that a
crash record states its own audit count truthfully. Not fixed here — the ruling covers one
S and nothing else.

## 4. Classification and stop-loss

- Prereg §6: `CRASHED` before 1 h → **HOLD**; "re-run after the cause is fixed and named";
  the repeat-once clause needs ≥ 1 h and a transport cause named from the host record —
  neither holds. The owner's ruling for this session: non-PASS is archived, not re-run.
- Prereg §7 (L6's own): a soak that fails the same way twice is the result. This is S
  failure #1. L5 §6's "two consecutive sessions to the same instrument cause" is not met
  (C2 #1 passed). The owner lifted the pull-v2 stop-loss for C2 with future faults
  re-counted under §7: this is the first such fault after the lift.

## 5. Options for the owner (not decided here)

1. **REC re-request** in the pull protocol (a `RECGET`/`REC` retry, the same shape as
   `AUDITGET`), so a CRC-dropped REC is refetched like an audit chunk — the natural closure
   of pull-v2 for the one frame type §6 item 4 protects absolutely. Firmware + host +
   twin + prereg v0.4 + review before any board time.
2. Fix the collector's crash-path summary to carry the host-verified audit count (item 3).
3. Whether the loss statistics (`host/l6_loss_stats.py`, three C1 sessions) should be
   extended with C1 #4, C2 #1 and S #1 — 6.4 MB more with one event — before a design
   decision on the console link itself.
