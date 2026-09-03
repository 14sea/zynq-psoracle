# L6 rel-v4 host batch — delivery package for review (host-only, 2026-09-02, after the correction-batch review)

> **Standing: host-only. Reviewed 2026-09-02 twice: HOLD on seven integration items (closed in
> §8, reviewed: main paths confirmed) and then HOLD on two new host acceptance blockers plus
> two items to pin before the firmware batch and two minor items (closed in §10, delivered,
> NOT yet reviewed); D-p1 bounds accepted with
> the exact semantics recorded in the v0.6 draft §3. No firmware, no image, no board, no
> ruling, no freeze; the stop-loss stands; `866bc5b` not pushed.** The owner's review of the correction batch
> (2026-09-02): PASS the correction line / HOLD the design on four items; D-t1 accepted;
> D-t2 accepted with two fail-closed fixes; **v0.5 not frozen — straight to v0.6**; the
> host-only batch below authorised; the firmware batch formally opened but started only
> after this batch is reviewed PASS. `403f4ab5…` (rec-v3), v0.4 and every session's
> evidence are untouched; the pinned rec-v3 image runs none of the rel-v4 code (by test).

## 0. The owner's rulings and where each lands

| # | ruling | landed |
|---|---|---|
| 1 | push `62d2922` | pushed; `origin/main = 62d2922` at the start of this batch |
| 2 | D-t1 accepted; D-t2: exactly one REC ledger per seq, at most one pull ledger per seq, extra seqs refused; the report computed from the three files as read back from disk | `host/l6_rate.py` (`_check_ledgers`; `rate_report_from_evidence_dir`, the only entry point; the CLI and the runner call it), `host/l6_runner.py` (the runner writes run_log/audits/timeline, then derives the report from the directory) — `tests/test_l6_rate_v05.py` (duplicate ledgers refused by seq; the runner wiring) |
| 3 | v0.5 not frozen; v0.6 carries its content; one C1 → C2 → S under the complete protocol | `docs/l6_soak_prereg_v0.6_draft.md` (self-contained), `docs/l6_soak_prereg_v0.5_draft.md` marked superseded never frozen, manifest `next_prereg` → v0.6-draft (`superseded_drafts`) |
| 4 | design HOLD: AUDITDONE loss; IDENT handshake before the first SIGNREQ; the STOP_SIGN evidence contract; remove the independence-based probability; pin the HB rounding and denominator | `docs/l6_frame_reliability_design.md` revision 2 (§3.8, §3.7, §3.1, §6, §3.4) — each closed with its implementation and test named below |
| 5 | stop-loss TRIGGERED; the host batch: v0.6 host state machines, caches, validator, twins behind a protocol switch, rec-v3 unchanged, per-frame loss/duplication/truncation/exhaustion tests | `host/l6_rel.py`, `host/l6_console.py` (`protocol="rel-v4"`), `host/l6_audit_pull.PullHost.on_wait`, `host/l6_timing.py` (`hb_i`), `host/l6_checks.structural_findings(protocol)`, `validators/records.py`, `host/l6_schedule.PROTOCOLS`, `host/l6_runner.py`; `tests/test_l6_rel.py` (38) |

## 1. D-t2, the two fail-closed fixes

| defect | fix | proof |
|---|---|---|
| `_check_ledgers` compared SETS of seqs: a second REC or pull ledger for a seq passed, and the dict built later kept the last one | every REC ledger carries a seq; a seq with two REC ledgers → `RateError("…more than one REC ledger for seq […]: refused, never last-wins")`; a seq with two pull ledgers → refused; a pull ledger for a seq that is not a record → refused | `BothLedgersOrNeither::test_duplicate_or_extra_ledgers_are_refused_never_last_wins` |
| the runner hashed the three files on disk but computed the report from the in-memory ledgers and timeline | `rate_report_from_evidence_dir(dir, session)`: reads `run_log.json`, `audits.json`, `timeline.json`, hashes those bytes, parses those bytes, computes; the runner calls it after `write_record` of the three; the CLI calls it; both-or-neither is decided on the files' presence | `InputBinding::test_the_runner_refuses_a_pinned_calibration_whose_inputs_moved` (the runner source calls `rate_report_from_evidence_dir(out_dir, plan["session"])` and no longer passes in-memory frames), `test_the_cli_hashes_the_files_it_reads_and_refuses_half_a_set` |

## 2. rel-v4 — what is implemented on the host, and what proves it

Every item is guarded by `ConsoleSession.rel` (`protocol == "rel-v4"`); under `rec-v3`
none of it runs (`Session::test_rec_v3_is_unchanged_none_of_the_new_frames_and_the_old_rules`:
the same script yields `AUDITREQ` + `SIGNOK` as C1 #5 ran, no IDENTACK, no SIGNGET, no
TERMACK/TERMGET, the old same-seq rule; the whole suite green).

| frame | host / twin (`host/l6_rel.py`) | loss | duplication | truncation (real reader) | exhaustion |
|---|---|---|---|---|---|
| `IDENT` | `IdentBoard` (resend ≤ 3 on the bound) / `IdentHost` (verify first, ack only a verified identity, re-ack an identical repeat, refuse a finding or a different second IDENT with NO ack); `ConsoleSession`: a SIGNREQ before the handshake → `PROTOCOL_IDENT`, the relay never reached | `test_ident_lost_is_resent_on_the_bound` | `test_ack_lost_the_identical_repeat_is_re_acknowledged_once_more` | `test_ident_torn_then_resent_the_reader_resyncs` | `test_three_losses_exhaust_to_stop_ident_and_nothing_is_established`; `test_an_identity_the_host_refuses_is_never_acknowledged`; `Session::…a_signreq_before_the_handshake_ends_the_epoch` |
| `SIGNREQ` | `SignBoard` (resend on SIGNGET or the bound ≤ 3; `audit_requested` read from SIGNOK) / `SignHost` (one relay call per seq; reply cached by (seq, request bytes); a byte-identical resend gets the cached line, the notary entry counts `replays`; SIGNGET ≤ 2 on a broken request; other content `PROTOCOL_SIGN`; a refusal cached the same way) | `test_signreq_lost_is_resent_on_the_bound_and_signed_once` | `test_signok_lost_the_identical_resend_gets_the_cached_reply_not_a_second_signature` (one signer call, `replays` 1, `relay.last_seq` unchanged) | `test_signreq_torn_then_resent_resyncs_and_signs_once`; `test_signreq_corrupted_draws_signget…` | `test_three_lost_replies_exhaust_to_stop_sign_with_one_signature_and_bounded_replays` |
| `AUDITREQ` | not a frame: `SIGNOK.audit_requested` (additive; the validator's `sign_reply` checker keeps only known keys) | `test_clean_exchange_folds_audit_requested_into_signok_no_auditreq_frame` | — | — | — |
| `AUDIT_READY` | `ReadyBoard` (resend ≤ 3 while no GET was seen, then abort as before) | `test_ready_lost_is_resent_on_the_bound` | ignored by the pending pull (existing) | (a torn READY is a lost READY) | `test_ready_lost_three_times_aborts_as_before` |
| `AUDITDONE` ▲ | `ReadyBoard` (after the last chunk, `AUDITWAIT {seq, served}` on each bound, ≤ 3, then give up as before) / `PullHost.on_wait` (the same DONE/ABORT line replayed ≤ 3; `waits_seen`, `done_replays`; `unconfirmed` at WAIT_MAX); `ConsoleSession` keeps the last pull for its AUDITWAIT | `test_done_lost_the_board_asks_and_the_same_done_is_replayed` (board audited, one wait, the two DONE lines identical) | idempotent DONE on the board | — | `test_done_lost_four_times_is_visible_on_both_sides` (board `STOP_AUDIT`, host `unconfirmed`, `waits_seen` 3) |
| `HB` | indexed `{i}` (`hb_line`); `Timeline.observe` records `hb_i`; `heartbeat_findings_rel`: at most one missing per record, session total ≤ `hb_missing_budget(R) = ⌊R/1000⌋`, R = SCORED records; unindexed/out-of-range named; selected by `structural_findings(protocol="rel-v4")` | `test_one_missing_in_a_calibration_crosses_the_zero_budget`; `…_in_a_soak_sized_session_is_within_budget_two_in_one_record_never` | `test_all_present_no_finding_duplicates_harmless` | — | (budget) `test_the_budget_is_floor_of_scored_records_over_1000` |
| `CLOSE` | `closing_from_term`: reconstructed from TERM's complete `closing_control`, marked `source: TERM`; `ConsoleSession._deliver_term` | `Session::…close_from_term` | — | — | `test_closing_control_is_reconstructed_from_term_only_when_complete` |
| `TERM` | `TermBoard` (TERMACK/TERMGET, ≤ 3) / `TermHost` (delivered once, acked, re-acked after the end without observing, TERMGET ≤ 2 on a broken line, a different second TERM `PROTOCOL_TERM`) | `test_term_lost_three_times_exhausts_and_the_host_saw_nothing` | `test_termack_lost_the_repeat_is_re_acknowledged_and_not_delivered_twice` | `test_term_torn_then_resent_resyncs`; `test_term_corrupted_draws_termget_then_delivered_once` | (same) |

**The session end to end** (`Session::test_rel_v4_ident_before_signreq_cached_reply_wait_replay_term_and_close_from_term`):
IDENT → IDENTACK; SIGNREQ 1 → SIGNOK with `audit_requested` and no AUDITREQ; the same
SIGNREQ again → the same SIGNOK line, one notary entry with `replays` 1, the epoch not
ended; READY + 8 chunks → DONE; AUDITWAIT → the same DONE replayed, `waits_seen` 1; TERM
(no CLOSE) → TERMACK, `closing_negative.source == "TERM"`; TERM again after the end →
re-acknowledged; the ledgers (`ident`/`signs`/`term`) as expected.

**The validator** (`ValidatorContract`): `STOP_SIGN` accepted only with `sign_stop
{attempts ≥ 1, why}` and nothing else, `replayed-only`, terminal (rule vii); rule (vii-b)
— an application-written epoch with a notary entry that has no record is refused by seq;
a collector-written (CRASHED) summary may leave the in-flight entry (the C1 #1 and S #1
logs are exactly that case). `self_report_class(STOP_SIGN) == "none"`.

**Selection** (`Session::test_the_schedule_and_the_runner_select_rel_v4_by_the_pinned_protocol`):
`expected_frames` keeps rel-v4's inbound brackets equal to rec-v3's; `HOST_PROTOCOLS =
("rec-v3", "rel-v4")`; the runner takes `plan["protocol"]` and the binding's protocol
from the pinned image, refuses a prereg/image protocol mismatch (`test_l6_runner`),
verifies the identity before the acknowledgement (`identity_check`), writes the rel-v4
ledgers into `audits.json`, selects the heartbeat rule by protocol.

## 3. The four HOLD items of the design, closed (revision 2)

| ▲ | item | closed by |
|---|---|---|
| 1 | a lost AUDITDONE unrecovered | §3.8: the AUDITDONE handshake (AUDITWAIT → the same DONE replayed ≤ 3; exhaustion visible on both sides: `STOP_AUDIT` / `unconfirmed`) — implemented and tested (table above) |
| 2 | "IDENTACK or the first sign reply" unsafe | §3.7: IDENTACK only, only after `check_l6_identity` passed, before any SIGNREQ; a SIGNREQ without it ends the epoch `PROTOCOL_IDENT` — implemented and tested |
| 3 | STOP_SIGN's evidence contract | §3.1: the exact record (`sign_stop` only, replayed-only, terminal, no nonce step), the notary entry behind it not an orphan, rule (vii-b) for every other orphan — implemented in the validator and tested |
| 4 | the independence-based "negligible" figure | §6: removed; the residual exposure is stated without a probability, and the document says why |
| — | HB 99.9 %: rounding and denominator | §3.4: `hb_missing_budget(R) = ⌊R/1000⌋`, R = SCORED records (the records the protocol fixes 16 heartbeats for); 0 for C1/C2, 6 for a 2 h soak; never two missing in one record — implemented and tested |

## 4. v0.6 draft

`docs/l6_soak_prereg_v0.6_draft.md`: self-contained; v0.5's text carried verbatim
(every rule readable without v0.4 or v0.5); §1 pins the rel-v4 image to be built; §2 adds
6i–6p (the protocol); §3 records D-t1/D-t2 as ruled with the two corrections, D-t3 as
ruled, proposes D-p1 (rel-v4 with its bounds); §4 adds items 19–23 (the design, the host
side, the validator, the tests, the firmware batch); §5 one C1 → C2 → S under the rel-v4
image; §6 adds items 10–13 (transactions closed, no unconfirmed pull, the heartbeat
budget, the SIGNREQ control, the extended recovery indicators); §7 the stop-loss ruling;
§9 the order. The v0.5 draft is marked superseded, never frozen.

## 5. What this batch does not do

No firmware, no image, no wire change on the board; nothing runs under the pinned rec-v3
image but rec-v3; no board, no ruling, no freeze; the stop-loss stands; C1 #5 stays HOLD
under v0.4; no probability is attached to the residual exposure.

## 6. Tests

`bash host/run_tests.sh` — the report cited in the commit: 949 tests / 1 skip / rc 0.
New: `tests/test_l6_rel.py` (38). Changed: `tests/test_l6_rate_v05.py` (+1, duplicate
ledgers; the runner wiring now names `rate_report_from_evidence_dir`),
`tests/test_l6_transport.py` (the runner wiring), `tests/test_l6_runner.py` (the
protocol refusals: not-implemented vs mismatch, rel-v4 accepted as a protocol).

## 7. Asked of the owner

1. Review of this batch (D-t2 fixes, rel-v4 host side and twins, the validator rules, the
   tests) and of the design revision 2.
2. D-p1: the rel-v4 bounds as written in the v0.6 draft §3.
3. The start of the firmware batch (§5 of the design: `p3_signtx.c`, `p3_termtx.c`, the
   pull's wait state, the IDENT/HB/CLOSE/TERM changes; C twins driven against
   `host/l6_rel.py`; two byte-identical builds; `next_image`; full P3 compatibility
   review).
4. Whether the v0.6 text is the right shape to freeze once the image exists.

## 8. Owner's review (2026-09-02): HOLD, seven items — the correction batch

| # | item (owner) | closed by | proof (`tests/test_l6_rel_correction.py` unless named) |
|---|---|---|---|
| 1 | the AUDITWAIT ledger written to `audits.json` was a stale copy taken at settle time (live `waits_seen 1, done_replays 1`, written `0, 0`) | `ConsoleSession.pull_ledgers` is a property rendered from the live `PullHost` objects (`_pulls`); the runner writes that property; `waits_exhausted` is a rendered fact | `Session::test_1_the_pull_ledger_written_after_an_auditwait_carries_the_replay` (real session: 1/1 after one wait, 3/3 + exhausted after three) |
| 2 | `unconfirmed` set on the third WAIT while the third replay might still succeed (board SCORED/audited vs host unconfirmed) | no verdict on the host: `PullHost.on_wait` only counts; the verdict is the board's record through `rel_closure_findings` — a host-completed pull whose record says `replayed-only` is "not confirmed on the board (waits_seen k, done_replays m)", a waited pull whose record says `audited` raises nothing; the `unconfirmed` field is gone | `test_2_the_verdict_on_a_waited_pull_is_the_boards_record_not_the_wait_count`; `test_l6_rel::ReadyAndDone` (adjusted) |
| 3 | the TERM transaction's re-ack branch unreachable: the collector ends the epoch on the first TERM and the runner leaves its loop | `l6_runner.session_loop_continues(collector, console, now, deadline)`: reads on while the epoch is open, and under rel-v4 for `TERM_LINGER_S` = (MAX_ATTEMPTS − 1) × BOARD_BOUND_S + 2 = 22 s after the first TERM (`ConsoleSession.lingering`); a resent TERM in that window is re-acknowledged (not observed); under rec-v3 the loop ends with the epoch as before; the deadline wins | `test_3_the_runner_lingers_after_the_term_under_rel_v4_and_re_acknowledges_a_resend` (real session + the loop condition; rec-v3 false immediately; the runner source uses the function) |
| 4 | IDENT wiring: a CRC-bad IDENT not ledgered; a malformed IDENT → `CRASHED`; a refused identity ended the epoch at once instead of letting the board exhaust to `STOP_IDENT` | `IdentHost.on_broken_line` (ledger `crc`/`malformed`, no ack), routed before the collector in both broken-line branches; a refusal sets `refused` (ledger `refused`, repeats `refused-repeat`), NO ack, NO host-side end, the declared identity still recorded; only a different second IDENT is `PROTOCOL_IDENT`; a SIGNREQ after a refusal ends the epoch `PROTOCOL_IDENT` naming it; the refusal is a `rel_closure_findings` finding | `test_4a_…crc_broken_ident…`, `test_4b_…malformed_ident_is_not_the_collectors_crash` (and rec-v3 still crashes), `test_4c_…refused_identity…the_board_exhausts_to_stop_ident` (three resends unacked, the board's STOP_IDENT TERM ends the epoch, the finding named), `test_4d_…signreq_after_the_refusal_is_protocol_ident` |
| 5 | v0.6 §6.10–13 not machine-enforced | `l6_checks.rel_closure_findings` (§6.10), `rel_control_findings` (§6.12, seq 1 exactly `["crc", "ok"]`, one SIGNGET, no replay), `rel_recovery_findings` (§6.13 bounds from `rel_pass_conditions_draft`), `l6_rel.heartbeat_findings_rel` (§6.11); `l6_rate.recovery_by_seq` computes `sign_retries` (one per non-ok attempt), `ready_resends`, `done_replays`, `hb_missing` per candidate and `rel_session_totals` `ident_repeats`/`term_retries`, both controls attributed as controls; `ls.FLAG_SIGN_CONTROL` armed by the plan under rel-v4; the runner calls all three under rel-v4 | `test_5a` (every closure defect named), `test_5b` (the control's exact shape, five wrong shapes), `test_5c` (indicators on C1 #5's ledgers + synthetic rel ledgers; each bound named), `test_5d` (hb_missing per SCORED record), `test_5e` (the runner's calls, the flag, the draft bounds) |
| 6 | STOP_SIGN accepted under `app_identity.protocol = rec-v3` | `validate_standalone_run_log` refuses STOP_SIGN unless the IDENT declares `rel-v4` | `test_6_stop_sign_is_refused_under_any_protocol_but_rel_v4` (the same log accepted past that rule under rel-v4) |
| 7 | CLOSE present, TERM's `closing_control` different, no comparison | `_deliver_term` compares the five fields when both exist: the CLOSE that arrived stands, the disagreement is `closing_conflict` in the rel ledgers and a `rel_closure_findings` finding | `test_7_a_close_that_disagrees_with_the_terms_closing_control_is_a_recorded_conflict` (agreeing pair: no conflict, no `source`; disagreeing: recorded and named) |

D-p1 recorded as ruled in the v0.6 draft §3: 3 board transmissions in all, host GET ≤ 2,
WAIT ≤ 3, replay/re-ack ≤ 3 — and the third WAIT is not a final failure. Design revision 3
(`docs/l6_frame_reliability_design.md`, ◆ marks) and the v0.6 draft (§2.6j/6m/6o, D-p1,
§4.21–22, §6.10/12/13) carry the seven closures.

## 9. Asked of the owner (correction batch)

1. Review of §8 and design revision 3.
2. Push of the commit, if the review passes.
3. The start of the firmware batch (unchanged scope; the C twins now also cover the
   IDENT refusal path, the AUDITWAIT counts and the CLOSE/TERM redundancy).

## 10. Owner's second review (2026-09-02): HOLD — two acceptance blockers, two pins, two minor items — the second correction batch

| # | item (owner) | closed by | proof (`tests/test_l6_rel_correction2.py`) |
|---|---|---|---|
| 1 | sign ledgers could last-wins (dict comprehensions in `rel_closure_findings` and `recovery_by_seq`); two identical seq-1 ledgers passed the closure | `l6_checks.unique_ledgers_by_seq`: exactly one ledger per seq, a duplicated seq named ("more than one sign ledger (refused, never last-wins)") and dropped from the map; the closure requires the sign-ledger seq set == the record seq set (missing / extra named by seq); `rel_control_findings` refuses a duplicated ledger before judging seq 1; the rate's `_check_ledgers` refuses duplicate / missing / extra sign ledgers and `recovery_by_seq` raises on a duplicate | `SignLedgersNeverLastWins` (4): the duplicate before and after the good one, an identical duplicate and a differing one, missing / extra / seq-less, and the rate report in both orders |
| 2 | an app-written TERM without `closing_control` passed when a CLOSE existed | `l6_rel.closing_control_findings`: the complete, typed five-field block is mandatory for every app-written summary — a missing block, a missing field, a wrong type each named; `rel_closure_findings` calls it regardless of CLOSE; `closing_from_term` rebuilds only from a complete block; both present must agree (§8 item 7) | `ClosingControlIsMandatory` (3): the three defects named; on the real session — CLOSE lost + complete TERM rebuilt, CLOSE lost + TERM without the block not rebuilt and named, CLOSE present + TERM without the block still named, both present and equal no finding |
| 3 | `flags.bit5` had no identity echo / verification | IDENT 1.3.0 `sign_retry_control`; `check_l6_identity(..., sign_retry_control=)`; the runner asks it under rel-v4 at both checks (`_sign_control_expectation`: None under rec-v3) | `Bit5Echo` (2): false / missing / non-bool refused, not asked under rec-v3; the runner's two calls |
| 4 | the 22 s linger assumed a 10 s board bound with no verifiable relation to the C poll count | `l6_rel.BOARD_BOUND_WALL_MAX_S` = 10 s, `FIRMWARE_BOUND_CONTRACT` naming the five poll-count bounds and the proof (source-audit test + C twin measurement in the firmware batch); `TERM_LINGER_S` derived from it; the twins model the bound at its upper bound; the v0.6 draft §2.6p states the contract and that it is unverified until the firmware batch | `BoundContract` (1) |
| 5 | after a refusal, a different second IDENT was logged as `refused-repeat` | byte-identical → `refused-repeat`; other bytes → `conflict`, `PROTOCOL_IDENT` | `MinorItems::test_5` |
| 6 | the heartbeat comment said "99.9 % of the 16 R frames" | the docstring says "at least 99.9 % of the SCORED records carry all 16 heartbeats" | `MinorItems::test_6` |

## 11. Asked of the owner (second correction batch)

1. Short review of §10.
2. Push of `866bc5b`, `e2c0caf` and this commit, if it passes.
3. The start of the firmware batch — with the bound contract (§10 item 4) and the IDENT
   1.3.0 echo (§10 item 3) as two of its deliverables.

## 12. Owner's third review (2026-09-02): HOLD on one narrow blocker — closed

| item (owner) | closed by | proof |
|---|---|---|
| `_check_ledgers` checked the sign ledgers only when `audits.signs` was present: with the key missing or null a rel-v4 calibration was accepted with `sign_retries` 0 (reproduced on C1 #5's evidence with the identity set to rel-v4) | `_check_ledgers(records, audits, frames, protocol)` takes the run log's `app_identity.protocol`; under rel-v4 `signs`, `ident` and `term` keys must exist, `signs` must be a list (null refused), `ident` an object, `term` an object or null; the exactly-one-per-seq / seq-sets-equal checks stay; rec-v3 still needs no `signs`; any non-integer seq in recs / pulls / signs is a `RateError` ("without an integer seq"), never a bare `ValueError` | `tests/test_l6_rel_correction2.py::RelReportNeedsTheSignLedgers` (3), through the real `rate_report_from_evidence_dir()` on a copy of C1 #5's evidence: key deleted, null, one missing, one duplicated, a non-integer seq, `ident` missing — each refused by name; rec-v3 without the key passes exactly as C1 #5 does; the committed C1 #5 evidence still yields the same report |

Package §10's claim "the rate refuses missing sign ledgers" now holds for the missing KEY
as well as for a missing seq.

## 13. Asked of the owner (third correction)

1. Shortest review of §12.
2. Push of `866bc5b`, `e2c0caf`, `e61e994` and this commit.
3. The start of the firmware batch with the IDENT 1.3.0 echo and the board-bound contract
   proof as mandatory deliverables.
