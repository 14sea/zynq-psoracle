# L6 §4 — the host-only instrument batch (delivered 2026-09-01, awaiting owner review)

> **Standing: host-only.** Authorised by the owner on 2026-09-01 after the v0.2 review of
> `docs/l6_soak_prereg.md` ("現在授權 §4 的 host-only 儀器批次"), with the boundary: host
> code, validators, fixtures, tests, a manifest draft and documents; a Python reference of
> the operators and the schedule; **no firmware change, no two-operator image build, no
> ruling, no board contact.** Nothing in this batch touched `firmware/`, `manifests/l5_*`
> or any evidence directory. `host/l6_runner.py` cannot run today by construction (§4
> below). The §2 firmware/image work waits for the review of this batch.

## 1. Item by item (prereg §4 → what exists → where it is proven)

| §4 | delivered | file | proof |
|---|---|---|---|
| 1 timestamps | `Timeline`: monotonic + wall receive stamp on every console line, every host send stamped, `console.ts.log` companion (raw `console.log` verbatim), `timeline.json`, `run_log.timing.records[seq]` = `t_signreq, t_reply, t_auditreq, hb[], audit[], t_rec, wall, breakdown` | `host/l6_timing.py` | `tests/test_l6_timing.py` — the attribution test runs over **session 4's real console frame order** (read-only) and recovers all six stages for all ten candidates |
| 2 rate report | `rate_report()` pure; CLI writes `rate_report.json` once; **refuses session 4's log** (no per-frame timing) | `host/l6_rate.py` | `tests/test_l6_rate.py` (refusal on the real session-4 log; exact numbers on a synthetic timed log) |
| 3 sampled audit policy | `check_audit_policy(..., policy="sampled", schedule=set)`: scheduled `SCORED` must be audited; every non-`SCORED` self-report (`AUTO_AUDIT_OUTCOMES`) must have been auto-audited (§3a item 2); `REFUSED_BY_GATE`/`STOP_AXI` exempt; the all-self-reporting branch unchanged | `validators/records.py` | `tests/test_l6_policy.py` — §3a item 5's two negatives on **session 3's real STOP_ARM record and its eight served chunks**, re-keyed to an unsampled seq: words withheld → `RecordError` naming exactly that seq (HOLD); a word flipped → `Falsified` (KILL); words intact → accepted as `audited_auto` |
| 4 arm-aware validator | `check_arm_schedule(log, schedule, n, expected_genomes)`: `arm` required on every candidate and equal to the schedule's; absent on both baselines; unknown names refused; optionally the genome must be what the scheduled operator's twin produces. `check_l6_identity()`: IDENT names `master_seed`, `schedule_mode`, `operator_data_sha256` | `validators/records.py` | `tests/test_l6_policy.py` (swapped arm, missing arm, arm on a bracket, unknown arm, twin mismatch, each identity field) |
| 5 ruling text + runner | `whole-of-probe P3-L6` checked by `pr.check_ruling`; an L5 ruling is refused by text. The runner = L5's console loop + relay + collector, with the preamble **copied verbatim** from `host/l5_runner.py` (the PASSed L5 instrument is not edited) | `host/l6_runner.py` | `tests/test_l6_runner.py::Refusals` — every refusal reached in order and about its own check; the last one before board contact is the boundary |
| 6 budget arithmetic | S: N = ⌊0.9 × min(rate_C1, rate_C2) × T⌋ with the rates read **only** from rate reports whose bytes hash to the manifest's pins; timeout = 1.25 × (N+2) × 3600/min(rate) + 600 s, recorded with its inputs; `--budget`/`--n` do not exist | `host/l6_schedule.py`, `host/l6_runner.py::plan_session` | `tests/test_l6_schedule.py::SoakArithmetic`, `tests/test_l6_runner.py::Plan` |
| 7 expected frames + CRC budget | `expected_frames(n, audited_seqs)` from the fixed brackets, `crc_budget = ceil(4 × total / 1000)`, computed in `plan_session` before the session and written to `run_log.l6` and the summary; the relay's drop budget IS this number; `structural_findings()` (missing REC / AUDIT / TERM) independent of it | `host/l6_schedule.py`, `host/l6_checks.py` | `tests/test_l6_schedule.py::ExpectedFramesAndBudget` (session 4's 263 frames reproduced exactly), `tests/test_l6_runner.py::Checks` |

Also delivered, because §2 will need them and the owner allowed a Python reference:

| | file | proof |
|---|---|---|
| A,B,B,A arm schedule, pair seeds, sampled audit schedule, seq↔index, identity-page flags | `host/l6_schedule.py` | `tests/test_l6_schedule.py` |
| the two operators (random-safe, map-guided) and the map data an image compiles in, derived from the pinned `local_map.json` + phenotype manifest; its sha256 `0c9c82a8…` is the pin the IDENT must name | `host/l6_operators.py` | `tests/test_l6_operators.py` (derivation hash pinned; universe == whitelist; uniform reach over all 292; same-LUT locality; corpus) |
| twin corpus, N = 256 `(master_seed, index)` pairs, both arms | `fixtures/l6_operator_corpus_v1.json` | `tests/test_l6_operators.py::Corpus` |
| PASS/HOLD conditions of §6 as pure functions | `host/l6_checks.py` | `tests/test_l6_runner.py::Checks` |
| the manifest draft (all pins that exist today; the image, the frozen prereg hash and the calibration records null) | `manifests/l6_manifest.json` | `tests/test_l6_operators.py::MapData`, `tests/test_l6_runner.py` |

## 2. What a session will produce (evidence directory)

`L6_0_preflight.json`, `L6_1_identity_page.json`, `ymodem.log`, `ymodem_app.log`,
`console.log` (verbatim bytes), **`console.ts.log`**, **`timeline.json`**, `run_log.json`
(with `timing` and `l6`), `audits.json`, **`rate_report.json`**, `summary.json` (with
`l6` = the plan, `findings`, `rate`, `arm_check`, `l6_identity`, `audit_policy`).

## 3. The frame sequence and the six stages

From `firmware/p3_app.c` (unchanged): `SIGNREQ` → host reply → `HB`#1 (streams built,
before the link-2 witness) → `HB`#2–4 (one per envelope DMA) → `HB`#5–16 (one per frame
readback) → `AUDIT`×8 (when served) → `REC`.

| stage | boundary |
|---|---|
| `sign` | `SIGNREQ` → reply |
| `stage` | reply → `HB`#1 |
| `link2_dma` | `HB`#1 → `HB`#4 (the link-2 witness and the three DMAs cannot be split further from the sequence) |
| `link3` | `HB`#4 → `HB`#16 |
| `audit` | `HB`#16 → last `AUDIT` (0 when none) |
| `arm_settle_score` | last `AUDIT` (or `HB`#16) → `REC` |

`wall` = `REC` − `SIGNREQ`; `period` = `SIGNREQ`(seq+1) − `SIGNREQ`(seq), which also
contains the application's work between records (operator time). Resolution: one runner
poll (~20 ms) — every line a poll returned shares its stamp; stated in the report.

## 4. Fail-closed today

`host/l6_runner.py` refuses, in order: a ruling whose text is not `whole-of-probe P3-L6`;
a session not in {C1, C2, S}; `manifests/l6_manifest.json` `prereg.sha256` null or not
the hash of `docs/l6_soak_prereg.md` (**null today**); `app_image_sha256` null (**null
today**) or not the file's hash; the watchdog not pinned ON with prescaler 7 / load
1 250 000 035; for S, either calibration record missing or not hashing to its pin (**null
today**); the boundary older than 6 h or failed; an existing evidence directory; the map
derivation not regenerating to the pinned hash. The ruling is consumed only after all of
these. `tests/test_l6_runner.py::Refusals::test_the_real_draft_manifest_cannot_run_anything`
pins that the committed draft refuses.

## 5. Choices made in this batch that the review should confirm or overturn

None of these is in the preregistration's text; each is the smallest reading I could make
and is isolated so a different ruling is a local change.

1. **CoV is over `period`, not `wall`** (`cov_wall` reported alongside). Reason: N is
   derived from the rate, the rate from the period, and §6.3 bounds "the coefficient of
   variation over candidates" of the quantity the budget rests on. C2's operator compute
   time is inside `period`, which is where §5 says it may differ.
2. **Baselines carry no `arm`.** §2.4 says `loop_record.arm ∈ {random_safe, map_guided}`;
   the blank baselines are brackets from no operator, so the validator requires the key
   absent on seq 1 and seq N+2 and present on every candidate. (Alternative: a third
   value `baseline`; rejected as widening the enum.)
3. **Identity-page `flags` bits 2–3 = schedule mode** (0 abba, 1 random-safe forced,
   2 map-guided forced, 3 refused); bit0 holdout and bit1 watchdog as before. A session
   with flags = 0 is bit-for-bit L5's word.
4. **Pair seed** = upper 32 bits of xorshift64 after 4 warm-up steps over
   `((master_seed<<32 | master_seed) ^ (pair+1)·golden)`. One step was not enough: it
   leaves the high half independent of the lowest bits, so pairs 0 and 1 produced the
   same seed and the same genome in the same arm (caught by the smoke, pinned by a test).
   The image's C twin must reproduce this exactly; the corpus is the contract.
5. **`mutation_bits = 4` for both arms** is a draft pin for the instrument only; the rate
   does not depend on it (every candidate rewrites all twelve frames). Claim B's own
   preregistration fixes the arms' value at its freeze.
6. **Timeout** = 1.25 × (N+2) × 3600/min(rate) + 600 s (§4.6 says "with margin"; the
   numbers are mine). C1/C2 have no calibration yet and take `--session-timeout-s`
   (default 7200 s), recorded as such.
7. **`STOP_AXI` stays exempt wholesale** (`NO_SELF_REPORT_OUTCOMES` unchanged). §3a item 3
   exempts a pre-staging `STOP_AXI`; the current firmware emits no `STOP_AXI` record at
   all (an AXI fault ends the epoch), and the audit gate refuses served words for it, so a
   post-staging variant would need a firmware decision first.
8. **The 20 s gap rule is over consecutive received frames of any type**, not `HB`
   frames only — the collector's silence rule is what the board must beat, and the host
   hears every frame.
9. **The preamble is duplicated**, not factored out of `host/l5_runner.py`: the L5 runner
   PASSED and has no host test of that preamble; editing it to share code would be a
   change without a gate.
10. **IDENT field names** `master_seed` (int = the page's seed word), `schedule_mode`
    (string), `operator_data_sha256` (64 hex) — additive `app_identity` 1.1.0;
    `loop_record` 1.1.0 adds `arm`. The C wire twin and the contract test are §2's.
11. **`--master-seed` is a required CLI argument** (§0: seeds are host-supplied) and is
    written into `run_log.l6` and the summary; there is no default.
12. **Default image path** `firmware/bsp/out/p3_app_l6.bin` — a name, so the L6 runner
    can never pick up the L5 image by omission (the hash check would refuse it anyway).

## 6. Not done here, by the boundary

No `p3_app.c` change (§2.6a auto-audit, §2.6 watchdog prescaler, the two operators, the
arm in the record, the IDENT fields), no `p3_data.h` regeneration, no build, no C twin of
the operators/schedule, no wire-contract test for the new fields, no ruling, no board.
