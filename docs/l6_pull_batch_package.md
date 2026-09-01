# L6 pull-protocol batch — delivery package (host-only, 2026-09-01; awaiting the whole-package review)

> **Standing: host-only.** The owner's design review accepted the sparse pull IN PRINCIPLE
> and authorised this continuous closing batch. Delivered here: the corrected loss
> statistics, the closed transaction contract, the REAL wire state machine on both sides,
> the firmware, the C wire twin, host/validator support, negative and mutation tests, two
> byte-identical builds, and the prereg v0.3 DRAFT. **v0.3 is not frozen; the new image
> `e19e1b12…` is pinned as `next_image` with `board_ready: false`; the runner still binds
> to v0.2 + `bd1454cd…` and refuses everything else. No ruling, no board.**

## 1. The four review blockers, closed

| blocker | fix | proof |
|---|---|---|
| loss denominators | `host/l6_loss_stats.py`: complete = CRC-valid ∧ well-shaped ∧ `word_count` = 384 (**626**); transmission opportunities = full-size chunks on the wire, a merged line counting as two (**630**); the caveat says three events across C1 #1/#3, C1 #2 read nothing | `docs/l6_console_loss_summary.md`, `evidence/l6_console_loss_stats.json` |
| overstated benefit | "≈ 96 %" → **≈ 80 %** of the bytes (framing/token/CRC remain): corpus over C1 #3's 64 complete audits = ratio 0.192–0.201, sparse 4 291–4 493 B, non-zero 87–103, longest reply 676 B | `host/l6_audit_pull.py` CLI; `tests/test_l6_audit_pull.py::CleanPull::test_corpus…` |
| transaction binding | one seq, one binding (span/total/chunks fixed by the first chunk and re-checked; a mixed-span chunk refused: "one transaction, one binding"); the host additionally binds frame token, frame seq, payload seq, the READY's triple, and the requested chunk on every reply | `validators/audit.py::_assemble_sparse`/`check_sparse_chunk`; `tests/test_l6_sparse.py`; `tests/test_l6_audit_pull.py::Binding` |
| real wire state machine | `PullBoard`/`PullHost` exchange REAL P3L5 lines over a faulty `Channel`: READY/GET/DONE lost and duplicated, malformed-during-pull = retry (not CRASHED), exhaustion → `AUDITABORT` → `STOP_AUDIT` with **no ARM** and a stop, the board's wait bounded, sampled selection + §3a auto-audit | `host/l6_audit_pull.py`; `tests/test_l6_audit_pull.py` (21 scenarios) |

## 2. The firmware (compiled, never run; the candidate image)

`firmware/bsp/src/console.c` gains `console_rx_ready()` (a status-register read, BSP glue).
`firmware/p3_wire.{h,c}`: `p3_wire_audit_ready`, `p3_wire_sparse_entries` (the packed
(uint16, uint32) encoder), `p3_wire_audit_sparse`, and the `audit_stop` evidence block;
`loop_record` may now be `STOP_AUDIT`. `firmware/p3_app.c`: the dense `serve_audit` is
replaced by `audit_pull(with_readback)` — `AUDIT_READY`, then a bounded loop
(`recv_line_bounded`, `P3_PULL_IDLE_POLLS` — a count, like the settle poll) answering
`AUDITGET` (as often as asked, `json_uint`-bound to this seq), exiting on `AUDITDONE`
(the only place `S.audit_served` is set) / `AUDITABORT` / the bound; the SCORED path
pulls iff requested, BEFORE the ARM, and a failed pull emits `STOP_AUDIT`
(+`audit_stop {why, chunks_served}`) and stops with **no ARM**; every non-`SCORED`
self-report pulls unconditionally. The C encoder is bit-identical to the Python reference
on C1 #3's real words (`ready`/`sparse` twin commands), and the C pull lines drive the
real host puller to DONE (`tests/test_firmware_wire_contract.py::PullWireContract`).
Static/mutation coverage: `tests/test_firmware_audit.py` — the pull precedes every
non-SCORED emit and the ARM; the record precedes the stop; the `return -1` that forbids
the ARM is asserted (its removal is the named mutant); the mark set only in the DONE
branch, exactly once; the bound present; serving ≠ audited.

**Two from-scratch builds byte-identical: `e19e1b1289ddd9e0…`** (`next_image`,
`board_ready: false`; `bd1454cd…` remains the board-ready pin and the historical image).

## 3. Host and validator

`validators/audit.py`: `app_audit_chunk` 2.0.0 sparse-v1 assembly beside the unchanged
dense 1.0.0 path (session 4's chunks still assemble); dense/sparse never mix within a
seq. `validators/records.py`: `STOP_AUDIT` (needs oracle + `audit_stop`, forbids
arm/score, can never be `audited`, staged ≠ commit still `Falsified`, always a HOLD under
both policies). `host/l6_console.py`: the session creates a `PullHost` on `AUDIT_READY`,
routes lines to it while pending (CRC failures are its retries AND the one ledger's
drops; the budget still ends the epoch), harvests verified chunks into
`collector.audits`, and records every pull's ledger (`audits.json` `pulls`).
`host/l6_schedule.expected_frames(..., protocol="pull-v2")` carries the new D-s4
brackets. The runner ticks the pull's timeout each loop.

## 4. Suite

Everything green in the staged tree (the report the commit carries); the corpus, fault,
negative and mutation tests named above are all in the default discovery.

## 5. Next (the owner's)

Whole-package review → freeze prereg v0.3 (write the draft's deltas into the frozen
text, new hash) → pin `next_image` as `pinned_at_build` (board-ready) → new bound
rulings → the board phase resumes at C1. Until each of those: no ruling, no board.
