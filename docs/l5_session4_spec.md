# L5 session 4 — the settle question (host-only specification, written before the board)

**Standing: host-only. This document authorises nothing.** Written after design review
round 4 (2026-09-01, PASS) lifted the prereg §6 design-review gate. It fixes, before any
ruling exists, what the next board session is *for*, what it must produce, and what may
and may not be concluded from it. It supersedes `docs/l5_diag_spec.md` (the session-3
specification), whose adjudication rows were written for the pre-settle firmware.

## 1. The one question

*Does the standalone application, waiting for the gate to settle before reading the
nonce, observe the nonce stepped?*

Sessions 1 and 3 read the nonce immediately after the strobe and saw it unchanged; session
3's record showed `gate_busy` set at that instant, and `rtl/p3_arm_gate.v` steps the nonce
only on `sh_done`. The early-read explanation is strongly supported; **standalone success
after bounded settling remains untested.** This session tests exactly that. It is not a
retry of sessions 1–3: the firmware is different in the two ways the correction batch
changed (`docs/l5_settle_correction.md`), and in nothing else.

## 2. What is identical to session 3, on purpose

`host/l5_runner.py` (same command line: `--audit-all --budget 8`), the carrier
`956379fa…`, the audit policy `all-self-reporting`, the brackets, watchdog off, the
boundary verifier, the preflight, the instrument rules. Only the pinned image differs:
**`a7c73d1f…`** (`manifests/l5_manifest.json`), reproducible from source.

## 3. Required output

Whatever the epoch's end, candidate 1's record must exist and carry `evidence.arm` with the
full `settle` block (`polls`, `polls_max`, `settled`, `status_first`, `status_last`),
`nonce_before`, `nonce_after`, `status_after`, `fault_after`, `writes_issued`,
`key_loaded_observed`, `ctrl_readback`; the audit words for every self-reporting candidate
must be served and must recompute on the host (the gate is inside
`validate_standalone_run_log` and cannot be skipped); the `IDENT` frame, the notary log,
the `TERM`, the full console, the `CPU_CLK_CTRL` preflight. A session that stops at the
ARM without a record carrying `settle` is an instrumentation failure and is reported as one.

## 4. Adjudication of the question — decided now

The outcome classes of `docs/l5_prereg.md` §5 apply **unchanged**; nothing here adds a way
to pass or changes what PASS/HOLD/KILL mean. This table says only what candidate 1's ARM
record means for the question in §1.

| candidate 1's record | the question | what it does NOT say |
|---|---|---|
| `settle.settled == true`, `nonce_after == step(nonce_before)`, outcome `SCORED` or `REFUSED_BY_PL` | **answered yes**: the standalone application observes the stepped nonce once it waits; sessions 1 and 3 were early reads | nothing about the rung beyond that record — the rest of the epoch is adjudicated by prereg §5 as it stands |
| `STOP_ARM`: `settled == true`, nonce unchanged | **answered no**: the gate settled and did not consume. The early-read explanation is refuted for this path and the question moves to the gate itself | not a root cause; the next step is a targeted probe (external observation of the gate, or an RTL read-only mirror — a new carrier), not a fifth immediate-read-style session |
| `STOP_SETTLE`: `settled == false`, `polls == polls_max` | **not answered**: the gate never settled within ~10⁶ reads. `status_first`/`status_last` and the nonce say what it was doing | nothing about consumption; the gate's completion time or the settle condition is now the question |
| any other stop before the ARM (identity, link 2, link 3, `STOP_AXI`), `PROTOCOL`, `CRASHED` | **not reached** | nothing about the ARM |
| a validator rejection | classified by type: `Falsified` → KILL, otherwise HOLD instrument — the runner's mapping, not a reading of this table | — |

**In every row the root cause remains undetermined until something explains it.** One
session is one observation.

## 5. Procedure

Unchanged from `docs/l5_prereg.md` §4 including "The ARM wait": power cycle; the boundary
verifier re-run as the runner (< 6 h); two new rulings — `whole-of-probe P3-L5` and
`provisioning P3-K` — created by the owner, consumed by any outcome; the blocking
`CPU_CLK_CTRL` preflight; the runner in the background, no shell timeout, waited on by pid.
The image on the board must be the pinned one; the runner refuses otherwise. Nothing is
re-issued after a stop; no second attempt within the session.

## 6. Stop-loss

`docs/l5_prereg.md` §6 remains in force (four sessions without `COMPLETED` is not a
threshold it names; the design review it demanded has been held). This session's own:
if it ends `STOP_ARM` or `STOP_SETTLE`, that is the result — the next step is the
targeted probe named in §4, and no further session runs the same firmware against the same
question.

## 7. What this session cannot establish

It cannot establish *why* a settled gate would refuse to consume, or *why* a gate would
not settle; only whether the standalone application, once it waits, sees what the host at
L3 saw. It says nothing about the interlock claim, which rests on L3 and is untouched.
