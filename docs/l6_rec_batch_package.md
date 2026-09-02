# L6 rec-v3 batch — delivery package for the full P3 compatibility review (host-only, 2026-09-01/02; correction batch 2026-09-02 after the owner's HOLD)

> **Standing: host-only, awaiting the owner's full P3 compatibility review.** Authorised
> after S #1's HOLD as a "pre-board protocol correction batch" that is NOT host-only in
> scope — firmware, image and preregistration draft change — but IS host-only in effect:
> no board, no ruling, no v0.4 freeze, no S re-run, no promotion. The candidate image
> `403f4ab5…` is `next_image` with `board_ready: false` and has never run (the first
> candidate `cd8360dc…` is withdrawn DEFECTIVE — §0); the frozen v0.3
> and its pinned image `e19e1b12…` are untouched; `host/l6_runner.py` now implements
> rec-v3 and refuses to run against v0.3 or a pull-v2 image, by construction.

## 0. The owner's review of the first candidate (2026-09-02): HOLD, four blockers — closed in the correction batch

| # | blocker | fix | proof |
|---|---|---|---|
| 1 | "bounded receive" bounded only the first byte; a RECACK/RECGET cut mid-line would block until the watchdog | `p3_rectx_recv_line` in the pure unit: an idle bound between bytes and an overall line bound (4 × idle), `-3` partial / `-2` nothing; `p3_app.c`'s `recv_line_bounded` is that receiver over the RX primitives (the audit pull gets it too); `p3_rectx_run` counts partials as stale | the wire twin now feeds every host line **byte by byte through the board's receiver** (`!raw` = no newline, `!idle` = silence): `RecWireContract::test_a_truncated_ack_without_a_newline_is_abandoned_and_the_record_resent`, `test_a_truncated_recget_and_a_line_with_no_newline_at_all_are_bounded_too`, `test_three_truncated_acks_exhaust_to_stop_rec_not_a_block`; `test_firmware_audit::RecTransaction::test_the_whole_line_receive_is_bounded_and_is_the_pure_units` (the blocking `recv_line` remains only in the L5 sign-reply wait, unchanged) |
| 2 | a CRC-broken resend of an accepted record was re-acknowledged on its header — not provably byte-identical; the twin and the session disagreed | `l6_console._on_broken_line`: a broken resend of an accepted record draws `RECGET`; the next CRC-valid resend earns `RECACK` only if equal to the accepted payload, else `PROTOCOL_REC` (the first record stands); the `RecHost` twin behaves the same | `test_l6_console::RecTransaction::test_a_duplicate_is_re_acknowledged_and_never_appended` (rewritten: GET → equal resend ACKed → GET → other content PROTOCOL, ledger `ok, duplicate, crc, duplicate, crc, conflict`); draft D-r3 |
| 3 | v0.4 PASS condition 7 not machine-enforced (only seq 1 was checked) | `l6_checks.rec_closure_findings`: record seqs == ledger seqs, every ledger accepted / no conflict / ≥ 1 RECACK / an accepted attempt, no ledger without a record, no record without a ledger, duplicated ledgers; the runner calls it | `test_l6_runner::Checks::test_rec_closure_gate_accepts_a_closed_session_and_names_every_defect` — discrimination: an arbitrary middle ledger removed → named; "only seq 1's ledger" → `[2, 3, 4]` named; extra/unaccepted/conflict/unacknowledged/no-ok each named; the runner's call asserted |
| 4a | the control check accepted a prefix and ≥ 1 GET | exactly `["crc", "ok"]`, accepted, no conflict, exactly one RECGET, ≥ 1 RECACK — and the draft §2.6c says so | `test_rec_control_check_requires_exactly_the_preregistered_shape` (9 shapes refused by name) |
| 4b | the sign-reply wait skipped any token-valid RECACK/RECGET without checking the seqs | skipped only when frame seq AND payload seq == the previous record's seq; anything else `PROTOCOL: an acknowledgement that is not the previous transaction's` | `test_firmware_audit::RecTransaction::test_a_stale_ack_in_the_reply_wait_must_name_the_previous_transaction`; draft §2.6f |
| 4c | `stale++ >= 64` tolerated a 65th line | `++stale >= P3_RECTX_STALE_LIMIT`: the 64th ignored line ends the wait, as the header says | `RecWireContract::test_the_stale_limit_is_exactly_sixty_four_ignored_lines` (63 → taken, 64 → resent) |

`cd8360dc…` is withdrawn as DEFECTIVE in the manifest (`withdrawn_images`, its build
record preserved as `evidence/l6_next_build/build_evidence_cd8360dc.json`); the corrected
image `403f4ab5e8073e13cde74168636e35b8721505f4b73d2da579d2e36788ee28cd` (ELF `8687ef8d…`,
98 324 B) is built twice byte-identical and is `next_image`, `board_ready: false`. What the
owner confirmed correct is unchanged: v0.3 and `e19e1b12…` untouched, the runner refuses
the committed v0.3/pull-v2 pair, the old calibrations are refused, the S #1
counterfactual and the loss statistics stand.

## 1. The owner's nine items, each with where it is and what proves it

| # | requirement | where | proven by |
|---|---|---|---|
| 1 | a reliable REC transaction: no next candidate before the host confirms; loss, CRC error and lost ACK/GET all bounded-retried; token/seq/current-candidate authority closed; duplicates idempotent | `firmware/p3_rectx.{h,c}` (the board state machine, pure); `firmware/p3_app.c` `emit_record` + `run_candidate`; `host/l6_rec.py` (both twins); `host/l6_console.py` (`_on_rec`, `_on_broken_line`, `pending_rec_seq`, the SIGNREQ-over-outstanding-record rule) | `tests/test_l6_rec.py` (18: S #1's loss shape, REC/ACK/GET each lost, duplicates, conflict, closure), `tests/test_l6_console.py::RecTransaction` (8) + `S1Replay`, `tests/test_firmware_wire_contract.py::RecWireContract` (7 — the C state machine run on the host over a pipe), `tests/test_firmware_audit.py::RecTransaction` (6, static wiring) |
| 2 | retry exhaustion stops subsequent candidates; a missing REC never success; never two accepted records | `p3_rectx_run` → −1 after 3; `p3_app.c`: `STOP_REC` on both continuing paths, stop paths keep their first cause; host: a record is appended once, a duplicate re-acknowledged, other content PROTOCOL | `test_l6_rec.py::BoundedRetry::test_exhaustion_stops_the_board_and_leaves_no_record`, `Idempotence::*`; `RecWireContract::test_the_bound_running_out_resends_and_exhaustion_stops_without_an_ack`, `test_a_fourth_recget_is_not_answered_the_bound_is_three`; `RecTransaction::test_an_unacknowledged_record_stops_the_epoch_and_no_next_candidate_is_proposed` (with the return-removal mutant) |
| 3 | every attempt and the original broken line in the one CRC ledger; content the validator's; no retry washes out a falsifier | Timeline (unchanged authority) + `RecLedger` (`audits.json` `recs[]`, raw lines verbatim); a valid-but-wrong record accepted once, `_on_rec` never asks again | `test_l6_console.py::RecTransaction::test_a_broken_rec_for_the_pending_candidate_is_asked_for_again…` (ledger count + lines kept), `test_the_hosts_asks_are_bounded_and_the_budget_still_ends_the_epoch`; `test_l6_rec.py::Content::test_a_valid_but_wrong_record_is_accepted_once_for_the_validator_and_never_retried` |
| 4 | the crash summary's `audited` from the host audit gate's marks, never a pull count or a firmware mark | `host/l6_checks.crash_audit_count` (calls `validators.audit.verify`); `l6_runner.run_l6` builds every collector-written summary from it | `tests/test_l6_crash_summary.py::S1Counterfactual::test_the_gate_count_is_31_from_the_host_audit_gate_marks`, `test_the_runner_builds_the_crashed_summary_from_the_gate`, `test_a_gate_refusal_yields_zero_with_the_refusal_named` |
| 5 | the S #1 counterfactual: summary corrected → still HOLD on the REC gap, never PASS | `tests/test_l6_crash_summary.py` on `evidence/l6_17A6_2026-09-01-11-S/` (read-only) | `test_with_the_count_corrected_the_session_is_still_a_hold_on_the_missing_rec_and_term`: validator accepts 464/31/464, structural gate names `missing REC for seq [465, 466]` and `missing TERM`, `outcome_for` = HOLD CRASHED |
| 6 | loss statistics extended to C1 #4, C2 #1, S #1 — exposure and events, no root cause | `host/l6_loss_stats.py` (schema 2.0.0: every session, every frame type, dense + sparse audits; the trailing partial line at session end recorded apart); `evidence/l6_console_loss_stats.json`; `docs/l6_console_loss_summary.md` §A | 4 events / 5 080 302 B / 14 583 frames; pull-v2 era 1 event / 2 748 841 B; the S #1 event the first on a REC line; the historical C1 section kept below |
| 7 | a preregistered forced REC-retry control, on the opening baseline, proving the real wire retry within minutes | identity page `flags.bit4` (`l6_schedule.FLAG_REC_CONTROL`, armed by `plan_session` in every session); `p3_rectx.c` corrupts one CRC digit of attempt 1 when asked; `p3_app.c` asks for seq 1 only; IDENT 1.2.0 echoes `rec_retry_control`; `l6_checks.rec_control_findings` = HOLD if the seq-1 ledger is not `crc` → `ok` with a RECGET | `test_l6_rec.py::ForcedControl` (3), `RecWireContract::test_the_control_corrupts_exactly_the_first_transmission`, `test_the_real_host_side_drives_the_c_board_through_the_control`; `test_firmware_audit.py::RecTransaction::test_the_control_corrupts_only_the_opening_baselines_first_transmission`; `test_l6_schedule.py` (bit4) |
| 8 | prereg v0.4 draft; v0.3 frozen, not overwritten | `docs/l6_soak_prereg_v0.4_draft.md`; `docs/l6_soak_prereg.md` byte-identical to the pin; manifest `prereg.protocol: pull-v2` + `next_prereg` (draft, sha null) | `test_package_consistency.py::PinnedL6Image::test_the_frozen_prereg_hashes_to_its_pin` (still green), `test_the_frozen_prereg_speaks_in_the_present_protocol`; `test_l6_runner.py::Refusals::test_an_image_not_marked_board_ready_or_not_rec_v3_is_refused` (the committed manifest cannot run a session: "freeze prereg v0.4 first") |
| 9 | the new image built twice from scratch, byte-identical; board-ready only after the full review | `IMAGE=p3_app_l6 firmware/bsp/build.sh` ×2 with `rm -rf out` between: `403f4ab5e8073e13cde74168636e35b8721505f4b73d2da579d2e36788ee28cd` (ELF `8687ef8d…`, 98 324 B; the first candidate `cd8360dc…` withdrawn DEFECTIVE, §0); `manifests/l6_manifest.json` `next_image` (`board_ready: false`, `protocol: rec-v3`); `evidence/l6_next_build/build_evidence.json` (earlier candidates' records preserved as `build_evidence_e19e1b12.json`, `build_evidence_cd8360dc.json`); `manifests/l6_bsp_inputs.json` regenerated — the same 65 files | `test_package_consistency.py::PinnedL6Image::test_one_image_one_authority` (next_image not board-ready, differs from the pin), `test_the_built_l6_binary_matches_the_manifest` (HEAD builds `next_image`), `test_bsp_inputs_manifest.py` |

**The owner's necessary condition — calibrations may not be reused across the protocol
change.** `host/l6_rate.rate_report` now carries `binding` = {image_sha256, prereg_sha256,
protocol, session, schedule_mode, master_seed} copied from `run_log.l6.binding`, which
the runner writes from the pins it verified in preflight; `plan_session("S", …)` refuses a
calibration report that carries no binding ("re-run C1/C2") or whose binding differs from
the current pins in any field. The v0.3 pins `786dc3ec…`/`a13e301f…` stay in the manifest
as the owner's record and are refused by construction
(`test_l6_runner.py::Plan::test_soak_refuses_a_calibration_not_bound_to_the_current_image_prereg_and_protocol`
checks the real pinned reports on disk).

## 2. The protocol, in one paragraph

`REC` → host `RECACK {seq}` (accepted, or a byte-identical duplicate) | `RECGET {seq}` (a
REC-shaped line for this seq arrived broken) → `REC` again, the same bytes, ≤ 3
transmissions in all, each waited for with the board's bound (`P3_REC_IDLE_POLLS`, a
count); unacknowledged → `STOP_REC`, restore, TERM, no next candidate. The host
acknowledges only the current candidate (the relay's answered sign exchange whose record
is outstanding); a REC for another seq or a SIGNREQ over an outstanding record is
PROTOCOL; duplicates are re-acknowledged and never appended; other content for the same
seq is PROTOCOL. Two firmware consequences: the RX FIFO is drained before every SIGNREQ,
and the sign-reply wait skips a stale RECACK/RECGET (bounded). Design:
`docs/l6_rec_transaction_design.md`.

## 3. Changes, exhaustively

Firmware: `p3_rectx.{h,c}` NEW (pure state machine; `P3_RECTX_ATTEMPTS 3`,
`P3_RECTX_CONTROL_FLAG 16`, `P3_RECTX_STALE_LIMIT 64`); `p3_app.c` — `emit_record` builds
once into `g_rec_line` and runs `p3_rectx_run` with this file's I/O (`rectx_*_cb`), returns
−1 when unacknowledged; `run_candidate` flushes the RX FIFO before SIGNREQ, its reply loop
uses `parse_frame_any` and skips stale RECACK/RECGET (`P3_REPLY_STALE_LIMIT 8`), the two
continuing paths stop on `S.rec_stop_why`, the seven stop paths void-cast their emit;
`establish_identity` decodes `flags.bit4` → `S.rec_control`, IDENT declares `protocol
rec-v3` + `rec_retry_control`; `P3_REC_IDLE_POLLS`; `p3_wire.{h,c}` — `app_identity`
1.2.0 (two fields, sorted keys); `bsp/src/console.c` — `console_rx_flush` (reads only);
`bsp/build.sh` + `Makefile` link `p3_rectx.c`; `p3_wire_twin.c` — `ident` gains
`protocol=`/`rec_control=`, `rec` refactored through `build_rec`, NEW `rectx` interactive
command. Host: `l6_rec.py` NEW; `l6_console.py` (the transaction, the pending rule);
`l6_checks.py` (`crash_audit_count`, `rec_control_findings`); `l6_rate.py` (`binding`);
`l6_schedule.py` (`FLAG_REC_CONTROL`, protocol `rec-v3`); `l6_runner.py` 0.2.0
(`HOST_PROTOCOL`, the two protocol refusals, `binding` into the plan/log, calibration
binding refusals, the crash summary from the gate, identity protocol/control check,
`rec_control_findings`, `audits.json` `recs`); `l6_loss_stats.py` (2.0.0);
`validators/records.py` (`check_l6_identity` protocol/control). Manifest:
`prereg.protocol`, `next_image`, `next_prereg`, `wire_additions.rec_transaction`,
`calibration.note`. Tests: `test_l6_rec.py` NEW, `test_l6_crash_summary.py` NEW, and the
additions/updates named in §1. Nothing else: no new MMIO target (the register-discipline
tests are unchanged and green), no SLCR, no DMA change, no change to the audit pull, the
settle poll, the watchdog, the operators or the schedule.

## 4. What is dynamic evidence and what is static

Dynamic, on the C source the image links: `p3_rectx.c` over a pipe (`RecWireContract`, 7
scenarios incl. the real `RecHost` driving it through the control) and `p3_wire.c`'s IDENT
1.2.0 through the real validator. Dynamic, on the host side: the wire model
(`test_l6_rec.py`), the real session object (`RecTransaction`, `S1Replay` on S #1's real
bytes), the S #1 counterfactual. **Static only**: `p3_app.c`'s wiring of the transaction
(build-once, the I/O callbacks, the stop on both continuing paths, the flush, the
stale-skip, the control's seq-1 gate) — `p3_app.c` does not execute on the host. The
first dynamic evidence of that wiring is a session under a future ruling, and the forced
control is designed so that it comes within seconds of `go`.

## 5. Suite

863 tests, 1 skip (the L5 binary, unchanged reason); the report the build evidence cites
is named in `evidence/l6_next_build/build_evidence.json` and verified green by the
generator; the package stands on the report of the final staged run
(`evidence/tests/`, the newest at the commit).

## 6. Not done, by the boundary

No ruling requested, no board contact, no C1/C2/S, no freeze of v0.4 (sha null), no
promotion of `next_image`, no change to `calibration.C1/C2` or to any session evidence
directory. The rec-v3 image has never run.

## 7. Next (the owner's)

Short re-review of the correction batch (§0), then the full P3 compatibility review of this package → promote `next_image` (board-ready,
`protocol: rec-v3`) → freeze v0.4 (new prereg hash; the manifest's `prereg` block moves to
v0.4 with v0.3 recorded as superseded) → rulings for NEW C1 and C2 under the rec-v3 image
(power cycle each) → the owner pins the bound calibrations → S under its own ruling.
