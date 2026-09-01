# L5 preregistration — the standalone loop, first bounded session (DRAFT, host-only)

> Registered **before** any board contact, as this line's rungs always have been. It fixes
> the claim, the non-claims, the procedure, the analysis and the stop conditions in advance,
> so the session's outcome cannot be argued into a pass afterwards. **It authorises
> nothing**: the build, the rulings and the board sequence are the owner's single
> authorisation after the D5 batch review (`docs/l5_review_package.md`).

## 1. Claim L5

> **On EBAZ4203 `17A6`, with the P3 carrier (`956379fa…`), a standalone application started
> from a U-Boot session runs N gated candidates within one epoch — proposing, staging,
> writing, reading back and arming them itself, with no host in the search loop — and every
> score it reports is one the PL granted only against a MAC the gate signer produced for
> that candidate, that table set and that nonce.**

The new thing is the *runtime property*: the loop and the PS oracle move onto the board
while the interlock's hardware enforcement (L3) and its refusals (L4) continue to hold.

## 2. Non-claims — stated first, because they are what an L5 PASS will be misread as

1. **Not autonomous discovery.** The seed is host-supplied in the identity page
   (deterministic/test mode, `zynq-ehw` Claim M1's own taxonomy; review #2 Q6). A
   board-derived seed is a later step and is not claimed here.
2. **Not "no host".** The host remains the permission authority: the gate signer holds `K`
   and vetoes any candidate the whitelist refuses (D1 §5c, review #2 Q1 accepted this narrow
   reading). "No host in the *search* loop" is the claim; "no host" is not.
3. **Not a search result.** Nothing is claimed about the quality, convergence or
   beats-random status of the candidates. Claim B belongs to `zynq-fabricmap`; M1's
   beats-random belongs to `zynq-autoehw`.
4. **Not persistence.** No champion is written to NAND, SD or any non-volatile store; the
   evidence lives in the streamed records and in the host collector.
5. **Not complete evidence of links 2 and 3.** On the standalone plane those are the
   application's self-report (`app_oracle_record`), compensated by the PL's own witness
   (3′), the `staged == commit` binding before any DMA, and the audit — which is a
   **bounded** guarantee, reported as such (rule ix).
6. **Nothing about flush frames or non-target bits.** As at L3.

## 3. Falsification — any one of these is a KILL for the claim, not a bad session

- A `score_record` exists whose `configuration_valid_hw` is false, or whose
  `hw_candidate_commit` differs from the commit the notary signed.
- The **closing unsigned ARM validates or scores** (the interlock did not hold).
- The nonce chain across the session's ARM attempts is not the model's xorshift from
  `NONCE_SEED` — the PL did not consume attempts as the model says it does.
- An audited candidate's raw words do not recompute the hashes its compact record claimed.
- A candidate reaches a DMA while `staged_sha256 != commit`.
- The application ARMs anything after a PL fault, or writes any address outside the pinned
  map (visible as an `STOP_AXI` that did not stop the epoch).

## 4. Procedure — fixed in advance

**Session shape.** Power-on → `BoardSession` identity → carrier setup load (sha-gated) →
`provisioning P3-K` (signer, JTAG mem-AP) → application image load (sha-gated) → `dcache
off` → identity page written and read back → `go`. Then: opening baseline, **N = 8**
search candidates, closing baseline (= restore), closing unsigned ARM.

**Budget: N = 8** for the first session. Small on purpose: the point of session 1 is that
the loop, the taxonomy, the brackets and the evidence chain behave as specified, not that
the board can run for hours. A long run is a later prereg with its own ruling.

**Audit rate: every candidate that has raw words — policy `all-self-reporting`.** For N = 8
the raw-word upload (≈ 16 KiB ≈ 1.5 s each) is affordable, so this session audits every
candidate it *can*. The 1/16 sampling rate in `docs/l5_design.md` §1 belongs to the long-run
prereg, not to this one.

This clause used to read "the first session audits **all** of them". That was not a
condition any implementation could meet, and saying it while shipping something weaker
would have been the worst of the options. A candidate refused by the **gate** never stages
anything: no raw words exist for it, so there is nothing to audit, and its record makes no
oracle self-report. Its corroboration is the notary log's own refusal, which the host wrote
itself and which rule (vii) cross-checks — stronger than an audit, not weaker.

The condition, exactly:

- every candidate that **staged** is audited before its own record is emitted. That
  includes a **link-2 refusal**, whose entire claim is `staged != commit` and which the
  host could not otherwise check; its audit carries the staging streams and says so
  (`span: "streams"`, no readback frames exist yet).
- a candidate refused by the gate, or stopped before staging (`STOP_AXI`), is **exempt and
  recorded as exempt**; marking it `audited` would be a false claim.
- `verified: "audited"` continues to mean the words were **served**, never that auditing
  was configured.

This is checked, not asserted: `validators.records.check_audit_policy` recomputes it from
the log and `host/l5_runner.py` calls it, so a session that quietly failed to audit a
self-reporting candidate cannot be reported as a pass. **A `PASS` requires
`check_audit_policy` to return without raising.**

**Rulings.** One `whole-of-probe P3-L5` and one `provisioning P3-K`, both created by the
owner, consumed by any outcome. Before the runner starts: power cycle, and
`host/verify_principal_boundary.py` re-run as the runner (< 6 h old).

**Watchdog: OFF for this session** — the owner's ruling on the D-c build finding
(`docs/l5_findings.md` §4, option 2). The identity page is written with **`flags.bit1 = 0`**,
so the application arms no watchdog and never touches the SCU WDT: the firmware gates both
the arm and the kick on that bit, and `tests/test_firmware_audit.py` now checks that gating.
`P3_WDT_LOAD` stays `0` in the image and is unreachable. **It must not be enabled by flipping
bit1 alone** — a load of 0 is an immediate timeout. Turning the watchdog on is a separate
change (option 1, a prescaler write) needing its own build, preregistration and ruling.

**Host recovery with the watchdog off.** The application cannot self-reset, so a hung or
silent application is the host's to end:

1. The collector declares **`CRASHED`** after 3 × H = 30 s of console silence (§3c) and
   writes the `session_summary` itself. This is unchanged by the watchdog being off — it was
   always the host's inference, never the application's report.
2. The runner then **stops**: no further PCAP or ARM operation, and **no restore attempt** —
   the fabric state is unknown, and an unsynchronised write is worse than a known unknown.
3. Evidence is **sealed as it stands**: the notary log, every framed line received, and the
   partial record set, with the outcome recorded as `CRASHED`, cause `host-ended, watchdog
   off`. Post-mortem reads on the next session are `diagnostic` and never adjudicable (§6a).
4. Recovery is a **power cycle**, and the next attempt needs **new rulings** (`whole-of-probe
   P3-L5` + `provisioning P3-K`). The consumed pair is never reused.

A `CRASHED` end is a **HOLD** under §5 — never a PASS, and never by itself a KILL.

**Pre-board preflight (blocking, at first power-on).** Read `CPU_CLK_CTRL` once —
`md.l 0xF8000120 1` — and store it with the session evidence. Until that read exists,
CPU_6x4x = 666.67 MHz and PERIPHCLK = 333.33 MHz are **assumed** (the standard 6:2:1 ratio),
not verified: the ARM PLL is board-confirmed from `ARM_PLL_CTRL`, the CPU divisor is not
(`docs/l5_findings.md` §5). **No timing conversion derived from those figures may be reported
as a verified fact before that read.** Nothing in this watchdog-off session depends on the
value, which is why it is a preflight and not a build blocker.

**Instrument rules that killed earlier sessions and are therefore procedure now.** The
runner runs in the background with **no shell timeout**; waiting is by pid, never
`pgrep -f`; the D-cache is off before staging (and on the standalone plane the buffers are
also non-cacheable by MMU attribute); every wait is bounded and every exception writes a
summary.

## 5. Analysis plan — decided now, not after the data

**PASS** requires all of:

1. `epoch_end.kind == COMPLETED`, with all three closing steps `done`.
2. The opening **and** closing baselines score exactly `[18, 22, 20, 20, 20, 18]` — the
   value L4 measured and fabricmap published as `base_restore`.
3. Every candidate is `SCORED` or `REFUSED_BY_GATE`; every `SCORED` record's
   `hw_candidate_commit` equals the notary's commit and its `functional_readout` equals the
   signed tables.
4. The nonce chain over every attempt, including the closing control, equals the model.
5. The closing unsigned ARM is refused with `F_ARM_AUTH` and no score.
6. Every audited candidate recomputes: raw words → both link-2 hashes and the link-3 hash.
7. `validators.records.validate_standalone_run_log` accepts the log (rules (i)–(ix)).
8. Zero disruptions; CRC drops within the budget (16).

**HOLD** — an instrument or transport failure (a `PROTOCOL` end, a CRASHED end, a lost
ruling, a console fault): the session is re-run after the cause is fixed and named. A HOLD
is never argued into a PASS.

**KILL** — any item in §3.

Anything else — a `STOPPED` end at link 2 or link 3 with the refusal correctly recorded and
the base restored — is a **correct refusal**, reported as such: it says the instrument
stopped where it should, and the rung is re-run once the cause is understood.

## 6. Stop-loss

Two consecutive sessions lost to the same instrument or transport cause ⇒ stop, fix the
cause, and prove the fix with an authorised soak before asking for a third ruling
(`decisions.md` kill criterion 3 — never relax a guard instead). Three sessions without a
COMPLETED end ⇒ the standalone plane goes back to design review before any further board
time.

## 7. What is already fixed before the session

The genome corpus (`N = 256`) and the C twin's agreement with the Python reference; the
schemas and the validator rules; the notary protocol and its drop budget; the reference
loop's state machine; the firmware source audit. None of these may be changed to make a
session pass: a change to any of them invalidates this preregistration and requires a new
one.

Also fixed: the application image itself. The build is done and its hash is pinned
(`manifests/l5_manifest.json` `pinned_at_build.app_image_sha256` = `8390c463…`).

**Image change on record (2026-08-31).** The earlier image `7540239f…` is **withdrawn**. It
was not superseded by a preference: its framed output could not satisfy this
preregistration's own validator — no `IDENT` although `app_identity` is required, no
heartbeat although 30 s of silence is a `CRASHED` end, no audit although §5 says the first
session audits every candidate, `loop_record`s with no `seq`/`verified`/`evidence`, and the
closing control emitted as an outcome that is not a `LOOP_OUTCOME`. `docs/l5_wire_findings.md`
records the finding and the fix. Nothing this preregistration says a session will DO has
changed: the same brackets, the same N, the same PASS/HOLD/KILL conditions, the same
stop-loss. What changed is that the application can now emit a session the host can
adjudicate at all, and that the C serialisation is checked against the real validator
(`tests/test_firmware_wire_contract.py`) instead of a Python model of it.
One test was *added* to the firmware source audit with that decision — the watchdog-gating
check described in §4. It is a strengthening (a property that was previously only read is now
checked) made **before** any session, not a relaxation to let one pass.

The post-build review (2026-08-31) added provenance artifacts and their guarding tests —
`manifests/l5_bsp_inputs.json` with `tests/test_bsp_inputs_manifest.py`, and
`evidence/l5_build/`. These are **defensive additions that do not change execution
semantics**: they pin and re-hash the exact build inputs and record the build's provenance;
they touch no firmware source, change no image (rebuilt byte-identical, `app_image_sha256`
unchanged at `7540239f…`), and alter nothing this preregistration says a board session will
do. They tighten what a passing build must prove about its inputs; they do not move the gate.
