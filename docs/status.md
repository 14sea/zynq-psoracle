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
| L5 the loop | **PASS (scoped)** on 17A6 — session 4 (`evidence/l5_17A6_2026-09-01-04/`, image `a7c73d1f…`, spec `docs/l5_session4_spec.md`). **Scope, verbatim from the ruling:** EBAZ4203 17A6, carrier `956379fa…`, application image `a7c73d1f…`, the U-Boot→standalone control-plane crossing, a host-supplied seed, N = 8, all-self-reporting audit, under the established notary/interlock. Not extrapolated to autonomous discovery, long-run stability, other carriers/dies, Linux, or a precise ARM-gate time; `CLK_621_TRUE` unread does not affect this PASS; 16 is a count of Strongly-Ordered reads, not a time unit. **What held:** `COMPLETED` with all three closing steps done; 10/10 `SCORED`; both baselines `[18, 22, 20, 20, 20, 18]`; 80 audit chunks → 10/10 audited records, recomputed by the host gate and independently; validator `{scored 10, audited 10, chain_length 11}`; audit policy seq 1–10, no exempt; closing unsigned control `fault 13`, `cfg_valid_hw` clear; zero disruptions / CRC drops / re-reads; every ARM `status_first 0x901` → 16 reads → `status_last 0xf54`, nonce stepped once each. **The early-read explanation of sessions 1/3 is silicon-verified on the standalone plane.** No §3 falsifier. History: session 1 (`d3828a8c…`) stopped at the ARM on an immediate nonce read; session 2 (`8390c463…`, DEFECTIVE) crashed on my `CTRL` read; session 3 (`10044abe…`) captured `gate_busy` at the immediate read, adjudicated HOLD (instrument); the design correction (settle poll, tally, audit gate, Falsified/HOLD boundary) passed four review rounds. `-04` rulings consumed; board untouched since. | owner, 2026-09-01, after checking the evidence item by item against `docs/l5_prereg.md` §5 (all eight) and §3 (none) — `docs/l5_session4_findings.md` §3 | `docs/l5_session4_findings.md`, `docs/l5_session4_spec.md`, `docs/l5_settle_correction.md`, `docs/l5_prereg.md` |
| L6 calibration + soak | **§4 host-only instrument batch PASS (owner, 2026-09-01, third short review); §2 firmware/image batch AUTHORISED — no ruling, no board, no C1/C2/S yet.** Prereg v0.2 reviewed and pushed (`04d09ea`); §4 delivered (`451f8b2`), re-review HOLD × 2 corrected (`726c9e7`: heartbeat over HB frames only, STOP_AXI exempt by content, steady-state periods, mutation_bits frozen as the operator contract, single-sample CoV None; `6ee3c38`: exactly 16 HB per SCORED record in the shared structural gate) → PASS. Owner's independent re-run 571 OK (one pre-existing principal-boundary test skipped in the review environment; the fail-closed report here is 571/0 skip — not a contradiction). §2 scope: A/B operators + A,B,B,A/forced schedule + pair-seed C twin; mutation_bits = 4 and operator_data_sha256 contract; IDENT 1.1, candidate arm, flags bits 2–3; sampled audit with auto-audit of every non-SCORED self-report incl. post-staging STOP_AXI; watchdog ON (prescaler 7, load 1 250 000 035, flag-gated); 16 HB per SCORED record in seq/order; 256-corpus bit-exact twin; real C wire→relay→validator contract tests; two clean byte-identical rebuilds, build evidence, manifest/image hash, P3 compatibility review package. Then: whole-package compatibility review + prereg freeze → one ruling for the board phase. | owner, 2026-09-01 (§4 PASS) | `docs/l6_soak_prereg.md`, `docs/l6_instrument.md`, `manifests/l6_manifest.json` (DRAFT until the image is pinned) |

Board: EBAZ4203 `17A6`, U-Boot control plane, carrier `builds/p3/p3.bit` (`956379fa…`). Clocks board-confirmed 2026-09-01 (`evidence/preflight/slcr_17A6_2026-09-01-05.json`, read-only ruling `-05`): ARM PLL 1333.33 MHz, CPU_6x4x 666.67 MHz, **`CLK_621_TRUE` = 1 (6:2:1)**, PERIPHCLK 333.33 MHz — the last open clock observation of the L5 line, closed; it did not bear on the PASS.
Sessions: 2 L2 instrument outcomes + 1 PASS; L3 session #1 STOP (instrument) + diagnostic ×2
+ 5 PASS; L4 1 PASS; L5 3 HOLD (1 STOPPED, 1 CRASHED, 1 instrument-rejected) + 1 PASS (scoped). No kill criterion triggered; prereg §6's design-review trigger fired after session 3 and was discharged by rounds 1–4.

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
