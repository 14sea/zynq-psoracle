# L6 session C1 #1 (2026-09-01-06) — HOLD: one contiguous byte loss on the console inside seq 24's audit burst

**Standing: HOLD (instrument/transport, prereg §6). Not a Claim B data point. The staged board
batch is stopped at C1 per the owner's rule; C2 has not run. No calibration pin was written.
Board untouched since the runner closed the port; the application was left running on the
board and, with no further kicks, the 30 s watchdog resets the PS on its own.**

Evidence `evidence/l6_17A6_2026-09-01-06-C1/`; rulings `rulings/p3_l6_2026-09-01-06.json` and
`rulings/p3_k_2026-09-01-06.json`, both consumed; boundary
`evidence/boundary/principal_boundary_2026-09-01-06.json` (R1–R5 PASS, written minutes before).

## 1. What ran

| | |
|---|---|
| image | `bd1454cd…` (the two-operator image), pinned; loaded and entered with `go` |
| preflight | every gate passed: ruling text and bindings (session C1, master seed 1278624577, prereg `90f5fa69…`, image `bd1454cd…`, manifest `63ab9374…`), P3-K ruling present and unconsumed, frozen carrier by file hash, boundary bound to the invocation |
| identity | IDENT 1.1.0: `master_seed 1278624577`, `schedule_mode random_safe_forced`, `operator_data_sha256 0c9c82a8…`, no findings — the compiled-in map data is the pinned derivation |
| watchdog | `flags.bit1 = 1` (flags word `0x6`): the first session with the watchdog ON; the application ran 23 candidates under it without a timeout, so the pre-init kick defect of `47b8fa09…` is confirmed absent on hardware |
| records | seq 1 (opening baseline, scores `[18, 22, 20, 20, 20, 18]`) and seq 2–23, all `SCORED`, each with 16 HB and 8 audit chunks, `arm = random_safe` on every candidate and none on the baseline |
| end | `CRASHED: unparseable frame` at seq 24 (collector §3c); `crc_dropped 0`, `bad_frames 1`, `disruptions []`, `transport_rereads []` |
| adjudication | `HOLD instrument: run_log rejected: audit seq 24: chunk numbers must be exactly 0..7: missing [4, 5, 6, 7]` — the validator's transport-class RecordError (not `Falsified`) |

## 2. The fault

In seq 24's audit burst the console stream lost one contiguous run of bytes: the line for
chunk 4 ends mid-payload and continues, without a newline, with the tail of chunk 5's header
(`…df8092c634f7d5880e20 eyJjaHVuayI6NSwi…` — the token's last 20 hex, the space, and chunk
5's payload). One 6002-byte line resulted; a normal chunk line is 3020 bytes, so about 38
bytes were lost across the boundary of the two lines. The line has seven space-separated
fields, so `parse_line` raised `FrameError` ("not a P3L5 frame") rather than `CrcError`, and
the collector's rule for a malformed frame is an immediate `CRASHED`. Chunks 5–7 of seq 24
then arrived intact but after the epoch end and were not evidence; the REC for seq 24 and the
SIGNREQ for seq 25 followed likewise.

Nothing else was lost in the session: 625 received frames, one bad, zero CRC failures. `dmesg`
carries no USB error at the time (its `vhci_hcd urb->status -104` lines are the port being
closed by the runner). The path is CH340 → usbipd → WSL `vhci_hcd`, no flow control; the L5
sessions moved ~250 KB of frames each without loss; this session had moved ~600 KB of frames
when the loss occurred. **Classification: a transport fault on the console, prereg §6 HOLD;
first occurrence; cause named as transport (§7 allows one repeat without a change).**

## 3. A second finding, about the instrument: the per-frame timestamps are per-burst

`SerialTransport.drain()` (zynq-psmap, not modifiable here) loops `read(4096)` on a port
opened with `timeout = 0.1` until a read returns nothing — i.e. it returns only when the board
has been silent for 100 ms. Inside a candidate the application never pauses that long, so all
26 frames of a candidate came back from one `drain()` and received one stamp: **25 distinct
receive stamps for 625 frames**. `t_signreq` is accurate (the SIGNREQ ends a burst — the board
waits for the reply), so the inter-proposal `period` and the rate are sound; but `t_rec` is
the *next* burst's stamp, so `wall ≈ period` and the six-stage breakdown is meaningless on
hardware (`stage` absorbed everything). `tests/test_l6_timing.py` proved attribution on
session 4's frame *order* with synthetic stamps; it could not see this. The §4.1 claim
"resolution ≈ one 20 ms poll" is wrong for the real transport and must be corrected.

Host-only fix (not applied — the batch is stopped): during the console phase the runner
should read the port non-blockingly itself (`_serial.timeout = 0`, `read(in_waiting)` per
20 ms poll) instead of `drain()`, so a stamp is a poll again; a test must drive the reader
with a transport that emits the frames at distinct times and assert distinct stamps.

## 4. Numbers (information only — a HOLD session pins nothing)

Over the 21 steady-state periods (seq 2 → 23): mean 2.449 s, CoV 0.019, **≈ 1470 evaluations
per hour** for the random-safe arm on this path — an order of magnitude faster than the L5
rate the preregistration's "2 h" was sized against by feel. At this rate the soak's
N = ⌊0.9 × min(rate) × 2 h⌋ would be in the thousands, and a C1/C2 all-self-reporting
session moves ~1.6 MB of audit frames over a link that has now shown one byte drop in
~600 KB.

## 5. What this session does and does not establish

- Establishes on hardware: the two-operator image boots, identifies, runs the random-safe
  schedule with the watchdog ON, emits 1.1.0 records the collector parses, and 23 candidates
  scored in a row with correct baselines — the §2 image is not the reason for the HOLD.
- Does not establish: C1 (no calibration record; `calibration.C1` stays null), anything about
  the map-guided arm, anything about the soak, any Claim B datum.

## 6. Options for the owner (not decided here)

1. Repeat C1 once with no change, as §7 permits for a transport cause named as such. The
   exposure is unchanged: any byte drop inside an audit burst is a HOLD under
   all-self-reporting, and the timestamp breakdown will again be per-burst.
2. First a host-only instrument batch: (a) the non-blocking reader so stamps are per poll
   (§3); (b) optionally, treat a malformed `P3L5` line as a CRC-class drop against the D-s4
   budget instead of an immediate `CRASHED` — this is a §3c collector-rule change and would
   not by itself rescue a session, because the lost chunks still leave the audit incomplete.
3. Anything that reduces the audit volume per session (fewer chunks, a sampled C1) or adds
   retransmission is a firmware/protocol change and a new review.
