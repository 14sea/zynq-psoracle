# L6 session C1 #2 (2026-09-01-07) — HOLD: the host collector declared silence 0.4 s after `go`

**Standing: HOLD (instrument, host side; prereg §6). Not a transport fault, not a board
fault, not a Claim B data point. `calibration.C1` stays null. The staged batch is stopped
at C1; the owner's stop-loss for a repeated console byte loss was NOT triggered — no byte
was lost, because none was read.** Evidence `evidence/l6_17A6_2026-09-01-07-C1/`; rulings
`2026-09-01-07`, both consumed; boundary `principal_boundary_2026-09-01-07.json` (PASS).

## 1. What happened

Power cycle (the UART re-enumerated 18:42), boundary R1–R5 PASS, preflight every gate,
carrier loaded, provisioning executed, identity page written and read back (`flags 0x6`),
image `bd1454cd…` transferred (`Transfer complete` 18:47:13), `go` sent — and the runner
wrote its summary at 18:47:14: `CRASHED: silence > 30s`, `last_seq 0`, `console.log` **0
bytes**, no IDENT, no frames, `crc_dropped 0`, no disruptions. The "30 s" is the rule's
threshold text; nothing was waited for.

## 2. The cause — in the runner, exposed by the new reader

`run_l6` constructs the `Collector` at its top, before the preamble, and the collector's
silence clock (`last_heard`) starts then. The preamble takes minutes (the 2 MB carrier
ymodem). Before this batch the console loop read through zynq-psmap's blocking `drain()`,
which returned only after 100 ms of board silence — i.e. after the IDENT/SIGNREQ burst —
so `on_line` had refreshed `last_heard` before `collector.poll()` ever ran, and the stale
clock was never seen. `host/l6_reader.L6LineReader` (this batch's fix for the per-burst
timestamps) returns immediately with nothing 20 ms after `go`; the first
`collector.poll()` then compared "now" with a `last_heard` four minutes old and ended the
epoch on the spot. The application on the board very probably ran its session unheard;
the host never read a byte, so nothing about it is evidence.

The same construction order exists in `host/l5_runner.py` and was masked there the same
way; the L5 runner is the PASSed instrument and is not edited — recorded here.

## 3. The fix (host-only, this commit)

`collector.last_heard = collector.clock()` immediately after `go` is sent: silence is
measured from the moment the console is handed to the application, and the 30 s rule
fires only on real silence. `tests/test_l6_reader.py::SilenceClockStartsAtGo` shows the
mechanism on the real `Collector` (a 240 s preamble then an empty first poll → CRASHED
without the reset; with it, live at 29 s of real silence and CRASHED at 31 s) and pins the
reset's position in `run_l6` (after `go`, before the loop, with the collector built before
the preamble).

## 4. Stop-loss accounting

Two sessions currently lack `COMPLETED`, for two different instrument causes (a console
byte loss; a host silence clock). The owner's rule after C1 #1 — a second byte loss of the
same kind stops board repeats — is not met. Prereg §7's inherited rule ("three sessions
without `COMPLETED` → design review before further board time") is met only if a third
session also fails to complete: C1 #3 is permitted after the review of this host fix; if
C1 #3 is also non-`COMPLETED`, design review is mandatory before any fourth board session
(owner, 2026-09-01). This host fix's review is a local one, not that design review.

## 5. What this session establishes

Nothing about the image, the arm, the rate or the transport: the host read no byte after
`go`. It establishes one host defect, now fixed and tested.
