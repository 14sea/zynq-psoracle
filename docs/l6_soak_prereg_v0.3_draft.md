# L6 preregistration v0.3 — draft, MERGED INTO THE FROZEN TEXT 2026-09-01 (historical)

> **Standing: HISTORICAL. Every delta below was merged into the frozen `docs/l6_soak_prereg.md` v0.3 on 2026-09-01 (owner-authorised freeze batch); this file records what the draft asked for and is no longer an authority.** The frozen
> v0.2 (`docs/l6_soak_prereg.md`, sha `90f5fa69…`) stands untouched; `host/l6_runner.py`
> still binds to it and to the board-ready image `bd1454cd…`. This draft records ONLY the
> deltas the pull protocol (`docs/l6_audit_pull_design.md`) requires; everything not named
> here is v0.2's text verbatim. Freezing v0.3 — a new hash, a new freeze, new ruling
> bindings — is the owner's decision after the whole-package review of the pull batch.

## Deltas against v0.2

1. **§2.6a (the image's audit duty)** becomes: for every candidate whose audit is due —
   a SCORED-path candidate the host selected by `AUDITREQ` at sign time, and every
   non-`SCORED` self-report unconditionally — the application announces `AUDIT_READY`
   and serves sparse-v1 chunks (`app_audit_chunk` 2.0.0) on each `AUDITGET`, as often as
   asked, until `AUDITDONE` or `AUDITABORT` or its own bounded wait
   (`P3_PULL_IDLE_POLLS`, a count) runs out. `verified: audited` means `AUDITDONE` was
   received — nothing less.
2. **§3a item 2** (unconditional audit of non-`SCORED` self-reports) is unchanged in
   meaning; the mechanism is the pull above.
3. **New outcome `STOP_AUDIT`** (validators 1.1): a SCORED-path candidate whose pull did
   not complete makes **no ARM attempt**; its record carries the oracle self-report and
   `evidence.audit_stop {why, chunks_served}`, is never `audited`, and the epoch stops
   (restore, TERM). Always a HOLD under either policy.
4. **D-s4 brackets** become protocol `pull-v2` (`host/l6_schedule.expected_frames`):
   inbound per audited record = `AUDIT_READY` × 1 + `AUDIT` × 8 (retransmissions arrive on
   top and are what the budget is FOR); `HB` stays 16 per record; the host's `AUDITGET` /
   `AUDITDONE` / `AUDITABORT` are outbound and not budgeted. The CRC budget formula is
   unchanged: `ceil(4 × expected_protocol_frames / 1000)`; the one inbound ledger
   (`host/l6_console.py`) enforces it for every frame type.
5. **§4.7 (audit service)**: the host-paced pull with ≤ 2 retries per chunk; every failed
   attempt kept verbatim (`audits.json` `pulls[].lines_kept`) and CRC-budgeted; a timeout
   is an attempt, not a CRC drop; retries exhausted → `AUDITABORT` → HOLD.
6. **§6.3 (rate)**: the audit stage is `AUDIT_READY` → `AUDITDONE` on the host clock,
   retries included; `period`, CoV and the N/timeout formulas are unchanged.

## What freezing v0.3 requires (the owner's checklist)

The pull-batch package review (`docs/l6_pull_batch_package.md`); pinning the new image
(`next_image`, today `board_ready: false`) as `pinned_at_build`; writing this draft's
deltas into the frozen text; the new manifest hash; new bound rulings. Until then: no
ruling, no board.
