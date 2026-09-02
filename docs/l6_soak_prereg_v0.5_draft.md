# L6 — calibration and soak of the P3 loop (preregistration v0.5, DRAFT; transport-recovery revision)

> **Standing: DRAFT, NOT FROZEN.** v0.4 (`docs/l6_soak_prereg.md`, sha `12799ef9…`) stays
> frozen and in force; it is not overwritten. This draft is the text that becomes v0.5
> when the owner freezes it — after the transport batch package
> (`docs/l6_transport_batch_package.md`) passes review. Freezing authorises nothing by
> itself: C1, C2 and S each still need their own ruling pair, a power cycle and a fresh
> boundary record, and the §7 stop-loss the owner declared TRIGGERED on 2026-09-02
> (S #1 + C1 #5) stands until the owner lifts it.
>
> **C1 #5 (ruling `2026-09-02-01`) is and stays HOLD under v0.4.** Nothing in this draft
> re-judges it, and `calibration.C1` stays null: the owner ruled that a revision which
> merely excluded the retried period to turn C1 #5 into a PASS is not acceptable. Under
> v0.5, C1 and C2 are run again; no calibration pinned under v0.4 or earlier is reused.
>
> **Written 2026-09-02** after C1 #5 (HOLD: one audit chunk lost bytes, the pull recovered
> it in ≈2.1 s, and that one period put the coefficient of variation at 0.274 over the
> 0.10 bound; `docs/l6_c1_session5_findings.md`) under the owner's authorised host-only
> v0.5 design batch. Everything not stated as changed below is v0.4's, verbatim in force.

## 0. The two questions, and what they are not

Unchanged from v0.4 §0, with one clarification to Q1: the calibration now reports TWO
rates and the recovery indicators (§6.3 below). The **inclusive** rate — every steady-state
period, recoveries included — is the conservative one and is what S's N is derived from.
The **nominal** rate — the periods of candidates without a transport recovery — is the
instrument's own spread and is bounded only together with a minimum number of clean
periods and the recovery bounds. Neither is a Claim B quantity.

## 1. Pins

As v0.4 §1. The application image is unchanged (`403f4ab5…`, rec-v3): this revision
changes no firmware and no wire protocol.

## 2. The two-operator image — requirements

As v0.4 §2, items 1–6f unchanged. Added, host side only (§4 items 13–15 below carry the
deliverables): the chunk timeout of the audit pull is a **monotonic deadline** armed by
each `AUDITGET`; a reply that arrives **torn** (no line end) is **quarantined** on the
timeout and never glued to the resend; a frame head arriving with no line end before it
**resynchronises** the reader (the bytes before it are a quarantined fragment); a stale
byte-identical reply of an already verified chunk is **ignored**, never an attempt. The
board's behaviour (`p3_app.c`, `p3_rectx.c`, the pull state) is untouched.

## 3. Decisions — as ruled (D-s1..D-s4, D-r1..D-r5), plus D-t1..D-t3 proposed for the owner

| # | question | proposed ruling |
|---|---|---|
| **D-t1** the two rates | The calibration report carries `inclusive` (all steady-state periods) and `nominal` (the steady-state periods of candidates **without** a transport recovery), each with n, mean, CoV and evaluations/hour, and names every excluded seq. **S's N = ⌊0.9 × min(inclusive rate_A, inclusive rate_B) × T⌋** (D-s3 with the inclusive rate), never the nominal one. |
| **D-t2** recovery attribution | A candidate is *recovered* iff its pull ledger has a non-ok attempt or a timeout, or its REC ledger a retry (`RECGET`), or a `CRC_DROP` / `BAD_FRAME` / `FRAGMENT` event falls inside its window [`t_signreq(seq)`, `t_signreq(seq+1)`). The forced REC-retry control of seq 1 (§2.6c) is attributed as *control*, not as a recovery. Stale duplicates are reported, never a recovery on their own. Attribution is `host/l6_rate.recovery_by_seq`, from the ledgers the runner already writes (`audits.json` `pulls[]`/`recs[]`, `timeline.json` frames), never from a received frame count. |
| **D-t3** the chunk timeout | Stays `CHUNK_TIMEOUT_S = 2.0` s (C1 #5's value) in this draft. C1 #5's 528 clean chunk round trips took median 42.9 ms, p99 83.1 ms, max 83.6 ms; the host soak holds every invariant at 0.5 s with 42 % less virtual time under faults (§4 item 15). **≈0.5 s is the candidate for validation; the owner pins the value**, and a change is a host-only change re-frozen before any ruling. |

## 4. Instrument changes required before any L6 ruling (host-only, tested, reviewed)

Items 1–12 of v0.4 stand (delivered). Added by this batch:

13. **Reader resynchronisation and fragment quarantine** (`host/l6_reader.py`): a
    `P3L5 <TYPE> <seq> <token32> ` head inside the buffer with no line end before it
    moves the bytes before it to `fragments` (verbatim, stamped, reason `resync`) and
    parses the new frame from its head; `quarantine(reason)` moves the unterminated
    residue on demand (the pull calls it on a chunk timeout). Nothing is dropped
    silently: every fragment is in `console.log` (raw), in the reader's `fragments` and
    in the timeline as a `FRAGMENT` event (`timeline.json` `fragments[]`; not a frame,
    not a CRC drop, not a bad frame). A half line split across polls, a head split
    across polls and a base64 payload ending in `P3L5` are not torn (tests).
14. **Monotonic chunk deadline, stale duplicates** (`host/l6_audit_pull.PullHost`): the
    deadline is armed by every `AUDITGET` on the runner's monotonic clock and checked
    on every loop (`tick()` takes no accumulated dt); the timeout callback quarantines
    the residue **before** the retry GET is sent; a byte-identical reply of a verified
    chunk is recorded in the ledger's `duplicates` and is never an attempt; a differing
    stale reply is still a failed attempt.
15. **Replay and fault-injection soak** (`host/l6_transport_soak.py`, evidence
    `evidence/l6_transport_soak/`): C1 #5's recorded bytes replayed through the new
    reader + pull recover chunk 1 of seq 39 on the **first** resend (attempts
    `[timeout, ok]`; glued in one read, `[ok]` with no timeout), and the C1 #5 reader
    reproduces the recorded `[timeout, malformed, ok]` on the same bytes (discrimination
    control). The seeded soak over 2000 candidates per configuration (faults: truncate,
    interior deletion, drop, duplicate, glued duplicate, late tail before/after the
    timeout; random poll splits including inside the head) reports, per configuration,
    every single fault recovered on the first resend, no clean candidate marked, pulls
    failed only where one chunk took more faults than the retry bound; the numbers are in
    the package. **The soak measures the host mechanism over a modelled channel and
    nothing about the CH340/usbipd path.**
16. **The rate report 1.1.0** (`host/l6_rate.py`): `inclusive`, `nominal`, `recovery` and
    per-candidate `recovery`/`clean` alongside the unchanged top-level numbers (which
    stay the inclusive ones, so v0.4's rule is computed exactly as before); the CLI reads
    `audits.json` and `timeline.json` beside the run log. A report made without the
    ledgers says so and carries no nominal rate.
17. **The v0.5 PASS rule as code** (`host/l6_checks.calibration_findings_v05`), selected by
    the runner **only when the manifest's `prereg.version` is v0.5**; under v0.4 the
    runner computes v0.4's rule unchanged (C1 #5 = HOLD is reproduced by test).

## 5. Sessions — fixed in advance

As v0.4 §5: C1 (random-safe, N = 64), C2 (map-guided, N = 64), S (abba, 2 h). **C1 and C2
are run again under v0.5**; no earlier calibration is reused (D-r5 binding refuses them:
their `binding.prereg_sha256` is v0.4's or older).

## 6. PASS / HOLD / KILL — decided now

As v0.4 §6, with item 3 replaced and items 3a–3c added:

3. a timing record for **every** candidate; the rate report carries both rates and the
   recovery indicators (§3 D-t1, D-t2), every period and every retry published;
3a. **nominal CoV ≤ 0.10** (C1, C2), computed over the steady-state periods of candidates
   without a transport recovery, **and at least `min_clean_periods` = 60 of the 63
   steady-state periods clean** — fewer is a HOLD however small the nominal CoV;
3b. **recovery bounds** (C1, C2): candidates with a recovery ≤ 3, pull timeouts ≤ 3, bad
   frames ≤ 3, fragments ≤ 3 (CRC drops by D-s4's budget, unchanged; any missing
   `AUDIT`/`REC`/`TERM` a structural HOLD, unchanged) — crossing any one is a HOLD named
   by the bound, so a nominal CoV never hides an unstable link;
3c. the **inclusive** rate is reported and bounded by nothing; it is the calibration
   value S's N is derived from (a slower, recovering link gives a smaller N, which is the
   conservative direction).

The bounds of 3a/3b are pinned in `manifests/l6_manifest.json` `next_prereg.pass_conditions_draft`
and become `pass_conditions` at the freeze. Read against C1 #5's evidence, this rule
would have raised no finding (nominal CoV 0.056 over 62 clean periods, 1 recovered
candidate, 1 timeout, 1 bad frame, 0 fragments) — **stated so the owner sees what the
rule does; C1 #5 is not re-judged and stays HOLD under v0.4.**

HOLD / KILL as v0.4, with: a HOLD on 3a/3b is an instrument or transport HOLD under §7
like any other.

## 7. Stop-loss

As v0.4 §7, with the owner's ruling of 2026-09-02 recorded: **S #1 and C1 #5 are two
consecutive sessions lost to the same instrument/transport failure class (contiguous
byte deletion on the console path) — the stop-loss is TRIGGERED**; no board ruling is
issued until the fix is named and proven host-side (this batch is that proof, pending
review) and the owner lifts it. This is a classification, not a claim that the two
events share a proven physical root cause.

## 8. What L6 does not establish

As v0.4 §8. Added: the host soak establishes nothing about the physical console path;
that other board→host frame types (`SIGNREQ`, `HB`, `AUDIT_READY`, `CLOSE`, `TERM`) are
still not re-requestable is unchanged and is why the owner approves no board session
before a complete transport/protocol review.

## 9. Order of work, and the hand-back

1. This batch, host-only, with tests; the package `docs/l6_transport_batch_package.md`;
   owner review. *(delivered 2026-09-02)*
2. Owner rulings: D-t1..D-t3 (the timeout value), the freeze of this text as v0.5 (sha
   pinned in the manifest, v0.4 superseded in history), the lifting of the §7 stop-loss.
3. Only then: a C1 ruling pair bound to v0.5 + power cycle → C2 → owner pins the bound
   records → S.
