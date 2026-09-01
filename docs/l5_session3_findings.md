# L5 session 3 on 17A6 (ruling `2026-09-01-03`) — the diagnostic session

**Standing: HOLD.** The runner's literal outcome string is
`KILL run_log rejected: audit must report audited <= total (rule ix)`. That string is the
runner mapping *every* validator rejection to the word KILL; `docs/l5_prereg.md` §5 defines
KILL as "any item in §3", and no §3 item was met (see §3 below). The rejection is a counter
in the firmware's `TERM` frame — an instrument defect — which §5 classes as **HOLD**. The
owner adjudicates; this document does not.

Evidence: `evidence/l5_17A6_2026-09-01-03/`, image `10044abe…` (the pinned image, unchanged),
carrier `956379fa…`, boundary `evidence/boundary/principal_boundary_2026-09-01-03.json`
(R1–R5 as the runner). Power-cycled before the session; both `-03` rulings consumed.

## 1. What happened

The session was run exactly as `docs/l5_diag_spec.md` prescribes — identical runner, budget,
audit policy and board sequence to session 1; only the instrumentation differs. Preflight
`CPU_CLK_CTRL = 0x1f000200` (third identical read). Identity, `IDENT`, notary round trip,
staging, link 2, DMA, link 3 and the 8-chunk audit all held, as in session 1. Then the
application ARMed candidate 1 (the blank / opening baseline, commit `3e24d936…`) and stopped:

```
epoch_end: STOPPED, last_seq 1, "the nonce did not step: the PL did not consume this ARM"
```

**This time the `STOP_ARM` record was emitted** — the thing session 2 died before doing —
and it carries every field the amended §2 requires:

| field | value |
|---|---|
| `status_after` | **`0x00000901`** (`status_at_start` was `0x900`) |
| `fault_after` | `0` |
| `writes_issued` | `25` (20 payload + 4 tag + strobe) |
| `nonce_before` / `nonce_after` | `9e3779b97f4a7c15` / `9e3779b97f4a7c15` — equal |
| `key_loaded_observed` | `true` |
| `ctrl_readback` | `"unavailable: CTRL is write-only"` |
| `verified` | `audited` |

The mandatory restore ran (`closing.restore: done`); baseline and unsigned control were not
reached. Zero disruptions, zero CRC drops, zero transport re-reads. 54 console lines:
`IDENT`×1, `SIGNREQ`×1, `HB`×16, `AUDIT`×8, `REC`×1, `TERM`×1.

**The audit checks out again, independently.** The 8 chunks reassemble to 2814 words; on the
host, `staged_stream_sha256`, link 2 and link 3 all recompute to the record's values and to
the signed commit `3e24d936…` (five-for-five MATCH, same recipe as `host/l5_refloop.py`).

## 2. The observation the session was for: `STATUS` bit 0 is set

`docs/l1_design.md` §"register map": **`STATUS` bit 0 = `gate_busy`**. `0x900 → 0x901`
across the strobe means: at the instant the application read `STATUS`, **the ARM gate was
busy**. Read against the RTL:

`rtl/p3_arm_gate.v`, state 0, on `arm_strobe` with a key loaded:
```
busy <= 1'b1; ... sh_start <= 1'b1; state <= 3'd1;
```
and the nonce steps only in state 1, **when `sh_done`** — after SipHash over the 20 payload
words and the nonce has completed:
```
3'd1: if (sh_done) begin
    nonce <= xorshift(nonce);      // "the nonce is consumed by THIS attempt whatever the outcome"
```

The application's `arm_attempt` (`firmware/p3_app.c`) does, in immediate succession:
```
axi_write(P3_CTRL, P3_ARM_STROBE);
*status = axi_read(P3_STATUS);
*fault  = axi_read(P3_FAULT);
*nonce_after = pl_nonce();
```
— three AXI reads issued straight after the strobe write, with **no wait for `gate_busy` to
clear**. The L3 host runner, whose sequence session 1 described as "identical", is not
identical here: `host/l3_runner.py` after the strobe **polls `STATUS` until
`!gate_busy && !scorer_busy && (fault || scorer_done)`** and only then reads `FAULT` and the
nonce (`ARM_TIMEOUT_S = 10.0`, with the comment "the PL is done in < 200 cycles at 50 MHz").
Session 1's refutation of the "wrong offsets / strobe" hypothesis compared the *writes* and
missed the *wait*.

So the register picture is: every write issued; no fault; the gate **did** take the strobe
and was mid-verification; the nonce had not stepped **yet** when it was read, within well
under the gate's own completion time (< 4 µs at 50 MHz; the A9 issues the three reads in a
fraction of that over a Strongly-Ordered window). The amended `docs/l5_diag_spec.md` §3 row
"`fault_after == 0`, `writes_issued == 25` → the gate neither acted nor faulted" is
**contradicted** by bit 0 — the gate acted. That row was written before the observation and
is left as written; this document is the record of what the observation actually was.

### What this does and does not establish

- **Established (from the record + the RTL):** the PS's strobe reached the gate; the gate
  entered verification; the application sampled the nonce while the gate was busy. Session
  1's "the PL did not consume this ARM" is therefore a **premature read**, not a
  non-consumption — the same code path, so the same explanation applies to session 1.
- **Not established on silicon:** that the nonce *would* have stepped had the application
  waited. The RTL says it must (state 1 steps it on `sh_done` whatever the tag outcome), and
  L3 saw it step five times through the host's poll, but no session has yet observed the
  standalone application read a stepped nonce. That is the one-line experiment a corrected
  build must perform.
- **Unobserved and now unknowable for this session:** what the gate did after the
  application gave up — with the real signer's tag it should have verified, swept and
  compared, then possibly `scorer_done`/`cfg_valid_hw` — because the application proceeded
  to restore while the gate was (probably) still running. Nothing was read afterwards.

## 3. Classification against the preregistration

| `docs/l5_prereg.md` §3 item | met? |
|---|---|
| `score_record` with `configuration_valid_hw` false or commit mismatch | no `score_record` exists |
| closing unsigned ARM validates or scores | not reached |
| nonce chain deviates from the model | no attempt was consumed within the session's own reading; `chain_length 0` |
| audited words do not recompute | they recompute (§1) |
| DMA while `staged != commit` | staged == commit |
| ARM after a fault / write outside the map | `fault_after 0`; 25 writes, all inside the map |

No falsification item is met → **not a KILL under §5**. The rejection is:

```
audit.audited = 1, audit.total = 0    → rule (ix): audited <= total
```
because `firmware/p3_app.c`: `in.total = S.scored + S.refused;` — a candidate that ends
`STOP_ARM` is neither, so the session-1 instrumentation batch made a record that its own
summary does not count. Host-only counterfactual (not evidence, run on a copy): with
`total = 1` the identical log is **accepted** (`scored 0, audited 1, chain_length 0`) and
`check_audit_policy` returns `audited: [1]`. It was the only rejection. Under §5 that is an
**instrument failure → HOLD**. The runner's `KILL run_log rejected: …` wording is broader
than the preregistration and should be made to say what §5 says (host-only change, later).

**Stop-loss (`docs/l5_diag_spec.md` §5):** this is the second stop at the ARM with the same
register picture, so per the spec *this is the result*; a third identical session is not to
be run. **`docs/l5_prereg.md` §6:** three sessions (1, 2, 3) without a `COMPLETED` end ⇒
**the standalone plane goes back to design review before any further board time.** Both
triggers are recorded here as triggered.

## 4. What a corrected build must change (proposal — not done, not authorised)

1. `arm_attempt`: after the strobe, **poll `STATUS` until `!gate_busy && !scorer_busy` and
   settled**, bounded (L3 used 10 s of host polling; the PL needs < 200 cycles), then read
   `FAULT` and the nonce; a timeout is its own recordable stop (`STATUS` at timeout
   preserved). This mirrors `host/l3_runner.py` and the RTL contract.
2. `TERM.audit.total` must count every candidate that made an attempt, including `STOP_ARM`
   (and be discrimination-tested: a STOP_ARM session's TERM must validate).
3. Runner: map a validator rejection to the §5 class it belongs to, not to `KILL`.
4. Contract test: the C wire twin must emit a `STOP_ARM` session whose `TERM` the real
   validator accepts (the existing contract test covers the happy path and the old flat
   record; it did not cover a counted STOP_ARM).
5. The design review §6 demands comes first; a new image, a prereg amendment naming the
   wait, a review round and new rulings follow. **Nothing here is a retry.**

## 5. Cost

Three rulings and one power cycle so far on the ARM question: session 1 lost the diagnostic
values, session 2 crashed on my CTRL read, session 3 captured the picture and was then
rejected by my counter. The observation the diagnostic was designed for was obtained; the
adjudication machinery around it was the weak part, twice.

## 6. Standing

- **HOLD** (instrument: `TERM` counter) — the owner adjudicates the runner's `KILL` string
  against §5; this document argues it is not a §3 item and says why.
- Both `-03` rulings consumed. Board untouched since the runner exited; not power-cycled.
- Pinned image remains `10044abe…` — the image that produced this evidence stays
  identifiable. It is **not** defective in what it emitted; it is wrong in *when* it reads
  the nonce and in what it counts.
- L3's hardware-enforced interlock result is untouched. L5's runtime property remains
  untested — and the reason it has looked untestable for three sessions is now, at least,
  named and traceable to source.
