# Frame reliability design — the board→host frames that are still not re-requestable (proposal, 2026-09-02)

> **Standing: PROPOSAL, host-authored, not ruled, nothing implemented in firmware.** The
> owner's ruling of 2026-09-02 on the transport batch: the host soak proves the model and
> the mechanism, not the physical path; `SIGNREQ`, `HB`, `AUDIT_READY`, `CLOSE` and `TERM`
> remain not re-requestable and can still fail a 2 h soak through the same byte-loss
> family; no new board session or ruling before a complete transport/protocol review;
> firmware/protocol/image changes are ruled separately after this design is reviewed.
> This document is that design. Every proposal below that touches `firmware/p3_app.c` or
> the wire protocol is a new image, a new P3 compatibility review and a new prereg version
> (v0.6); the host-only parts are marked.

## 1. What the evidence says about the exposure

Five loss events over seven sessions (`docs/l6_console_loss_summary.md`): C1 #1 `AUDIT 24`
(~39 B, a line boundary), C1 #3 `AUDIT 20`/`62` (~309/~229 B interior), S #1 `REC 465`
(~540 B interior), C1 #5 `AUDIT 39` chunk 1 (~77 B, interior + tail). 5,566,850 bytes
received, 0.90 events/MB. Every event fell inside a line of ≥ 652 bytes; 73 % of all
received bytes are in lines ≥ 600 B, so with five events the data cannot say whether the
loss is per byte (uniform) or tied to long bursts. Both readings are carried below; the
design must not depend on either.

**What S sends** (`host/l6_schedule.expected_frames`, N = 6539, sampled audit 1/16; line
sizes = C1 #5's means):

| frame | count in S | bytes/line | MB | re-requestable today? | on loss today |
|---|---|---|---|---|---|
| `IDENT` | 1 | 816 | 0.00 | no | the identity check fails → HOLD; a CRC-failed IDENT is a drop and the same |
| `SIGNREQ` | 6541 | 374 | 2.45 | **no** | the host answers nothing to a broken line; the board's sign-reply wait is the L5 blocking `recv_line` (watchdog-covered) → watchdog reset at 30 s → U-Boot banner → `CRASHED: console banner`. **Session over.** |
| `AUDITREQ` (host→board, on the sign exchange) | 412 | ~120 | — | no | the board audits nothing for a SCORED candidate the host selected → `missing AUDIT` structural HOLD |
| `HB` | 104 656 | 55 | 5.76 | **no** | the count is not 16 for that record → `heartbeat_completeness_findings` structural HOLD (the epoch continues; PASS is impossible) |
| `AUDIT_READY` | 412 | 235 | 0.10 | **no** | the host never pulls; the board's idle bound (`P3_PULL_IDLE_POLLS`) runs out → `STOP_AUDIT`, no ARM, epoch STOPPED → HOLD |
| `AUDIT` | 3296 | 440 | 1.45 | yes (pull-v2) | re-requested per chunk, ≤ 2 retries |
| `REC` | 6541 | 2301 | 15.05 | yes (rec-v3) | `RECGET`, ≤ 3 transmissions |
| `CLOSE` | 1 | 217 | 0.00 | **no** | `closing_negative` absent → L5 §5 "closing unsigned ARM refused" cannot be verified → HOLD |
| `TERM` | 1 | 540 | 0.00 | **no** | the session summary is collector-written → `missing TERM` structural HOLD |
| total | 121 449 | | 24.80 | | 8.30 MB (33 %) in frames that cannot be recovered |

Under the per-byte reading (0.90 events/MB) a soak sees ≈ 22 events, ≈ 7.5 of them on a
non-re-requestable frame: P(no such event in 2 h) ≈ e^−7.5 ≈ 0.06 %. Under the long-burst
reading the exposed bytes are `REC` (2.3 KB) and the larger `AUDIT` chunks, all
re-requestable, and the fatal frames (≤ 374 B each) are hardly exposed — but that reading
rests on five events and is not a design assumption. **Either way a soak that can be
ended by one lost 55-byte `HB` or one lost `SIGNREQ` is not a soak of the instrument;
it is a soak of the console path.**

## 2. Design principle

Every board→host frame is one of:

- **(i) re-requestable** — the host can ask for it again and the board resends the same
  bytes, bounded (`AUDIT`, `REC` today);
- **(ii) reconstructible** — its content is carried again by a later frame, so its loss
  costs evidence only if the later frame is lost too;
- **(iii) budgeted** — its loss is a counted transport event with a preregistered bound,
  and the interlock evidence does not rest on it.

The board never waits for the host without a bound (§2.6e already), and every bound ends
in a resend or a named stop. The host never turns the loss of a frame in class (i)/(ii)
into a structural HOLD; it turns the loss of a frame in class (iii) into a recovery
indicator. Host→board frames (`SIGNOK`/`SIGNREF`/`AUDITREQ`/`AUDITGET`/`AUDITDONE`/
`RECACK`/`RECGET`) are covered by the board's bounded waits + resends, which already exist
for `REC` and the pull and are proposed here for `SIGNREQ`.

## 3. Per frame

### 3.1 `SIGNREQ` → a transaction (firmware + host + prereg)

Today: `send_payload("SIGNREQ")` then the blocking `recv_line` for `SIGNOK`/`SIGNREF`
(with optional `AUDITREQ` first). A broken `SIGNREQ` gets no reply; the board blocks until
the watchdog resets it.

Proposal: the sign exchange becomes a transaction like rec-v3's:
- the board serialises the `SIGNREQ` once (same genome, same PL nonce read) and sends it;
  it waits **bounded** (`P3_SIGN_IDLE_POLLS`, a count of RX polls, the §2.6e receiver) for
  `SIGNOK`/`SIGNREF`/`AUDITREQ`; on a `SIGNGET {seq}` from the host, or when the bound runs
  out, it resends **the same bytes**, ≤ 3 transmissions; exhaustion → `STOP_SIGN` (restore,
  TERM; no candidate proposed);
- the host, on a CRC-failed or malformed `SIGNREQ`-shaped line whose seq is the expected
  next seq, sends `SIGNGET {seq}`; on a byte-identical duplicate `SIGNREQ` (the board
  resent because our reply was lost) it **replays the same reply line** — the relay must
  be idempotent on (seq, payload bytes): a resend never re-signs and never advances the
  nonce chain (the reply is cached per seq; the notary log records one signature and the
  replay count); a same-seq `SIGNREQ` with other bytes is `PROTOCOL_SIGN`;
- `AUDITREQ` rides **inside** the sign reply (a field of `SIGNOK`'s payload) instead of a
  separate frame, so it cannot be lost apart from the reply — the reply is what the board
  waits for and resends for (see 3.2).

Cost: one bounded wait replaces one blocking wait; the L5 "sign-reply wait is
watchdog-covered" statement changes and the L5 §5 conditions are re-audited (the watchdog
stays; the wait is just no longer the thing that trips it). Discrimination tests: a
`SIGNREQ` lost → `SIGNGET`/resend → one record; a `SIGNOK` lost → resend → the same
reply replayed, one signature in the notary log; three lost → `STOP_SIGN`, nothing
signed twice. **Class (i).**

### 3.2 `AUDITREQ` → folded into `SIGNOK` (firmware + host)

Today: a separate host→board frame before the reply. Proposal: `SIGNOK` carries
`audit_requested: true|false`; the board reads it from the reply it already waits for.
No separate frame to lose; the `AUDIT_READY` the board then emits echoes it. **Class (ii).**

### 3.3 `AUDIT_READY` → resent on the board's bound (firmware + host)

Today: the board announces once, then waits `P3_PULL_IDLE_POLLS` for the host's first
`AUDITGET`; if the announcement was lost the wait runs out and the board aborts the audit
(`STOP_AUDIT`, no ARM, epoch STOPPED on the SCORED path).

Proposal: when the idle bound runs out **before any `AUDITGET` was seen**, the board
resends `AUDIT_READY` (same bytes), ≤ 3 transmissions, then aborts as today; the host
ignores a duplicate `READY` while a pull is pending (it already does). A host-only
alternative — probing with `AUDITGET chunk 0` after `HB`#16 when no `READY` arrives — is
**not** proposed: a `GET` arriving while the board is not in its pull state reaches the
sign-reply wait as an "unexpected reply type" and ends the epoch `PROTOCOL`. **Class (i).**

### 3.4 `HB` → indexed, and its loss budgeted (firmware small + host + prereg)

Today: 16 `HB` frames per SCORED record with payload `-`; the host requires exactly 16
received (`heartbeat_completeness_findings`) — one lost 55-byte line is a structural HOLD.
The `HB` is liveness and timing evidence (the six-stage breakdown), not interlock
evidence: the interlock facts are in the signed record and the audited words.

Proposal: (a) the `HB` payload carries its index `{i: 0..15}` so a missing one is
identified and a duplicate is harmless; (b) the completeness rule becomes: indices seen ⊆
0..15, each at most once, **every index present for ≥ 99.9 % of SCORED records and never
two missing in one record**, missing heartbeats counted as a recovery indicator with that
bound (§6.3b of the prereg); the breakdown of a record with a missing `HB` is `None`
(wall time stands, as for an unclosed pull); the liveness rule (silence > 3 × heartbeat
interval) is unchanged. A `HB` loss is then **class (iii)**. (b) alone is host + prereg
only, but without (a) a lost `HB` cannot be told from a duplicated one; (a) is a
one-token firmware change (`send_frame("HB", seq, "-")` → the index).

### 3.5 `CLOSE` → reconstructible from `TERM` (firmware small + host)

Today: the closing unsigned control's result (`fault`, `kind`, `status`, nonce before/after)
is one frame. Proposal: the `TERM` payload repeats the closing control's fields
(`closing_unsigned: {fault, status, nonce_before, nonce_after}` instead of the bare
`"done"`), and `CLOSE` is still sent first; the validator accepts the control from
either. With 3.6, `TERM` is re-requestable, so `CLOSE` becomes **class (ii)**.

### 3.6 `TERM` → a transaction (firmware small + host)

Today: sent once, last; lost → the collector writes the summary → `missing TERM`.
Proposal: after `TERM` the board waits bounded for `TERMACK {seq}`; on `TERMGET` or the
bound, resends the same bytes, ≤ 3 transmissions; then halts as today (nothing follows a
`TERM`, so exhaustion changes nothing on the board). The host sends `TERMACK`; a
CRC-failed `TERM`-shaped line draws `TERMGET`. **Class (i).**

### 3.7 `IDENT` → repeated until acknowledged (firmware small + host)

Today: sent once at `go`; the host's first frame to the board is the reply to `SIGNREQ 1`.
Proposal: the board repeats `IDENT` (same bytes) every idle bound until it sees any host
line for this token (an `IDENTACK`, or the first sign reply), ≤ N; the host acknowledges
with `IDENTACK` and ignores byte-identical repeats (a different `IDENT` is `PROTOCOL`).
**Class (i).**

### 3.8 Already covered

`AUDIT` chunks (pull-v2, ≤ 2 retries per chunk) and `REC` (rec-v3, ≤ 3 transmissions):
class (i). The host-side torn-line handling (`docs/l6_transport_batch_package.md`) applies
to every frame type through the reader, so the resends above never glue to a residue.

## 4. What the PASS rules become (for a v0.6 prereg, not v0.5)

- D-s4's structural rule keeps "any missing `AUDIT`, `REC`, `TERM`" and adds "any missing
  `SIGNREQ` reply, any `STOP_SIGN`"; a missing `HB` moves from structural to budgeted
  (3.4); `CLOSE` may be supplied by `TERM` (3.5).
- The recovery indicators (v0.5 §6.3b) gain `sign_retries`, `ready_resends`,
  `hb_missing`, `term_retries`, `ident_repeats`, each with a bound; a soak's expected
  frames and CRC budget (D-s4) are unchanged in formula (retransmissions arrive on top).
- The forced controls: rec-v3's seq-1 `REC` control stays; a **forced `SIGNREQ`-retry
  control** on seq 1 (the board corrupts the first `SIGNREQ`'s CRC when `flags.bit5` is
  set) proves 3.1 on the wire in every session, with the same exact-shape rule as §2.6c.

## 5. Order and what needs the owner

1. Host-only, can go first under v0.5: the relay's idempotent reply cache keyed on (seq,
   payload bytes) with a notary-log replay count; `SIGNGET`/`TERMGET`/`IDENTACK`/`TERMACK`
   senders behind a protocol-version switch (inert under rec-v3); the `HB`-index-tolerant
   completeness check behind the same switch; the recovery indicators of §4; tests over
   the faulty channel for each. None of it changes what rec-v3 sessions do.
2. Firmware (one batch, one image, one full P3 compatibility review): 3.1 (bounded sign
   wait, resend, `STOP_SIGN`, the seq-1 control), 3.2, 3.3, 3.4(a), 3.5, 3.6, 3.7 — all
   through the pure-unit pattern of `p3_rectx.c` (a `p3_signtx.c`, a `p3_termtx.c`) so the
   wire twin drives them on the host; two byte-identical builds; `next_image`, not
   board-ready.
3. Prereg v0.6 with §4 above; freeze; C1/C2/S under it.

**Residual exposure after the design:** every board→host frame is class (i)/(ii)/(iii);
what remains is the CRC budget (D-s4) and the retry bounds themselves — a burst that eats
three transmissions of one frame ends the session as `STOP_*`, named. At 0.90 events/MB
and 24.8 MB that is ≈ 22 events per soak, each recovered by one resend when it is alone;
the probability that any one frame is hit three times in a row is what the bounds leave
(≈ 22 × (event rate per line)² — negligible next to today's 7.5 fatal events).

## 6. What this document does not claim

It does not name the physical cause of the byte loss (CH340 → usbipd → WSL `vhci_hcd`, no
flow control; nothing here measures it), does not claim the long-burst reading, does not
authorise any firmware change, and does not re-judge any session.
