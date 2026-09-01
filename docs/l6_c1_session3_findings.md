# L6 session C1 #3 (2026-09-01-08) — HOLD: two contiguous byte losses inside audit bursts; the board completed the session

**Standing: HOLD (transport, prereg §6). The epoch COMPLETED on the board; the log is
refused by the validator because two audit chunks arrived with bytes missing. Not a Claim B
data point. `calibration.C1` stays null. The owner's stop-loss for a repeat of C1 #1's byte
loss is MET: board repeats stop here and the line moves to transport / protocol design.**
Evidence `evidence/l6_17A6_2026-09-01-08-C1/`; rulings `2026-09-01-08`, both consumed;
boundary `principal_boundary_2026-09-01-08.json` (PASS, minutes before).

## 1. What the board did — everything

Power cycle (UART re-enumerated 18:57), boundary PASS, preflight PASS, image `bd1454cd…`,
watchdog ON, IDENT as pinned. **66 records, all `SCORED`: the opening baseline, 64
scheduled random-safe candidates, the closing baseline — both baselines exactly
`[18, 22, 20, 20, 20, 18]`, the closing unsigned control refused with fault 13, `TERM`
`COMPLETED / budget`, 1056 HB (16 each), 66 REC, 528 audit chunks sent.** Zero
disruptions, no board-side stop of any kind. Both host fixes worked: 931 distinct receive
stamps for 1719 frames (per read, not per burst), and no false silence at `go`.

## 2. The fault — the console lost bytes twice, both inside audit bursts

Two `AUDIT` lines failed CRC and were dropped: seq 20 chunk 3 (2711 bytes on the wire
instead of 3019 — **308 bytes missing**, contiguous, inside the payload) and seq 62 chunk
3 (2791 bytes — **228 missing**). Every other line of the session parsed and verified; the
lost bytes fell wholly inside one line each time, so no line boundary was destroyed, no
frame was malformed, and the collector correctly counted them as CRC drops rather than a
crash. The validator then refused the log at the first incomplete audit (`audit seq 20:
missing [3]`) — a transport-class `RecordError`, not a falsifier.

This is the third contiguous byte loss on the console in three sessions, all inside audit
bursts (38, 308 and 228 bytes; C1 #2 read nothing). The path is CH340 → usbipd → WSL
`vhci_hcd`, no flow control, 115 200 baud, the application streaming 24 KB of audit per
candidate back-to-back. The breakdown the new reader made visible says where the exposure
is: per candidate, `audit` 1.845 s of a 2.27 s period — 76 % of the link's time is the
audit stream, and every byte of it must arrive intact for an all-self-reporting session
to pass.

## 3. Two host findings on the way

1. **The D-s4 CRC budget is not enforced for audit lines.** The runner hands only
   `SIGNREQ` lines to `NotaryRelay.handle_line`, which is where CRC drops are counted
   against the budget; `AUDIT`/`HB`/`REC` lines that fail CRC are dropped by the collector
   without being counted there. The summary therefore says `crc_dropped 0` while the
   timeline counted 2. The budget must count every dropped line (host-only fix, not made
   here: the batch is stopped).
2. The rate report, now with a real breakdown (information only, nothing is pinned): 64
   candidates, 63 steady-state periods, **1586 evaluations/hour, CoV 0.019**, failure
   rate 0; per candidate sign 0.10 s, stage 0.04 s, link2+DMA 0.02 s, link3 0.04 s,
   audit 1.85 s, ARM+settle+score 0.19 s.

## 4. Stop-loss

C1 #1's byte loss recurred (twice). Per the owner's ruling of 2026-09-01, board repeats
stop immediately; no fourth C1 ruling; the next step is transport / protocol design. The
session count for prereg §7 is three without a `PASS` (two non-`COMPLETED`, one
`COMPLETED`-but-refused), so a full design review precedes any fourth board session in
any case.

## 5. What this session establishes

On hardware, for the first time: the two-operator image completes a 64-candidate
random-safe session under the watchdog with correct brackets and closing control, and the
instrument's timestamps and silence clock behave. It does not establish C1 (the audit
record is incomplete), and it shows that the console link, as it stands, cannot carry an
all-self-reporting session of this size reliably.

## 6. Options for the design review (not decided here)

- Protocol/firmware: re-request or retransmit an audit chunk that fails CRC (the words
  stay in the board's buffers until the record is emitted); or smaller chunks with the
  same total; or an audit rate below 100 % for calibration too (the prereg fixed C1/C2 as
  all-self-reporting — a prereg change).
- Transport: a different host path for the console (a direct FTDI/CP210x port on the
  host instead of CH340 over usbip; hardware flow control) — an instrument change with
  its own identity gate.
- Host: count every CRC drop against the budget (finding 3.1), regardless.
