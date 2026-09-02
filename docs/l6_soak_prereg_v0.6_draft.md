# L6 — calibration and soak of the P3 loop (preregistration v0.6, DRAFT — self-contained text; transport-recovery + rel-v4 reliability revision)

> **Standing: DRAFT, NOT FROZEN. This is the complete text that becomes v0.6 at the
> owner's freeze — it stands on its own and does not refer the reader to v0.4 or to the
> v0.5 draft for any rule.** v0.4 (`docs/l6_soak_prereg.md`, sha `12799ef9…`, frozen
> 2026-09-02) stays frozen and in force until then; it is not overwritten. **v0.5 was never
> frozen** (owner 2026-09-02: not worth a frozen intermediate under a transport known not
> to survive a long soak); its three rates, planning, recovery attribution and input
> binding are carried here verbatim, and `docs/l6_soak_prereg_v0.5_draft.md` is
> superseded by this text. v0.6 additionally preregisters the **rel-v4 wire protocol**
> (`docs/l6_frame_reliability_design.md` revision 2; host side and twins in
> `host/l6_rel.py`, delivered; firmware batch opened by the owner, not yet started), so
> that C1 → C2 → S run ONCE under the complete protocol. Freezing authorises nothing by itself:
> C1, C2 and S each still need their own ruling pair, a power cycle and a fresh boundary
> record; the §7 stop-loss the owner declared TRIGGERED on 2026-09-02 (S #1 + C1 #5)
> stands until the owner lifts it; and the owner has said no new board session or ruling
> is approved before a complete transport/protocol review
> (`docs/l6_frame_reliability_design.md` is that design, proposed, not ruled).
>
> **C1 #5 (ruling `2026-09-02-01`) is and stays HOLD under v0.4.** Nothing here re-judges
> it; `calibration.C1` stays null. The owner ruled that a revision which merely excluded
> the retried period to turn C1 #5 into a PASS is not acceptable: the rule below bounds
> a nominal spread only together with a preregistered minimum clean sample and
> independent recovery bounds, and sizes S from a rate that includes every recovery.
> Under v0.6, C1 and C2 are run again — once, under the rel-v4 image; no calibration
> pinned under v0.4 or earlier is reused.
>
> **History.** v0.2 (sha `90f5fa69…`, push-v1) ran C1 #1–#3; v0.3 (sha `8daa81f2…`,
> pull-v2) ran C1 #4, C2 #1 (PASS, pinned at the time, historical now) and S #1 (HOLD:
> `REC 465` lost ~536 bytes — the one frame the pull could not re-request); v0.4
> (rec-v3: the record became a transaction, image `403f4ab5…`) ran C1 #5 (HOLD: one
> audit chunk lost bytes, the pull recovered it in ≈2.1 s, and that one period put the
> coefficient of variation at 0.274 over the 0.10 bound; `docs/l6_c1_session5_findings.md`).
> The host-side defect behind the 2.1 s — the reader kept an unterminated residue for ever
> so the resend glued to it — is fixed host-only in the transport batch
> (`docs/l6_transport_batch_package.md`, reviewed PASS scoped 2026-09-02). Written
> 2026-09-02 under the owner's authorised host-only v0.5 design batch, its correction
> batch (three freeze blockers closed: both ledgers or neither with exactly one ledger per
> seq; input-file hash binding with the report derived from the files on disk; the
> planning rate) and the rel-v4 host batch (`docs/l6_rel_batch_package.md`).
>
> L6 exists because of the `zynq-fabricmap` owner ruling recorded in
> `zynq-fabricmap/docs/claimb_resumption_memo.md` §0: Claim B's readback leg is
> RESUMPTION-ELIGIBLE but stays PAUSED "until a calibration/soak preregistration has passed
> and the two-operator image has completed P3 compatibility review", and "the first Claim B
> ruling must not be spent on calibration or integration debugging." L6 is that
> preregistration. It preregisters the **instrument** (the P3 stack); Claim B's own
> preregistration, arms, budget and score stay `zynq-fabricmap`'s.

Frozen when: committed with its content sha256 recorded in `manifests/l6_manifest.json`
(`prereg.sha256`) and every later artifact pinning that hash; `host/l6_runner.py` refuses
any text that does not hash to the pin. Any edit from there is a new version with a new
hash and a new freeze.

## 0. The two questions, and what they are not

- **Q1 (calibration).** On the P3 path, with the image Claim B will actually use, what is the
  measured end-to-end rate per candidate — sign round trip, staging, link-2 witness, DMA,
  link-3 readback, audit service, record transaction, ARM + settle + score — and its failure
  rate? Claim B's preregistration (`claimb_preregistration.md` §6, "The budget still cannot
  be frozen here") defines exactly this calibration and says the budget derives from it.
  **The calibration reports THREE rates** (§3 D-t1, §6.3): the **inclusive** rate (every
  steady-state period, recoveries included), the **nominal** rate (the steady-state periods
  of candidates without a transport recovery — the instrument's own spread, bounded only
  together with a minimum clean sample and the recovery bounds), and the **planning** rate
  (every candidate over the whole bracketed span — brackets, transitions and every
  recovery wherever it fell), which is what S's N is derived from. **No PASS calibration
  exists to pin under v0.6: `calibration.C1`/`C2` are null.** What exists is historical:
  C1 #4 (`786dc3ec…`, 3909.9 evaluations/hour, CoV 0.016) and C2 #1 (`a13e301f…`, 3633.0
  evaluations/hour, CoV 0.015), both PASS on 17A6 under v0.3 and the pull-v2 image
  `e19e1b12…`, recorded in the manifest as `calibration.historical_pull_v2`; C1 #5 under
  v0.4 (HOLD; informational 3607.8 evaluations/hour inclusive, 3734.4 nominal over 62
  clean periods, 3508.9 planning). **None may be reused**: the record transaction changed
  the period (v0.4), v0.6 changes what a calibration report is (D-t1, D-t2) and the wire protocol (rel-v4); the
  runner refuses a report whose `binding` is not the current pins (D-r5) or that carries
  no `planning` rate and no `inputs` (D-t2). C1 and C2 under this v0.6 — under the rel-v4
  image — are what produce the pinnable records.
- **Q2 (soak).** Does the P3 loop hold every invariant L5 established — heartbeat cadence,
  nonce chain, host-recomputed audits, baseline equality, fail-closed ends — **for hours,
  unattended, under the sampled audit policy and with the watchdog decided**? L5's PASS
  explicitly excluded long-run stability. S #1 (v0.3) ran 231 s of a correct soak and then
  lost a record line; it established nothing about hours.

**Not Claim B.** No primary metric, no holdout, no comparison between arms is made or
reported as a finding here; the arms run only so that the *instrument* is calibrated and
soaked in the configuration Claim B will use. **Not autonomous discovery**: seeds are
host-supplied. **Not cross-chip**: `17A6` only. **Nothing about the ICAPE2 readback path.**
**Nothing about the physical console path**: the host soak of §4.15 models a channel; it
measures nothing about CH340/usbipd.

## 1. Pins

| | pinned to |
|---|---|
| instrument repositories | `zynq-psmap` `191ab05`; `zynq-psoracle` at the commit that freezes this document; `zynq-fabricmap` artifacts at `71666b02` (link 1, `local_map.json`, certificates), re-verified by hash at session start (fabricmap's falsifier 3) |
| carrier | `builds/p3/p3.bit` `956379fa…` (unchanged since L1) |
| application image | **the rel-v4 two-operator image** (§2, items 1–6f as `403f4ab5…` plus 6i–6o) — to be built in the firmware batch (twice, byte-identical), P3-compatibility-reviewed, then pinned in `manifests/l6_manifest.json` (`next_image` until promoted). Until it exists this text cannot be frozen. `403f4ab5…` (rec-v3) ran C1 #5 and is superseded, not defective, at the promotion. **L6 does not run on `a7c73d1f…`, `bd1454cd…` or `e19e1b12…`**: calibrating one image to budget another would repeat the mistake `zynq-autoehw` caught (a "2 h" derived from the wrong path's rate); `cd8360dc…` is withdrawn DEFECTIVE and must not run |
| board / control plane | EBAZ4203 `17A6`, U-Boot → standalone crossing, D4 principal boundary verified as the runner < 6 h before every session |
| genome universe | 292 bits over the twelve target FARs, addresses sha256 `895baf85…` (`manifests/l5_manifest.json` `genome`) |
| host transport | `host/l6_reader.py` (resync + quarantine), `host/l6_audit_pull.py` (`CHUNK_TIMEOUT_S = 2.0`, D-t3; `on_wait`), `host/l6_rel.py` (rel-v4 hosts + twins), `host/l6_console.py` (`protocol="rel-v4"`), `host/l6_timing.py` at the freezing commit |

## 2. The two-operator image — requirements for its P3 compatibility review

`firmware/p3_search.c` says "A real search replaces this file and nothing else." Claim B's
interleaving rule ("seed *s* runs in arm A and in arm B, adjacent and alternating, A,B,B,A")
requires the **arm to be chosen per candidate**, so the replacement must be, in full:

1. **Two operators on the board**, both pure functions of `(master_seed, index)`:
   *random-safe* — uniform over the 292 whitelisted addresses; *map-guided* — consulting the
   pinned `local_map` structure (which bits are addressable, same-LUT, same-frame) compiled
   into the image as `p3_data.h` is. The map data in the image must hash to the pinned
   `local_map.json`'s derivation, checked by a host test that regenerates it.
2. **A preregistered arm schedule**: `arm(index)` derived deterministically from the master
   seed by the A,B,B,A pairing rule; the seed pair `(s, arm)` is what a record carries. The
   schedule is written into the Claim B preregistration at its freeze, not here; L6 uses the
   same generator with L6's own master seed.
3. **Python twins of both operators and of the schedule**, with a corpus equality test in the
   style of `tests/test_firmware_twin.py`: for N ≥ 256 `(seed, index)` pairs, board genome ==
   host genome, arm == arm, bit for bit.
4. **The record names the arm** (`loop_record.arm ∈ {random_safe, map_guided}`) and the
   `IDENT` frame names the master seed and the operator-image identity; the validator
   requires the record's arm to equal the schedule's for that index (a discrimination test:
   a swapped arm is refused).
5. **Everything else unchanged and re-audited**: the wire contract (`tests/test_firmware_wire_contract.py`),
   the settle poll (strobe once, bounded read-only wait), the serialiser tally, the audit
   service, the MMIO allowlists against the RTL (`tests/test_axi_map_vs_rtl.py`), the DMA
   order, no ICAPE2, no SLCR write, the identity-page flag gating of the watchdog.
6. **Watchdog** per D-s1 (§3, ruled ON): prescaler 7, load 1 250 000 035 → 30.0 s at
   PERIPHCLK 333.33 MHz (board-confirmed), kicked at the same progress points as the
   heartbeat, selected by the identity page's `flags.bit1`; a session with bit1 = 0 must
   behave exactly as L5 did; the build and its tests pin the actual load value written.
6a. **The audit transport is the host-paced sparse pull** (v0.3; `docs/l6_audit_pull_design.md`).
   For every candidate whose audit is due — a SCORED-path candidate the host selected by
   `AUDITREQ` at sign time, and every non-`SCORED` self-report (`STOP_LINK2`/`STOP_LINK3`/
   `REFUSED_BY_PL`/`STOP_ARM`/`STOP_SETTLE`/a post-staging `STOP_AXI`) **unconditionally**
   (§3a item 2) — the application announces `AUDIT_READY {seq, span, total_words, chunks,
   nonzero}` and serves `app_audit_chunk` 2.0.0 sparse-v1 chunks on each `AUDITGET`, as
   often as asked, until `AUDITDONE` or `AUDITABORT` or its own bounded wait
   (`P3_PULL_IDLE_POLLS`, a count of RX polls, like the settle poll) runs out. A sparse
   chunk lists the non-zero words of one 384-position window as strictly ascending, unique
   `(uint16 position, uint32 word)` pairs; an unlisted position is zero — lossless, the
   host rebuilds every word and recomputes the three hashes unchanged. `verified: audited`
   means `AUDITDONE` was received, nothing less. **A SCORED-path pull that does not
   complete means NO ARM**: the record is the new outcome `STOP_AUDIT` (evidence: the
   oracle self-report + `audit_stop {why, chunks_served}`, never `audited`, always a HOLD
   under either policy) and the epoch stops (restore, TERM).
6b. **The loop record is a transaction (rec-v3, v0.4).** For every record the application
   sends `REC` and waits, with a bound (`P3_REC_IDLE_POLLS`, a count of RX-FIFO polls like
   the settle poll), for the host's `RECACK {seq}` (accepted, or a byte-identical duplicate
   of the accepted record) or `RECGET {seq}` (a REC-shaped line for this seq arrived
   broken); on a `RECGET`, or when the wait runs out, it sends **the same bytes** again (the
   record is serialised once; the serialiser's tally counts it once); after **3
   transmissions** without an acknowledgement the epoch stops (`STOP_REC`: restore, TERM)
   and **no further candidate is proposed**. Token, frame seq and payload seq bind every
   line; the application answers only its own record's `RECACK`/`RECGET` and ignores stale
   or foreign lines (bounded). Before every `SIGNREQ` it drains the RX FIFO (stale host
   lines are stale by construction). The state machine is `firmware/p3_rectx.c`, a pure
   unit compiled on the host and driven by the contract test over a pipe; `p3_app.c`
   supplies only its I/O.
6c. **The forced REC-retry control.** Identity page `flags.bit4`. When set — **and the
   runner sets it in every session** — the application corrupts the CRC of the first
   transmission of the opening baseline's record (seq 1, one hex digit of the CRC field)
   so that every session proves the real wire retry within its first seconds. **The
   preregistered shape is exact**: the host's per-seq ledger for seq 1 reads attempts
   `["crc", "ok"]` and nothing more, accepted, no conflict, exactly one `RECGET` sent by
   the host and at least one `RECACK`. Any other shape — a third attempt because the
   RECACK was lost, a second RECGET, a resend accepted without a RECGET — is a different
   transport event that makes the control's evidence ambiguous and is a HOLD naming the
   shape (`host/l6_checks.rec_control_findings`). The deliberate drop counts against the
   D-s4 budget like any other. The IDENT echoes the flag. **In the rate report the
   control is attributed as `control`, never as a recovery (D-t2).**
6d. **`app_identity` 1.2.0** adds `protocol` (`"rec-v3"`) and `rec_retry_control` (bool);
   **1.3.0 (rel-v4) adds `sign_retry_control` (bool)** — the page's `flags.bit5` echoed as
   the application decoded it. The runner refuses an image whose IDENT does not declare
   the pinned protocol, and a session whose IDENT does not echo BOTH control flags
   (`validators.records.check_l6_identity(..., rec_retry_control, sign_retry_control)`,
   asked before the IDENTACK and again at adjudication; under rec-v3 only bit4 is asked).
6e. **Every wait for a host line is bounded on the whole line.** The application's receiver
   (`p3_rectx_recv_line`, the pure unit) abandons a line as partial when no byte arrives for
   the idle bound after at least one did, and in any case after four idle bounds in all,
   so a `RECACK`/`RECGET` (or an `AUDITGET`) cut mid-line, with its newline lost, is
   discarded and the transaction's own bound then runs out — a resend, or `STOP_REC` —
   never a block until the watchdog. (The L5 sign-reply wait is unchanged and remains
   watchdog-covered.) Per wait, at most `P3_RECTX_STALE_LIMIT` (64) lines that are not
   this transaction's are ignored; the 64th ends the wait like the bound.
6f. **A stale acknowledgement in the sign-reply wait is skipped only when it names the
   transaction just completed** — frame seq and payload seq both equal to the previous
   record's seq, at most `P3_REPLY_STALE_LIMIT` (8) of them; any other `RECACK`/`RECGET`
   there ends the epoch PROTOCOL.
6g. **The host side of the console is torn-line safe (host-only, delivered 2026-09-02).** The reader
   (`host/l6_reader.py`) resynchronises on a frame head: a `P3L5 <TYPE> <seq> <token32> `
   head that appears inside its buffer with no line end before it can only mean the bytes
   before it lost their terminator — those bytes are **quarantined** (kept verbatim,
   stamped, reason `resync`) and the new frame is parsed from its own head; the full head
   is required, so a base64 payload ending in `P3L5` is never split, and a head split
   across two polls is not a head until it completes. The audit pull's chunk timeout is a
   **monotonic deadline** armed by every `AUDITGET` (D-t3: 2.0 s) — when it passes, the
   reader's unterminated residue is quarantined **before** the retry `AUDITGET` goes out,
   so a resend never glues to it. A stale byte-identical reply of a chunk already verified
   is recorded (`duplicates`) and is never an attempt; a differing stale reply is a failed
   attempt. Every quarantined fragment is in `console.log` (raw), in the reader's
   `fragments` and in the timeline as a `FRAGMENT` event — not a frame, not a CRC drop,
   not a bad frame; nothing is dropped silently. A half line split across polls is
   completed by the later read exactly as before.
6h. **The rate report is derived from three files it names (host-only, delivered 2026-09-02).** The runner
   writes `run_log.json`, `audits.json` (pull and REC ledgers) and `timeline.json` (the
   inbound ledger, fragments included) first and derives `rate_report.json` from those
   files' bytes, recording their sha256 as `inputs`; the report carries nominal and
   recovery figures **only when both ledgers are present and valid** (a REC ledger for
   every record, a completed pull for every audited record, a `SIGNREQ` frame for every
   record) — one without the other is refused, never taken as zero faults (D-t2).
6i. **The wire protocol is rel-v4** (`docs/l6_frame_reliability_design.md` rev. 2; the
   host side and every board twin in `host/l6_rel.py`): every board→host frame is
   re-requestable, reconstructible or budgeted, and every host→board frame the board
   waits for is covered by the board's bounded resend. The IDENT declares
   `protocol: "rel-v4"`; the runner selects the host behaviour by the pinned image's
   protocol and refuses a prereg/image protocol mismatch.
6j. **IDENT is a handshake completed before the first SIGNREQ.** The application sends
   `IDENT` and waits bounded (`P3_IDENT_IDLE_POLLS`) for `IDENTACK {seq 0}`, resending the
   same bytes on the bound, ≤ 3 transmissions; exhaustion → `STOP_IDENT` (restore not
   needed, TERM) and **no `SIGNREQ` is ever sent**. The host acknowledges only an identity
   it verified (§2.4's fields, the protocol, the control flags); an identity it refuses
   draws no acknowledgement and no host-side end — the board exhausts to `STOP_IDENT` and
   its TERM ends the epoch, the refusal being a closure finding; a broken IDENT-shaped
   line is in the IDENT ledger, never the collector's crash; a `SIGNREQ` with no
   established identity, or after a refusal, ends the epoch `PROTOCOL_IDENT`.
6k. **The sign exchange is a transaction.** The application serialises `SIGNREQ` once and
   waits bounded (`P3_SIGN_IDLE_POLLS`) for `SIGNOK`/`SIGNREF`; on `SIGNGET {seq}` or the
   bound it resends the same bytes, ≤ 3 transmissions; exhaustion → **`STOP_SIGN`**, a
   terminal record (`evidence.sign_stop {attempts, why}` and nothing else; `verified`
   replayed-only; no ARM, no nonce consumed; restore, TERM; no further candidate). The
   host signs ONCE per seq and replays the cached reply to a byte-identical resend (the
   notary entry counts `replays`); a same-seq request with other bytes is `PROTOCOL_SIGN`.
   **`AUDITREQ` is not a frame**: `SIGNOK` carries `audit_requested`. The **forced
   SIGNREQ-retry control** (identity page `flags.bit5`, armed by the runner in every
   session) corrupts the CRC of the first transmission of seq 1's `SIGNREQ`; its exact
   shape is the host's sign ledger for seq 1 = attempts `["crc", "ok"]`, one `SIGNGET`,
   one notary entry with `replays` 0 — any other shape is a HOLD naming it.
6l. **`AUDIT_READY` is resent on the pull's idle bound while no `AUDITGET` was seen**, ≤ 3
   transmissions, then the audit is given up as §2.6a says.
6m. **`AUDITDONE` is a completion handshake.** After the last chunk the application waits
   bounded for `AUDITDONE`/`AUDITABORT`; on the bound it sends `AUDITWAIT {seq, served}`,
   ≤ 3, and the host replays the same `AUDITDONE`/`AUDITABORT` line; exhaustion gives the
   audit up exactly as §2.6a says (SCORED path: `STOP_AUDIT`, no ARM). The host takes no
   verdict from the wait count: whether the board confirmed the audit is read from its
   record (`verified`) by the closure check (§6.10); the pull ledger written to
   `audits.json` carries `waits_seen`/`done_replays`/`waits_exhausted` as rendered at the
   end of the session.
6n. **Heartbeats carry their index** (`HB` payload `{i: 0..15}`); a missing heartbeat is
   identified and budgeted (§6.11), a duplicate harmless.
6o. **`TERM` is a transaction** (`TERMACK`/`TERMGET`, the same bytes, ≤ 3, then halt) and
   **carries the closing control's fields** (`closing_control {fault, kind, status,
   nonce_before, nonce_after}`) so a lost `CLOSE` is reconstructed from it (marked
   `source: TERM`). **The application-written TERM MUST carry the complete, typed block**
   (five fields: `fault` int, `kind` str, `status` str, `nonce_before`/`nonce_after` 16
   hex): a missing block, a missing field or a wrong type is a closure finding
   (`l6_rel.closing_control_findings`) whether or not a `CLOSE` arrived; a lost `CLOSE` is
   rebuilt only from a complete block; a `CLOSE` that did arrive stands and is compared
   with the block — a disagreement is a closure finding. The runner keeps reading for
   `TERM_LINGER_S` after the first TERM so a resent TERM (our ACK lost) is re-acknowledged.
6p. **Every new bounded wait is the §2.6e receiver** (whole-line bound, stale lines ignored
   up to `P3_RECTX_STALE_LIMIT`), implemented as pure units in the pattern of
   `firmware/p3_rectx.c` (`p3_signtx.c`, `p3_termtx.c`, the pull's wait state) and driven
   on the host by the wire-contract test against the twins of `host/l6_rel.py`. **The
   bound contract**: every rel-v4 idle bound is a poll count in the image
   (`P3_IDENT_IDLE_POLLS`, `P3_SIGN_IDLE_POLLS`, `P3_PULL_IDLE_POLLS`, `P3_REC_IDLE_POLLS`,
   `P3_TERM_IDLE_POLLS`) whose wall time on the pinned clocks is **≤
   `BOARD_BOUND_WALL_MAX_S` = 10 s** (`host/l6_rel.FIRMWARE_BOUND_CONTRACT`); the firmware
   batch pins the counts, bounds their wall time in a source-audit test and measures it
   with the C twin; the host's `TERM_LINGER_S` = (MAX_ATTEMPTS − 1) × 10 s + 2 s = 22 s is
   derived from that bound and from nothing else. Until the firmware batch proves it, the
   relation is a stated contract, not a verified fact.
7. Review by the owner against this list, item by item, before any L6 ruling; the image
   hash is then pinned in `manifests/l6_manifest.json` and this document is frozen.
   *(Items 1–6f: reviewed and pinned 2026-09-02 for v0.4. Items 6g–6h: the transport
   batch, reviewed PASS scoped 2026-09-02; the correction batch, pending. Items 6i–6p:
   host side delivered (`docs/l6_rel_batch_package.md`), firmware batch opened, not
   started.)*

## 3. Decisions — RULED by the owner (D-s1..D-s4 2026-09-01; D-r1..D-r5, D-t1, D-t2, D-t3 2026-09-02) and proposed (D-p1, the rel-v4 protocol)

| id | ruling |
|---|---|
| **D-s1** watchdog | **ON.** Prescaler 7, 30 s (`load 1 250 000 035` at PERIPHCLK 333.33 MHz, board-confirmed 2026-09-01-05). Arm and kick are gated by the identity page's `flags.bit1`; the **bit1 = 0 path keeps L5's behaviour exactly**. The build and its tests must pin the **actual** load value written, not the derivation. |
| **D-s2** audit policy for the soak | **Sampled, accepted in principle, with the timing requirement of §3a as a condition.** (v0.2 history: the v0.1 wording "every non-`SCORED` self-reporting record audited" could not be honoured under the push-era wire protocol; §3a fixed the rule, and the pull transport (§2.6a) is its implementation — the words persist on the board until pulled or the record is emitted.) |
| **D-s3** soak duration | **2 h, accepted.** N = ⌊0.9 × min(rate_A, rate_B) × T⌋, with rate_A and rate_B imported **only** from the two calibration records (C1, C2) by their hashes **and their bindings (D-r5) and their input files (D-t2)**; **under v0.6 the rate is each record's `planning` rate (D-t1).** |
| **D-s4** CRC budget | **Frame-count scaling, with a closed formula:** `budget = ceil(4 × expected_protocol_frames / 1000)`, where `expected_protocol_frames` is derived **before the session starts** from N, the audit schedule and the fixed brackets (`IDENT`×1, `SIGNREQ`×(N+2), `HB`×16 per candidate, `AUDIT_READY`×1 + `AUDIT`×8 per audited candidate — protocol `rec-v3` keeps pull-v2's inbound brackets, `host/l6_schedule.expected_frames`; retransmitted chunks and records arrive on top and are what the budget is FOR; the host's `AUDITGET`/`AUDITDONE`/`AUDITABORT`/`RECACK`/`RECGET` are outbound and not budgeted; the control's deliberately corrupted first `REC` of seq 1 is a CRC drop, not a frame — `REC`×(N+2), `CLOSE`×1, `TERM`×1) — **never from the count actually received**. Independently of the CRC total, **any missing `AUDIT`, `REC` or `TERM`** is the corresponding structural defect and is a HOLD even when the CRC drops are within budget; under rec-v3 a missing `REC` can only mean the transaction was exhausted or the board advanced without acknowledgement, both of which are ends in their own right. A `FRAGMENT` (§2.6g) is neither a frame nor a drop: it is a recovery indicator (§6.3b). |
| **D-r1** one ledger | Every inbound line that fails CRC or is malformed, of any type, is counted once in the session's inbound ledger (`timeline.json`) and, when it is a REC attempt, also in the per-seq REC ledger (`audits.json` `recs[]`, raw lines verbatim). Retries never remove the original broken line from either. Fragments are in the same inbound ledger (`fragments[]`, `FRAGMENT` events). |
| **D-r2** content is the validator's | A CRC-valid record is accepted once and judged by `validate_standalone_run_log`; a retry never replaces an accepted record; a same-seq record with other content is a PROTOCOL end; a falsifier cannot be washed out by retransmission. |
| **D-r3** current-candidate authority | The host acknowledges only the record of the candidate whose sign exchange the relay answered and whose record is outstanding; a `REC` for another seq, and a `SIGNREQ` while a record is outstanding, end the epoch PROTOCOL ("the board advanced without an acknowledgement"). **A byte-identical duplicate of the accepted record is the only thing re-acknowledged**: a broken resend of an accepted record draws a `RECGET`, and the next CRC-valid resend earns the `RECACK` only if it equals the accepted payload — otherwise PROTOCOL. |
| **D-r4** the crash-path summary | A collector-written (`CRASHED`) `session_summary` carries `audit.audited` = the number of records whose served words the **host audit gate** verified (`validators.audit.verify`), never a pull count and never the firmware's mark; if the gate refuses the chunks the count is 0 with the refusal named. |
| **D-r5** calibration binding | Every rate report carries `binding` = {image_sha256, prereg_sha256, protocol, session, schedule_mode, master_seed} written by the runner from the pins it verified; the S runner imports rate_A/rate_B only from reports whose bytes hash to the pins **and** whose binding equals the current pins; a report without a binding is refused. A new image, preregistration or protocol therefore needs new C1/C2. |
| **D-t1** the three rates (RULED 2026-09-02: accepted) | The calibration report carries `inclusive` (every steady-state period, recoveries included), `nominal` (the steady-state periods of candidates **without** a transport recovery; every excluded seq named) and `planning` = candidates × 3600 / (`t_rec`(last record) − `t_signreq`(first record)): every candidate the session scored over **everything** the session took — both brackets, both transitions and every recovery wherever it fell. A steady-state period is interior→interior only, so a recovery on the **last** candidate lands in the last→closing transition and moves neither the inclusive nor the nominal rate; it does move the planning rate (review 2026-09-02; `tests/test_l6_rate_v05.py` is the counterexample). **S's N = ⌊0.9 × min(planning_A, planning_B) × T⌋**, never from the inclusive or the nominal rate. |
| **D-t2** recovery attribution and the ledgers (RULED 2026-09-02: accepted, with two fail-closed corrections — exactly one REC ledger per seq and at most one pull ledger per seq, extra seqs refused; the report derived from the three files as read back from disk, `host/l6_rate.rate_report_from_evidence_dir`, the only entry point) | A candidate is *recovered* iff its pull ledger has a non-ok attempt or a timeout, or its REC ledger a retry (`RECGET`), or a `CRC_DROP` / `BAD_FRAME` / `FRAGMENT` event falls inside its window [`t_signreq(seq)`, `t_signreq(seq+1)`). The forced REC-retry control of seq 1 (§2.6c) is attributed as *control*, not as a recovery. Stale duplicates are reported, never a recovery on their own. Attribution is `host/l6_rate.recovery_by_seq`, from the ledgers the runner writes (`audits.json` `pulls[]`/`recs[]`, `timeline.json` frames), never from a received frame count. **Both ledgers must be present and valid or the report carries no nominal/recovery figures** (one without the other is refused). **The report names the sha256 of the three files it was derived from (`inputs`)**; a calibration pin is verified against the report's bytes (D-r5) AND against those three files beside it; under v0.6 a report without `inputs` or without `planning` is refused. |
| **D-t3** the chunk timeout (RULED 2026-09-02) | **`CHUNK_TIMEOUT_S = 2.0` s, pinned.** ≈0.5 s is NOT adopted: the host soak shows the mechanism works at 0.5 s over a modelled channel, but nothing shows the real CH340/usbipd path is safe at 0.5 s under a host scheduling stall. (C1 #5's 528 clean chunk round trips: median 42.9 ms, p99 83.1 ms, max 83.6 ms — recorded, not acted on.) |
| **D-p1** the rel-v4 bounds (RULED 2026-09-02: accepted with the exact semantics) | Board transmissions: 3 in all = the first + 2 resends (IDENT, SIGNREQ, AUDIT_READY, TERM); host re-requests (SIGNGET/TERMGET/RECGET): at most 2 per seq; AUDITWAIT: at most 3; host replays / re-acknowledgements: at most 3 per seq. **Seeing the third AUDITWAIT is not a final failure**: the third replay may still reach the board; the verdict is the board's closure evidence (its record's `verified`), never the wait count. The STOP_SIGN evidence contract and rule (vii-b) (`validators/records.py`); the heartbeat budget ⌊R/1000⌋ over R = SCORED records, never two missing in one record. The protocol itself (§2.6i–6p) is the design the owner reviews; the firmware batch is the owner's to start. |

### 3a. The audit timing requirement (D-s2's blocker, and its resolution)

**The blocker (v0.2 HISTORICAL — resolved by pull-v2).** Under the push-era wire protocol
the host's `AUDITREQ` was attached to the sign reply, i.e. it reached the application
**before staging**, and the application pushed raw words only if it had been asked; there
was no evidence ring, so a candidate the sampled schedule did not select that then turned
out to be a non-`SCORED` self-report could no longer be audited — "all non-`SCORED`
self-reporting records audited" could not be honoured after the fact. **The pull
transport (§2.6a) removes the constraint**: the words persist in the board's buffers until
the record is emitted, and the application itself announces `AUDIT_READY` for every
non-`SCORED` self-report, so item 2 below is implementable directly. The rule stands
unchanged; only its mechanism moved from an unconditional push to the unconditional
announcement of a pull. rec-v3 leaves the audit transport untouched; rel-v4 adds only the READY resend and the DONE handshake (§2.6l–6m).

**The rule, fixed here:**

1. **`SCORED` candidates** are audited per the preregistered sampled schedule (every 16th by
   seq, plus the first and the last candidate and both baselines), requested by `AUDITREQ`
   as today; the transport is §2.6a's pull.
2. **Any outcome that produces a raw self-report and is not `SCORED`** — `STOP_LINK2`
   (streams span), `STOP_LINK3`, `REFUSED_BY_PL`, `STOP_ARM`, `STOP_SETTLE` (full span) — is
   audited **unconditionally by the firmware itself, before it emits the record, without
   waiting for an `AUDITREQ`**. The words are served from the same buffers and in the same
   chunk format; the record then goes out as now.
3. **`REFUSED_BY_GATE`** and a **`STOP_AXI` before staging** stay exempt under the existing
   rule (nothing was staged; no raw words exist).
4. **Marks are derived by the host from raw recomputation** (`validators/audit.py` inside
   `validate_standalone_run_log`); the firmware's own mark is never trusted, exactly as now.
5. **Negative test, required before any L6 ruling:** a candidate that the sampled schedule
   did not select and that later ends in one of the outcomes of item 2, whose words were
   **not** auto-served, must make the session a **HOLD** (an unaudited self-report under the
   policy), and the discrimination test must show the check firing on exactly that record.
   A second negative: auto-served words that do not recompute are `Falsified` (KILL), as for
   any served words.

Implemented in the v0.3 image and carried unchanged into the v0.4 image (`403f4ab5…`) and
validators; the pull transport, its retries (≤ 2 per chunk, every failed attempt kept
verbatim in `audits.json` `pulls[]` and CRC-budgeted, a timeout an attempt but not a
drop), the one inbound CRC ledger (`host/l6_console.py`, authoritative for every frame
type) and `STOP_AUDIT` are §2.6a's.

## 4. Instrument changes required before any L6 ruling (host-only, tested, reviewed)

1. **Timestamps.** The collector records a monotonic and a wall-clock receive time for every
   frame; `run_log.json` carries per-record timing (`t_signreq`, `t_reply`, `t_first_hb`, …,
   `t_rec`) and `console.log` gains a timestamped companion (`console.ts.log`) — the raw
   `console.log` bytes stay verbatim. A test proves the stage boundaries are attributable
   from the frame sequence — under the pull: `SIGNREQ` → reply → `HB`×16 →
   `AUDIT_READY` → (`AUDITGET` → `AUDIT`)×chunks, retries included → `AUDITDONE`/`AUDITABORT`
   → `REC` (→ `RECACK`); the audit stage is `AUDIT_READY` → `AUDITDONE`/`AUDITABORT` on the
   host clock, and a pull with neither end is unclosed: wall time stands, breakdown none.
   (The v0.2 push shape, `HB`×16 → `AUDIT`×8 → `REC`, remains what the C1 #1–#3 evidence
   contains.) Under rec-v3 `t_rec` is the first CRC-valid `REC` of the seq — a retried
   record's wall time honestly includes its retry.
2. **Rate report.** `host/l6_rate.py` derives from a run log: per-candidate wall time and its
   breakdown, evaluations per hour, the coefficient of variation, and the failure rate —
   the four numbers Claim B's §6 calibration asks for — **and its `binding` (D-r5)**. Pure
   function, tested on session 4's log (it must refuse: no timestamps) and on a synthetic
   timed log.
3. **Sampled audit policy** (D-s2, as fixed by §3a) in `validators/records.py`, with the host gate unchanged; the policy check must know the schedule and must require the §3a item-2 auto-audit for every non-`SCORED` self-report.
4. **Arm-aware validator**: `loop_record.arm` required and checked against the schedule
   (§2.4); `check_audit_policy` and the chain unchanged.
5. **Ruling text** `whole-of-probe P3-L6` checked by `host/l6_runner.py` (the L5 runner with
   `--duration`, the sampled policy, timestamps and the rate report; nothing else), plus
   `provisioning P3-K` per session as always. Old texts are refused.
6. **Budget arithmetic in the runner**: N is an input pinned from the **two** calibration
   records' hashes, bindings and input files (D-s3, D-r5, D-t2), never typed by hand; the
   session timeout is derived from N and the measured rates with margin, and is recorded.
7. **Expected-frame-count and CRC budget** (D-s4): computed before the session from N, the
   schedule and the brackets, recorded in the summary with the formula's inputs; the
   collector's structural checks (missing `AUDIT`/`REC`/`TERM`) stay independent of it.
8. **The REC transaction's host side** (rec-v3) in `host/l6_console.py` (`RECACK`/`RECGET`,
   idempotent duplicates, the conflicting-duplicate and advanced-without-ACK PROTOCOL ends,
   the pending-window rule for malformed REC-shaped lines, the per-seq ledger), modelled in
   `host/l6_rec.py` and tested over a faulty channel.
9. **`crash_audit_count`** (D-r4) in `host/l6_checks.py`, used by the runner for every
   collector-written summary; the S #1 counterfactual is a test.
10. **`rec_control_findings`** (§2.6c) and **`rec_closure_findings`** (§6 condition 7) in
    `host/l6_checks.py`, both called by the runner, both discrimination-tested.
11. **Rate-report `binding`** (D-r5) in `host/l6_rate.py`; the runner's S plan refuses
    unbound or mismatched calibrations by name.
12. **Loss statistics** over all sessions and every frame type (`host/l6_loss_stats.py`,
    `evidence/l6_console_loss_stats.json`, `docs/l6_console_loss_summary.md`): exposure and
    events only, no root cause; the rec-v3 control's deliberate drop recorded apart.
13. **Reader resynchronisation and fragment quarantine** (§2.6g; `host/l6_reader.py`):
    `fragments` verbatim with stamps and reasons, `quarantine(reason)` on demand, the
    `FRAGMENT` event in the timeline (`host/l6_timing.py`, schema 1.2.0); a half line
    across polls, a head split across polls and a payload ending in `P3L5` proven not
    torn; a late headless tail after the quarantine proven to be noise.
14. **Monotonic chunk deadline, stale duplicates** (§2.6g; `host/l6_audit_pull.PullHost`):
    armed by every `AUDITGET` on the runner's monotonic clock (`tick()` takes no
    accumulated dt); the timeout callback quarantines the residue **before** the retry;
    byte-identical stale replies in `duplicates`, never an attempt.
15. **Replay and fault-injection soak** (`host/l6_transport_soak.py`, evidence
    `evidence/l6_transport_soak/`): C1 #5's recorded bytes replayed through the new reader
    and pull recover chunk 1 of seq 39 on the **first** resend (`[timeout, ok]`; glued in
    one read, `[ok]` with no timeout), and the C1 #5 reader reproduces the recorded
    `[timeout, malformed, ok]` on the same bytes (discrimination control); the seeded soak
    over 2000 candidates per configuration (truncate, interior deletion, drop, duplicate,
    glued duplicate, late tail before/after the timeout; random poll splits including
    inside the head) shows every single fault recovered on the first resend at 2.0 s and
    at 0.5 s, pulls failing only where one chunk took more faults than the retry bound,
    no clean candidate marked. **The soak measures the host mechanism over a modelled
    channel and nothing about the CH340/usbipd path** (hence D-t3).
16. **The rate report 1.2.0** (`host/l6_rate.py` 0.3.0): `inclusive`, `nominal`, `recovery`,
    `planning`, `inputs`, per-candidate `recovery`/`clean`; the unchanged top-level
    numbers stay the inclusive ones (v0.4's rule is computed exactly as before); the CLI
    reads `audits.json` and `timeline.json` beside the run log and hashes all three files;
    both ledgers or neither (D-t2), exactly one REC ledger per seq and at most one pull
    ledger per seq, extra seqs refused, invalid ledgers refused by name;
    `rate_report_from_evidence_dir` is the only entry point (the runner calls it after
    writing the files, so the bytes hashed are the bytes computed on).
17. **The three-rate PASS rule as code** (`host/l6_checks.calibration_findings_v05`, named
    for the draft that introduced it), selected by the runner **only when the manifest's
    `prereg.version` is v0.5 or v0.6** (`host/l6_runner.V05_RULE_VERSIONS`); under v0.4
    the runner computes v0.4's rule unchanged (C1 #5 = HOLD is reproduced by test).
18. **Input verification at the S import** (`host/l6_checks.calibration_inputs_findings`,
    called by the runner's preflight): the three files beside a pinned calibration must
    hash to the report's `inputs`; under v0.5 a report without `inputs` or `planning` is
    refused; the S plan records `rate_source: planning`.
19. **The frame reliability design** (`docs/l6_frame_reliability_design.md` rev. 2): every
    frame classified, the STOP_SIGN contract, the IDENT handshake before the first
    SIGNREQ, the AUDITDONE handshake, the heartbeat budget with its rounding and
    denominator, no probability attached to the residual exposure.
20. **rel-v4 host side and board twins** (`host/l6_rel.py`): `IdentHost`/`IdentBoard`,
    `SignHost` (one signature per seq, the cached reply, `SIGNGET`, `audit_requested`
    folded into `SIGNOK`)/`SignBoard`, `ReadyBoard` (READY resend, AUDITWAIT),
    `PullHost.on_wait` (DONE replay, `unconfirmed`), `TermHost`/`TermBoard`,
    `closing_from_term`, indexed heartbeats and `heartbeat_findings_rel`; the
    `ConsoleSession` switch `protocol="rel-v4"` (rec-v3 unchanged by test); the runner
    selects the protocol from the pinned image, verifies the identity before the
    acknowledgement, writes the transaction ledgers into `audits.json` (`ident`, `signs`,
    `term`) and selects the heartbeat rule by protocol; `l6_schedule.PROTOCOLS["rel-v4"]`.
21. **The validator's rel-v4 rules** (`validators/records.py`): `STOP_SIGN` as a terminal
    loop-record outcome with its exact evidence, accepted only when the IDENT declares
    `rel-v4`; rule (vii-b) — in an application-written epoch every notary entry has a
    record of its seq. **The §6.10–13 gates as code** (`host/l6_checks.rel_closure_findings`,
    `rel_control_findings`, `rel_recovery_findings`; `l6_rel.heartbeat_findings_rel`),
    called by the runner under rel-v4; `l6_runner.session_loop_continues` (the TERM linger).
22. **Per-frame tests** (`tests/test_l6_rel.py`): loss, duplication, truncation through the
    real reader, and exhaustion for IDENT, SIGNREQ, AUDIT_READY, AUDITDONE, TERM; the
    heartbeat budget; CLOSE from TERM; the session under rel-v4 end to end; rec-v3
    unchanged; the validator contract. **Integration negatives on the real session and
    the runner's loop condition** (`tests/test_l6_rel_correction.py`: the live pull
    ledger, the verdict from the board's record, the TERM linger, the IDENT wiring, the
    §6.10–13 gates, STOP_SIGN's protocol gate, the CLOSE/TERM comparison;
    `tests/test_l6_rel_correction2.py`: sign ledgers never last-wins in both orders, the
    mandatory closing_control in four cases, the bit5 echo, the bound contract, the
    refused-repeat comparison).
23. **The firmware batch** (opened by the owner 2026-09-02; starts after items 19–22 are
    reviewed PASS): §2.6i–6p in the firmware, the C twins driven by the wire-contract test
    against `host/l6_rel.py`, two byte-identical builds, `next_image`, a full P3
    compatibility review; then this text is frozen.

## 5. Sessions — fixed in advance

| session | image | N | audit | watchdog | control | purpose | its own rulings |
|---|---|---|---|---|---|---|---|
| **C1** calibration, random-safe schedule forced | rel-v4 two-operator | 64 | all-self-reporting | D-s1 | armed | the three rates + breakdown + failure rate + recovery indicators, arm A | `P3-L6` + `P3-K` |
| **C2** calibration, map-guided schedule forced | rel-v4 two-operator | 64 | all-self-reporting | D-s1 | armed | same, arm B (operator compute time may differ) | `P3-L6` + `P3-K` |
| **S** soak, A,B,B,A schedule | rel-v4 two-operator | ⌊0.9 × min(planning_A, planning_B) × T⌋, rates by the **v0.6** C1/C2 record hashes, bindings and input files | sampled per §3a | D-s1 | armed | Q2 | `P3-L6` + `P3-K` |

**C1 and C2 are run once under v0.6 and the rel-v4 image**; no earlier calibration is
reused (D-r5 refuses their binding; D-t2 refuses their missing `planning`/`inputs`). Seeds: C1 = C2 =
1278624577 (0x4c364341), S = 1278628687 (0x4c36534f), pinned in the manifest; every L6
(master_seed, index) tuple is EXCLUDED from any future Claim B schedule. Each session:
power cycle → boundary verifier as the runner → identity → carrier load (sha-gated) →
provisioning → image load (sha-gated) → `dcache off` → identity page (master seed, N,
flags incl. bit4 and bit5, arm-schedule mode) → `go`; the IDENT handshake; opening baseline, N candidates, closing
baseline, closing unsigned control — the L5 brackets unchanged. Runner in the background,
no shell timeout, waited on by pid. A calibration session is **not** a Claim B data point
even though both arms run: its genomes are consumed by the calibration and the seed pairs
are excluded from Claim B's schedule (recorded in the Claim B preregistration at freeze).

## 6. PASS / HOLD / KILL — decided now

**PASS (L6)** requires, for C1, C2 and S each:

1. every L5 §5 condition — `COMPLETED` with the three closing steps, both baselines exactly
   `[18, 22, 20, 20, 20, 18]`, (ii)/(iii) for every `SCORED`, the nonce chain over every
   attempt, the closing unsigned ARM refused `F_ARM_AUTH`, every audited candidate
   recomputing on the host, `validate_standalone_run_log` accepting, zero disruptions;
2. the sampled policy of §3a (S) or all-self-reporting (C1/C2) satisfied by host-derived marks — every non-`SCORED` self-report auto-audited, every scheduled `SCORED` audited;
3. a timing record for **every** candidate, and a rate report (schema 1.2.0) that carries
   the three rates (D-t1), the recovery indicators (D-t2), every period and every retry
   published; the audit stage of the breakdown is `AUDIT_READY` → `AUDITDONE`/`AUDITABORT`
   on the host clock, retries included; an unclosed pull keeps its wall time and no
   breakdown;
3a. **nominal CoV ≤ 0.10** (C1, C2), computed over the steady-state periods of candidates
   without a transport recovery, **and at least `min_clean_periods` = 60 of the 63
   steady-state periods clean** — fewer is a HOLD however small the nominal CoV;
3b. **recovery bounds** (C1, C2): candidates with a recovery ≤ 3, pull timeouts ≤ 3, bad
   frames ≤ 3, fragments ≤ 3 (CRC drops by D-s4's budget, unchanged; any missing
   `AUDIT`/`REC`/`TERM` a structural HOLD, unchanged) — crossing any one is a HOLD named
   by the bound, so a nominal CoV never hides an unstable link
   (`host/l6_checks.calibration_findings_v05`; the bounds pinned in the manifest's
   `pass_conditions` at the freeze — today `next_prereg.pass_conditions_draft`);
3c. the **inclusive** and **planning** rates are reported and bounded by nothing; the
   planning rate is the calibration value S's N is derived from (a slower, recovering
   link — wherever the recovery fell, the last candidate included — gives a smaller N,
   the conservative direction);
3d. the report was derived with **both ledgers** and names its three **input files**
   (D-t2); a report without them is not a calibration record;
4. for S: no heartbeat gap > 20 s (L2's guard), CRC drops within D-s4's closed-formula budget (and no missing `AUDIT`/`REC`/`TERM` regardless of it), wall time
   ≥ 0.9 T, and every `settle.polls` within [1, 10 × the C1/C2 median] — a slower gate is a
   finding, not a failure, but it stops the session as `STOP_SETTLE` would if it exceeds the
   bound;
5. the record's arm equals the schedule's for every index;
6. the forced REC-retry control exercised on seq 1 exactly as §2.6c states;
7. **REC closure, machine-enforced** (`host/l6_checks.rec_closure_findings`, called by the
   runner): the set of loop-record seqs equals the set of REC-ledger seqs; every ledger
   accepted, without conflict, with at least one `RECACK` sent and an accepted attempt; no
   ledger without a record (an exhausted or advanced-without-ACK transaction) and no
   record without a ledger; every violation named by seq;
8. the IDENT declaring `rec-v3` and echoing the control flag;
9. for S, the rate report's `binding` equal to the pins, both calibrations bound to the
   same image/prereg/protocol, both calibrations' input files hashing to their `inputs`;
10. **rel-v4 transactions closed**, machine-enforced (`host/l6_checks.rel_closure_findings`
   over `audits.json` `ident`/`signs`/`term`/`closing_conflict` + `pulls`): the identity
   accepted, acknowledged, not refused, no conflict; the IDENT declaring `rel-v4` and
   echoing both control flags; **exactly one sign ledger per record and the sign-ledger
   seq set equal to the record seq set** (a duplicated, missing or extra seq named;
   never last-wins — the control check and the rate refuse a duplicated ledger too),
   every one accepted with no conflict (and every notary entry's seq recorded, rule
   vii-b); the TERM's `closing_control` complete and typed; no `STOP_SIGN`,
   `STOP_IDENT` or `PROTOCOL_*` end; **every pull the host completed confirmed by the
   board's record** (`verified: audited` — a waited pull whose record says replayed-only
   is named with its counts); the TERM transaction accepted and acknowledged; CLOSE and
   TERM's `closing_control` in agreement;
11. **heartbeats**: for every SCORED record the indices 0..15 seen, at most one missing per
   record, and the session total of missing heartbeats ≤ ⌊R/1000⌋ with R = the number of
   SCORED records (`host/l6_rel.hb_missing_budget`: 0 for C1/C2, 6 for a 2 h soak);
   heartbeat losses are a recovery indicator alongside 3b's;
12. the forced SIGNREQ-retry control exercised on seq 1 exactly as §2.6k states
   (`host/l6_checks.rel_control_findings`), alongside the REC control of item 6;
13. the recovery indicators of 3b extended with `sign_retries`, `ready_resends`,
   `term_retries`, `ident_repeats`, `done_replays`, each ≤ 3 for C1/C2
   (`host/l6_checks.rel_recovery_findings`; `hb_missing` by item 11) — computed by
   `l6_rate.recovery_by_seq` / `rel_session_totals`, one per non-ok attempt, both
   controls attributed as controls, pinned in the manifest's `pass_conditions` at the
   freeze (today `next_prereg.rel_pass_conditions_draft`).

Read against C1 #5's evidence, items 3a/3b would have raised no finding (nominal CoV 0.056
over 62 clean periods, 1 recovered candidate, 1 timeout, 1 bad frame, 0 fragments) —
**stated so the reader sees what the rule does; C1 #5 is not re-judged and stays HOLD
under v0.4, with `calibration.C1` null.**

**HOLD** — an instrument or transport failure (`PROTOCOL`, `CRASHED`, `STOP_REC` — the
transaction exhausted, its attempts in the ledger —, `PROTOCOL_REC` — a conflicting
duplicate, a REC for another seq, a SIGNREQ over an outstanding record —, a lost ruling,
a console fault, a validator rejection that is not a §3 falsifier), the control not
exercised, a nominal CoV above 0.10, fewer clean periods than 3a's minimum, a recovery
bound of 3b or 13 crossed, a report without both ledgers or its inputs (3d), a
`STOP_SIGN`/`STOP_IDENT`, an unconfirmed pull, a heartbeat budget crossed (11), a
`STOPPED` end at link 2/3 with the refusal correctly recorded. Re-run after the cause is fixed and named.
A `CRASHED` soak after ≥ 1 h is a HOLD whose evidence is kept whole; it may be repeated
**once** without a change only if the cause is named as transport (dmesg/usbip record),
otherwise the fix comes first.

**KILL** — any L5 prereg §3 item (they apply unchanged: the interlock and the nonce model are
under the same test for hours), raised as `Falsified` by the validator.

## 7. Stop-loss

`docs/l5_prereg.md` §6 stands: two consecutive sessions lost to the same instrument cause →
stop, fix, prove with an authorised host-side soak before a third ruling; three sessions
without `COMPLETED` → design review before further board time. L6's own: a soak that fails
the same way twice is the result — the next step is a targeted fix with its own review, not a
third soak. `zynq-psmap/docs/stop_loss.md`'s rule is inherited: a new instrument is not a new
mechanism. The owner's lifting of the pull-v2 byte-loss stop-loss (2026-09-01) stood for
v0.3; S #1 counted as S failure #1 under it.

**Owner's ruling of 2026-09-02, recorded:** S #1 and C1 #5 are two consecutive sessions
lost to the same instrument/transport failure class — contiguous byte deletion on the same
console path (S #1 on a `REC` ended the session; C1 #5 on an `AUDIT` was recovered by
rec-v3 but the recovery itself put the CoV over the bound; the different frame types and
consequences do not change the observable failure class). **The stop-loss is TRIGGERED**:
no board ruling until the fix is named and proven host-side (the transport batch is that
proof, reviewed PASS scoped) and the owner lifts it; the owner has further said that the
host soak proves the model and the mechanism, not the physical path, and that `SIGNREQ`,
`HB`, `AUDIT_READY`, `CLOSE` and `TERM` are still not re-requestable and can still fail a
2 h soak through the same byte-loss family — hence §4.19. This is a classification, not
a claim that the two events share a proven physical root cause.

## 8. What L6 does not establish

Claim B (zero data points remain zero); anything on another die, carrier, control plane or
Linux; the ICAPE2 readback path or the H-PAD/H-ADDR/H-IDLE hypotheses; that a 2 h soak
predicts a longer one (the Claim B budget must sit inside what was soaked, or the soak is
extended by its own ruling); anything about the physical console path (the host soak and
the rel-v4 simulations are models of a channel, not measurements of CH340/usbipd); that
rel-v4 on the board behaves as its twins do until the firmware batch's wire-contract
tests and a board session say so.

## 9. Order of work, and the hand-back

1. Host-only instrument changes (§4) with tests; owner review. *(v0.2/v0.3/v0.4: done;
   items 13–18: delivered 2026-09-02, the transport fix reviewed PASS scoped, the D-t2
   corrections and items 19–22 delivered in the rel-v4 host batch, pending review.)*
2. The firmware batch (§4.23): the rel-v4 two-operator image with its C twins driven
   against `host/l6_rel.py`; byte-identical rebuilds; the owner's full P3 compatibility
   review; hash pinned as `next_image`, promoted at the freeze.
3. The owner's rulings: D-p1, the freeze of this text as v0.6 (sha into the manifest,
   v0.4 superseded in history, the v0.5 draft recorded as never frozen), the §7 stop-loss
   ruling.
4. Only then: rulings C1, C2, S issued one session at a time, each with a power cycle —
   ONE C1 → C2 → S under v0.6; the owner pins the bound C1/C2 records (report bytes,
   binding and input files) before S.
5. `docs/l6_findings.md`: the measured rates, the soak record, PASS/HOLD/KILL per §6.
6. The whole L6 package goes to `zynq-fabricmap`'s owner for the separate decision on
   whether Claim B leaves PAUSED (`claimb_resumption_memo.md` §0); Claim B's own
   preregistration then derives its budget and seed schedule from L6's calibration record
   by hash.
