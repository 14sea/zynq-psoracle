# L6 — calibration and soak of the P3 loop (preregistration v0.4, DRAFT; rec-v3 revision)

> **Standing: DRAFT, NOT FROZEN.** v0.3 (`docs/l6_soak_prereg.md`, sha `8daa81f2…`) stays
> frozen and historical; it is not overwritten. This draft is the text that becomes v0.4
> when the owner freezes it — after the rec-v3 review package
> (`docs/l6_rec_batch_package.md`) passes and the rec-v3 image is promoted board-ready.
> Freezing authorises nothing by itself: C1, C2 and S each still need their own ruling
> pair, a power cycle and a fresh boundary record. `host/l6_runner.py` implements rec-v3
> already and refuses to run against v0.3 or a pull-v2 image, by construction.
>
> **Written 2026-09-01** after S #1 (ruling `2026-09-01-11`, HOLD: `REC 465` lost ~536
> console bytes at go+231 s; the pull protocol could re-request any audit chunk but not
> the record; a host crash-path summary defect found on the way) under the owner's
> pre-board protocol correction batch. Everything not stated as changed below is v0.3's,
> verbatim in force.

## 0. The two questions, and what they are not

Unchanged from v0.3 §0 — with one correction to Q1's standing: **the v0.3 calibrations
(`calibration.C1` = `786dc3ec…`, `calibration.C2` = `a13e301f…`, both PASS, both pinned by the
owner) are historical under v0.4 and may not be reused.** The REC transaction adds one
host round trip inside every candidate's period, so the nominal candidate period of the
rec-v3 image is not the pull-v2 image's. C1 and C2 are re-run under the rec-v3 image; only
their reports, bound to it, may size S.

## 1. Pins

As v0.3 §1, except: **application image** = the rec-v3 two-operator image (§2), pinned in
`manifests/l6_manifest.json` at promotion (today `next_image` `cd8360dc…`, `board_ready:
false`). The carrier, board, genome universe and instrument repositories are unchanged.

## 2. The two-operator image — requirements (v0.3 §2, items 1–6a unchanged) plus:

6b. **The loop record is a transaction (rec-v3).** For every record the application sends
   `REC` and waits, with a bound (`P3_REC_IDLE_POLLS`, a count of RX-FIFO polls like the
   settle poll), for the host's `RECACK {seq}` (accepted, or a byte-identical duplicate of
   the accepted record) or `RECGET {seq}` (a REC-shaped line for this seq arrived broken);
   on a `RECGET`, or when the wait runs out, it sends **the same bytes** again (the record
   is serialised once; the serialiser's tally counts it once); after **3 transmissions**
   without an acknowledgement the epoch stops (`STOP_REC`: restore, TERM) and **no further
   candidate is proposed**. Token, frame seq and payload seq bind every line; the
   application answers only its own record's `RECACK`/`RECGET` and ignores stale or
   foreign lines (bounded). Before every `SIGNREQ` it drains the RX FIFO (stale host lines
   are stale by construction), and its sign-reply wait skips a stale `RECACK`/`RECGET`
   (bounded) rather than calling it a protocol failure. The state machine is
   `firmware/p3_rectx.c`, a pure unit compiled on the host and driven by the contract
   test; `p3_app.c` supplies only its I/O.
6c. **The forced REC-retry control.** Identity page `flags.bit4`. When set — **and the
   runner sets it in every session** — the application corrupts the CRC of the first
   transmission of the opening baseline's record (seq 1, one hex digit of the CRC field)
   so that every session proves the real wire retry within its first seconds: the host
   must `RECGET`, the application must resend byte-identical, and the host's per-seq
   ledger must read exactly `crc` then `ok` with the record accepted. The deliberate
   drop counts against the D-s4 budget like any other. The IDENT echoes the flag.
6d. **`app_identity` 1.2.0** adds `protocol` (`"rec-v3"`) and `rec_retry_control` (bool).
   The runner refuses an image whose IDENT does not declare `rec-v3`, and a session whose
   IDENT does not echo the page's control flag.
7. Review by the owner against this list, item by item (the rec-v3 review package),
   before promotion, freeze and any ruling.

## 3. Decisions — RULED by the owner (v0.3 §3 unchanged) plus the rec-v3 rules

| id | rule |
|---|---|
| **D-s4** CRC budget | v0.3's closed formula, with the brackets of protocol `rec-v3` = pull-v2's inbound brackets (`RECACK`/`RECGET` are outbound; a retransmitted `REC` arrives on top; the control's corrupted first `REC` of seq 1 is a CRC drop, not a frame). **A missing `REC` remains fatal regardless of budget** — under rec-v3 it can only mean the transaction was exhausted or the board advanced without acknowledgement, both of which are ends in their own right. |
| **D-r1** one ledger | Every inbound line that fails CRC or is malformed, of any type, is counted once in the session's inbound ledger (`timeline.json`) and, when it is a REC attempt, also in the per-seq REC ledger (`audits.json` `recs[]`, raw lines verbatim). Retries never remove the original broken line from either. |
| **D-r2** content is the validator's | A CRC-valid record is accepted once and judged by `validate_standalone_run_log`; a retry never replaces an accepted record; a same-seq record with other content is a PROTOCOL end; a falsifier cannot be washed out by retransmission. |
| **D-r3** current-candidate authority | The host acknowledges only the record of the candidate whose sign exchange the relay answered and whose record is outstanding; a `REC` for another seq, and a `SIGNREQ` while a record is outstanding, end the epoch PROTOCOL ("the board advanced without an acknowledgement"). |
| **D-r4** the crash-path summary | A collector-written (`CRASHED`) `session_summary` carries `audit.audited` = the number of records whose served words the **host audit gate** verified (`validators.audit.verify`), never a pull count and never the firmware's mark; if the gate refuses the chunks the count is 0 with the refusal named. |
| **D-r5** calibration binding | Every rate report carries `binding` = {image_sha256, prereg_sha256, protocol, session, schedule_mode, master_seed} written by the runner from the pins it verified; the S runner imports rate_A/rate_B only from reports whose bytes hash to the pins **and** whose binding equals the current pins; a report without a binding is refused. A new image, preregistration or protocol therefore needs new C1/C2. |

### 3a. The audit timing requirement — unchanged (v0.3 §3a; pull-v2's mechanism stands).

## 4. Instrument changes (v0.3 §4 unchanged) plus, delivered host-only in this batch:

8. **The REC transaction's host side** in `host/l6_console.py` (`RECACK`/`RECGET`, idempotent
   duplicates, the conflicting-duplicate and advanced-without-ACK PROTOCOL ends, the
   pending-window rule for malformed REC-shaped lines, the per-seq ledger), modelled in
   `host/l6_rec.py` and tested over a faulty channel.
9. **`crash_audit_count`** (D-r4) in `host/l6_checks.py`, used by the runner for every
   collector-written summary; the S #1 counterfactual is a test.
10. **`rec_control_findings`** (§2.6c) in `host/l6_checks.py`: a session armed with the
    control whose seq-1 ledger is not `crc` → `ok` with a `RECGET` sent is a HOLD.
11. **Rate-report `binding`** (D-r5) in `host/l6_rate.py`; the runner's S plan refuses
    unbound or mismatched calibrations by name.
12. **Loss statistics** over all six sessions and every frame type
    (`host/l6_loss_stats.py`, `evidence/l6_console_loss_stats.json`,
    `docs/l6_console_loss_summary.md`): exposure and events only, no root cause.

## 5. Sessions — fixed in advance

| session | image | N | audit | watchdog | control | purpose | its own rulings |
|---|---|---|---|---|---|---|---|
| **C1** calibration, random-safe forced | rec-v3 two-operator | 64 | all-self-reporting | D-s1 | armed | rate + breakdown + failure rate, arm A, under rec-v3 | `P3-L6` + `P3-K` |
| **C2** calibration, map-guided forced | rec-v3 two-operator | 64 | all-self-reporting | D-s1 | armed | same, arm B | `P3-L6` + `P3-K` |
| **S** soak, A,B,B,A | rec-v3 two-operator | ⌊0.9 × min(rate_A, rate_B) × T⌋, rates by the **rec-v3** C1/C2 record hashes and bindings | sampled per §3a | D-s1 | armed | Q2 | `P3-L6` + `P3-K` |

Seeds as v0.3 (C1 = C2 = 1278624577, S = 1278628687); every L6 (master_seed, index) tuple
stays EXCLUDED from any future Claim B schedule. Each session: power cycle → boundary as
the runner → identity → carrier (sha-gated) → provisioning → image (sha-gated) → `dcache
off` → identity page (seed, N, flags incl. bit4) → `go`; the L5 brackets unchanged.

## 6. PASS / HOLD / KILL — v0.3 §6 with these additions

PASS additionally requires, for C1, C2 and S each: (6) the forced REC-retry control
exercised on seq 1 exactly (`crc` → `ok`, accepted, one `RECGET`); (7) every record's
transaction closed by the host's own `RECACK` — a record in the log without one in the
ledger is an instrument defect; (8) the IDENT declaring `rec-v3` and echoing the control
flag; (9) for S, the rate report's `binding` equal to the pins and both calibrations bound
to the same image/prereg/protocol.

HOLD additionally: `STOP_REC` (the transaction exhausted — a transport HOLD with the
attempts in the ledger), `PROTOCOL_REC` (a conflicting duplicate, a REC for another seq, a
SIGNREQ over an outstanding record), the control not exercised. KILL unchanged (L5 §3).

## 7. Stop-loss — v0.3 §7 unchanged. The owner's lifting of the pull-v2 byte-loss stop-loss
(2026-09-01) stands; S #1 counts as S failure #1 under it; a second S lost the same way is
the result and the next step is a targeted fix with its own review, not a third soak.

## 8. What L6 does not establish — v0.3 §8 unchanged.

## 9. Order of work, and the hand-back

1. This batch (host-only): the transaction on both sides, the control, the crash-path fix,
   the binding, the statistics, this draft, two byte-identical builds of the rec-v3 image
   (`next_image`, not board-ready) — **the rec-v3 review package**.
2. The owner's full P3 compatibility review of the package; promotion of `next_image` to
   `pinned_at_build` (board-ready, `protocol: rec-v3`); this draft frozen as v0.4 (new
   hash pinned; v0.3 superseded, in history).
3. Rulings C1, C2 under v0.4 (new calibrations, bound); then S, one session at a time,
   each with a power cycle. A non-PASS is archived and never re-run without a ruling.
4. `docs/l6_findings.md`; the whole L6 package to `zynq-fabricmap`'s owner as in v0.3 §9.
