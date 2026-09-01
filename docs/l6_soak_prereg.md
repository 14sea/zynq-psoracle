# L6 — calibration and soak of the P3 loop (preregistration, DRAFT v0.2, host-only; D-s1..D-s4 ruled 2026-09-01)

> **Standing: DRAFT. Host-only. This document authorises nothing — no build, no ruling, no
> board contact.** Written 2026-09-01 on the `zynq-fabricmap` owner ruling recorded in
> `zynq-fabricmap/docs/claimb_resumption_memo.md` §0: Claim B's readback leg is
> RESUMPTION-ELIGIBLE but stays PAUSED "until a calibration/soak preregistration has passed
> and the two-operator image has completed P3 compatibility review", and "the first Claim B
> ruling must not be spent on calibration or integration debugging." L6 is that
> preregistration. It lives here because it preregisters the **instrument** (the P3 stack);
> Claim B's own preregistration, arms, budget and score stay `zynq-fabricmap`'s.

Frozen when: committed with its content sha256 recorded in `manifests/l6_manifest.json` and
every later artifact pinning that hash. Until then it is a proposal.

## 0. The two questions, and what they are not

- **Q1 (calibration).** On the P3 path, with the image Claim B will actually use, what is the
  measured end-to-end rate per candidate — sign round trip, staging, link-2 witness, DMA,
  link-3 readback, audit service, ARM + settle + score — and its failure rate? Claim B's
  preregistration (`claimb_preregistration.md` §6, "The budget still cannot be frozen here")
  defines exactly this calibration and says the budget derives from it. **No P3 session has
  measured it: session 4's evidence carries no timestamps** (a 253 s wall time from file
  mtimes covers the 2 MB carrier transfer; the per-candidate rate is unknown).
- **Q2 (soak).** Does the P3 loop hold every invariant L5 established — heartbeat cadence,
  nonce chain, host-recomputed audits, baseline equality, fail-closed ends — **for hours,
  unattended, under the sampled audit policy and with the watchdog decided**? L5's PASS
  explicitly excluded long-run stability.

**Not Claim B.** No primary metric, no holdout, no comparison between arms is made or
reported as a finding here; the arms run only so that the *instrument* is calibrated and
soaked in the configuration Claim B will use. **Not autonomous discovery**: seeds are
host-supplied. **Not cross-chip**: `17A6` only. **Nothing about the ICAPE2 readback path.**

## 1. Pins

| | pinned to |
|---|---|
| instrument repositories | `zynq-psmap` `191ab05`; `zynq-psoracle` at the commit that freezes this document; `zynq-fabricmap` artifacts at `71666b02` (link 1, `local_map.json`, certificates), re-verified by hash at session start (fabricmap's falsifier 3) |
| carrier | `builds/p3/p3.bit` `956379fa…` (unchanged since L1) |
| application image | **the two-operator image** (§2) — built, byte-identical across two from-scratch builds, P3-compatibility-reviewed, pinned in `manifests/l6_manifest.json`. **L6 does not run on `a7c73d1f…`**: calibrating one image to budget another would repeat the mistake `zynq-autoehw` caught (a "2 h" derived from the wrong path's rate) |
| board / control plane | EBAZ4203 `17A6`, U-Boot → standalone crossing, D4 principal boundary verified as the runner < 6 h before every session |
| genome universe | 292 bits over the twelve target FARs, addresses sha256 `895baf85…` (`manifests/l5_manifest.json` `genome`) |

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
6a. **Unconditional audit for non-`SCORED` self-reports** (§3a item 2): the firmware serves
   the raw words before emitting any `STOP_LINK2`/`STOP_LINK3`/`REFUSED_BY_PL`/`STOP_ARM`/
   `STOP_SETTLE` record, with or without an `AUDITREQ`.
7. Review by the owner against this list, item by item, before any L6 ruling; the image
   hash is then pinned in `manifests/l6_manifest.json` and this document is frozen.

## 3. Decisions — RULED by the owner, 2026-09-01

| id | ruling |
|---|---|
| **D-s1** watchdog | **ON.** Prescaler 7, 30 s (`load 1 250 000 035` at PERIPHCLK 333.33 MHz, board-confirmed 2026-09-01-05). Arm and kick are gated by the identity page's `flags.bit1`; the **bit1 = 0 path keeps L5's behaviour exactly**. The build and its tests must pin the **actual** load value written, not the derivation. |
| **D-s2** audit policy for the soak | **Sampled, accepted in principle, with the timing requirement of §3a as a condition.** The v0.1 wording "every non-`SCORED` self-reporting record audited" is **not implementable under the current wire protocol** (§3a) and is replaced by §3a's rule. |
| **D-s3** soak duration | **2 h, accepted.** N = ⌊0.9 × min(rate_A, rate_B) × T⌋, with rate_A and rate_B imported **only** from the two calibration records (C1, C2) by their hashes. |
| **D-s4** CRC budget | **Frame-count scaling, with a closed formula:** `budget = ceil(4 × expected_protocol_frames / 1000)`, where `expected_protocol_frames` is derived **before the session starts** from N, the audit schedule and the fixed brackets (`IDENT`×1, `SIGNREQ`×(N+2), `HB`×16 per candidate, `AUDIT`×8 per audited candidate, `REC`×(N+2), `CLOSE`×1, `TERM`×1) — **never from the count actually received**. Independently of the CRC total, **any missing `AUDIT`, `REC` or `TERM`** is the corresponding structural defect and is a HOLD even when the CRC drops are within budget. |

### 3a. The audit timing requirement (D-s2's blocker, and its resolution)

**The blocker.** Under the current wire protocol the host's `AUDITREQ` is attached to the
sign reply, i.e. it reaches the application **before staging**, and the application serves
raw words only `if (S.audit_requested)` (`firmware/p3_app.c`, the `serve_audit` call sites).
There is no evidence ring: once a candidate's outcome is known, its words are gone if they
were not requested. So under a sampled schedule, a candidate the schedule did **not** select
that then turns out to be `STOP_LINK2`, `STOP_LINK3`, `REFUSED_BY_PL`, `STOP_ARM` or
`STOP_SETTLE` can no longer be audited — "all non-`SCORED` self-reporting records audited"
cannot be honoured after the fact.

**The rule, fixed here:**

1. **`SCORED` candidates** are audited per the preregistered sampled schedule (every 16th by
   seq, plus the first and the last candidate and both baselines), requested by `AUDITREQ`
   as today.
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

This is a **firmware change** (item 2) and therefore part of the two-operator image's P3
compatibility review (§2), plus a validator change (the sampled policy with item 2's
obligations). Both wait for the owner's authorisation of §4 and §2; nothing is implemented by
this document.

## 4. Instrument changes required before any L6 ruling (host-only, tested, reviewed)

1. **Timestamps.** The collector records a monotonic and a wall-clock receive time for every
   frame; `run_log.json` carries per-record timing (`t_signreq`, `t_reply`, `t_first_hb`, …,
   `t_rec`) and `console.log` gains a timestamped companion (`console.ts.log`) — the raw
   `console.log` bytes stay verbatim. A test proves the stage boundaries are attributable
   from the frame sequence (`SIGNREQ` → reply → `HB`×16 → `AUDIT`×8 → `REC`).
2. **Rate report.** `host/l6_rate.py` derives from a run log: per-candidate wall time and its
   breakdown, evaluations per hour, the coefficient of variation, and the failure rate —
   the four numbers Claim B's §6 calibration asks for. Pure function, tested on session 4's
   log (it must refuse: no timestamps) and on a synthetic timed log.
3. **Sampled audit policy** (D-s2, as fixed by §3a) in `validators/records.py`, with the host gate unchanged; the policy check must know the schedule and must require the §3a item-2 auto-audit for every non-`SCORED` self-report.
4. **Arm-aware validator**: `loop_record.arm` required and checked against the schedule
   (§2.4); `check_audit_policy` and the chain unchanged.
5. **Ruling text** `whole-of-probe P3-L6` checked by `host/l6_runner.py` (the L5 runner with
   `--duration`, the sampled policy, timestamps and the rate report; nothing else), plus
   `provisioning P3-K` per session as always. Old texts are refused.
6. **Budget arithmetic in the runner**: N is an input pinned from the **two** calibration
   records' hashes (D-s3), never typed by hand; the session timeout is derived from N and the
   measured rates with margin, and is recorded.
7. **Expected-frame-count and CRC budget** (D-s4): computed before the session from N, the
   schedule and the brackets, recorded in the summary with the formula's inputs; the
   collector's structural checks (missing `AUDIT`/`REC`/`TERM`) stay independent of it.

## 5. Sessions — fixed in advance

| session | image | N | audit | watchdog | purpose | its own rulings |
|---|---|---|---|---|---|---|
| **C1** calibration, random-safe schedule forced | two-operator | 64 | all-self-reporting | D-s1 | rate + breakdown + failure rate, arm A | `P3-L6` + `P3-K` |
| **C2** calibration, map-guided schedule forced | two-operator | 64 | all-self-reporting | D-s1 | same, arm B (operator compute time may differ) | `P3-L6` + `P3-K` |
| **S** soak, A,B,B,A schedule | two-operator | ⌊0.9 × min(rate_A, rate_B) × T⌋, rates by C1/C2 record hash | sampled per §3a | D-s1 | Q2 | `P3-L6` + `P3-K` |

Each session: power cycle → boundary verifier as the runner → identity → carrier load
(sha-gated) → provisioning → image load (sha-gated) → `dcache off` → identity page (master
seed, N, flags, arm-schedule mode) → `go`; opening baseline, N candidates, closing baseline,
closing unsigned control — the L5 brackets unchanged. Runner in the background, no shell
timeout, waited on by pid. A calibration session is **not** a Claim B data point even though
both arms run: its genomes are consumed by the calibration and the seed pairs are excluded
from Claim B's schedule (recorded in the Claim B preregistration at freeze).

## 6. PASS / HOLD / KILL — decided now

**PASS (L6)** requires, for C1, C2 and S each:

1. every L5 §5 condition — `COMPLETED` with the three closing steps, both baselines exactly
   `[18, 22, 20, 20, 20, 18]`, (ii)/(iii) for every `SCORED`, the nonce chain over every
   attempt, the closing unsigned ARM refused `F_ARM_AUTH`, every audited candidate
   recomputing on the host, `validate_standalone_run_log` accepting, zero disruptions;
2. the sampled policy of §3a (S) or all-self-reporting (C1/C2) satisfied by host-derived marks — every non-`SCORED` self-report auto-audited, every scheduled `SCORED` audited;
3. a timing record for **every** candidate, and a rate report whose coefficient of variation
   over candidates is ≤ 0.10 (C1, C2) — larger is a HOLD with the distribution published;
4. for S: no heartbeat gap > 20 s (L2's guard), CRC drops within D-s4's closed-formula budget (and no missing `AUDIT`/`REC`/`TERM` regardless of it), wall time
   ≥ 0.9 T, and every `settle.polls` within [1, 10 × the C1/C2 median] — a slower gate is a
   finding, not a failure, but it stops the session as `STOP_SETTLE` would if it exceeds the
   bound;
5. the record's arm equals the schedule's for every index.

**HOLD** — an instrument or transport failure (`PROTOCOL`, `CRASHED`, a lost ruling, a console
fault, a validator rejection that is not a §3 falsifier), a CoV above 0.10, a `STOPPED` end at
link 2/3 with the refusal correctly recorded. Re-run after the cause is fixed and named. A
`CRASHED` soak after ≥ 1 h is a HOLD whose evidence is kept whole; it may be repeated **once**
without a change only if the cause is named as transport (dmesg/usbip record), otherwise the
fix comes first.

**KILL** — any L5 prereg §3 item (they apply unchanged: the interlock and the nonce model are
under the same test for hours), raised as `Falsified` by the validator.

## 7. Stop-loss

`docs/l5_prereg.md` §6 stands: two consecutive sessions lost to the same instrument cause →
stop, fix, prove with an authorised host-side soak before a third ruling; three sessions
without `COMPLETED` → design review before further board time. L6's own: a soak that fails
the same way twice is the result — the next step is a targeted fix with its own review, not a
third soak. `zynq-psmap/docs/stop_loss.md`'s rule is inherited: a new instrument is not a new
mechanism.

## 8. What L6 does not establish

Claim B (zero data points remain zero); anything on another die, carrier, control plane or
Linux; the ICAPE2 readback path or the H-PAD/H-ADDR/H-IDLE hypotheses; that a 2 h soak
predicts a longer one (the Claim B budget must sit inside what was soaked, or the soak is
extended by its own ruling).

## 9. Order of work, and the hand-back

1. Host-only instrument changes (§4) with tests; owner review.
2. Two-operator image (§2) with twins and static audits; byte-identical rebuilds; owner's
   P3 compatibility review; hash pinned; this document frozen (D-s1..D-s4 filled).
3. Rulings C1, C2, S issued one session at a time, each with a power cycle.
4. `docs/l6_findings.md`: the measured rate, the soak record, PASS/HOLD/KILL per §6.
5. The whole L6 package goes to `zynq-fabricmap`'s owner for the separate decision on
   whether Claim B leaves PAUSED (`claimb_resumption_memo.md` §0); Claim B's own
   preregistration then derives its budget and seed schedule from L6's calibration record
   by hash.
