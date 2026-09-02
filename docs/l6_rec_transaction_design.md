# L6 — the REC transaction (rec-v3): design and what the host-only batch proves

> **Standing: host-only, delivered 2026-09-01 in the owner's pre-board protocol
> correction batch after S #1; corrected 2026-09-02 after the owner's review (§8).** No
> ruling, no board, no S. After the owner's full P3 compatibility review PASS (2026-09-02)
> the image `403f4ab5…` is the board-ready pin (`protocol: rec-v3`) and prereg v0.4 is
> frozen; it has never run; the first candidate `cd8360dc…` is withdrawn DEFECTIVE (§8).

## 1. What it has to fix

S #1 (ruling `2026-09-01-11`): 464 SCORED records in 231 s, every audit pulled and verified,
then `REC 465` arrived with ~536 contiguous interior bytes missing, failed CRC, was
dropped, and the collector ended the epoch on `466 after 464`. The pull protocol (v0.3)
made every audit chunk re-requestable and the console's byte loss survivable there —
and left the one frame type that carries the record itself with no re-request. Prereg
v0.3 §6 item 4 makes a missing REC fatal regardless of budget, correctly: a record the
host never received is not evidence. The fix is not to relax that rule but to make the
record deliverable under loss.

A second, host-side defect found in the same session: the collector-written crash summary
carried `audited 0` while the host audit gate had verified 31, so the validator's stated
reason was rule (ix) instead of the seq gap. That is fixed in the same batch (§6).

## 2. The protocol

```
board → host   REC     <seq> <token> <loop_record>          attempt 1 (the record, built once)
host  → board  RECACK  {seq}   accepted — or a byte-identical duplicate of the accepted record
host  → board  RECGET  {seq}   a REC-shaped line for this seq arrived broken: send it again
board → host   REC     …       the SAME bytes, attempt k ≤ 3 (on RECGET, or when the wait runs out)
```

**Closure.** Token, frame seq and payload seq bind every line. The board answers only a
RECACK/RECGET whose seq is the record it is waiting on; stale or foreign lines are ignored
(bounded). The host acknowledges only the **current candidate** — the seq whose sign
exchange the relay answered and whose record is not yet accepted (`pending_rec_seq`). A
REC for any other seq, and a SIGNREQ while a record is outstanding, are PROTOCOL ends
("the board advanced without an acknowledgement"): the relay signs nothing for a board
that has moved on unconfirmed.

**Idempotence.** The record is serialised once (the tally counts it once) into its own
buffer; every transmission is those bytes. A byte-identical duplicate of the accepted
record is re-acknowledged and never appended. The same seq with other content is a
PROTOCOL end — never a second accepted record, never a "newer" one.

**Bounded retry, every way a frame is lost.** REC lost or broken → the host sends RECGET on
a broken REC-shaped line (at most 2 per seq) and, whatever the host does, the board's own
bounded wait (`P3_REC_IDLE_POLLS`, a count of RX-FIFO polls like the settle poll) runs out
and it resends; RECACK lost → the board resends, the host re-acknowledges; RECGET lost →
the board's wait covers it. After **3 transmissions** without acknowledgement the board
STOPS: `STOP_REC` (restore, TERM), no further candidate. A record the host never
confirmed is never treated as delivered; on the host the missing record stays the
structural HOLD it always was.

**One ledger.** Every attempt — the original broken line included — is in the session's
inbound ledger (the Timeline: CRC authority for every type; a broken REC counts against
D-s4 like any drop) and in the per-seq REC ledger (`audits.json` `recs[]`: attempts,
outcomes, raw lines kept verbatim, GETs and ACKs sent, accepted, conflict).

**Content is the validator's.** A CRC-valid record that is wrong (a nonce that did not
step, a readback that is not the commit) is accepted once and judged by
`validate_standalone_run_log`; a retry never replaces it and cannot wash out a falsifier.

**Two small firmware consequences.** (a) The board reads the console only inside a
transaction, so a host line that lands outside one (a RECACK repeated after the board had
already been acknowledged and moved on) would sit in the 64-byte RX FIFO, overflow and
merge with the next reply: the board now **drains the RX FIFO before every SIGNREQ**
(`console_rx_flush`, reads only) and its sign-reply loop **skips a stale RECACK/RECGET**
(bounded, `P3_REPLY_STALE_LIMIT`) instead of calling it a PROTOCOL failure. (b) The
record's line buffer is separate from the general frame buffer so the resend is the
original bytes even after HB/TERM frames.

## 3. The preregistered control (forced REC-retry)

Identity page `flags.bit4`. When set, the board corrupts the CRC of the **first
transmission of the opening baseline's record (seq 1)** — one hex digit — so every session
proves the real wire retry in its first seconds: the host must RECGET, the board must
resend byte-identical, and the per-seq ledger must read exactly `crc` → `ok` with the
record accepted and a RECGET sent. `host/l6_checks.rec_control_findings` makes a session
armed with the control whose ledger does not show that a HOLD ("control not exercised").
The deliberate drop counts against the budget like any other. The IDENT (1.2.0) echoes
the flag as `rec_retry_control` and declares `protocol: rec-v3`; the runner refuses an
image whose IDENT does not say so. The runner arms the control in every session (C1, C2,
S) — the plan writes the flag, the prereg v0.4 draft says so.

## 4. What the model proves (host-only) and what the C code proves

`host/l6_rec.py` — `RecBoard` / `RecHost` exchange real P3L5 lines over a faulty
`Channel`; `tests/test_l6_rec.py` (18): the S #1 loss shape (interior deletion of ~536
bytes) recovered by one RECGET; a REC dropped whole, a RECACK lost, a RECGET lost, each
recovered inside the bound with exactly one accepted record; duplicates re-acknowledged;
a conflicting duplicate a PROTOCOL end with the first record standing; exhaustion after
three broken transmissions → STOP_REC, no record, the host's asks bounded; a valid but
wrong record accepted once and refused by the validator, never retried; the control's
corruption exactly one CRC digit on attempt 1 of seq 1.

`host/l6_console.py` — the runner's session object implements RecHost against the real
Collector and NotaryRelay; `tests/test_l6_console.py::RecTransaction` (8) and `S1Replay`:
S #1's recorded console bytes through the new session draw a RECGET for 465, and the old
image's SIGNREQ 466 over the outstanding record is named as the PROTOCOL end; 464 records
stand, `crc_dropped_by_type {"REC": 1}`, the broken 1775-byte line kept in the ledger.

`firmware/p3_rectx.c` — the board's state machine as a pure unit with injected I/O, the
SAME source the image links, compiled into the wire twin and **run on the host over a
pipe** by `tests/test_firmware_wire_contract.py::RecWireContract` (7): one transmission
and an ACK; a RECGET resends the same bytes; the bound running out resends and three
misses exhaust with `STOP_REC` and no ACK; a fourth GET is not answered; stale, foreign,
wrong-seq, malformed and CRC-broken lines are ignored and counted; the control corrupts
exactly attempt 1 and equals `l6_rec.corrupt_crc`; and the real `RecHost` drives the C
board through the control to one accepted record. What stays static (`tests/test_firmware_audit.py::RecTransaction`,
6): `p3_app.c` builds the record once into its own buffer and hands it to `p3_rectx_run`
with this file's I/O; the unacknowledged path stops the epoch on both continuing outcomes
(SCORED, REFUSED_BY_GATE) and the stop paths keep their own first cause; the control is
`S.rec_control && seq == 1`; the flush precedes every SIGNREQ; the reply loop skips only
stale acks, bounded; `p3_rectx.c` is pure.

## 5. Rate and the calibrations

The transaction adds one host round trip per record (RECACK, ~75 bytes) inside the
candidate's period — a few tens of milliseconds at 115 200 baud plus one runner poll — so
the nominal candidate period under rec-v3 is **not** v0.3's. The v0.3 calibrations
(`786dc3ec…`, `a13e301f…`) are therefore not reusable: the rate report now carries a
`binding` (image, prereg, protocol, session, mode, seed — `l6_rate.binding_of`, written by
the runner from the pins it verified) and the S runner refuses a calibration whose binding
is not the current pins or that carries none. New C1 and C2 under the rec-v3 image
precede any S.

## 6. The crash-path summary

`host/l6_checks.crash_audit_count`: a collector-written (CRASHED) summary's `audited` is
the number of records whose served words the **host audit gate** verified
(`validators.audit.verify`'s marks — the same derivation the validator uses), never the
pull-DONE count and never the firmware's mark; if the gate refuses the chunks the count is
0 with the refusal named, and the validator will then state that refusal as the first
reason. `tests/test_l6_crash_summary.py` on S #1's real evidence: the shipped summary says
0 and the validator names (ix); the gate says 31; with 31 the validator accepts the 464
records and the structural gate names `missing REC [465, 466]` and `missing TERM` — HOLD,
never PASS (owner's counterfactual, batch item 5).

## 8. The owner's review of the first candidate (2026-09-02): four blockers, closed

1. **The bounded receive bounded only the first byte.** `recv_line_bounded` waited for the
   first byte with a bound and then blocked for the newline: a RECACK/RECGET cut mid-line
   would have held the application until the watchdog, not resent. The whole-line receiver
   is now `p3_rectx_recv_line` in the pure unit (idle bound between bytes, an overall line
   bound of four idle bounds; `-3` partial, `-2` nothing), `p3_app.c` supplies only the RX
   primitives, and the wire twin feeds every host line **byte by byte through that
   receiver**: `RecWireContract` proves a half ACK without a newline, a whole GET without
   its newline and a four-byte fragment are each abandoned and the record resent, and
   three truncated ACKs exhaust to `STOP_REC` — never a block.
2. **A broken resend of an accepted record was re-acknowledged on its header alone.** A
   broken line cannot be known to be the byte-identical duplicate that alone earns a
   RECACK: it now draws a RECGET, and the next CRC-valid resend is compared with the
   accepted payload — equal → RECACK, different → PROTOCOL_REC (the first record stands).
   The session object and the `RecHost` twin now behave the same way.
3. **v0.4 PASS condition 7 was not machine-enforced.** `rec_closure_findings` (§7 of the
   draft): record seqs == ledger seqs, every ledger accepted/no conflict/acknowledged/with
   an accepted attempt, no ledger without a record and no record without a ledger; the
   runner calls it; the discrimination test removes an arbitrary middle ledger and feeds
   "only seq 1's ledger" — both named.
4. **Two text/implementation gaps.** The control check now requires exactly `["crc", "ok"]`,
   accepted, no conflict, exactly one RECGET and an ACK (the draft says so, §2.6c); the
   sign-reply wait skips a RECACK/RECGET only when frame seq AND payload seq name the
   previous transaction, else PROTOCOL; the stale limit ends the wait on the 64th ignored
   line, as the header says.

The first candidate image `cd8360dc…` is withdrawn as DEFECTIVE (blocker 1 is a firmware
defect that would have blocked until the watchdog); the corrected image is rebuilt twice and pinned as
the new `next_image`, still not board-ready.

## 7. Not done, by the boundary

No ruling, no board, no S, no prereg freeze (v0.3 stays frozen; v0.4 is a draft), no
promotion of `next_image`, no change to `calibration.C1/C2` (the owner's pins stay; the
runner refuses them under v0.4 by construction). The image has never run: every statement
about the board's behaviour above is host-side — the C state machine on the host is the
strongest of it, the `p3_app.c` wiring the weakest (static).
