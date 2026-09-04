# L6 session S #3 (2026-09-04-01) — PASS: the first COMPLETED soak. 12 570 records in 6763.9 s under the frozen v0.7, every gate empty, and the transport faults that ended S #1 and S #2 recovered in flight

**Standing: PASS as the runner adjudicated it (prereg v0.7 §6, every item; `findings: []`).
This is the ONE soak the owner's S ruling pair authorised. It is a runner outcome, not an
owner adjudication: nothing is pinned by it, and whether L6's Q2 is answered — and whether
Claim B may be reconsidered — is the owner's separate decision.** Evidence
`evidence/l6_17A6_2026-09-04-01-S/`; rulings `2026-09-04-01` (whole-of-probe P3-L6, session
S, master_seed 1278628687; provisioning P3-K; both bound to prereg `95d177a1…`, image
`5deee74c…`, manifest `3fea5c4b…`; both consumed with outcome PASS); boundary
`evidence/boundary/principal_boundary_2026-09-04-01.json` (R1–R5 PASS, 05:35). First
session under the frozen v0.7 and the first L6 soak ever to reach `COMPLETED`.

## 1. What the board did

Power cycle by the owner (UART re-enumerated 05:35 → ttyUSB4), boundary PASS, preflight
READ (`CPU_CLK_CTRL 0x1f000200`), carrier `956379fa…`, FCLK0 50.0 MHz, IDCODE `0x13722093`,
`17A6 verify`, provisioning rc 0, image `5deee74c…` hash-checked, identity page written
(abba, N 12568, watchdog bit1, bit4 and bit5 armed). `go` 05:40.

**IDENT 1.3.0: `protocol rel-v4`, both control flags echoed**, `schedule_mode abba`,
`master_seed 1278628687`, operator `0c9c82a8…`; one transmission, one `IDENTACK`. TERM
accepted on its first transmission; `closing_conflict: null`.

**12 570 records, all `SCORED`, chain length 12 571** — seq 1 the opening baseline, seq
2–12 569 the 12 568 scheduled candidates (6284 `random_safe` + 6284 `map_guided`,
`arm_check` 12 568/12 568, brackets [1, 12570]), seq 12 570 the closing baseline. Both
baselines exactly `[18, 22, 20, 20, 20, 18]`. Closing control refused with fault 13
(`0x00000982`, nonce `57deb8c5…` → `96b4c859…`), carried by TERM and CLOSE in agreement.
`TERM COMPLETED / budget`; the board's own summary: `audited 789/12570`, `scored 12570`,
`refused_by_gate 0`, closing baseline/restore/unsigned control all `done`. Zero disruptions,
`epoch_final 0`, `transport_rereads []`.

**Audit (sampled, §3a):** 789 due, **789 pulled and verified** — every pull `done`, none
failed, zero `AUDITWAIT`, zero DONE replays, zero timeouts; the host recomputed all three
hashes for each. `run_log_validation: scored 12570, audited 789, chain_length 12571`; the
validator accepted.

## 2. Wall time — the point of D-n1

| | |
|---|---|
| span (first `SIGNREQ` → last `REC`) | **6763.9 s** |
| §6.4 floor, 0.9 × T | 6480 s |
| margin | **+283.9 s** |
| runner timeout | 8739 s |
| D-n1's post-hoc prediction from S #2's pace | 6784.9 s — **0.31 % high** |

N came from `sessions.S.n_rule = policy_matched_wall` (D-n1), the faster arm: rates
6982.314889 / 6950.492576 evaluations/hour, unrounded product 12568.166801, **N 12568**,
789 sampled audits, 233 364 expected inbound frames, CRC and bad-frame budget 934, timeout
8739 s. The plan's own evidence records the rule, the arm (`max`) and the formula.

Under v0.6's rule the same soak would have been N 6061 and finished in ≈ 55 min — below the
0.9 T floor, a HOLD by construction. The prediction landing within 0.31 % of the measured
span is the first end-to-end check of the whole D-n1 chain: policy-matched rates from the
imported calibrations, the fixed point, the faster arm, and the post-hoc normalisation.

## 3. The transport, and what the v0.7 rules did with it

Over 233 350 received frames (233 364 expected; the difference is exactly the 14 missing
heartbeats of §3c):

| event | count | budget | what handled it |
|---|---|---|---|
| CRC drops | **42** | 934 | 2 are the forced seq-1 controls; the rest recovered below |
| — of type `REC` | 26 | | the REC transaction: 25 real retries + the control, every ledger `["crc", "ok"]` |
| — of type `SIGNREQ` | 7 | | the SIGNREQ transaction: 6 real retries + the control, every ledger `["crc", "ok"]` |
| — of type `AUDIT` | 5 | | the pull's chunk re-request: 5 retries, 0 timeouts |
| — of type `HB` | 4 | | budgeted, §3c |
| **bad frames** | **4** | 934 | **D-b1's ledger policy** — see §3a |
| fragments (reader resync) | 3 | 3 (C1/C2 bound; S has none) | quarantined verbatim, never glued to a resend |
| candidates with a recovery | 52 of 12 568 | — | 0.41 % |

Every transaction closed: 12 570 sign ledgers and 12 570 REC ledgers, one per record, all
accepted, no conflict; 789 pulls all `done`; IDENT and TERM each one transmission.
`rel_closure_findings`, `rel_control_findings`, `rec_closure_findings` and
`rec_control_findings` are all empty, and both forced controls are exactly `["crc", "ok"]`
with one GET and no replay.

### 3a. D-b1, proved on hardware — and a counterfactual from this session's own bytes

Four malformed lines arrived, at go + 546.2 s, 1146.3 s, 1354.8 s and 5346.2 s. Under v0.7
each was recorded once in the ledger and went no further; the board's own bounded resends
carried the affected frames.

`evidence/l6_v07_counterfactual/s_2026-09-04-01_policy_replay.json`: this session's own
`console.log` (50 642 507 bytes, sha in that file) replayed through the real reader,
`ConsoleSession`, `Collector` and `NotaryRelay`, changing **one flag**:

| policy | outcome |
|---|---|
| `crash` (v0.6) | **`CRASHED: unparseable frame` at record 1011**, go + 546.2 s — 9 minutes in |
| `ledger` (v0.7) | `COMPLETED`, 12 570 records, 4 bad frames, 42 CRC drops — the session as it ran |

Same bytes, same code, one policy apart. The soak that just passed would have been a HOLD
nine minutes into it under the frozen v0.6.

### 3b. The pull and the sign transactions

Five AUDIT chunks arrived CRC-broken and were re-requested once each; no chunk needed a
second retry, no pull timed out, no `AUDIT_READY` was resent and no `AUDITWAIT` was sent in
the whole soak. Six `SIGNREQ` lines were re-requested (`SIGNGET`) and answered from the
cached signature — the notary signed each seq exactly once.

### 3c. D-h1, proved on hardware

14 heartbeats were lost, spread over **7 SCORED records** (seq 855 ×1, 1012 ×2, 1487 ×1,
2077 ×4, 2104 ×1, 2490 ×2, 10011 ×3). The v0.7 record budget is ⌊12570/1000⌋ = **12
records**, so `heartbeat_findings_v07` is **clean**. Under v0.6's per-record cap the same
evidence gives **5 findings** (every record that lost two or more), and the soak would have
been a HOLD on that alone — with every record accepted and every audit verified. No
heartbeat gap exceeded 20 s.

## 4. The rates

`rate_report.json` (sha `8af02b917ca457ccccdbd016976e9c88bfe468f1c5256b469f7f1e5f58542d5b`),
derived from the three files beside it as read back from disk, `binding` = {image
`5deee74c…`, prereg `95d177a1…`, rel-v4, S, abba, 1278628687}:

| rate | value |
|---|---|
| inclusive (12 567 steady-state periods) | 6691.9 evaluations/hour, CoV 0.365 |
| nominal (12 515 clean periods; 52 excluded) | CoV 0.2475 |
| planning (12 568 candidates over the span) | 6689.2 evaluations/hour |

The CoV bounds of §6.3a are C1/C2 conditions and do not apply to S; a soak's spread is
wider by construction, because only every sixteenth record carries an audit stage. S's own
conditions — §6.4's heartbeat gap, the CRC and bad-frame budgets, the wall fraction and the
settle bound — are all satisfied, which is why `findings` is empty.

## 5. What this session establishes, and what it does not

Established: **Q2's answer for 2 hours** — the P3 loop holds every L5 invariant unattended
for 6763.9 s under the sampled audit policy with the watchdog armed: heartbeat cadence,
nonce chain over 12 571 links, host-recomputed audits, baseline equality, the fail-closed
ends, the two forced controls, and every rel-v4 transaction closed. And, on real hardware
rather than a model, that the three v0.7 rules do what they were ruled to do: D-b1 kept a
soak alive that v0.6 would have ended at record 1011, D-h1 kept one that v0.6 would have
HOLD-ed on heartbeats, and D-n1 sized N so that a "2 h soak" ran 6763.9 s.

Not established: anything about Claim B (still zero data points); any other die, carrier or
control plane; the ICAPE2 readback path; that 2 h predicts longer (§8's rule stands — the
Claim B budget must sit inside what was soaked, or the soak is extended by its own ruling);
anything about the physical console path beyond this session's own event counts.

## 6. Open for the owner (not decided here)

1. Adjudicate S #3. If PASS, L6's Q1 (C1 #6 / C2 #2, pinned) and Q2 (this soak) are both
   answered, and the L6 package can go to `zynq-fabricmap`'s owner for the separate
   decision on whether Claim B leaves PAUSED (§9.6).
2. Nothing is pinned by a soak; `calibration.C1`/`C2` are unchanged.
3. C1 #5, S #1 and S #2 keep their HOLDs; none is re-judged by this session.
