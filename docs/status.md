# Canonical status — zynq-psoracle (P3)

**This table is the only authoritative statement of rung status.** Every other document
that mentions a rung's state (architecture, decisions, designs, review packages, findings)
is a record of what was true *when it was written*; where the two disagree, this table wins
and the other text is historical. Updated with every adjudication.

| rung | state | adjudicated | evidence / record |
|---|---|---|---|
| L0 host-only architecture | **PASS** | owner, whole-line gate review 2026-08-29 (`docs/whole_line_gate_review_result.md`) | `docs/p3_architecture.md` §3 v0.3, `docs/l0_review_result.md`, `validators/`, `docs/import_manifest.md` |
| D4 key custody | **PASS** | owner re-review 2026-08-29 | `evidence/boundary/` (R1–R5 as the runner), `docs/decisions.md` D4 v0.3 |
| L1 P3 carrier | **PASS** (preparation) | owner re-review 2026-08-29 | `builds/p3/` (public build, +7.58 ns, isolation 6/0, ICAPE2 0), `docs/l1_design.md` |
| L2 = P2b non-perturbation | **PASS** on 17A6 | owner 2026-08-30, run #3 (ruling `2026-08-30-03`) | `evidence/l2_17A6_2026-08-30-03/`, `docs/l2_findings.md`; heartbeat pinned [49.5, 50.5] MHz |
| L3 one gated candidate | **PASS (scoped)** on 17A6 | owner 2026-08-31, five sessions | `evidence/l3_17A6_2026-08-30-03/`, `…2026-08-31-0{2,3,4,5}/`, `docs/l3_findings.md` |
| L4 fault / restore / baseline | **PASS** on 17A6 | owner 2026-08-31 (this table records the adjudication the owner gave in the L0–L4 review; see below) | `evidence/l4_17A6_2026-08-31-06/`, `docs/l4_findings.md` |
| L0–L4 overall review | **PASS (scoped)** — 2026-08-31, after two HOLDs (documentation drift → this table + historical banners; test-evidence plumbing → fail-closed `host/test_report.py`) | owner | this file; `evidence/tests/test_report_2026-08-31T15350{1,7}Z.json` |
| L5 the loop | **HOLD. Three board sessions, none adjudicating the rung. Session 3 is adjudicated HOLD (instrumentation defect) by the owner; a host-only design correction is built and awaits design review.** Session 1 (`evidence/l5_17A6_2026-09-01-01/`, image `d3828a8c…`): first execution; everything to the ARM held on silicon; stopped because the nonce did not step. Session 2 (`evidence/l5_17A6_2026-09-01-02/`, image `8390c463…` — DEFECTIVE, must not be run): CRASHED on my `CTRL` read-back (`CTRL` is write-only in `rtl/p3_axil.v`); fixed without widening the RTL contract, guarded by `tests/test_axi_map_vs_rtl.py` (closed sets both ways). **Session 3 (`evidence/l5_17A6_2026-09-01-03/`, image `10044abe…`, diagnostic per `docs/l5_diag_spec.md`): the `STOP_ARM` record was emitted with every required field — `status_after 0x901` (bit 0 = `gate_busy` SET), `fault_after 0`, `writes_issued 25`, nonces equal, audit five-for-five on the host.** `rtl/p3_arm_gate.v` steps the nonce only on `sh_done`; `arm_attempt` read it immediately after the strobe, where `host/l3_runner.py` had polled `gate_busy` clear first. *Early-read explanation strongly supported; standalone success after bounded settling remains untested.* **Adjudication vs. the runner:** the evidence keeps the runner's literal `KILL run_log rejected: audit must report audited <= total (rule ix)`; the owner adjudicated **HOLD** — no prereg §3 item met, the sole rejection was `TERM.audit.total` omitting the `STOP_ARM` record (the same log with `total = 1` validates), and the KILL wording was the runner's over-wide mapping, since corrected (`classify_rejection`). **Correction (host-only, 2026-09-01, `docs/l5_settle_correction.md`):** bounded read-only settle poll before the nonce read, new neutral `STOP_SETTLE`, `TERM.audit` from the serialiser's tally, Falsified-vs-HOLD classification, negative tests both ways; pinned image now `a7c73d1f…` (`10044abe…` withdrawn as superseded, not defective). **Design review round 1 (owner) = HOLD: the audit gate only trusted the record's `verified` mark — fixed host-only (`validators/audit.py`: closed reassembly, three-domain recompute, host-derived marks, mismatch = `Falsified`; the contract session now has the C code chunk real words). Round 2 = HOLD on one boundary inside the gate (full-length words that do not parse / repeat an envelope / stage fewer than twelve frames were `RecordError`, i.e. HOLD; they are content the record's hashes cannot be recomputed from — now `Falsified`, KILL; transport defects before assembly stay HOLD). Awaiting round 3; not run on hardware.** Prereg §6 design-review trigger fired; no ruling; board untouched since session 3. | HOLD per `docs/l5_prereg.md` §5 — owner's ruling 2026-09-01 (the runner's KILL string diverges and is recorded as such) | `docs/l5_session3_findings.md`, `docs/l5_settle_correction.md`, `docs/l5_session2_findings.md`, `docs/l5_session1_findings.md`, `docs/l5_diag_spec.md` |

Board: EBAZ4203 `17A6`, U-Boot control plane, carrier `builds/p3/p3.bit` (`956379fa…`).
Sessions: 2 L2 instrument outcomes + 1 PASS; L3 session #1 STOP (instrument) + diagnostic ×2
+ 5 PASS; L4 1 PASS; L5 3 HOLD (1 STOPPED, 1 CRASHED, 1 instrument-rejected). No kill criterion triggered; prereg §6 design-review trigger fired after L5 session 3.

## Test-suite status and environment caveat

`host/run_tests.sh` runs the suite and lands an evidence report **fail-closed**
(`host/test_report.py`: atomic write → registration in `docs/import_manifest.md` → `git add`;
any failure → exit 3 regardless of the suite's status; the suite's own status is returned
only when the report landed). The report records `exit_status`, counts, `skipped`,
`head_at_run` (the HEAD when the suite ran — necessarily earlier than the commit that
includes the report; `worktree_dirty` says whether the tree differed), the `sudo -u
p3signer` probe and `boundary_available`.

`test_known_answer_through_the_real_signer` needs the D4 boundary to be usable; where sudo
is blocked (`no new privileges`, `/etc/sudo.conf` ownership) it **skips with the exact sudo
error as the reason** — a skip is counted, never green. Reviewer's sandbox 2026-08-31 saw
233/1 before this; after: 

| environment | report | ran | result | boundary_available | no_new_privs | exit |
|---|---|---|---|---|---|---|
| this host, user `test`, sudo works | `evidence/tests/test_report_2026-08-31T153501Z.json` | 240 | OK | true | false | 0 |
| same host under `setpriv --no-new-privs` (sudo refused exactly as in the sandbox) | `evidence/tests/test_report_2026-08-31T153507Z.json` | 240 | OK (skipped=1) | false | true | 0 |

Earlier reports in `evidence/tests/` (`152909Z`…`153424Z`) predate the fail-closed tool and
carry a `commit` field that is simply the HEAD at their run time; they are kept as evidence.
Fail-closed behaviour itself is unit-tested (read-only output dir, unwritable manifest,
non-repo → `ReportError` / exit 3).
