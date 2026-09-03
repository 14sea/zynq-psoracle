# Frame reliability design — rel-v4: every board→host frame re-requestable, reconstructible or budgeted (revision 4, 2026-09-02)

> **Standing: DESIGN, host-authored; revision 4 after the owner's second review (two host
> acceptance blockers, two items to pin before the firmware batch, two minor items — closed
> and marked ●; revision 3's ◆ and revision 1's ▲ stay). The HOST SIDE and the BOARD TWINS of this
> design are implemented in `host/l6_rel.py` behind the protocol switch `rel-v4`
> (`host/l6_console.py`, `host/l6_runner.py`; rec-v3 unchanged by test); the validator
> carries the STOP_SIGN contract and the orphan-entry rule; `tests/test_l6_rel.py` runs
> every frame through loss, duplication, truncation (through the real reader) and
> exhaustion. NOTHING here is implemented in firmware: the firmware batch is formally
> opened by the owner (2026-09-02) and starts only after this host/design batch is
> reviewed PASS; it is a new image, a full P3 compatibility review, and the self-contained
> v0.6 preregistration (`docs/l6_soak_prereg_v0.6_draft.md`). The owner's D-t3 stands:
> the pull's chunk timeout is 2.0 s.**

## 1. What the evidence says about the exposure

Five loss events over seven sessions (`docs/l6_console_loss_summary.md`): C1 #1 `AUDIT 24`
(~39 B, a line boundary), C1 #3 `AUDIT 20`/`62` (~309/~229 B interior), S #1 `REC 465`
(~540 B interior), C1 #5 `AUDIT 39` chunk 1 (~77 B, interior + tail). 5,566,850 bytes
received, 0.90 events/MB. Every event fell inside a line of ≥ 652 bytes; 73 % of all
received bytes are in lines ≥ 600 B, so with five events the data cannot say whether the
loss is per byte (uniform) or tied to long bursts. Both readings are carried below; the
design does not depend on either. **Nothing here assumes that events are independent of
one another** (▲ item 4: the earlier revision's "negligible" residual-risk figure rested
on independence that five events cannot support; it is removed — §6 states the residual
exposure without a probability).

**What S sends** (`host/l6_schedule.expected_frames`, N = 6539, sampled audit 1/16; line
sizes = C1 #5's means):

| frame | count in S | bytes/line | MB | re-requestable under rec-v3? | on loss under rec-v3 |
|---|---|---|---|---|---|
| `IDENT` | 1 | 816 | 0.00 | no | the identity check fails → HOLD; a CRC-failed IDENT is a drop and the same |
| `SIGNREQ` | 6541 | 374 | 2.45 | **no** | the host answers nothing to a broken line; the board's sign-reply wait is the L5 blocking `recv_line` (watchdog-covered) → watchdog reset at 30 s → U-Boot banner → `CRASHED: console banner`. **Session over.** |
| `AUDITREQ` (host→board, on the sign exchange) | 412 | ~120 | — | no | the board audits nothing for a SCORED candidate the host selected → `missing AUDIT` structural HOLD |
| `HB` | 104 656 | 55 | 5.76 | **no** | the count is not 16 for that record → `heartbeat_completeness_findings` structural HOLD (the epoch continues; PASS is impossible) |
| `AUDIT_READY` | 412 | 235 | 0.10 | **no** | the host never pulls; the board's idle bound (`P3_PULL_IDLE_POLLS`) runs out → `STOP_AUDIT`, no ARM, epoch STOPPED → HOLD |
| `AUDIT` | 3296 | 440 | 1.45 | yes (pull-v2) | re-requested per chunk, ≤ 2 retries |
| `AUDITDONE` (host→board) | 412 | ~100 | — | **no** ▲ | the board's idle wait runs out → the audit is given up (`STOP_AUDIT` on the SCORED path) while the host believes it audited → rule (ix) refuses the log → HOLD |
| `REC` | 6541 | 2301 | 15.05 | yes (rec-v3) | `RECGET`, ≤ 3 transmissions |
| `CLOSE` | 1 | 217 | 0.00 | **no** | `closing_negative` absent → L5 §5 "closing unsigned ARM refused" cannot be verified → HOLD |
| `TERM` | 1 | 540 | 0.00 | **no** | the session summary is collector-written → `missing TERM` structural HOLD |
| total | 121 449 | | 24.80 | | 8.30 MB (33 %) in frames that cannot be recovered, plus the two host→board frames |

Under the per-byte reading (0.90 events/MB) a soak sees ≈ 22 events, ≈ 7.5 of them on a
non-re-requestable frame. Under the long-burst reading the exposed bytes are `REC`
(2.3 KB) and the larger `AUDIT` chunks, all re-requestable, and the fatal frames (≤ 374 B
each) are hardly exposed — but that reading rests on five events and is not a design
assumption. **Either way a soak that can be ended by one lost 55-byte `HB` or one lost
`SIGNREQ` is not a soak of the instrument; it is a soak of the console path.**

## 2. Design principle

Every board→host frame is one of:

- **(i) re-requestable** — the host can ask for it again and the board resends the same
  bytes, bounded (`AUDIT`, `REC` today; `SIGNREQ`, `AUDIT_READY`, `TERM`, `IDENT` under
  rel-v4);
- **(ii) reconstructible** — its content is carried again by a later frame, so its loss
  costs evidence only if the later frame is lost too (`AUDITREQ` inside `SIGNOK`, `CLOSE`
  inside `TERM`);
- **(iii) budgeted** — its loss is a counted transport event with a preregistered bound,
  and the interlock evidence does not rest on it (`HB`).

And every host→board frame the board waits for is covered by a **bounded wait on the
board with a resend of the board's own frame** (the board re-asks by resending `SIGNREQ`,
`REC`, `AUDIT_READY`, `TERM`, `IDENT`; for `AUDITDONE` it announces `AUDITWAIT`), so a
lost reply is recovered by the board's next transmission, never by a block. The board
never waits for the host without a bound (§2.6e already), and every bound ends in a
resend or a named stop. The host never turns the loss of a class (i)/(ii) frame into a
structural HOLD; it turns the loss of a class (iii) frame into a recovery indicator.

## 3. Per frame

### 3.1 `SIGNREQ` → a transaction (firmware + host + prereg) — host side implemented

Today: `send_payload("SIGNREQ")` then the blocking `recv_line` for `SIGNOK`/`SIGNREF`
(with optional `AUDITREQ` first). A broken `SIGNREQ` gets no reply; the board blocks until
the watchdog resets it.

The sign exchange becomes a transaction like rec-v3's:
- the board serialises the `SIGNREQ` once (same genome, same PL nonce read) and sends it;
  it waits **bounded** (`P3_SIGN_IDLE_POLLS`, a count of RX polls, the §2.6e receiver) for
  `SIGNOK`/`SIGNREF`; on a `SIGNGET {seq}` from the host, or when the bound runs out, it
  resends **the same bytes**, ≤ 3 transmissions; exhaustion → **`STOP_SIGN`** (below);
- the host (`l6_rel.SignHost`): on a CRC-failed or malformed `SIGNREQ`-shaped line whose
  seq is the expected next seq (or unreadable), `SIGNGET {seq}` (≤ 2 per seq); on a
  **byte-identical duplicate** `SIGNREQ` (the board resent because our reply was lost) it
  **replays the cached reply line** — the relay is called ONCE per seq, the reply cached by
  (seq, request bytes); the notary entry gains `replays` (a count), never a second entry,
  never a second signature, never a nonce step (the nonce is the PL's and steps only on
  ARM); a same-seq `SIGNREQ` with other bytes is `PROTOCOL_SIGN` (the first signature
  stands); replays are bounded by the board's attempts;
- `AUDITREQ` is no longer a frame: `SIGNOK`'s payload carries `audit_requested: bool`
  (additive; the validator's `sign_reply` checker ignores unknown keys), so the request
  cannot be lost apart from the reply the board waits for and resends for (3.2).

**▲ The `STOP_SIGN` evidence contract (item 3), closed in `validators/records.py`:**
`STOP_SIGN` is a `loop_record` outcome; the record carries `evidence.sign_stop {attempts
≥ 1, why}` and **nothing else** (no `sign_reply`, no `sign_refusal`, no `arm`, no `score`,
no `app_oracle_record`; `verified` = `replayed-only`: nothing was staged). It is
**terminal**: no record may follow it (rule vii); the epoch ends `STOPPED` with the
restore and TERM as for `STOP_REC`. The **nonce is not consumed** (no ARM happened; the
chain does not step; the next SIGNREQ never comes). The **notary log** may hold an entry
for that seq — the host signed, the reply was lost three times — and that entry is
**not an orphan** because a record of its seq exists; the entry's `replays` count says
how often the cached reply went out. ◆ **`STOP_SIGN` exists only under rel-v4**: the
validator refuses the outcome when the IDENT declares any other protocol (a board without
a sign transaction has nothing to exhaust). **Rule (vii-b)**: in an application-written epoch
every notary entry has a record of its seq (`SCORED`, a stop, `REFUSED_BY_GATE`, or
`STOP_SIGN`); an entry without a record is a rejection (under rec-v3 that is a lost
reply; under rel-v4 it cannot happen without a `STOP_SIGN` record). A collector-written
(`CRASHED`) summary may leave the in-flight candidate's entry and says so by its kind.

A **forced SIGNREQ-retry control** on seq 1 (`flags.bit5`: the board corrupts the CRC of
the first `SIGNREQ` transmission) proves the transaction on the wire in every session,
with the same exact-shape rule as rec-v3's §2.6c (`["crc", "ok"]`, one `SIGNGET`, one
notary entry, `replays` 0).

Cost: one bounded wait replaces one blocking wait; the L5 "sign-reply wait is
watchdog-covered" statement changes and the L5 §5 conditions are re-audited (the watchdog
stays; the wait is no longer the thing that trips it). Tests (`SignTransaction`, 8): lost,
corrupted (SIGNGET), reply lost (cached replay, one signature, `replays` 1), three lost
replies (STOP_SIGN, one entry, `replays` 2), other content (PROTOCOL_SIGN), torn + resent
(resync), a refusal cached the same way. **Class (i).**

### 3.2 `AUDITREQ` → folded into `SIGNOK` (host implemented; firmware reads the field)

`SIGNOK` carries `audit_requested`; the board reads it from the reply it already waits
for and resends for. No separate frame to lose. Under rec-v3 the separate `AUDITREQ`
frame is still sent (test: `rec_v3_is_unchanged`). **Class (ii).**

### 3.3 `AUDIT_READY` → resent on the board's bound (twin implemented; firmware)

When the pull's idle bound runs out **before any `AUDITGET` was seen**, the board resends
`AUDIT_READY` (same bytes), ≤ 3 transmissions, then aborts as today; the host ignores a
duplicate `READY` while a pull is pending (it already does). A host-only probe with
`AUDITGET chunk 0` is **not** used: a `GET` reaching a board that is not in its pull
state lands in the sign-reply wait as an "unexpected reply type" and ends the epoch
`PROTOCOL`. Tests (`ReadyAndDone`): READY lost once → resent, audited; lost three times →
`STOP_AUDIT` as before. **Class (i).**

### 3.4 `HB` → indexed, its loss budgeted (host implemented; firmware one token; prereg)

Today: 16 `HB` frames per SCORED record with payload `-`; the host requires exactly 16
received — one lost 55-byte line is a structural HOLD. The `HB` is liveness and timing
evidence, not interlock evidence.

(a) The `HB` payload carries its index `{i: 0..15}` (`send_frame("HB", seq, "-")` → the
index); the timeline records it (`hb_i`). (b) The completeness rule
(`l6_rel.heartbeat_findings_rel`, selected by `structural_findings(protocol="rel-v4")`):
indices seen ⊆ 0..15, each at most once (a duplicate is harmless and reported); a record
missing **two or more** is a structural finding; the **session total of missing
heartbeats ≤ `hb_missing_budget(R) = ⌊R / 1000⌋`** with **R = the number of SCORED records**
(the records the protocol fixes 16 heartbeats for — the denominator; the 16 × R expected
frames are the "99.9 %" the earlier revision named, taken per record and rounded DOWN, ▲
the owner's "pin the integer rounding and the denominator"): a 64-candidate calibration
(R = 66) tolerates none, a 2 h soak (R ≈ 6541) tolerates 6; an unindexed `HB` is a
protocol finding (not a rel-v4 image); the breakdown of a record with a missing `HB` is
`None` (wall time stands); the liveness rule (silence > 3 × heartbeat interval) is
unchanged. Tests (`Heartbeats`, 6). **Class (iii).**

### 3.5 `CLOSE` → reconstructible from `TERM` (host implemented; firmware small)

The `TERM` payload repeats the closing control's fields as `closing_control {fault, kind,
status, nonce_before, nonce_after}` (additive; `closing.unsigned_control` stays
`done|not_reached`); `CLOSE` is still sent first. The host (`l6_rel.closing_from_term`,
`ConsoleSession._deliver_term`) reconstructs `closing_negative` from the TERM when no
`CLOSE` arrived, marked `source: TERM`; the validator's rule (viii) reads it as before.
◆ When a `CLOSE` did arrive, the two are **compared** (fault, kind, status, nonce_before,
nonce_after): the CLOSE that arrived stands, and a disagreement is recorded
(`closing_conflict`) and named by `rel_closure_findings`.
With 3.6, `TERM` is re-requestable, so `CLOSE` is **class (ii)**.

### 3.6 `TERM` → a transaction (host implemented; firmware small)

● The linger rests on a contract, not a model: every rel-v4 idle bound is a poll count in
the image whose wall time on the pinned clocks is ≤ `BOARD_BOUND_WALL_MAX_S` = 10 s
(`l6_rel.FIRMWARE_BOUND_CONTRACT`: the counts named, the proof = a source-audit test plus
the C twin's measurement in the firmware batch); `TERM_LINGER_S` = (MAX_ATTEMPTS − 1) ×
10 s + 2 s is derived from it. Until the firmware batch proves the bound, "the runner
always catches both TERM resends" is a stated contract, not a verified fact.

After `TERM` the board waits bounded for `TERMACK {seq}`; on `TERMGET` or the bound it
resends the same bytes, ≤ 3 transmissions; then halts as today (nothing follows a
`TERM`, so exhaustion changes nothing on the board). The host (`l6_rel.TermHost`)
delivers the first CRC-valid `TERM` to the collector ONCE, acknowledges it, re-acknowledges
a byte-identical repeat (also after the epoch's end, without observing it as evidence),
draws `TERMGET` on a broken `TERM`-shaped line (≤ 2), and ends `PROTOCOL_TERM` on a
different second `TERM`. ◆ **The runner lingers**: the collector ends the epoch on the
first TERM, so the console loop's condition (`l6_runner.session_loop_continues`) keeps
reading for `TERM_LINGER_S` = (MAX_ATTEMPTS − 1) × BOARD_BOUND_S + 2 s under rel-v4 — the
window in which the board resends a TERM whose ACK was lost — and the resend is
re-acknowledged without being observed as evidence; under rec-v3 the loop ends with the
epoch exactly as before; the runner's own bound always wins. Tests (`TermTransaction`, 6;
`test_l6_rel_correction::Session::test_3`). **Class (i).**

### 3.7 `IDENT` → a handshake completed BEFORE the first `SIGNREQ` (host implemented; firmware small)

● The IDENT (1.3.0) echoes `flags.bit5` as `sign_retry_control`, exactly as bit4 is echoed
as `rec_retry_control`; `check_l6_identity` verifies both under rel-v4, before the
acknowledgement and at adjudication (`l6_runner._sign_control_expectation`); after a
refusal only a byte-identical repeat is a `refused-repeat` — other bytes are a conflict.

▲ (item 2) The earlier revision let the first sign reply count as the acknowledgement;
that would let the host enter the signing path before it had verified the identity. Now:
the board sends `IDENT` and waits bounded for **`IDENTACK {seq 0}`**; on the bound it
resends the same bytes, ≤ 3; exhaustion → `STOP_IDENT` (TERM, **no `SIGNREQ` is ever
sent**). The host (`l6_rel.IdentHost`) **verifies the identity first** (`check_l6_identity`:
master seed, schedule mode, operator data, protocol, the control flag — the runner's
`identity_check`) and acknowledges **only** an identity with no finding; a
byte-identical repeat is re-acknowledged (bounded). ◆ **A finding is a refusal, not a
host-side end**: no acknowledgement, the identity ledgered as `refused` (repeats as
`refused-repeat`), the declared identity still recorded as evidence, and the epoch left
open for the board to resend, exhaust and stop itself with `STOP_IDENT` — its TERM ends
the epoch; the refusal is a closure finding (`rel_closure_findings`). A different second
`IDENT` is channel misbehaviour and ends the epoch `PROTOCOL_IDENT`. ◆ A CRC-failed or
malformed `IDENT`-shaped line is in the IDENT ledger (`crc`/`malformed`) and is never the
collector's `CRASHED: unparseable frame` (under rec-v3 it still is). **A `SIGNREQ` that
arrives while no identity is established — or after a refusal — ends the epoch
`PROTOCOL_IDENT`**; the relay is never reached. Tests (`IdentHandshake`, 7; `Session`;
`test_l6_rel_correction::Session::test_4a–4d` on the real session). **Class (i).**

### 3.8 `AUDITDONE` → a completion handshake (host implemented; twin; firmware) ▲ (item 1)

Today a lost `AUDITDONE` is silent on the wire: the board's idle wait runs out, it gives
the audit up (`STOP_AUDIT` on the SCORED path), and the host — which verified every
chunk — says `audited`; rule (ix) then refuses the log. Now: after serving the last
chunk the board waits bounded for `AUDITDONE`/`AUDITABORT`; when its bound runs out it
sends **`AUDITWAIT {seq, served}`** (≤ `WAIT_MAX` = 3, one per bound), and the host
**replays the same `AUDITDONE`/`AUDITABORT` line** it sent (`PullHost.on_wait`, ≤ 3; the
pull ledger records `waits_seen`, `done_replays`, `waits_exhausted`); a duplicate
`AUDITDONE` is idempotent on the board. Exhaustion: the board gives the audit up exactly
as today (a SCORED-path pull without `DONE` is `STOP_AUDIT`, no ARM). ◆ **The host takes
no verdict from the wait count** (revision 2's `unconfirmed` at the third `AUDITWAIT` was
premature: the third replay may still reach the board — the owner reproduced a board
`SCORED/audited` against a host `unconfirmed`). The verdict is the board's closure
evidence: `rel_closure_findings` names a pull the host completed whose record says
`replayed-only` — "the audit was not confirmed on the board (waits_seen k, done_replays
m)" — and says nothing for a waited pull whose record says `audited`. ◆ The pull ledger
the runner writes is rendered from the live objects (`ConsoleSession.pull_ledgers`), so
replays that follow the settle are in `audits.json`. Tests (`ReadyAndDone`;
`test_l6_rel_correction::Session::test_1`, `test_2`). **Class (i), host→board.**
◆ **Firmware review 2026-09-03 (blocker 1, contract defect):** `served` is the number
of DISTINCT chunks served (popcount of the served set), not transmissions — a re-served
chunk does not raise it, and after the last chunk it equals the chunk count; and an
`AUDITDONE` that arrives BEFORE every chunk was served is not a completion — the board
gives the audit up as on exhaustion (no `verified`, `STOP_AUDIT`, no ARM) and the Python
twin does the same (`PullBoard` → `ABORTED`). A DONE is the host's word that it verified
every chunk; one that precedes them is channel misbehaviour or a forged line, and
fail-closed is the only safe reading. `p3_pull.c`, `l6_audit_pull.PullBoard`;
`test_firmware_rel_contract::test_1_*`, `test_3_*`; `test_l6_rel::ReadyAndDone`.

### 3.9 Already covered

`AUDIT` chunks (pull-v2, ≤ 2 retries per chunk) and `REC` (rec-v3, ≤ 3 transmissions):
class (i). The host-side torn-line handling (`docs/l6_transport_batch_package.md`) applies
to every frame type through the reader — every simulation in `tests/test_l6_rel.py` runs
the board→host bytes through the real reader, and the `truncate` cases show the resync.

## 4. What the PASS rules become (v0.6, `docs/l6_soak_prereg_v0.6_draft.md`) — ◆ machine-enforced

`host/l6_checks.rel_closure_findings` (§6.10: identity accepted/acknowledged/not refused,
the IDENT declaring rel-v4, every record's sign transaction accepted without conflict and
no sign ledger without a record, no `STOP_SIGN`/`STOP_IDENT`, no `PROTOCOL` end, every
host-completed pull confirmed by the board's record, the TERM transaction accepted and
acknowledged, CLOSE/TERM agreement, ● the TERM's `closing_control` complete and typed —
`l6_rel.closing_control_findings`: a missing block, a missing field, a wrong type each
named, whether or not a CLOSE arrived; ● exactly one sign ledger per record with the seq
sets equal — `unique_ledgers_by_seq`, a duplicate named and never last-wins, shared by the
control check and refused by the rate), `rel_control_findings` (§6.12: seq 1 exactly
`["crc", "ok"]`, one `SIGNGET`, no replay), `rel_recovery_findings` (§6.13: `sign_retries`,
`ready_resends`, `ident_repeats`, `term_retries`, `done_replays` each within the pinned
bound — the manifest's `next_prereg.rel_pass_conditions_draft`) and
`l6_rel.heartbeat_findings_rel` (§6.11) — all called by the runner under rel-v4; the
indicators are computed by `l6_rate.recovery_by_seq` (per candidate, one per non-ok
attempt) and `rel_session_totals` (IDENT/TERM), with both controls attributed as controls.

- D-s4's structural rule keeps "any missing `AUDIT`, `REC`, `TERM`" and adds "any
  `STOP_SIGN`, `STOP_IDENT`, an unconfirmed pull, a `PROTOCOL_*` end"; a missing `HB`
  moves from structural to budgeted (3.4); `CLOSE` may be supplied by `TERM` (3.5).
- The recovery indicators (v0.5 §6.3b) gain `sign_retries` (SIGNGETs + replays),
  `ready_resends`, `hb_missing`, `term_retries`, `ident_repeats`, `done_replays`, each
  with a bound; a soak's expected frames and CRC budget (D-s4) are unchanged in formula
  (retransmissions and `AUDITWAIT` arrive on top).
- The forced controls: rec-v3's seq-1 `REC` control stays; the forced `SIGNREQ`-retry
  control (3.1) is added with the same exact-shape rule.

## 5. Order and what needs the owner

1. **This batch (host-only, delivered):** `host/l6_rel.py` (twins + hosts + the faulty
   channel through the real reader), the `ConsoleSession` switch, `PullHost.on_wait`, the
   timeline's `hb_i`, `structural_findings(protocol)`, the validator's `STOP_SIGN` and
   rule (vii-b), `l6_schedule.PROTOCOLS["rel-v4"]`, the runner selecting the protocol from
   the pinned image and verifying the identity before the acknowledgement; 38 tests, and
   the rec-v3 path unchanged (`Session::test_rec_v3_is_unchanged…`, the whole suite).
2. **Firmware batch (opened by the owner 2026-09-02; starts after 1 is reviewed PASS):**
   3.1 (bounded sign wait, resend, `STOP_SIGN`, the seq-1 control), 3.2, 3.3, 3.4(a), 3.5,
   3.6, 3.7, 3.8 — through the pure-unit pattern of `p3_rectx.c` (a `p3_signtx.c`, a
   `p3_termtx.c`, the pull's wait state) so the wire twin drives them on the host; two
   byte-identical builds; `next_image`, not board-ready; a full P3 compatibility review.
3. Prereg v0.6 frozen (self-contained); then one C1 → C2 → S under it.

## 6. Residual exposure after the design — stated, not computed

After rel-v4 every board→host frame is class (i)/(ii)/(iii) and every host→board frame
is covered by the board's bounded resend. What remains: the CRC budget (D-s4), the retry
bounds themselves (a burst that eats all three transmissions of one frame ends the
session as a named `STOP_*`), the `HB` budget, and the `unconfirmed` pull. ▲ (item 4)
No probability is attached to any of these: the five observed events do not establish
that events are independent, and a figure derived from independence would not be
evidence. The measure that stands is the exposure itself — ≈ 22 events per soak at the
observed rate, each recovered by one resend when it stands alone — and the session's
recovery ledgers, which say afterwards what happened.

## 7. What this document does not claim

It does not name the physical cause of the byte loss (CH340 → usbipd → WSL `vhci_hcd`, no
flow control; nothing here measures it), does not claim the long-burst reading, does not
authorise any firmware change (the firmware batch is the owner's to start), does not
re-judge any session, and attaches no probability to the residual exposure.
