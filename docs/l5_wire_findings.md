# L5 — the wire-protocol defect, and the fix

**Standing: host-only. No board contact, no ruling, nothing pushed.** This document is the
main new artefact of the post-build package resubmitted on 2026-08-31.

## 1. What was found, and how

The previous post-build package passed review and the next step was to go to the board. It
did not survive the check that came first: the reviewer's step 4 named an executable that
does not exist, and looking for it surfaced a larger problem.

Five findings, each confirmed against the source before anything was changed:

| | finding | evidence |
|---|---|---|
| A | **No L5 board runner.** L2, L3, L3-diag and L4 each had one; L5 had only libraries. `l5_notary.py` exposes `NotaryRelay`/`Collector`, `l5_refloop.py` is a reference state machine; neither has an entry point. `docs/l5_design.md` §5 "host-side pieces (done)" never listed a runner. | `host/*.py` CLI survey |
| B | **The application never transmitted its identity.** It emitted `REC`, `SIGNREQ`, `TERM` only, and parsed `SIGNOK`/`SIGNREF` only. `validate_standalone_run_log` *requires* `app_identity`. | `p3_app.c` send sites; `validators/records.py:390` |
| C | **Audit-on-request did not exist.** No `AUDIT` emitted, no `AUDITREQ` parsed, `S.audited` assigned nowhere, and the evidence ring was declared and TLB-mapped but never written. The preregistration says the first session audits **every** candidate. | `p3_app.c`; `docs/l5_prereg.md:63` |
| D | **No heartbeats.** The collector calls three heartbeat intervals (30 s) of silence a `CRASHED` end, and a candidate is silent from its sign reply until its record. | `l5_notary.py` `Collector.poll` |
| E | **`loop_record` was structurally incompatible.** The schema requires `seq`, `genome`, `outcome`, `verified`, `evidence`; the application emitted a flat payload with **no `seq`** (so `Collector.on_line` would have crashed on the very first record), **no `verified`**, and **no nested `evidence`**. The closing control was emitted as outcome `CLOSING_CONTROL`, which is not a `LOOP_OUTCOME`. | `records.py:44`; `l5_notary.py:191`; `p3_app.c` `emit_record` |

**Root cause, stated plainly.** The end-to-end rehearsal exercised `host/l5_refloop.py` — the
*Python* reference of the loop — against a fake PL. The C twin test covered `p3_derive.c`
(hashes, derive, streams). Nothing anywhere consumed the bytes `p3_app.c` actually emits, so
both ends of the chain were verified and the join between them was empty. Every test was
green while the image could not have produced a session the host could adjudicate.

## 2. The fix

**The serialisation is now a pure unit.** `firmware/p3_wire.{c,h}` builds every payload and
every framed line, with no MMIO and no board dependency — the same architectural move
`p3_derive.c` already makes for the hashes. `p3_app.c` keeps the HAL and the state machine
and builds no JSON by hand (guarded: `test_no_payload_is_hand_built_any_more`).

**The contract test consumes the real C bytes.** `firmware/p3_wire_twin.c` (`make wire`)
exposes that exact source on stdin/stdout, and `tests/test_firmware_wire_contract.py` runs a
whole session in which the C code emits `IDENT`/`SIGNREQ`/`REC`/`CLOSE`/`TERM`, the **real**
`NotaryRelay` and **real** signer answer the requests, the **real** `Collector` parses every
line, and the **real** `validate_standalone_run_log` adjudicates the assembled log. Two
discrimination tests prove the check has teeth: the old flat record and `CLOSING_CONTROL` as
an outcome are both rejected.

**The application now sends what the protocol requires:**

- `IDENT` after the identity checks — and **also when identity is refused**, because a
  refused identity is still evidence. All findings are collected and reported rather than
  the first one aborting silently.
- `HB` at every progress point of a candidate (after staging, after each envelope write,
  after each of the twelve readbacks). Deliberately **progress-driven, not clock-driven**:
  the global timer's rate follows CPU_6x4x, still an assumption until the pre-board
  `CPU_CLK_CTRL` read, and liveness must not rest on an unverified constant.
- `AUDIT` chunks of the raw words — the three re-read staging streams then the twelve
  readback frames, base64url, 384 words per chunk — served after link 3 and **before** the
  record that claims them.
- `CLOSE` for the closing unsigned ARM, filed by the collector under `closing_negative`.
- `loop_record`s with `seq`, `verified` and the nested `evidence` the outcome requires.

**`verified: audited` means the words were served.** Not that auditing was configured. The
mark is `S.audit_served && S.audit_served_seq == rec->seq`, set only after the chunks are
sent (`test_the_audited_mark_means_words_were_served`).

**The hardware witness is read, not echoed.** `hw_candidate_commit` and
`functional_readout` come from `HW_COMMIT0`/`READOUT0`. Echoing the signed values back would
have made validator rules (ii) and (iii) vacuous.

### The audit's timing, and what it can and cannot cover (round 4)

The request is attached to the notary exchange **before** the candidate is staged, so the
words it will be asked for do not exist yet and cannot be fabricated to fit a record; they
are served after the words exist and **before** the record that claims them, which is why
`verified` can be truthful at emission.

Review round 3 flagged that "session 1 audits every candidate" was incompatible with this
timing. The premise needed one correction — the *current* candidate is audited, not only
earlier ones — but the conclusion was right for a different reason: **candidates that end
before staging have no raw words at all**, so no timing can audit them. The fix is both
halves of the reviewer's choice:

- *protocol* — a candidate that staged and then refused itself at **link 2** now serves its
  staged words before its record. Its whole claim is `staged != commit`, which the host
  otherwise had to take on trust; it is now checkable. The audit carries `span` and
  `total_words` so a short audit (streams only, no readback frames) can never be read as a
  full one.
- *preregistration* — the condition is now `all-self-reporting`: every candidate that
  staged is audited; a **gate** refusal staged nothing and is exempt **and recorded as
  exempt**, corroborated instead by the notary log's own refusal under rule (vii). It is
  machine-checked by `validators.records.check_audit_policy`, which `host/l5_runner.py`
  calls, so a `PASS` cannot be reported if a self-reporting candidate went unaudited.

Still true and still a limitation: because the request arrives in advance, this is **weaker
than a surprise post-hoc audit** at rates below 100 %. At this session's rate every
self-reporting candidate is audited, so the gap does not bite here. A surprise audit of an
*earlier* candidate needs the W-deep ring plus a way to record the result without the
collector rewriting the application's own self-report; that is not built and is not
claimed.

## 3. `fclk0_hz_decoded`

The schema requires it; the application cannot measure it. The source audit permits exactly
one SLCR symbol — the IDCODE read — and that guard was **not** weakened to add a field. The
host writes FCLK0 into the identity page's previously reserved word 22 and the application
echoes it. It is **host-supplied and echoed, not an application measurement**, and is
labelled that way in `p3_derive.h`, `l5_refloop.py` and here. The identity's weight rests on
what the application does observe: IDCODE, STATUS, `key_loaded` and the nonce echo.

## 4. The runner

`host/l5_runner.py` (ruling text `whole-of-probe P3-L5`). It is thin on purpose — on this
rung the loop lives in the firmware and the host is the notary, not the decision maker:
claim the ruling and refuse without a boundary record < 6 h old → precheck, identity, dcache
off → **the blocking preflight `CPU_CLK_CTRL`, read once and stored** → setup-load the
carrier, provision K (P3-K) → write the identity page, ymodem the image to `0x0200_0000`,
`go` → relay and collect → assemble and adjudicate. It refuses to start against an image
that is not the pinned one. A `CRASHED` end is sealed, never repaired (prereg §4).

`tests/test_l5_runner.py` covers what the runner owns: frame recovery from a split byte
stream, console noise that is kept but not mistaken for a frame, the U-Boot banner as a
crash signal, `\n`-terminated replies (the application's `recv_line` skips `\r`, so a
`\r`-terminated reply would hang it forever), and the unpinned-image refusal — asserted on
the *reason*, because a refusal for an earlier cause would prove nothing.

## 5. The image

`app_image_sha256` = **`a7c73d1f…`** (see §7 for the history; `10044abe…`, the image this section was written for, is now withdrawn as superseded). Two clean builds are byte-identical, and
`firmware/bsp/build.sh` now emits the `.bin` itself — it previously produced only the ELF, so
the pinned hash was not reproducible from the script alone.

**The previous image `7540239f…` is WITHDRAWN**, recorded in the manifest's
`withdrawn_images`. It is not merely superseded: it could never have produced an adjudicable
session.

## 6. What this does *not* establish

The contract test judges the bytes `p3_wire.c` produces. It cannot judge how `p3_app.c`
populates them, because that file is MMIO- and BSP-bound and does not compile on the host;
those are **static** source-audit checks (`tests/test_firmware_audit.py`, class
`WireWiring`), and they are named as static so a green run is not read as the board having
run. The application has still **never been executed on hardware**. Nothing here is evidence
about the PL, the transport, or timing.

## 7. Image history

| image | standing |
|---|---|
| `7540239f…` | **withdrawn** — could never have produced an adjudicable session (§1) |
| `b279459c…` | **withdrawn** — no defect in what it emitted, but a link-2 refusal was unauditable |
| `d3828a8c…` | withdrawn — **not defective**: this is the image that ran session 1 and produced its evidence (`docs/l5_session1_findings.md`); superseded by the instrumentation batch |
| `8390c463…` | withdrawn, **DEFECTIVE — must not be run**: its `CTRL` read-back is SLVERR on this carrier and crashes at every ARM before any record is emitted (session 2) |
| `10044abe…` | withdrawn — **not defective**: the `CTRL` read removed, `ctrl_readback` recorded as unavailable; ran session 3 (`docs/l5_session3_findings.md`) and stays identifiable for it; superseded because it read the nonce before the gate had settled and counted `total` as `scored + refused` |
| `a7c73d1f…` | **pinned** — bounded settle poll before the nonce read, `STOP_SETTLE` outcome, `TERM.audit` from the serialiser's tally (`docs/l5_settle_correction.md`); byte-identical across two from-scratch rebuilds; has not run on hardware |
