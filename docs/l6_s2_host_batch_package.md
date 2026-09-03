# The host batch after S #2 — delivery package for the owner's review (host-only, 2026-09-03; revision 3 after the owner's two HOLDs of the same day)

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
| `d905c15` | (4/6) the explicit calibration import (D-i1), the self-contained v0.7 draft, this package, the suite report |
| `e4d6a31` | (5/6) the first correction batch: the global bad-frame bound (B1), the import's version pairing and verbatim evidence (B2), D-n1 as ruled — the faster arm sizes N (B3), the draft's drift with a draft-specific guard (B4), and the proof narrative tightened (B5) |
| this one | (6/6) the second correction batch, closing the three interface gaps the owner then found: the pull-exhaustion collision (B1′), the normalisation's audit fraction (B3′), and the §5 S row with the two superseded sizing rules (B4′) |

## 1. What each owner requirement became, and the test that holds it

| requirement (owner 2026-09-03) | where | test |
|---|---|---|
| a malformed `P3L5` line is recorded **exactly once** by the Timeline as `BAD_FRAME`, not acknowledged, not signed, advances no seq, and is **not** handed to the collector | `host/l6_console.py`: `bad_frame_policy` ∈ {`crash` (v0.6, default), `ledger` (v0.7)}, `bad_frame_budget` | `test_l6_s2_host_batch.S2RecordedBytes::test_under_the_ledger_policy_the_host_survives_the_merged_line`, `ModelledRecResend::test_a_malformed_line_does_not_refresh_liveness_or_sign_or_advance` |
| S #2's raw bytes prove only that the host survives the line (the recording ends at the port close) | the replay drives the REAL reader / ConsoleSession / Collector / NotaryRelay over `evidence/l6_17A6_2026-09-03-03-S/console.log` | `S2RecordedBytes::test_under_v06_the_replay_reproduces_the_days_crash` (the control: the day's `CRASHED: unparseable frame`, `last_seq 144`), `…::test_under_the_ledger_policy_the_host_survives_the_merged_line` |
| then a **modelled byte-identical `REC 145` resend**: accepted once, `RECACK`, normal progress | the PYTHON twin `l6_rec.RecBoard` — the board's transaction as modelled on the host, cross-verified against the image's own C unit (`firmware/p3_rectx.c`) by the wire-contract tests, never the firmware itself — continues from the replay's state | `ModelledRecResend::test_a_byte_identical_resend_after_the_bound_is_accepted_once_and_acknowledged` |
| negatives: no resend, wrong resend, conflicting resend, the malformed line repeated, budget exhaustion | — | `…::test_no_resend_is_the_collectors_silence_end_not_a_silent_continuation`, `…::test_a_wrong_resend_another_seq_is_protocol_rec`, `…::test_a_conflicting_resend_same_seq_other_bytes_is_protocol_rec`, `…::test_a_second_identical_resend_is_re_acknowledged_never_appended`, `…::test_the_malformed_line_again_and_again_is_bounded_by_the_budget` |
| a non-fatal bad frame needs an explicit **terminal bound** in S — never unbounded tolerance, and the bound must be **global**: every malformed shape, the transaction-shaped and in-pull ones included | the budget is checked BEFORE the transaction routing in `host/l6_console.py`; past it the global reason wins, no transaction advances, no re-request is sent, and a pull in flight is failed with that reason and aborted exactly once | `test_l6_s2_host_batch.BadFrameBudgetIsGlobal` (6): the six shapes (REC / IDENT / SIGNREQ / TERM / non-transaction / in-pull) at `bad_frame_budget=0`, the ledger keeping the line that crossed the bound, within-budget recovery unchanged, a non-integer / bool / negative budget refused, and v0.6 untouched; `…::test_the_malformed_line_again_and_again_is_bounded_by_the_budget`; `test_l6_v07_rules.SoakBadFrameBound` (3) |
| opening baseline always; the closing baseline only on `COMPLETED` | `host/l6_checks.py:82` `baseline_findings` | `test_l6_v07_rules.BaselineGate` (3): S #2's artefact reproduced on a COMPLETED fixture and absent on the real CRASHED log; C1 #6 unchanged |
| v0.7 must **rule the heartbeat rule explicitly** (per-record cap kept or dropped for an aggregate budget + index completeness + the 20 s liveness) | `host/l6_rel.heartbeat_findings_v07` beside the unchanged `heartbeat_findings_rel`; `l6_checks.structural_findings(..., hb_rule=)`; §3 D-h1 and §6.11 of the draft state the choice | `test_l6_v07_rules.HeartbeatRuleV07` (6), including the S #2 shape under both rules and an unknown rule refused |
| the soak's N: keep wall ≥ 0.9 T, compute a policy-matched rate from the pinned calibrations' immutable timing inputs, publish unrounded intermediates and the single final floor, use a recorded pace only as a post-hoc gate — and size N from the **faster** arm while the timeout keeps the slower one | `host/l6_soak_plan.py` (4 named rules, `ARM_FOR_RULE`, fixed point on the audit fraction), `l6_runner.plan_session` under `sessions.S.n_rule` | `test_l6_v07_rules.SoakPlanLocked` (8) and `RuleSelection` (5) |
| the post-hoc gate excludes seq 1's forced controls and normalises the pace to the final sampled-audit fraction | `lsp.observed_interval_s(exclude_seqs=(1,))` and `validation_gate(target_audit_fraction=…)` | `SoakPlanLocked::test_the_post_hoc_pace_excludes_the_seq_1_controls_and_is_normalised` |
| the v0.7 draft must not inherit v0.6's present tense | `docs/l6_soak_prereg_v0.7_draft.md` regenerated from the frozen text | `test_l6_v07_rules.V07DraftDrift` (5) |
| reusing the v0.6 calibrations must be an **explicit import** by report and the three input hashes, never a pretence that they bind the new prereg; honoured under v0.7 only; the version paired with the hash; the evidence verbatim | `manifests/…` `calibration.<k>.imported`, enforced in `l6_runner.plan_session` against the manifest's own `prereg.supersedes` chain; §3 D-i1 | `test_l6_v07_import.ExplicitImport` (9): refused without it; refused under any version but v0.7; `from_prereg_version` mandatory and paired with the hash through the supersedes chain; a wrong hash / other report / other inputs / no justification each refused; the import relaxes the prereg hash and nothing else; the plan's evidence carries the three input hashes verbatim, no placeholder |
| nothing of v0.7 may run under v0.6 | `l6_runner.rules_for` keyed on `prereg.version` | `RuleSelection::test_under_v06_nothing_of_v07_runs`, `…::test_under_v07_the_ledger_policy…`, `ExplicitImport::test_under_v06_nothing_of_this_runs…` |
| a full modelled-channel soak | `host/l6_session_soak.py` | `test_l6_session_soak` (13) |

## 2. The two replays, side by side

**Raw bytes (S #2's own console.log, 586 454 bytes, read-only).** Driven through the real
stack in random poll-sized pieces:

| policy | outcome |
|---|---|
| `crash` (v0.6) | `CRASHED: unparseable frame`, `last_seq 144` — the day's outcome, reproduced exactly; `bad_frames 1`, `crc_dropped 2` = `{SIGNREQ 1, REC 1}` (the two controls) |
| `ledger` (v0.7) | the epoch stays OPEN. `bad_frames 1`, the same two CRC drops, 144 records, `relay.last_seq 145`, seq 145 pending, **nothing sent for the merged line** (`RECACK` 144, `RECGET` 1 = the control only, `SIGNOK` 145, `SIGNGET` 1 = the control only), no fragment |

The replay CONSUMES the merged line from the recording, so the modelled continuation does
not deliver it again: `RecBoard.start()` establishes the state the recording ends in —
attempt 1 sent, and mangled on the way — and only the bound's resend is delivered. (Two
tests do deliver a malformed line again on purpose, and say so: the repeated-line budget
case and the policy unit check.)

**What the recording cannot show**, because it stops 0.2 s later at the port close: whether
the board really resent. So the modelled continuation, using the PYTHON twin of the REC
transaction (`l6_rec.RecBoard`, cross-verified against the image's C unit
`firmware/p3_rectx.c` by the wire-contract tests): attempt 1 delivered as the
recorded merged line → the bound elapses → **the same bytes** resent → accepted once, one
`RECACK 145`, record 145 appended once, ledger `["ok"]`, the twin `acked` after 2 attempts,
and the next `SIGNREQ 146` proceeds. This is a model of the board, not a measurement of it:
`RecBoard` is the Python twin, cross-verified against the image's C unit by the
wire-contract tests, and the clock is virtual.

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

**Which gates the model runs, exactly.** The soak drives the PROTOCOL gates over the
artefacts each session leaves: `structural_findings` under both heartbeat rules, REC
closure and control, rel-v4 closure and control, and the baseline gate. It does NOT run
`l6_checks.soak_findings` — that needs a rate report and a real duration — so the
heartbeat GAP, the CRC and bad-frame budgets, the wall fraction and the settle bound are
not claimed here; the bad-frame bound is exercised directly in
`tests/test_l6_s2_host_batch.py`, and a test asserts the soak's own gate set so the claim
cannot drift.

`evidence/l6_session_soak/rel_v4_soak_sized_2026-09-03.json` — 3 sessions at the soak's own
size (N = 12568, the `policy_matched_wall` candidate under D-n1 as ruled) at ≈ 6× the
recorded line fault rate: `COMPLETED` 12570/12570 every time, zero unrecovered, every
protocol gate empty **except** the heartbeat rule, and there the two rules part:

| seed | records that lost heartbeats | v0.7 (record budget 12) | v0.6 (one per record) |
|---|---|---|---|
| 101 | 2 | clean | HOLD — 1 record named |
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

**The arm that sizes N (owner's ruling 2026-09-03).** `min()` is right for a timeout — the
slow arm must fit — and wrong for a wall-time floor: a soak running near the faster arm
finishes a min-sized N too early and fails `wall ≥ 0.9 T` by construction. So every
policy-matched rule sizes N from **max(rate_A, rate_B)** while the timeout keeps
`min(rate)`; `planning` stays on `min` because it reproduces v0.6 exactly, which is what
S #2 ran. The gate's input excludes seq 1 (its two forced retry controls are not the loop's
pace) and is normalised to the candidate's own sampled-audit fraction:
`interval − (f_intervals(S #2) − f_target) × mean_audit_s`. `f_intervals` is the audited
share **of the intervals this mean is made of** — an interval is s → s+1, so seq s's audit
stage lies inside it and the last record's audit lies in no interval: 142 intervals of
which 9 are audited (seq 2, 16, 32, 48, 64, 80, 96, 112, 128), with `mean_audit_s` taken
over exactly those nine. Using the whole session's PLANNED fraction here was wrong in the
other direction (owner's review 2026-09-03): the number being corrected is this prefix's
mean, so the fraction must be this prefix's.

| rule | arm | rate C1 | rate C2 | unrounded product | **N** | sampled audits | predicted wall at S #2's pace | gate |
|---|---|---|---|---|---|---|---|---|
| `planning` (v0.6, what S #2 ran) | min | 3381.372371 | 3367.753097 | 6061.955574 | 6061 | 382 | 3273 s | **FAIL** |
| `policy_matched_period` | max | 6222.945767 | 6199.917170 | 11201.302380 | 11201 | 704 | 6047 s | FAIL |
| **`policy_matched_wall`** | max | 6982.314889 | 6950.492576 | 12568.166801 | **12568** | 789 | **6784.94 s** | **PASS** (floor 6480 s, margin 304.94 s; timeout 8739 s) |
| `policy_matched_span` | max | 5871.045460 | 5851.734220 | 10567.881829 | 10567 | 664 | 5705 s | FAIL |

Against the owner's own regression targets, every figure now reproduces to the digit:
N 12568, 789 sampled audits, 233 364 expected inbound frames, CRC and bad-frame budget 934,
timeout 8739 s; 142 intervals, 9 audited, mean audit stage 0.4773988638 s, raw interval
0.5401501666 s, normalised 0.5398581010 s, predicted wall 6784.9366 s, margin 304.9366 s.

The owner's two candidate estimators are both here and their difference is identified:
`policy_matched_period` (≈ the "6197" figure) works from the inter-proposal period, which
includes the gap between one record and the next SIGNREQ; `policy_matched_wall` (≈ "6952")
works from the candidate's own SIGNREQ→REC wall time. The difference is exactly that gap,
0.0627 s per record in C1. **`policy_matched_wall` is the rule the owner ruled for v0.7**;
the other three are computed and published beside it so the choice stays auditable. The
rounded-label counterexample is locked as a test: `floor(0.9 × 6952 × 2)` = 12513 while the
unrounded 6952.2375 gives 12514 — N is the floor of the unrounded product, taken once, and
never the floor of a displayed value. S #1's pace is computed and reported but does not
gate: it ran pull-v2, another protocol.

## 5. Candidate artefacts and hashes

| artefact | sha256 |
|---|---|
| `docs/l6_soak_prereg_v0.7_draft.md` (the freeze candidate, 746 lines, self-contained) | `7958554c21166c924c0e775ee26fbdcac0970377361072b2f8eecd67290f94fd` |
| `manifests/l6_manifest.json` (UNCHANGED — still the pushed one) | `54583314c16295c24f083efe402ec0cf98a54da5ca8d30afbfd5851c5eedfc68` |
| the frozen preregistration in force (`docs/l6_soak_prereg.md`, v0.6) | `bfd69d1037c4d2715759befef766d353b99741c8ff6ef6cb0ca30bbd325a620a` |
| the pinned image (unchanged, no rebuild) | `5deee74c44785ebe88168ccffaa5f399f26a7c5a567fccb3d430cf4eb14cdc7c` |

**What the freeze would change in the manifest, if the owner rules for it** (not done
here): `prereg` → v0.7 with the draft's hash, v0.6 into `supersedes`; `sessions.S.n_rule`
= the rule the owner picks; `calibration.C1/C2.imported` = the D-i1 declarations; the
draft's bounds merged into `pass_conditions`. The runner reads all of it from the manifest
already — `rules_for()` turns nothing on until `prereg.version` says v0.7.

## 6. Suite

`bash host/run_tests.sh` — 1097 tests, 1 skip, rc 0 (`evidence/tests/test_report_2026-09-03T190303Z.json`). New: `tests/test_l6_s2_host_batch.py`
(21), `tests/test_l6_v07_rules.py` (34), `tests/test_l6_session_soak.py` (14),
`tests/test_l6_v07_import.py` (9). The rule-version guard in `tests/test_l6_transport.py`,
the withdrawn-hash allowance for the draft and the import manifest are updated; every
pre-existing test is unchanged and green, which is the point: under v0.6 nothing of this
batch runs.

## 7. Asked of the owner

1. Review this batch (host-only, no board, nothing pinned).
2. Confirm the corrections of §8 close the HOLD.
3. On PASS: the push, then the v0.7 freeze (its sha into the manifest, v0.6 superseded in
   history, `sessions.S.n_rule = policy_matched_wall` and the two import declarations
   written), and only then the ruling on the next board session.

## 8. The owner's HOLD of 2026-09-03, and what each blocker became

The owner's review of `d905c15` accepted the direction and the four decisions in principle
(**D-h1 PASS**; **D-b1** policy accepted, implementation HOLD; **D-n1** `policy_matched_wall`
chosen but with the sizing arm corrected; **D-i1** the import accepted, enforcement HOLD)
and named five blockers. Each is closed here, with the test that would have caught it:

| # | the blocker, as the owner reproduced it | the correction |
|---|---|---|
| **B1** | the bad-frame bound sat AFTER the transaction routing, so a REC/IDENT/SIGNREQ/TERM-shaped or in-pull malformed line returned before it — with `bad_frame_budget=0` the epoch stayed open and a `RECGET` still went out | the bound is checked FIRST and is global: past it the epoch ends `PROTOCOL_BAD_FRAME_BUDGET`, no transaction advances, nothing is sent, and a pull in flight is failed with the global reason and aborted exactly once (its attempt still ledgered). The constructor now also refuses a bool or negative budget. `BadFrameBudgetIsGlobal` (6) covers the six shapes |
| **B2** | dropping `from_prereg_version` still imported; a v0.8 target still imported; the plan's evidence replaced the three input hashes with `"(the report's)"` | the import is honoured only under v0.7; `from_prereg_version` is mandatory and is verified as a PAIR with the hash against the manifest's own `prereg.supersedes` chain; the evidence keeps the declaration verbatim. Four new negatives in `ExplicitImport` |
| **B3** | N was still `min(rate_C1, rate_C2)`, which cannot guarantee a wall-time floor | `ARM_FOR_RULE`: every policy-matched rule sizes N from the faster arm, `planning` keeps `min` as the v0.6 control, and the timeout always uses the slower arm. The gate now excludes seq 1's forced controls and normalises the pace to the target audit fraction. The regression targets reproduce (N 12568 / 789 / 233 364 / 934 / 8739 s) |
| **B4** | the draft still said the calibrations were null and the image had not run, D-p1 contradicted D-h1, the three-rate rule omitted v0.7, §9 re-ran C1 → C2 → S under v0.6, and §6 item 14 printed before 13 | the draft is regenerated from the frozen text with each of those corrected, and `V07DraftDrift` (5) refuses the stale phrasings, requires the present ones, and checks the item order |
| **B5** | the continuation test re-delivered the merged line the replay had already consumed; the package called the Python `RecBoard` a C twin; the session soak claimed gates it did not run; the tracked red report had no explanation | the continuation starts from `RecBoard.start()` and delivers only the resend (the two tests that do repeat a malformed line say why); the package names `RecBoard` as the Python twin cross-verified against the C unit; the soak's gate set is named and asserted; `docs/decisions.md` records what the red report was |

## 9. The owner's second HOLD of 2026-09-03, and the three gaps it closed

The owner passed B2 and B5, and the main N formula (`policy_matched_wall`, the faster arm
for N and the slower for the timeout, with the regression targets reproducing), and found
three remaining interface gaps:

| # | the gap, as the owner reproduced it | the correction |
|---|---|---|
| **B1′** | when one malformed line was BOTH past the global bound and the pull's third failure, the pull failed itself inside the silenced-sender window, so its `AUDITABORT` never went out: `bad_frames 3`, `PROTOCOL_BAD_FRAME_BUDGET`, 3 attempts, 3 `AUDITGET`, **0 `AUDITABORT`** | the silenced-callback trick is gone. Past the bound the terminal attempt is written to the pull's ledger directly (same seq, chunk, attempt index and `malformed` outcome, the line kept verbatim) and the pull is then failed through its NORMAL sender: no fourth `AUDITGET`, exactly one `AUDITABORT`, and its payload carries the global reason. `BadFrameBoundAndPullExhaustionCollide` (2) is the dedicated collision test the owner specified, with the non-collision case beside it |
| **B3′** | the normalisation used S #2's whole-session planned audit fraction (382/6063) to correct a mean built from a 142-interval prefix | it now uses the audited share of those intervals — 9/142, with the mean audit stage over exactly those nine, and seq 144's audit correctly counted in no interval. Every figure now equals the owner's: raw 0.5401501666 s, normalised 0.5398581010 s, wall 6784.9366 s, margin 304.9366 s. The `n_vs_t` evidence is regenerated and this package's own numbers corrected |
| **B4′** | the draft's §5 S row still printed `⌊0.9 × min(rate_A, rate_B) × T⌋`, contradicting D-n1 in the same document; D-s3 and D-t1 stated their v0.6 `min` formulas as present-tense rules | the S row states the ruled formula (`max`, `policy_matched_wall`, the faster arm); D-s3 and D-t1 keep their formulas but are explicitly marked as v0.6 history that **D-n1 supersedes**. `V07DraftDrift` now reads the S row itself and both decision rows, instead of looking for a phrase anywhere in the file |

Nothing else moved: N, the audit count, the frame count, the budgets and the timeout are
unchanged, no hardware was re-run, and the manifest is still `54583314…`.
