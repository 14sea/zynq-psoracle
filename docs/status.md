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
| L0–L4 overall review | **HOLD → pending re-review** (2026-08-31): documentation drift (fixed by this table + historical banners) and a test-environment caveat (below) | owner | this file |
| L5 the loop | not specified; **D1** (standalone) to be specified first | — | `docs/decisions.md` D1 |

Board: EBAZ4203 `17A6`, U-Boot control plane, carrier `builds/p3/p3.bit` (`956379fa…`).
Sessions: 2 L2 instrument outcomes + 1 PASS; L3 session #1 STOP (instrument) + diagnostic ×2
+ 5 PASS; L4 1 PASS. No kill criterion triggered.

## Test-suite status and environment caveat

`python3 -m unittest discover -s tests` = **234 tests**. One of them,
`test_known_answer_through_the_real_signer`, drives the REAL signer principal through
`sudo -n -u p3signer`; it needs a host where the D4 boundary exists and sudo works. In a
sandbox where sudo is blocked (`sudo: The "no new privileges" flag is set`, or
`/etc/sudo.conf` ownership) it **used to fail** and the run was 233/1 — reported by the
reviewer 2026-08-31. It now **skips with the environment's exact sudo error as the reason**
(never a silent pass); a skip is not green and is counted in the report. `host/run_tests.sh`
records exit status, counts, and the sudo probe into `evidence/tests/test_report_<date>.json`;
the latest report from the host with the real boundary is listed there.
