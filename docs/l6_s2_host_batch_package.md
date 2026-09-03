# The host batch after S #2 — delivery package for the owner's review (host-only, 2026-09-03)

> **Standing: HOST-ONLY, local commits, NOT pushed. No board contact, no ruling created or
> consumed, no firmware change (the pinned image stays `5deee74c…`), no evidence of C1 #6 /
> C2 #2 / S #2 rewritten, no pin changed: `manifests/l6_manifest.json` is byte-identical to
> the pushed one (`54583314c16295c24f083efe402ec0cf98a54da5ca8d30afbfd5851c5eedfc68`) and
> the frozen preregistration is still v0.6 (`bfd69d10…`). `docs/l6_soak_prereg_v0.7_draft.md`
> is a complete FREEZE CANDIDATE and is NOT marked frozen; the manifest changes at the
> owner's freeze, not here. `calibration.C1`/`C2` stay pinned and ACTIVE; C1 #5 stays HOLD;
> S #2 stays HOLD and is not re-run; Claim B stays closed.**

Authorised by the owner 2026-09-03 after the §7 ruling (S #1 and S #2 are "the same way
twice": contiguous byte deletion on the same console path running into a `REC` frame —
no third soak under v0.6; targeted host fix → host-only proof → independent review →
v0.7 re-freeze).

## 0. The commit chain

| commit | what |
|---|---|
| `96ffcee` | (1/n) the malformed non-transaction line: ledgered once, bounded, never the collector's `CRASHED`; S #2's recorded bytes replayed both ways; the modelled byte-identical `REC 145` resend and its negatives |
| `505e178` | (2/n) the v0.7 candidate rules — crash-path baseline gate, the record-budget heartbeat rule, the soak's bad-frame bound, rule selection by prereg version — and the N-versus-T comparison with its post-hoc gate |
| `52989e1` | (3/n) the modelled-channel SESSION soak: 12 seeds × 300 candidates both policies, and 3 soak-sized sessions; a model defect found and fixed on the way |
| this one | (4/n) the explicit calibration import (D-i1), the self-contained v0.7 draft, this package, the suite report |

## 1. What each owner requirement became, and the test that holds it

| requirement (owner 2026-09-03) | where | test |
|---|---|---|
| a malformed `P3L5` line is recorded **exactly once** by the Timeline as `BAD_FRAME`, not acknowledged, not signed, advances no seq, and is **not** handed to the collector | `host/l6_console.py`: `bad_frame_policy` ∈ {`crash` (v0.6, default), `ledger` (v0.7)}, `bad_frame_budget` | `test_l6_s2_host_batch.S2RecordedBytes::test_under_the_ledger_policy_the_host_survives_the_merged_line`, `ModelledRecResend::test_a_malformed_line_does_not_refresh_liveness_or_sign_or_advance` |
| S #2's raw bytes prove only that the host survives the line (the recording ends at the port close) | the replay drives the REAL reader / ConsoleSession / Collector / NotaryRelay over `evidence/l6_17A6_2026-09-03-03-S/console.log` | `S2RecordedBytes::test_under_v06_the_replay_reproduces_the_days_crash` (the control: the day's `CRASHED: unparseable frame`, `last_seq 144`), `…::test_under_the_ledger_policy_the_host_survives_the_merged_line` |
| then a **modelled byte-identical `REC 145` resend**: accepted once, `RECACK`, normal progress | the firmware's REC twin `l6_rec.RecBoard` continues from the replay's state | `ModelledRecResend::test_a_byte_identical_resend_after_the_bound_is_accepted_once_and_acknowledged` |
| negatives: no resend, wrong resend, conflicting resend, the malformed line repeated, budget exhaustion | — | `…::test_no_resend_is_the_collectors_silence_end_not_a_silent_continuation`, `…::test_a_wrong_resend_another_seq_is_protocol_rec`, `…::test_a_conflicting_resend_same_seq_other_bytes_is_protocol_rec`, `…::test_a_second_identical_resend_is_re_acknowledged_never_appended`, `…::test_the_malformed_line_again_and_again_is_bounded_by_the_budget` |
| a non-fatal bad frame needs an explicit **terminal bound** in S — never unbounded tolerance | the console ends the epoch `PROTOCOL_BAD_FRAME_BUDGET` at the first past the budget; `l6_checks.soak_findings` names the total in the adjudication either way | `…::test_the_malformed_line_again_and_again_is_bounded_by_the_budget`, `…::test_the_ledger_policy_refuses_to_run_unbounded` (a ledger policy without a budget is refused at construction), `test_l6_v07_rules.SoakBadFrameBound` (3) |
| opening baseline always; the closing baseline only on `COMPLETED` | `host/l6_checks.py:82` `baseline_findings` | `test_l6_v07_rules.BaselineGate` (3): S #2's artefact reproduced on a COMPLETED fixture and absent on the real CRASHED log; C1 #6 unchanged |
| v0.7 must **rule the heartbeat rule explicitly** (per-record cap kept or dropped for an aggregate budget + index completeness + the 20 s liveness) | `host/l6_rel.heartbeat_findings_v07` beside the unchanged `heartbeat_findings_rel`; `l6_checks.structural_findings(..., hb_rule=)`; §3 D-h1 and §6.11 of the draft state the choice | `test_l6_v07_rules.HeartbeatRuleV07` (6), including the S #2 shape under both rules and an unknown rule refused |
| the soak's N: keep wall ≥ 0.9 T, compute a policy-matched rate from the pinned calibrations' immutable timing inputs, publish unrounded intermediates and the single final floor, and use a recorded pace only as a post-hoc gate | `host/l6_soak_plan.py` (4 named rules, fixed point on the audit fraction), `l6_runner.plan_session` under `sessions.S.n_rule` | `test_l6_v07_rules.SoakPlanLocked` (6) and `RuleSelection` (5) |
| reusing the v0.6 calibrations must be an **explicit import** by report and the three input hashes, never a pretence that they bind the new prereg | `manifests/…` `calibration.<k>.imported`, enforced in `l6_runner.plan_session`; §3 D-i1 | `test_l6_v07_import.ExplicitImport` (7): refused without it, the import relaxes the prereg hash and nothing else, a wrong hash / other report / other inputs / no justification each refused |
| nothing of v0.7 may run under v0.6 | `l6_runner.rules_for` keyed on `prereg.version` | `RuleSelection::test_under_v06_nothing_of_v07_runs`, `…::test_under_v07_the_ledger_policy…`, `ExplicitImport::test_under_v06_nothing_of_this_runs…` |
| a full modelled-channel soak | `host/l6_session_soak.py` | `test_l6_session_soak` (13) |

## 2. The two replays, side by side

**Raw bytes (S #2's own console.log, 586 454 bytes, read-only).** Driven through the real
stack in random poll-sized pieces:

| policy | outcome |
|---|---|
| `crash` (v0.6) | `CRASHED: unparseable frame`, `last_seq 144` — the day's outcome, reproduced exactly; `bad_frames 1`, `crc_dropped 2` = `{SIGNREQ 1, REC 1}` (the two controls) |
| `ledger` (v0.7) | the epoch stays OPEN. `bad_frames 1`, the same two CRC drops, 144 records, `relay.last_seq 145`, seq 145 pending, **nothing sent for the merged line** (`RECACK` 144, `RECGET` 1 = the control only, `SIGNOK` 145, `SIGNGET` 1 = the control only), no fragment |

**What the recording cannot show**, because it stops 0.2 s later at the port close: whether
the board really resent. So the modelled continuation, using the firmware's own REC twin
(`l6_rec.RecBoard`, the C twin of `firmware/p3_rectx.c`): attempt 1 delivered as the
recorded merged line → the bound elapses → **the same bytes** resent → accepted once, one
`RECACK 145`, record 145 appended once, ledger `["ok"]`, the twin `acked` after 2 attempts,
and the next `SIGNREQ 146` proceeds. This is a model of the board, not a measurement of it.

## 3. The modelled session soak

`host/l6_session_soak.py`: the board twins composed into whole rel-v4 sessions (IDENT →
per-seq SIGNREQ transaction → 16 indexed heartbeats → the sampled pull → the REC
transaction → TERM, both seq-1 controls armed) against the real host stack, over a wire
that injects `delete_run` (a contiguous run that carries into the following lines — S #2's
shape), `truncate`, `crc`, `dup`, `drop`, plus lost host→board acknowledgements.

**A model defect found and fixed while building it, reported because it changed results.**
The deletion run's remainder had no time bound, so one 900-byte run "ate" three
`AUDIT_READY` resends the board sent 10 s apart and the session died of silence. A
deletion run is a burst ON THE WIRE: its remainder now expires after 50 ms of transmit-idle
(`CARRY_MAX_GAP_S`), which a test locks. Every "unrecovered" case in the first matrix was
this artefact.

`evidence/l6_session_soak/rel_v4_session_soak_2026-09-03.json` — 12 seeds × 300 candidates,
both policies, `p_fault` 0.004 per board→host line:

| policy | result |
|---|---|
| `ledger` | **`COMPLETED` 302/302 records, all 12 seeds, zero unrecovered faults.** 268 faults in all: 115 crossed a frame boundary, 64 ran into a `REC`; 71 malformed lines absorbed, 106 CRC drops (within a budget of 23 per session — the controls plus recovered corruption), 74 fragments. The REC transaction did the recovering: 48 records of 3624 needed a second transmission, **none a third** |
| `crash` (control) | `CRASHED: unparseable frame` at the **first** malformed line, all 12 seeds, 2–137 records in |

`evidence/l6_session_soak/rel_v4_soak_sized_2026-09-03.json` — 3 sessions at the soak's own
size (N = 12511, the `policy_matched_wall` candidate) at ≈ 6× the recorded line fault rate:
`COMPLETED` 12513/12513 every time, zero unrecovered, every gate empty **except** the
heartbeat rule, and there the two rules part:

| seed | records that lost heartbeats | v0.7 (record budget 12) | v0.6 (one per record) |
|---|---|---|---|
| 101 | 2 | clean | HOLD — `seq 10711: 8 heartbeats missing` |
| 102 | 6 | clean | HOLD — 4 records named + the aggregate |
| 103 | 4 | clean | HOLD — 2 records named + the aggregate |

That is the argument for D-h1 from evidence rather than assertion: under v0.6 a single
contiguous loss HOLDs a 2 h soak in which **every record was accepted**.

## 4. N against T

From the two PINNED calibration reports and the run logs their `inputs` hash (verified;
`lsp.load_pinned` refuses a tampered pin), T = 7200 s, wall floor 0.9 T = 6480 s. Every
intermediate unrounded, one floor at the end. The gate is post-hoc: N × S #2's recorded
SIGNREQ→SIGNREQ interval (0.545067… s, from `evidence/l6_17A6_2026-09-03-03-S/run_log.json`,
hash-checked) must lie in [6480 s, timeout).

| rule | rate C1 | rate C2 | unrounded product | **N** | sampled audits | predicted wall at S #2's pace | gate |
|---|---|---|---|---|---|---|---|
| `planning` (v0.6, what S #2 ran) | 3381.372371 | 3367.753097 | 6061.955574 | 6061 | 382 | 3304 s | **FAIL** |
| `policy_matched_period` | 6223.142350 | 6200.113435 | 11160.204184 | 11160 | 701 | 6083 s | FAIL |
| **`policy_matched_wall`** | 6982.535019 | 6950.711806 | 12511.281251 | **12511** | 785 | **6819 s** | **PASS** (margin 339 s; timeout 8702 s) |
| `policy_matched_span` | 5870.958375 | 5851.647270 | 10532.965085 | 10532 | 662 | 5741 s | FAIL |

The owner's two candidate estimators are both here and their difference is identified:
`policy_matched_period` (≈ the "6197" figure) works from the inter-proposal period, which
includes the gap between one record and the next SIGNREQ; `policy_matched_wall` (≈ "6952")
works from the candidate's own SIGNREQ→REC wall time. The difference is exactly that gap,
0.0627 s per record in C1. **Neither is pre-approved: the owner picks the rule at the
freeze.** The rounded-label counterexample is locked as a test: `floor(0.9 × 6952 × 2)`
= 12513 while the unrounded 6952.2375 gives 12514 and this batch's own unrounded
6950.711806 gives 12511 — N is never derived from a displayed value. S #1's pace is
computed and reported but does not gate: it ran pull-v2, another protocol.

## 5. Candidate artefacts and hashes

| artefact | sha256 |
|---|---|
| `docs/l6_soak_prereg_v0.7_draft.md` (the freeze candidate, 740 lines, self-contained) | `96ca3acb9a25ba909fca9e2bc316053685ac4d2d1e5481fecdf0842c6a84d0b5` |
| `manifests/l6_manifest.json` (UNCHANGED — still the pushed one) | `54583314c16295c24f083efe402ec0cf98a54da5ca8d30afbfd5851c5eedfc68` |
| the frozen preregistration in force (`docs/l6_soak_prereg.md`, v0.6) | `bfd69d1037c4d2715759befef766d353b99741c8ff6ef6cb0ca30bbd325a620a` |
| the pinned image (unchanged, no rebuild) | `5deee74c44785ebe88168ccffaa5f399f26a7c5a567fccb3d430cf4eb14cdc7c` |

**What the freeze would change in the manifest, if the owner rules for it** (not done
here): `prereg` → v0.7 with the draft's hash, v0.6 into `supersedes`; `sessions.S.n_rule`
= the rule the owner picks; `calibration.C1/C2.imported` = the D-i1 declarations; the
draft's bounds merged into `pass_conditions`. The runner reads all of it from the manifest
already — `rules_for()` turns nothing on until `prereg.version` says v0.7.

## 6. Suite

`bash host/run_tests.sh` — 1074 tests, 1 skip, rc 0 (`evidence/tests/test_report_2026-09-03T181348Z.json`). New: `tests/test_l6_s2_host_batch.py`
(11), `tests/test_l6_v07_rules.py` (22), `tests/test_l6_session_soak.py` (13),
`tests/test_l6_v07_import.py` (7). The rule-version guard in `tests/test_l6_transport.py`
and the import manifest are updated; every pre-existing test is unchanged and green,
which is the point: under v0.6 nothing of this batch runs.

## 7. Asked of the owner

1. Review this batch (host-only, no board, nothing pinned).
2. Rule **D-b1** (the malformed-line policy and its bound), **D-h1** (the heartbeat rule —
   the per-record cap kept or replaced by the record budget), **D-n1** (the N rule by name,
   with the wall floor kept at 0.9 T), **D-i1** (the explicit import of C1 #6 / C2 #2, or
   re-calibration under v0.7).
3. On PASS: the push, then the v0.7 freeze (its sha into the manifest, v0.6 superseded in
   history, `sessions.S.n_rule` and the imports written), and only then the ruling on the
   next board session.
